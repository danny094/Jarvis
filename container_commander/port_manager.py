"""
Container Commander — Port Management Utilities
===============================================
Provides deterministic port checks for Blueprint deploys and read-only
inspection helpers used by SysInfo MCP tools.
"""

from __future__ import annotations

import json
import logging
import socket
from typing import Dict, List, Tuple

try:
    import docker  # type: ignore
except Exception:  # pragma: no cover - optional in lightweight test envs
    docker = None

logger = logging.getLogger(__name__)


def _iter_proc_ports(proc_path: str, protocol: str, listen_states: set[str]) -> List[dict]:
    rows: List[dict] = []
    try:
        with open(proc_path, "r", encoding="utf-8") as f:
            lines = f.readlines()[1:]
    except Exception:
        return rows

    for line in lines:
        parts = line.split()
        if len(parts) < 4:
            continue
        state = parts[3]
        if listen_states and state not in listen_states:
            continue
        local = parts[1]
        try:
            port = int(local.split(":")[1], 16)
        except Exception:
            continue
        rows.append({"port": port, "protocol": protocol, "source": "proc"})
    return rows


def list_used_ports(include_udp: bool = True) -> List[dict]:
    """Read host-level listening ports from /proc (best effort)."""
    rows: List[dict] = []
    rows.extend(_iter_proc_ports("/proc/net/tcp", "tcp", {"0A"}))   # LISTEN
    rows.extend(_iter_proc_ports("/proc/net/tcp6", "tcp", {"0A"}))  # LISTEN
    if include_udp:
        # UDP has no LISTEN in the TCP sense; include common bound states.
        rows.extend(_iter_proc_ports("/proc/net/udp", "udp", {"07", "0A"}))
        rows.extend(_iter_proc_ports("/proc/net/udp6", "udp", {"07", "0A"}))

    dedup = {(r["port"], r["protocol"]): r for r in rows}
    return sorted(dedup.values(), key=lambda r: (r["port"], r["protocol"]))


def check_port(port: int, protocol: str = "tcp") -> Tuple[bool, str]:
    """Check whether a host port is bindable (best-effort)."""
    proto = str(protocol or "tcp").lower()
    family = socket.AF_INET
    sock_type = socket.SOCK_DGRAM if proto == "udp" else socket.SOCK_STREAM
    sock = socket.socket(family, sock_type)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", int(port)))
        return True, "free"
    except OSError as e:
        return False, str(e)
    finally:
        try:
            sock.close()
        except Exception:
            pass


def find_free_port(
    min_port: int = 8000,
    max_port: int = 9000,
    protocol: str = "tcp",
    excluded_ports: set[int] | None = None,
) -> int:
    """Return first free host port in [min_port, max_port]."""
    excluded = excluded_ports or set()
    for port in range(int(min_port), int(max_port) + 1):
        if port in excluded:
            continue
        ok, _ = check_port(port, protocol=protocol)
        if ok:
            return port
    raise RuntimeError(f"no free {protocol} port found in range {min_port}-{max_port}")


def _expand_host_port_token(token: str) -> List[int]:
    token = str(token or "").strip()
    if not token:
        return []
    if "-" in token:
        start_str, end_str = token.split("-", 1)
        start = int(start_str.strip())
        end = int(end_str.strip())
        if end < start:
            raise ValueError(f"invalid port range '{token}'")
        return list(range(start, end + 1))
    return [int(token)]


def validate_port_bindings(port_bindings: Dict[str, str]) -> List[dict]:
    """
    Validate host-side availability for docker-py style `ports` mapping.
    Returns a conflict list (empty => safe to proceed).
    """
    conflicts: List[dict] = []
    for container_key, host_value in dict(port_bindings or {}).items():
        proto = "tcp"
        if "/" in container_key:
            _, proto = container_key.rsplit("/", 1)
        try:
            host_ports = _expand_host_port_token(str(host_value))
        except Exception as e:
            conflicts.append(
                {
                    "host_port": host_value,
                    "protocol": proto,
                    "container": container_key,
                    "reason": f"invalid_host_port: {e}",
                }
            )
            continue

        for host_port in host_ports:
            ok, reason = check_port(host_port, protocol=proto)
            if not ok:
                conflicts.append(
                    {
                        "host_port": host_port,
                        "protocol": proto,
                        "container": container_key,
                        "reason": reason,
                    }
                )
    return conflicts


def list_blueprint_ports() -> List[dict]:
    """
    List port reservations for TRION-managed containers.
    Reads `trion.port_bindings` label (if present), falls back to Docker attrs.
    """
    if docker is None:
        return []
    try:
        client = docker.from_env()
        containers = client.containers.list(all=True, filters={"label": "trion.managed=true"})
    except Exception as e:
        logger.debug("[PortManager] Docker unavailable for list_blueprint_ports: %s", e)
        return []

    result: List[dict] = []
    for c in containers:
        labels = c.labels or {}
        raw = labels.get("trion.port_bindings", "").strip()
        parsed = {}
        if raw:
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {}
        if not parsed:
            parsed = {}
            try:
                ports_obj = ((c.attrs or {}).get("NetworkSettings", {}) or {}).get("Ports", {}) or {}
                for container_port, bindings in ports_obj.items():
                    if not bindings:
                        continue
                    host_port = bindings[0].get("HostPort", "")
                    if host_port:
                        parsed[container_port] = str(host_port)
            except Exception:
                parsed = {}

        result.append(
            {
                "container_id": c.id,
                "name": c.name,
                "blueprint_id": labels.get("trion.blueprint", "unknown"),
                "status": c.status,
                "ports": parsed,
            }
        )
    return result
