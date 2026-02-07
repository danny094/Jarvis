"""
Container Commander — Engine (Lifecycle Manager)
═══════════════════════════════════════════════════
Docker SDK integration for container lifecycle:
- Build images from Blueprint Dockerfiles
- Start/Stop/Remove containers
- Execute commands inside running containers
- Stream logs
- Collect stats
- Auto-cleanup (TTL)

Uses docker.from_env() to connect to the host Docker daemon.
"""

import os
import io
import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple

import docker
from docker.errors import (
    DockerException, NotFound, APIError, BuildError, ImageNotFound
)

from .models import (
    Blueprint, ContainerInstance, ContainerStatus,
    ResourceLimits, NetworkMode, SessionQuota
)
from .blueprint_store import resolve_blueprint, log_action
from .secret_store import get_secrets_for_blueprint, log_secret_access

logger = logging.getLogger(__name__)


class PendingApprovalError(Exception):
    """Raised when a deploy requires user approval first."""
    def __init__(self, approval_id: str, reason: str):
        self.approval_id = approval_id
        self.reason = reason
        super().__init__(f"Approval required ({approval_id}): {reason}")

# ── Constants ─────────────────────────────────────────────

TRION_LABEL = "trion.managed"
TRION_PREFIX = "trion_"
NETWORK_NAME = "trion-sandbox"
DEFAULT_QUOTA = SessionQuota()


# ── Singleton Client ──────────────────────────────────────

_client: Optional[docker.DockerClient] = None
_lock = threading.Lock()


def get_client() -> docker.DockerClient:
    """Get or create the Docker client (singleton)."""
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                _client = docker.from_env()
                _ensure_network()
    return _client


def _ensure_network():
    """Create the trion-sandbox network if it doesn't exist."""
    client = _client
    try:
        client.networks.get(NETWORK_NAME)
    except NotFound:
        client.networks.create(
            NETWORK_NAME,
            driver="bridge",
            internal=True,  # No external access by default
            labels={TRION_LABEL: "true"}
        )
        logger.info(f"[Engine] Created network: {NETWORK_NAME}")


# ── Active Container Registry ─────────────────────────────

_active: Dict[str, ContainerInstance] = {}
_quota = SessionQuota()
_ttl_timers: Dict[str, threading.Timer] = {}


# ── Image Management ──────────────────────────────────────

def build_image(blueprint: Blueprint) -> str:
    """
    Build a Docker image from a Blueprint's Dockerfile.
    Returns the image tag.
    """
    client = get_client()
    tag = f"trion/{blueprint.id}:latest"

    if blueprint.image:
        # Pre-built image — just pull if needed
        try:
            client.images.get(blueprint.image)
        except ImageNotFound:
            logger.info(f"[Engine] Pulling image: {blueprint.image}")
            client.images.pull(blueprint.image)
        return blueprint.image

    if not blueprint.dockerfile:
        raise ValueError(f"Blueprint '{blueprint.id}' has no dockerfile and no image")

    logger.info(f"[Engine] Building image: {tag}")
    dockerfile_obj = io.BytesIO(blueprint.dockerfile.encode("utf-8"))

    try:
        image, build_logs = client.images.build(
            fileobj=dockerfile_obj,
            tag=tag,
            rm=True,
            forcerm=True,
            labels={TRION_LABEL: "true", "trion.blueprint": blueprint.id}
        )
        for chunk in build_logs:
            if "stream" in chunk:
                logger.debug(f"[Build] {chunk['stream'].strip()}")
        return tag
    except BuildError as e:
        logger.error(f"[Engine] Build failed for {blueprint.id}: {e}")
        raise


def image_exists(blueprint: Blueprint) -> bool:
    """Check if the image for a blueprint already exists."""
    client = get_client()
    tag = blueprint.image or f"trion/{blueprint.id}:latest"
    try:
        client.images.get(tag)
        return True
    except ImageNotFound:
        return False


# ── Container Lifecycle ───────────────────────────────────

def start_container(
    blueprint_id: str,
    override_resources: Optional[ResourceLimits] = None,
    extra_env: Optional[Dict[str, str]] = None,
    resume_volume: Optional[str] = None,
    _skip_approval: bool = False
) -> ContainerInstance:
    """
    Start a container from a blueprint.
    
    1. Resolve blueprint (with inheritance)
    2. Check quota
    3. Build/pull image
    4. Inject secrets
    5. Create + start container with resource limits
    6. Register TTL timer
    7. Return ContainerInstance
    """
    # 1. Resolve blueprint
    bp = resolve_blueprint(blueprint_id)
    if not bp:
        raise ValueError(f"Blueprint '{blueprint_id}' not found")

    # 1.5 Human-in-the-Loop check
    if not _skip_approval:
        from .approval import check_needs_approval, request_approval
        approval_reason = check_needs_approval(bp.network)
        if approval_reason:
            pending = request_approval(
                blueprint_id=blueprint_id,
                reason=approval_reason,
                network_mode=bp.network,
                override_resources=override_resources,
                extra_env=extra_env,
                resume_volume=resume_volume,
            )
            raise PendingApprovalError(pending.id, approval_reason)

    # 2. Check quota
    resources = override_resources or bp.resources
    _check_quota(resources)

    # 3. Build/pull image
    image_tag = build_image(bp)

    # 4. Inject secrets
    env_vars = {}
    if bp.secrets_required:
        secrets_list = [s.model_dump() for s in bp.secrets_required]
        env_vars = get_secrets_for_blueprint(blueprint_id, secrets_list)
        for name in env_vars:
            log_secret_access(name, "inject", "", blueprint_id)

    if extra_env:
        env_vars.update(extra_env)

    # 5. Create container
    client = get_client()
    container_name = f"{TRION_PREFIX}{blueprint_id}_{int(time.time())}"
    # Volume: reuse existing or create new
    if resume_volume:
        volume_name = resume_volume
        logger.info(f"[Engine] Resuming with existing volume: {volume_name}")
    else:
        volume_name = f"trion_ws_{blueprint_id}_{int(time.time())}"

    # Create workspace volume (skip if resuming)
    if not resume_volume:
        client.volumes.create(name=volume_name, labels={TRION_LABEL: "true"})

    # Build mount config
    volumes = {volume_name: {"bind": "/workspace", "mode": "rw"}}
    for mount in bp.mounts:
        host_path = os.path.abspath(mount.host)
        volumes[host_path] = {"bind": mount.container, "mode": mount.mode}

    # Network mode
    # Network isolation
    from .network import resolve_network as net_resolve
    net_info = net_resolve(bp.network, container_name)
    network_mode = net_info["network"]

    # Resource limits
    mem_bytes = _parse_memory(resources.memory_limit)
    swap_bytes = _parse_memory(resources.memory_swap)

    try:
        container = client.containers.run(
            image_tag,
            detach=True,
            name=container_name,
            environment=env_vars,
            volumes=volumes,
            network=network_mode,
            labels={
                TRION_LABEL: "true",
                "trion.blueprint": blueprint_id,
                "trion.volume": volume_name,
                "trion.started": datetime.utcnow().isoformat(),
            },
            # Resource limits
            cpu_period=100000,
            cpu_quota=int(float(resources.cpu_limit) * 100000),
            mem_limit=mem_bytes,
            memswap_limit=swap_bytes,
            pids_limit=resources.pids_limit,
            # Safety
            stdin_open=True,
            tty=False,
            auto_remove=False,
        )
    except APIError as e:
        # Cleanup volume on failure
        try:
            client.volumes.get(volume_name).remove()
        except Exception:
            pass
        raise RuntimeError(f"Container start failed: {e}")

    # 6. Register
    instance = ContainerInstance(
        container_id=container.id,
        blueprint_id=blueprint_id,
        name=container_name,
        status=ContainerStatus.RUNNING,
        memory_limit_mb=mem_bytes / (1024 * 1024),
        started_at=datetime.utcnow().isoformat(),
        ttl_remaining=resources.timeout_seconds,
        cpu_limit_alloc=float(resources.cpu_limit),
        volume_name=volume_name,
    )

    _active[container.id] = instance
    _update_quota_used()

    # 7. TTL timer
    if resources.timeout_seconds > 0:
        _set_ttl_timer(container.id, resources.timeout_seconds)

    # Add network info to instance for API response
    instance.network_info = net_info
    log_action(container.id, blueprint_id, "start",
               f"image={image_tag}, mem={resources.memory_limit}, cpu={resources.cpu_limit}")

    logger.info(f"[Engine] Started: {container_name} ({container.short_id})")
    return instance


def stop_container(container_id: str, remove: bool = True) -> bool:
    """Stop a running container and optionally remove it."""
    client = get_client()
    try:
        container = client.containers.get(container_id)
        blueprint_id = container.labels.get("trion.blueprint", "unknown")

        container.stop(timeout=10)
        if remove:
            container.remove(force=True)

        # Cancel TTL timer
        timer = _ttl_timers.pop(container_id, None)
        if timer:
            timer.cancel()

        # Update registry
        if container_id in _active:
            _active[container_id].status = ContainerStatus.STOPPED
            del _active[container_id]

        _update_quota_used()
        log_action(container_id, blueprint_id, "stop")
        logger.info(f"[Engine] Stopped: {container_id[:12]}")
        return True

    except NotFound:
        _active.pop(container_id, None)
        return False
    except Exception as e:
        logger.error(f"[Engine] Stop failed: {e}")
        return False


def exec_in_container(container_id: str, command: str, timeout: int = 30) -> Tuple[int, str]:
    """
    Execute a command inside a running container.
    Returns: (exit_code, output)
    """
    client = get_client()
    try:
        container = client.containers.get(container_id)
        if container.status != "running":
            return (-1, f"Container is not running (status: {container.status})")

        exec_result = container.exec_run(
            command,
            demux=True,
            workdir="/workspace",
        )

        stdout = (exec_result.output[0] or b"").decode("utf-8", errors="replace") if exec_result.output[0] else ""
        stderr = (exec_result.output[1] or b"").decode("utf-8", errors="replace") if exec_result.output[1] else ""
        output = stdout + ("\n" + stderr if stderr else "")

        log_action(container_id, "", "exec", command[:200])
        return (exec_result.exit_code, output.strip())

    except NotFound:
        return (-1, "Container not found")
    except Exception as e:
        return (-1, f"Exec error: {str(e)}")


def get_container_logs(container_id: str, tail: int = 100) -> str:
    """Get logs from a container."""
    client = get_client()
    try:
        container = client.containers.get(container_id)
        logs = container.logs(tail=tail, timestamps=True).decode("utf-8", errors="replace")
        return logs
    except NotFound:
        return "Container not found"
    except Exception as e:
        return f"Error: {str(e)}"


def get_container_stats(container_id: str) -> Dict:
    """Get live resource stats from a container."""
    client = get_client()
    try:
        container = client.containers.get(container_id)
        stats = container.stats(stream=False)

        # Parse CPU
        cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - \
                    stats["precpu_stats"]["cpu_usage"]["total_usage"]
        system_delta = stats["cpu_stats"]["system_cpu_usage"] - \
                       stats["precpu_stats"]["system_cpu_usage"]
        num_cpus = stats["cpu_stats"].get("online_cpus", 1)
        cpu_percent = (cpu_delta / system_delta) * num_cpus * 100.0 if system_delta > 0 else 0.0

        # Parse Memory
        mem_usage = stats["memory_stats"].get("usage", 0)
        mem_limit = stats["memory_stats"].get("limit", 1)
        mem_mb = mem_usage / (1024 * 1024)

        # Parse Network
        net_rx = sum(v.get("rx_bytes", 0) for v in stats.get("networks", {}).values())
        net_tx = sum(v.get("tx_bytes", 0) for v in stats.get("networks", {}).values())

        # Update active instance
        instance = _active.get(container_id)
        if instance:
            instance.cpu_percent = round(cpu_percent, 1)
            instance.memory_mb = round(mem_mb, 1)
            instance.network_rx_bytes = net_rx
            instance.network_tx_bytes = net_tx

            started = instance.started_at
            if started:
                runtime = (datetime.utcnow() - datetime.fromisoformat(started)).total_seconds()
                instance.runtime_seconds = int(runtime)

            # Efficiency score
            instance.efficiency_score, instance.efficiency_level = _calc_efficiency(instance)

        return {
            "container_id": container_id,
            "cpu_percent": round(cpu_percent, 1),
            "memory_mb": round(mem_mb, 1),
            "memory_limit_mb": round(mem_limit / (1024 * 1024), 1),
            "network_rx_bytes": net_rx,
            "network_tx_bytes": net_tx,
            "efficiency": {
                "score": instance.efficiency_score if instance else 0,
                "level": instance.efficiency_level if instance else "green",
            }
        }

    except NotFound:
        return {"error": "Container not found"}
    except Exception as e:
        return {"error": str(e)}


# ── List Containers ───────────────────────────────────────

def list_containers() -> List[ContainerInstance]:
    """List all TRION-managed containers."""
    client = get_client()
    result = []

    try:
        containers = client.containers.list(
            all=True,
            filters={"label": TRION_LABEL}
        )

        for c in containers:
            bp_id = c.labels.get("trion.blueprint", "unknown")
            vol = c.labels.get("trion.volume", "")
            started = c.labels.get("trion.started", "")

            status = ContainerStatus.RUNNING if c.status == "running" else \
                     ContainerStatus.STOPPED if c.status in ("exited", "dead") else \
                     ContainerStatus.ERROR

            instance = _active.get(c.id, ContainerInstance(
                container_id=c.id,
                blueprint_id=bp_id,
                name=c.name,
                status=status,
                started_at=started,
                volume_name=vol,
            ))
            instance.status = status
            result.append(instance)

    except Exception as e:
        logger.error(f"[Engine] List containers failed: {e}")

    return result


# ── Quota Management ──────────────────────────────────────

def get_quota() -> SessionQuota:
    """Get current quota usage."""
    return _quota


def _check_quota(resources: ResourceLimits):
    """Raise if starting a new container would exceed quota."""
    if len(_active) >= _quota.max_containers:
        raise RuntimeError(
            f"Container quota exceeded: {len(_active)}/{_quota.max_containers} running"
        )

    mem_mb = _parse_memory(resources.memory_limit) / (1024 * 1024)
    if _quota.memory_used_mb + mem_mb > _quota.max_total_memory_mb:
        raise RuntimeError(
            f"Memory quota exceeded: {_quota.memory_used_mb}+{int(mem_mb)} > {_quota.max_total_memory_mb} MB"
        )

    cpu = float(resources.cpu_limit)
    if _quota.cpu_used + cpu > _quota.max_total_cpu:
        raise RuntimeError(
            f"CPU quota exceeded: {_quota.cpu_used}+{cpu} > {_quota.max_total_cpu}"
        )


def _update_quota_used():
    """Recalculate quota usage from active containers."""
    _quota.containers_used = len(_active)
    _quota.memory_used_mb = sum(i.memory_limit_mb for i in _active.values())
    _quota.cpu_used = sum(i.cpu_limit_alloc for i in _active.values())


# ── TTL / Auto-Cleanup ───────────────────────────────────

def _set_ttl_timer(container_id: str, seconds: int):
    """Set an auto-kill timer for a container."""
    def _timeout():
        logger.warning(f"[Engine] TTL expired for {container_id[:12]}, stopping...")
        stop_container(container_id)

    timer = threading.Timer(seconds, _timeout)
    timer.daemon = True
    timer.start()
    _ttl_timers[container_id] = timer


def cleanup_all():
    """Stop and remove all TRION-managed containers."""
    client = get_client()
    try:
        containers = client.containers.list(filters={"label": TRION_LABEL})
        for c in containers:
            try:
                c.stop(timeout=5)
                c.remove(force=True)
            except Exception:
                pass
        _active.clear()
        _update_quota_used()
        logger.info(f"[Engine] Cleanup complete — all TRION containers removed")
    except Exception as e:
        logger.error(f"[Engine] Cleanup failed: {e}")


# ── Efficiency Score ──────────────────────────────────────

def _calc_efficiency(instance: ContainerInstance) -> Tuple[float, str]:
    """
    Calculate efficiency score based on resource usage and runtime.
    Score: 0.0 (bad) to 1.0 (good)
    """
    runtime = instance.runtime_seconds
    cpu = instance.cpu_percent
    mem_pct = (instance.memory_mb / instance.memory_limit_mb * 100) if instance.memory_limit_mb > 0 else 0

    score = 1.0

    # Penalize long idle containers
    if runtime > 300 and cpu < 1.0:
        score -= 0.3
    elif runtime > 600 and cpu < 5.0:
        score -= 0.5

    # Penalize high memory with low CPU (likely idle)
    if mem_pct > 80 and cpu < 2.0:
        score -= 0.2

    score = max(0.0, min(1.0, score))

    if score >= 0.7:
        level = "green"
    elif score >= 0.4:
        level = "yellow"
    else:
        level = "red"

    return round(score, 2), level


# ── Network Resolution ────────────────────────────────────

def _resolve_network(mode: NetworkMode) -> str:
    """Resolve NetworkMode to Docker network name."""
    if mode == NetworkMode.NONE:
        return "none"
    elif mode == NetworkMode.INTERNAL:
        return NETWORK_NAME
    elif mode == NetworkMode.BRIDGE:
        return "bridge"
    elif mode == NetworkMode.FULL:
        return "bridge"  # Same as bridge but noted for Human-in-the-Loop
    return NETWORK_NAME


# ── Helpers ───────────────────────────────────────────────

def _parse_memory(mem_str: str) -> int:
    """Parse memory string like '512m', '2g' to bytes."""
    mem_str = mem_str.strip().lower()
    if mem_str.endswith("g"):
        return int(float(mem_str[:-1]) * 1024 * 1024 * 1024)
    elif mem_str.endswith("m"):
        return int(float(mem_str[:-1]) * 1024 * 1024)
    elif mem_str.endswith("k"):
        return int(float(mem_str[:-1]) * 1024)
    return int(mem_str)
