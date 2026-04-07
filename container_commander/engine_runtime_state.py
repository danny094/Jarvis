"""
Internal helpers for engine quota tracking, TTL timers, and runtime recovery.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Tuple

from .models import ContainerInstance, ContainerStatus, ResourceLimits, SessionQuota


@dataclass
class RuntimeStateRefs:
    active: Dict[str, ContainerInstance]
    ttl_timers: Dict[str, threading.Timer]
    quota: SessionQuota
    state_lock: Any
    pending_starts: int
    pending_memory_mb: float
    pending_cpu: float
    last_runtime_sync_monotonic: float


def get_quota(state: RuntimeStateRefs) -> SessionQuota:
    return state.quota.model_copy(deep=True)


def check_quota(
    resources: ResourceLimits,
    state: RuntimeStateRefs,
    *,
    parse_memory: Callable[[str], int],
) -> None:
    mem_mb = parse_memory(resources.memory_limit) / (1024 * 1024)
    cpu = float(resources.cpu_limit)
    with state.state_lock:
        containers_total = len(state.active) + state.pending_starts
        if containers_total >= state.quota.max_containers:
            raise RuntimeError(
                f"Container quota exceeded: {containers_total}/{state.quota.max_containers} running_or_pending"
            )

        mem_total = state.quota.memory_used_mb + state.pending_memory_mb + mem_mb
        if mem_total > state.quota.max_total_memory_mb:
            raise RuntimeError(
                f"Memory quota exceeded: {int(mem_total)} > {state.quota.max_total_memory_mb} MB (used+pending+requested)"
            )

        cpu_total = state.quota.cpu_used + state.pending_cpu + cpu
        if cpu_total > state.quota.max_total_cpu:
            raise RuntimeError(
                f"CPU quota exceeded: {cpu_total} > {state.quota.max_total_cpu} (used+pending+requested)"
            )


def reserve_quota(
    resources: ResourceLimits,
    state: RuntimeStateRefs,
    *,
    parse_memory: Callable[[str], int],
) -> Tuple[float, float]:
    mem_mb = parse_memory(resources.memory_limit) / (1024 * 1024)
    cpu = float(resources.cpu_limit)
    with state.state_lock:
        containers_total = len(state.active) + state.pending_starts
        if containers_total >= state.quota.max_containers:
            raise RuntimeError(
                f"Container quota exceeded: {containers_total}/{state.quota.max_containers} running_or_pending"
            )

        mem_total = state.quota.memory_used_mb + state.pending_memory_mb + mem_mb
        if mem_total > state.quota.max_total_memory_mb:
            raise RuntimeError(
                f"Memory quota exceeded: {int(mem_total)} > {state.quota.max_total_memory_mb} MB (used+pending+requested)"
            )

        cpu_total = state.quota.cpu_used + state.pending_cpu + cpu
        if cpu_total > state.quota.max_total_cpu:
            raise RuntimeError(
                f"CPU quota exceeded: {cpu_total} > {state.quota.max_total_cpu} (used+pending+requested)"
            )

        state.pending_starts += 1
        state.pending_memory_mb += mem_mb
        state.pending_cpu += cpu
    return mem_mb, cpu


def release_quota_reservation(mem_mb: float, cpu: float, state: RuntimeStateRefs) -> None:
    with state.state_lock:
        state.pending_starts = max(0, state.pending_starts - 1)
        state.pending_memory_mb = max(0.0, state.pending_memory_mb - float(mem_mb or 0.0))
        state.pending_cpu = max(0.0, state.pending_cpu - float(cpu or 0.0))


def commit_quota_reservation(
    instance: ContainerInstance,
    mem_mb: float,
    cpu: float,
    state: RuntimeStateRefs,
) -> None:
    with state.state_lock:
        state.pending_starts = max(0, state.pending_starts - 1)
        state.pending_memory_mb = max(0.0, state.pending_memory_mb - float(mem_mb or 0.0))
        state.pending_cpu = max(0.0, state.pending_cpu - float(cpu or 0.0))
        state.active[instance.container_id] = instance
        update_quota_used_unlocked(state)


def update_quota_used_unlocked(state: RuntimeStateRefs) -> None:
    state.quota.containers_used = len(state.active)
    state.quota.memory_used_mb = sum(i.memory_limit_mb for i in state.active.values())
    state.quota.cpu_used = sum(i.cpu_limit_alloc for i in state.active.values())


def sync_runtime_state_from_docker(
    state: RuntimeStateRefs,
    *,
    force: bool,
    get_client: Callable[[], Any],
    trion_label: str,
    logger: Any,
) -> None:
    now_mono = time.monotonic()
    with state.state_lock:
        if not force and (now_mono - float(state.last_runtime_sync_monotonic or 0.0)) < 2.0:
            return

    try:
        client = get_client()
        containers = client.containers.list(filters={"label": trion_label, "status": "running"})
    except Exception as exc:
        logger.debug(f"[Engine] Runtime sync skipped (docker unavailable): {exc}")
        return

    reconciled: Dict[str, ContainerInstance] = {}
    for container in containers:
        container_id = container.id
        labels = container.labels or {}
        blueprint_id = labels.get("trion.blueprint", "unknown")
        started_at = labels.get("trion.started", "")
        session_id = labels.get("trion.session_id", "")
        volume_name = labels.get("trion.volume", "")

        try:
            ttl_seconds = int(labels.get("trion.ttl_seconds", "0") or "0")
            expires_at_epoch = int(labels.get("trion.expires_at", "0") or "0")
        except ValueError:
            ttl_seconds = 0
            expires_at_epoch = 0
        remaining = max(0, expires_at_epoch - int(time.time())) if expires_at_epoch > 0 else 0

        try:
            host_config = container.attrs.get("HostConfig", {})
            mem_bytes = host_config.get("Memory", 0)
            mem_mb = mem_bytes / (1024 * 1024) if mem_bytes else 512.0
            nano_cpus = host_config.get("NanoCpus", 0)
            cpu_alloc = round(nano_cpus / 1e9, 2) if nano_cpus else 1.0
        except Exception:
            mem_mb = 512.0
            cpu_alloc = 1.0

        reconciled[container_id] = ContainerInstance(
            container_id=container_id,
            blueprint_id=blueprint_id,
            name=container.name,
            status=ContainerStatus.RUNNING,
            started_at=started_at,
            ttl_remaining=remaining if ttl_seconds > 0 else 0,
            memory_limit_mb=mem_mb,
            cpu_limit_alloc=cpu_alloc,
            volume_name=volume_name,
            session_id=session_id,
        )

    with state.state_lock:
        stale_ids = [cid for cid in state.active.keys() if cid not in reconciled]
        for container_id in stale_ids:
            timer = state.ttl_timers.pop(container_id, None)
            if timer:
                try:
                    timer.cancel()
                except Exception:
                    pass
        state.active.clear()
        state.active.update(reconciled)
        update_quota_used_unlocked(state)
        state.last_runtime_sync_monotonic = time.monotonic()


def set_ttl_timer(
    container_id: str,
    seconds: int,
    state: RuntimeStateRefs,
    *,
    emit_ws_activity: Callable[..., None],
    logger: Any,
    get_client: Callable[[], Any],
    stop_container: Callable[[str], Any],
) -> None:
    with state.state_lock:
        existing = state.ttl_timers.pop(container_id, None)
    if existing:
        existing.cancel()

    def _timeout() -> None:
        logger.warning(f"[Engine] TTL expired for {container_id[:12]}, stopping...")
        emit_ws_activity(
            "container_ttl_expired",
            level="warn",
            message=f"TTL expired for {container_id[:12]}",
            container_id=container_id,
            ttl_seconds=seconds,
        )

        try:
            from mcp.client import call_tool as _mcp_call

            session_id = ""
            blueprint_id = "unknown"
            try:
                client = get_client()
                runtime_container = client.containers.get(container_id)
                runtime_container.reload()
                blueprint_id = runtime_container.labels.get("trion.blueprint", "unknown")
                session_id = runtime_container.labels.get("trion.session_id", "")
            except Exception:
                with state.state_lock:
                    in_memory = state.active.get(container_id)
                if in_memory:
                    blueprint_id = in_memory.blueprint_id
                    session_id = in_memory.session_id
            _mcp_call(
                "workspace_event_save",
                {
                    "conversation_id": "_container_events",
                    "event_type": "container_ttl_expired",
                    "event_data": {
                        "container_id": container_id,
                        "blueprint_id": blueprint_id,
                        "session_id": session_id,
                        "expired_at": datetime.utcnow().isoformat() + "Z",
                        "reason": "ttl_expired",
                        "ttl_seconds": seconds,
                    },
                },
            )
        except Exception as exc:
            logger.error(f"[Engine] Failed to write TTL event: {exc}")

        stop_container(container_id)

    timer = threading.Timer(seconds, _timeout)
    timer.daemon = True
    timer.start()
    with state.state_lock:
        state.ttl_timers[container_id] = timer


def recover_runtime_state(
    state: RuntimeStateRefs,
    *,
    get_client: Callable[[], Any],
    trion_label: str,
    set_ttl_timer: Callable[[str, int], None],
    update_quota_used: Callable[[], None],
    emit_ws_activity: Callable[..., None],
    logger: Any,
) -> dict:
    try:
        client = get_client()
    except Exception as exc:
        logger.error(f"[Engine] Recovery: Docker client unavailable: {exc}")
        return {"recovered": 0, "expired_on_startup": 0, "error": str(exc)}

    recovered = 0
    expired_on_startup = 0

    try:
        containers = client.containers.list(filters={"label": trion_label, "status": "running"})
    except Exception as exc:
        logger.error(f"[Engine] Recovery: Docker scan failed: {exc}")
        return {"recovered": 0, "expired_on_startup": 0, "error": str(exc)}

    now_epoch = int(time.time())

    for container in containers:
        container_id = container.id

        with state.state_lock:
            if container_id in state.active:
                continue

        labels = container.labels
        blueprint_id = labels.get("trion.blueprint", "unknown")
        started_at = labels.get("trion.started", "")
        session_id = labels.get("trion.session_id", "")
        volume_name = labels.get("trion.volume", "")

        try:
            ttl_seconds = int(labels.get("trion.ttl_seconds", "0") or "0")
            expires_at_epoch = int(labels.get("trion.expires_at", "0") or "0")
        except ValueError:
            ttl_seconds = 0
            expires_at_epoch = 0

        remaining = max(0, expires_at_epoch - now_epoch) if expires_at_epoch > 0 else 0

        try:
            host_config = container.attrs.get("HostConfig", {})
            mem_bytes = host_config.get("Memory", 0)
            mem_mb = mem_bytes / (1024 * 1024) if mem_bytes else 512.0
            nano_cpus = host_config.get("NanoCpus", 0)
            cpu_alloc = round(nano_cpus / 1e9, 2) if nano_cpus else 1.0
        except Exception:
            mem_mb = 512.0
            cpu_alloc = 1.0

        if ttl_seconds > 0 and remaining <= 0:
            logger.warning(
                f"[Engine] Recovery: {container_id[:12]} TTL elapsed "
                f"(ttl={ttl_seconds}s) — stopping at startup"
            )
            try:
                from mcp.client import call_tool as _mcp_call

                _mcp_call(
                    "workspace_event_save",
                    {
                        "conversation_id": "_container_events",
                        "event_type": "container_ttl_expired",
                        "event_data": {
                            "container_id": container_id,
                            "blueprint_id": blueprint_id,
                            "session_id": session_id,
                            "expired_at": datetime.utcnow().isoformat() + "Z",
                            "reason": "ttl_expired_at_startup",
                            "ttl_seconds": ttl_seconds,
                        },
                    },
                )
            except Exception as exc:
                logger.error(f"[Engine] Recovery: Failed to write TTL expiry event: {exc}")
            try:
                container.stop(timeout=5)
                container.remove(force=True)
            except Exception as exc:
                logger.error(f"[Engine] Recovery: Stop failed for {container_id[:12]}: {exc}")
            emit_ws_activity(
                "container_ttl_expired",
                level="warn",
                message=f"TTL expired on startup for {container_id[:12]}",
                container_id=container_id,
                blueprint_id=blueprint_id,
                reason="ttl_expired_at_startup",
                ttl_seconds=ttl_seconds,
            )
            expired_on_startup += 1
            continue

        instance = ContainerInstance(
            container_id=container_id,
            blueprint_id=blueprint_id,
            name=container.name,
            status=ContainerStatus.RUNNING,
            started_at=started_at,
            ttl_remaining=remaining if ttl_seconds > 0 else 0,
            memory_limit_mb=mem_mb,
            cpu_limit_alloc=cpu_alloc,
            volume_name=volume_name,
            session_id=session_id,
        )
        with state.state_lock:
            state.active[container_id] = instance

        if ttl_seconds > 0 and remaining > 0:
            set_ttl_timer(container_id, remaining)

        logger.info(
            f"[Engine] Recovery: registered {blueprint_id}/{container_id[:12]} "
            f"ttl_remaining={remaining}s"
        )
        recovered += 1

    update_quota_used()
    logger.info(
        f"[Engine] Recovery complete: "
        f"{recovered} recovered, {expired_on_startup} expired at startup"
    )
    return {"recovered": recovered, "expired_on_startup": expired_on_startup, "error": None}


def cleanup_all(
    state: RuntimeStateRefs,
    *,
    get_client: Callable[[], Any],
    trion_label: str,
    logger: Any,
) -> None:
    client = get_client()
    try:
        containers = client.containers.list(filters={"label": trion_label})
        for container in containers:
            try:
                container.stop(timeout=5)
                container.remove(force=True)
            except Exception:
                pass
        with state.state_lock:
            for timer in list(state.ttl_timers.values()):
                try:
                    timer.cancel()
                except Exception:
                    pass
            state.ttl_timers.clear()
            state.active.clear()
            update_quota_used_unlocked(state)
        logger.info("[Engine] Cleanup complete — all TRION containers removed")
    except Exception as exc:
        logger.error(f"[Engine] Cleanup failed: {exc}")
