"""
Container Commander — Whitelist Proxy Manager
═══════════════════════════════════════════════════
Manages a Squid-based HTTP proxy for controlled internet access.

Instead of giving containers direct internet (NetworkMode.FULL),
containers get NetworkMode.BRIDGE + HTTP_PROXY pointing to Squid.
Squid only allows domains on the whitelist.

Flow:
  1. Blueprint defines allowed_domains: ["pypi.org", "api.github.com"]
  2. On deploy, proxy.py generates a Squid ACL config
  3. Container gets env: HTTP_PROXY=http://trion-proxy:3128
  4. Squid blocks everything except whitelisted domains
  5. All requests are logged for audit

Squid runs as a TRION-managed container itself.
Config is generated dynamically per-container via ACL files.

Proxy Container:
  - Image: ubuntu/squid or sameersbn/squid
  - Volume: trion_proxy_config → /etc/squid/conf.d/
  - Network: trion-sandbox (internal) + bridge (for outbound)
  - Port: 3128
"""

import os
import logging
from datetime import datetime
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)

PROXY_CONTAINER_NAME = "trion-proxy"
PROXY_IMAGE = "ubuntu/squid:latest"
PROXY_PORT = 3128
PROXY_CONFIG_VOLUME = "trion_proxy_config"
PROXY_LOG_VOLUME = "trion_proxy_logs"
TRION_LABEL = "trion.managed"

# Default whitelist — always allowed
DEFAULT_WHITELIST = [
    "pypi.org",
    "files.pythonhosted.org",
    "registry.npmjs.org",
    "api.github.com",
    "github.com",
    "raw.githubusercontent.com",
    "dl-cdn.alpinelinux.org",
    "deb.debian.org",
    "archive.ubuntu.com",
]


def _get_client():
    from .engine import get_client
    return get_client()


# ── Proxy Lifecycle ───────────────────────────────────────

def ensure_proxy_running() -> bool:
    """Ensure the Squid proxy container is running."""
    client = _get_client()

    try:
        container = client.containers.get(PROXY_CONTAINER_NAME)
        if container.status == "running":
            return True
        container.start()
        logger.info("[Proxy] Restarted existing proxy")
        return True
    except Exception:
        pass

    # Create config volume
    try:
        client.volumes.get(PROXY_CONFIG_VOLUME)
    except Exception:
        client.volumes.create(name=PROXY_CONFIG_VOLUME, labels={TRION_LABEL: "true"})

    try:
        client.volumes.get(PROXY_LOG_VOLUME)
    except Exception:
        client.volumes.create(name=PROXY_LOG_VOLUME, labels={TRION_LABEL: "true"})

    # Write base squid config
    _write_base_config(client)

    try:
        container = client.containers.run(
            PROXY_IMAGE,
            detach=True,
            name=PROXY_CONTAINER_NAME,
            volumes={
                PROXY_CONFIG_VOLUME: {"bind": "/etc/squid/conf.d", "mode": "rw"},
                PROXY_LOG_VOLUME: {"bind": "/var/log/squid", "mode": "rw"},
            },
            network="bridge",
            labels={
                TRION_LABEL: "true",
                "trion.service": "proxy",
            },
            restart_policy={"Name": "unless-stopped"},
        )

        # Also connect to internal network so TRION containers can reach it
        from .network import ensure_shared_network
        net_name = ensure_shared_network()
        net = client.networks.get(net_name)
        net.connect(container)

        logger.info("[Proxy] Started Squid proxy container")
        return True

    except Exception as e:
        logger.error(f"[Proxy] Failed to start: {e}")
        return False


def stop_proxy():
    """Stop the Squid proxy container."""
    client = _get_client()
    try:
        container = client.containers.get(PROXY_CONTAINER_NAME)
        container.stop(timeout=5)
        container.remove(force=True)
        logger.info("[Proxy] Stopped")
    except Exception as e:
        logger.debug(f"[Proxy] Stop: {e}")


def get_proxy_url() -> str:
    """Get the proxy URL for container environment injection."""
    return f"http://{PROXY_CONTAINER_NAME}:{PROXY_PORT}"


# ── Whitelist Management ──────────────────────────────────

def set_whitelist(blueprint_id: str, domains: List[str]) -> bool:
    """
    Set the allowed domains for a blueprint.
    Creates an ACL file in the Squid config volume.
    """
    client = _get_client()
    all_domains = list(set(DEFAULT_WHITELIST + domains))

    acl_content = f"# Whitelist for {blueprint_id}\n"
    acl_content += f"# Generated: {datetime.utcnow().isoformat()}\n"
    for domain in sorted(all_domains):
        acl_content += f".{domain}\n"

    # Write ACL file into proxy config volume via temp container
    try:
        client.containers.run(
            "alpine:latest",
            command=f"sh -c 'echo \"{acl_content}\" > /config/{blueprint_id}.acl'",
            volumes={PROXY_CONFIG_VOLUME: {"bind": "/config", "mode": "rw"}},
            remove=True,
            labels={TRION_LABEL: "true", "trion.temp": "proxy-config"},
        )

        # Reload squid config
        _reload_squid(client)

        logger.info(f"[Proxy] Whitelist set for {blueprint_id}: {len(all_domains)} domains")
        return True

    except Exception as e:
        logger.error(f"[Proxy] Whitelist write failed: {e}")
        return False


def get_whitelist(blueprint_id: str) -> List[str]:
    """Get the current whitelist for a blueprint."""
    client = _get_client()
    try:
        result = client.containers.run(
            "alpine:latest",
            command=f"cat /config/{blueprint_id}.acl",
            volumes={PROXY_CONFIG_VOLUME: {"bind": "/config", "mode": "ro"}},
            remove=True,
        )
        lines = result.decode("utf-8", errors="replace").strip().split("\n")
        return [l.lstrip(".") for l in lines if l and not l.startswith("#")]
    except Exception:
        return list(DEFAULT_WHITELIST)


def remove_whitelist(blueprint_id: str) -> bool:
    """Remove the whitelist ACL for a blueprint."""
    client = _get_client()
    try:
        client.containers.run(
            "alpine:latest",
            command=f"rm -f /config/{blueprint_id}.acl",
            volumes={PROXY_CONFIG_VOLUME: {"bind": "/config", "mode": "rw"}},
            remove=True,
        )
        _reload_squid(client)
        return True
    except Exception:
        return False


def get_proxy_env(blueprint_id: str) -> Dict[str, str]:
    """
    Get environment variables to inject into a container
    for proxied internet access.
    """
    url = get_proxy_url()
    return {
        "HTTP_PROXY": url,
        "HTTPS_PROXY": url,
        "http_proxy": url,
        "https_proxy": url,
        "NO_PROXY": "localhost,127.0.0.1,.trion-sandbox",
        "no_proxy": "localhost,127.0.0.1,.trion-sandbox",
    }


# ── Internal ──────────────────────────────────────────────

def _write_base_config(client):
    """Write the base squid.conf into the config volume."""
    squid_conf = """# TRION Proxy — Base Config
http_port 3128
# ACL: Allow only whitelisted domains
acl trion_whitelist dstdomain "/etc/squid/conf.d/default.acl"
http_access allow trion_whitelist
http_access deny all
# Logging
access_log /var/log/squid/access.log squid
cache_log /var/log/squid/cache.log
# Performance
cache_mem 64 MB
maximum_object_size 50 MB
# Security
forwarded_for delete
via off
"""

    default_acl = "# Default whitelist\n"
    for domain in DEFAULT_WHITELIST:
        default_acl += f".{domain}\n"

    try:
        # Write both files
        for filename, content in [("squid.conf", squid_conf), ("default.acl", default_acl)]:
            escaped = content.replace("'", "'\\''")
            client.containers.run(
                "alpine:latest",
                command=f"sh -c 'printf \\'%s\\' \\'{escaped}\\' > /config/{filename}'",
                volumes={PROXY_CONFIG_VOLUME: {"bind": "/config", "mode": "rw"}},
                remove=True,
            )
    except Exception as e:
        logger.error(f"[Proxy] Base config write failed: {e}")


def _reload_squid(client):
    """Send SIGHUP to Squid to reload config."""
    try:
        container = client.containers.get(PROXY_CONTAINER_NAME)
        container.kill(signal="SIGHUP")
        logger.debug("[Proxy] Squid config reloaded")
    except Exception as e:
        logger.debug(f"[Proxy] Reload: {e}")
