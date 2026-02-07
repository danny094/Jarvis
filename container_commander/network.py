"""
Container Commander — Network Isolation Manager
═══════════════════════════════════════════════════
4 isolation levels for container networking:

  none     → No network at all (--network none). Pure sandbox.
             Container cannot reach anything, not even other containers.

  internal → Isolated bridge network (trion-sandbox, internal=True).
             Containers can talk to each other but NOT to the host or internet.
             Default for most blueprints.

  bridge   → Docker default bridge. Container can reach the host network
             and other Docker containers, but no internet unless host routes it.

  full     → Docker bridge with internet access. REQUIRES explicit user
             approval (Human-in-the-Loop). Flagged in deploy response.

Network naming:
  - Shared:    trion-sandbox       (internal, for all internal-mode containers)
  - Per-container: trion-iso-{id}  (for containers that need their own network)
"""

import logging
from typing import Optional, List, Dict

import docker
from docker.errors import NotFound, APIError

from .models import NetworkMode

logger = logging.getLogger(__name__)

TRION_LABEL = "trion.managed"
SHARED_INTERNAL = "trion-sandbox"


def _get_client():
    from .engine import get_client
    return get_client()


# ── Network Setup ─────────────────────────────────────────

def ensure_shared_network() -> str:
    """Create the shared internal network if it doesn't exist."""
    client = _get_client()
    try:
        client.networks.get(SHARED_INTERNAL)
    except NotFound:
        client.networks.create(
            SHARED_INTERNAL,
            driver="bridge",
            internal=True,  # Key: no external/internet access
            labels={TRION_LABEL: "true", "trion.network.type": "internal"},
            options={"com.docker.network.bridge.enable_icc": "true"},
        )
        logger.info(f"[Network] Created shared internal: {SHARED_INTERNAL}")
    return SHARED_INTERNAL


def create_isolated_network(container_name: str) -> str:
    """
    Create a per-container isolated network.
    Used when a container should not talk to other TRION containers.
    """
    client = _get_client()
    net_name = f"trion-iso-{container_name}"
    try:
        client.networks.create(
            net_name,
            driver="bridge",
            internal=True,
            labels={
                TRION_LABEL: "true",
                "trion.network.type": "isolated",
                "trion.network.container": container_name,
            },
        )
        logger.info(f"[Network] Created isolated: {net_name}")
    except APIError as e:
        if "already exists" in str(e).lower():
            logger.debug(f"[Network] {net_name} already exists")
        else:
            raise
    return net_name


# ── Resolution ────────────────────────────────────────────

def resolve_network(mode: NetworkMode, container_name: str = "") -> Dict:
    """
    Resolve a NetworkMode to Docker network config.
    
    Returns:
        {
            "network": str,           # Docker network name or "none"/"bridge"
            "requires_approval": bool, # True if Human-in-the-Loop needed
            "isolation_level": str,    # Description for UI
            "internet_access": bool,   # Whether container can reach internet
        }
    """
    if mode == NetworkMode.NONE:
        return {
            "network": "none",
            "requires_approval": False,
            "isolation_level": "Full Sandbox — no network",
            "internet_access": False,
        }

    elif mode == NetworkMode.INTERNAL:
        net = ensure_shared_network()
        return {
            "network": net,
            "requires_approval": False,
            "isolation_level": "Internal — TRION containers only",
            "internet_access": False,
        }

    elif mode == NetworkMode.BRIDGE:
        return {
            "network": "bridge",
            "requires_approval": False,
            "isolation_level": "Bridge — host network access",
            "internet_access": False,  # Depends on host iptables
        }

    elif mode == NetworkMode.FULL:
        return {
            "network": "bridge",
            "requires_approval": True,  # Human-in-the-Loop!
            "isolation_level": "Full — internet access enabled",
            "internet_access": True,
        }

    # Fallback
    return {
        "network": ensure_shared_network(),
        "requires_approval": False,
        "isolation_level": "Internal (fallback)",
        "internet_access": False,
    }


# ── Management ────────────────────────────────────────────

def list_networks() -> List[Dict]:
    """List all TRION-managed networks."""
    client = _get_client()
    result = []
    try:
        for net in client.networks.list(filters={"label": TRION_LABEL}):
            labels = net.attrs.get("Labels", {})
            containers = net.attrs.get("Containers", {})
            result.append({
                "name": net.name,
                "id": net.short_id,
                "type": labels.get("trion.network.type", "unknown"),
                "internal": net.attrs.get("Internal", False),
                "driver": net.attrs.get("Driver", ""),
                "container_count": len(containers),
                "containers": [c.get("Name", "") for c in containers.values()] if containers else [],
            })
    except Exception as e:
        logger.error(f"[Network] List failed: {e}")
    return result


def remove_network(network_name: str) -> bool:
    """Remove a TRION network (only if no containers attached)."""
    client = _get_client()
    try:
        net = client.networks.get(network_name)
        labels = net.attrs.get("Labels", {})
        if labels.get(TRION_LABEL) != "true":
            logger.warning(f"[Network] Refusing to remove non-TRION network: {network_name}")
            return False
        net.remove()
        logger.info(f"[Network] Removed: {network_name}")
        return True
    except NotFound:
        return False
    except APIError as e:
        if "has active endpoints" in str(e).lower():
            logger.warning(f"[Network] Cannot remove {network_name}: containers still connected")
        else:
            logger.error(f"[Network] Remove failed: {e}")
        return False


def cleanup_networks() -> List[str]:
    """Remove all empty TRION isolated networks."""
    removed = []
    for net in list_networks():
        if net["type"] == "isolated" and net["container_count"] == 0:
            if remove_network(net["name"]):
                removed.append(net["name"])
    return removed


# ── Info Helper ───────────────────────────────────────────

def get_network_info(container_id: str) -> Optional[Dict]:
    """Get network info for a running container."""
    client = _get_client()
    try:
        container = client.containers.get(container_id)
        networks = container.attrs.get("NetworkSettings", {}).get("Networks", {})
        result = {}
        for name, config in networks.items():
            result[name] = {
                "ip": config.get("IPAddress", ""),
                "gateway": config.get("Gateway", ""),
                "mac": config.get("MacAddress", ""),
            }
        return result
    except NotFound:
        return None
