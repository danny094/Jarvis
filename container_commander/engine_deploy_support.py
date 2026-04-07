"""
Internal deploy support helpers for port mappings and readiness handling.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple


def build_port_bindings(port_specs: List[str]) -> Dict[str, str]:
    """
    Convert blueprint port strings into docker-py compatible bindings.
    Supported forms:
      - "47984:47984"
      - "47984:47984/tcp"
      - "48100-48110:48100-48110/udp"
      - "8080" (host=container)
    """
    bindings: Dict[str, str] = {}
    reserved_host_ports: set[int] = set()
    for raw in list(port_specs or []):
        spec = str(raw or "").strip()
        if not spec:
            continue
        proto = "tcp"
        if "/" in spec:
            spec, proto_raw = spec.rsplit("/", 1)
            proto = (proto_raw or "tcp").strip().lower() or "tcp"
        if ":" in spec:
            host_port, container_port = spec.split(":", 1)
        else:
            host_port, container_port = spec, spec
        host_port = host_port.strip()
        container_port = container_port.strip()
        if not container_port:
            continue
        if host_port in ("", "0", "auto"):
            from .port_manager import find_free_port

            host_port = str(
                find_free_port(
                    min_port=int(os.environ.get("COMMANDER_AUTO_PORT_MIN", "8000")),
                    max_port=int(os.environ.get("COMMANDER_AUTO_PORT_MAX", "9000")),
                    protocol=proto,
                    excluded_ports=reserved_host_ports,
                )
            )

        host_parts = [part.strip() for part in host_port.split("-", 1)]
        container_parts = [part.strip() for part in container_port.split("-", 1)]
        if len(host_parts) == 2 or len(container_parts) == 2:
            if len(host_parts) != 2 or len(container_parts) != 2:
                raise ValueError(f"invalid mixed port range mapping: '{raw}'")
            h_start, h_end = int(host_parts[0]), int(host_parts[1])
            c_start, c_end = int(container_parts[0]), int(container_parts[1])
            if h_end < h_start or c_end < c_start or (h_end - h_start) != (c_end - c_start):
                raise ValueError(f"invalid port range mapping: '{raw}'")
            offset_max = h_end - h_start
            for offset in range(offset_max + 1):
                host_p = h_start + offset
                container_p = c_start + offset
                if host_p in reserved_host_ports:
                    raise ValueError(f"duplicate host port in blueprint request: {host_p}/{proto}")
                reserved_host_ports.add(host_p)
                bindings[f"{container_p}/{proto}"] = str(host_p)
            continue

        host_int = int(host_port)
        if host_int in reserved_host_ports:
            raise ValueError(f"duplicate host port in blueprint request: {host_int}/{proto}")
        reserved_host_ports.add(host_int)
        bindings[f"{container_port}/{proto}"] = str(host_int)
    return bindings


def seconds_to_nanos(value: object) -> Optional[int]:
    try:
        seconds = float(value)  # type: ignore[arg-type]
    except Exception:
        return None
    if seconds <= 0:
        return None
    return int(seconds * 1_000_000_000)


def build_healthcheck_config(config: Dict) -> Optional[Dict]:
    """
    Build Docker healthcheck dict from a simple Blueprint healthcheck object.
    """
    cfg = dict(config or {})
    if not cfg:
        return None

    result: Dict = {}
    test = cfg.get("test")
    if isinstance(test, str) and test.strip():
        result["test"] = ["CMD-SHELL", test.strip()]
    elif isinstance(test, list) and test:
        result["test"] = [str(x) for x in test]
    else:
        return None

    interval = seconds_to_nanos(cfg.get("interval_seconds"))
    timeout = seconds_to_nanos(cfg.get("timeout_seconds"))
    start_period = seconds_to_nanos(cfg.get("start_period_seconds"))
    if interval:
        result["interval"] = interval
    if timeout:
        result["timeout"] = timeout
    if start_period:
        result["start_period"] = start_period

    retries = cfg.get("retries")
    if retries is not None:
        try:
            result["retries"] = max(1, int(retries))
        except Exception:
            pass
    return result


def derive_readiness_timeout_seconds(config: Dict) -> int:
    """
    Derive a sane readiness timeout from healthcheck config.
    Supports explicit override via:
      - ready_timeout_seconds
      - readiness_timeout_seconds
    """
    cfg = dict(config or {})
    explicit = cfg.get("ready_timeout_seconds", cfg.get("readiness_timeout_seconds"))
    if explicit is not None:
        try:
            val = int(float(explicit))
            if val > 0:
                return max(15, min(1800, val))
        except Exception:
            pass

    try:
        interval = max(1.0, float(cfg.get("interval_seconds", 30)))
    except Exception:
        interval = 30.0
    try:
        retries = max(1, int(cfg.get("retries", 3)))
    except Exception:
        retries = 3
    try:
        start_period = max(0.0, float(cfg.get("start_period_seconds", 0)))
    except Exception:
        start_period = 0.0
    try:
        timeout = max(1.0, float(cfg.get("timeout_seconds", 5)))
    except Exception:
        timeout = 5.0

    derived = int(start_period + (interval * retries) + (timeout * 2) + 30)
    return max(30, min(900, derived))


def wait_for_container_health(
    container: Any,
    timeout_seconds: int,
    poll_interval_seconds: float = 2.0,
) -> Tuple[bool, str, str]:
    """
    Wait until Docker health status is 'healthy' or timeout/failure occurs.
    Returns (ready, error_code, reason).
    """
    deadline = time.monotonic() + max(1, int(timeout_seconds))
    poll = max(0.5, float(poll_interval_seconds or 2.0))
    last_status = "starting"
    last_log = ""

    while time.monotonic() < deadline:
        try:
            container.reload()
        except Exception as exc:
            return False, "container_not_ready", f"container_exited_before_ready_auto_stopped: reload_failed={exc}"

        state = (container.attrs or {}).get("State") or {}
        if not state.get("Running", False):
            exit_code = state.get("ExitCode")
            status = state.get("Status", "exited")
            return (
                False,
                "container_not_ready",
                f"container_exited_before_ready_auto_stopped: status={status} exit_code={exit_code}",
            )

        health = state.get("Health") or {}
        status = str(health.get("Status") or "").strip().lower()
        if status:
            last_status = status

        logs = health.get("Log") or []
        if logs:
            last_out = str((logs[-1] or {}).get("Output") or "").strip()
            if last_out:
                last_log = " ".join(last_out.split())[:240]

        if status == "healthy":
            return True, "", "healthy"
        if status == "unhealthy":
            reason = "healthcheck_unhealthy_auto_stopped: container reported unhealthy"
            if last_log:
                reason = f"{reason}; last_log={last_log}"
            return False, "healthcheck_unhealthy", reason

        time.sleep(poll)

    reason = (
        f"healthcheck_timeout_auto_stopped: readiness timeout after {int(timeout_seconds)}s "
        f"(last_status={last_status})"
    )
    if last_log:
        reason = f"{reason}; last_log={last_log}"
    return False, "healthcheck_timeout", reason


def cleanup_failed_container_start(
    client: Any,
    container: Any,
    volume_name: str,
    remove_workspace_volume: bool,
) -> None:
    """Best-effort cleanup for containers that fail readiness checks."""
    try:
        container.remove(force=True)
    except Exception:
        pass
    if remove_workspace_volume and volume_name:
        try:
            client.volumes.get(volume_name).remove()
        except Exception:
            pass
