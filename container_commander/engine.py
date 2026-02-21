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


class PolicyViolationError(Exception):
    """Raised when a command is blocked by the Blueprint's exec policy."""
    def __init__(self, command: str, allowed: list, blueprint_id: str):
        self.command = command
        self.allowed = allowed
        self.blueprint_id = blueprint_id
        super().__init__(
            f"policy_denied: '{command.split()[0] if command else '?'}' not in allowed_exec "
            f"for '{blueprint_id}'. Allowed: {allowed}"
        )

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
    _skip_approval: bool = False,
    session_id: str = "",
    conversation_id: str = "",
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
                session_id=session_id,
                conversation_id=conversation_id,
            )
            raise PendingApprovalError(pending.id, approval_reason)

    # 2. Check quota
    resources = override_resources or bp.resources
    _check_quota(resources)

    # 3. Trust Gate — Digest Pinning (opt-in, fail closed for pinned blueprints)
    # Must run BEFORE build_image() to prevent pulling an untrusted image.
    from .trust import check_digest_policy
    _digest_policy = check_digest_policy(bp)
    if not _digest_policy["allowed"]:
        # Audit: write trust_blocked event before raising
        try:
            from mcp.client import call_tool as _mcp_call
            import json as _json
            _mcp_call("workspace_event_save", {
                "conversation_id": "_container_events",
                "event_type": "trust_blocked",
                "event_data": {
                    "blueprint_id": blueprint_id,
                    "image": bp.image or "",
                    "pinned_digest": bp.image_digest,
                    "actual_digest": _digest_policy.get("actual_digest"),
                    "reason": _digest_policy["reason"],
                    "blocked_at": datetime.utcnow().isoformat() + "Z",
                },
            })
        except Exception:
            pass
        raise RuntimeError(_digest_policy["reason"])
    elif _digest_policy["mode"] == "unpinned_warn":
        logger.warning(f"[Engine] {_digest_policy['reason']}")

    # 3.1 Signature Verify (P6-A) — mode-aware: off | opt_in | strict
    # Only for image-based blueprints; Dockerfile builds have no registry image to verify.
    if bp.image:
        from .trust import verify_image_signature
        _sig_result = verify_image_signature(bp.image)
        if not _sig_result["verified"]:
            # Audit event (non-critical — don't let MCP failure hide the block)
            try:
                from mcp.client import call_tool as _mcp_call
                _mcp_call("workspace_event_save", {
                    "conversation_id": "_container_events",
                    "event_type": "signature_blocked",
                    "event_data": {
                        "blueprint_id": blueprint_id,
                        "image": bp.image,
                        "mode": _sig_result["mode"],
                        "reason": _sig_result["reason"],
                        "tool": _sig_result.get("tool"),
                        "blocked_at": datetime.utcnow().isoformat() + "Z",
                    },
                })
            except Exception:
                pass
            raise RuntimeError(f"[Signature-Block] {_sig_result['reason']}")
        elif _sig_result["mode"] != "off":
            logger.info("[Engine] Signature OK: %s", _sig_result["reason"])

    # 3.5 Build/pull image (after trust gate — avoids pulling untrusted images)
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
        # Compute durable TTL metadata (persisted in Docker labels for recovery)
        _ttl_secs = resources.timeout_seconds
        _expires_epoch = (int(time.time()) + _ttl_secs) if _ttl_secs > 0 else 0

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
                "trion.session_id": session_id or "",
                "trion.conversation_id": conversation_id or "",
                # Phase 4: Durable TTL — survives service restart
                "trion.ttl_seconds": str(_ttl_secs),
                "trion.expires_at": str(_expires_epoch),
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
        session_id=session_id or "",
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


MAX_EXEC_OUTPUT = 8000  # chars per stream before truncation


def _check_exec_policy(container, command: str):
    """
    Enforce blueprint's allowed_exec policy.
    Raises PolicyViolationError if command prefix is not allowed.
    Empty allowed_exec = no restriction (backward compat).
    """
    blueprint_id = container.labels.get("trion.blueprint", "")
    if not blueprint_id:
        return
    try:
        from .blueprint_store import get_blueprint as _get_bp
        bp = _get_bp(blueprint_id)
        if bp is None:
            # Blueprint was soft-deleted or not found — fail closed: deny exec
            raise PolicyViolationError(
                command, [], blueprint_id
            )
        if bp.allowed_exec:
            cmd_prefix = command.strip().split()[0] if command.strip() else ""
            if cmd_prefix not in bp.allowed_exec:
                raise PolicyViolationError(command, bp.allowed_exec, blueprint_id)
    except PolicyViolationError:
        raise
    except Exception as _e:
        # Policy check itself failed (e.g. DB error) — fail closed: deny exec
        logger.error(f"[Engine] Policy check failed for {blueprint_id}: {_e} — DENYING exec (fail closed)")
        raise PolicyViolationError(command, [], blueprint_id) from _e


def exec_in_container(container_id: str, command: str, timeout: int = 30) -> Tuple[int, str]:
    """
    Execute a command inside a running container.
    Returns: (exit_code, combined_output)
    Raises PolicyViolationError if command is not in blueprint's allowed_exec list.
    """
    client = get_client()
    try:
        container = client.containers.get(container_id)
        if container.status != "running":
            return (-1, f"Container is not running (status: {container.status})")

        _check_exec_policy(container, command)

        exec_result = container.exec_run(command, demux=True, workdir="/workspace")
        stdout = (exec_result.output[0] or b"").decode("utf-8", errors="replace") if exec_result.output[0] else ""
        stderr = (exec_result.output[1] or b"").decode("utf-8", errors="replace") if exec_result.output[1] else ""
        output = stdout + ("\n" + stderr if stderr else "")

        log_action(container_id, "", "exec", command[:200])
        return (exec_result.exit_code, output.strip())

    except PolicyViolationError:
        raise
    except NotFound:
        return (-1, "Container not found")
    except Exception as e:
        return (-1, f"Exec error: {str(e)}")


def exec_in_container_detailed(
    container_id: str, command: str, timeout: int = 30
) -> Dict:
    """
    Execute a command with structured output (for MCP tool use).
    Returns: {exit_code, stdout, stderr, truncated, container_id}
    Raises PolicyViolationError if command is not in blueprint's allowed_exec list.
    """
    client = get_client()
    try:
        container = client.containers.get(container_id)
        if container.status != "running":
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Container is not running (status: {container.status})",
                "truncated": False,
                "container_id": container_id,
            }

        _check_exec_policy(container, command)

        exec_result = container.exec_run(command, demux=True, workdir="/workspace")
        stdout = (exec_result.output[0] or b"").decode("utf-8", errors="replace") if exec_result.output[0] else ""
        stderr = (exec_result.output[1] or b"").decode("utf-8", errors="replace") if exec_result.output[1] else ""

        truncated = len(stdout) > MAX_EXEC_OUTPUT or len(stderr) > MAX_EXEC_OUTPUT
        stdout = stdout[:MAX_EXEC_OUTPUT].strip()
        stderr = stderr[:MAX_EXEC_OUTPUT].strip()

        log_action(container_id, "", "exec", command[:200])
        return {
            "exit_code": exec_result.exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "truncated": truncated,
            "container_id": container_id,
        }

    except PolicyViolationError:
        raise
    except NotFound:
        return {"exit_code": -1, "stdout": "", "stderr": "Container not found",
                "truncated": False, "container_id": container_id}
    except Exception as e:
        return {"exit_code": -1, "stdout": "", "stderr": f"Exec error: {str(e)}",
                "truncated": False, "container_id": container_id}


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


def inspect_container(container_id: str) -> Dict:
    """
    Return detailed information about a specific TRION container.
    Pulls from Docker SDK attrs + in-memory _active registry.
    Returns a clean dict (not raw Docker API response).
    """
    client = get_client()
    try:
        c = client.containers.get(container_id)
        attrs = c.attrs

        state = attrs.get("State", {})
        config = attrs.get("Config", {})
        host_config = attrs.get("HostConfig", {})
        network_settings = attrs.get("NetworkSettings", {})

        mem_bytes = host_config.get("Memory", 0)
        mem_mb = round(mem_bytes / (1024 * 1024), 1) if mem_bytes else None

        nano_cpus = host_config.get("NanoCpus", 0)
        cpu_count = round(nano_cpus / 1e9, 2) if nano_cpus else None

        networks = network_settings.get("Networks", {})
        ip_address = next(
            (v.get("IPAddress") for v in networks.values() if v.get("IPAddress")),
            None
        )

        mounts = [
            f"{m.get('Source', '?')}:{m.get('Destination', '?')}"
            for m in attrs.get("Mounts", [])
            if m.get("Type") == "volume"
        ]

        labels = c.labels
        blueprint_id = labels.get("trion.blueprint", "unknown")

        in_memory = _active.get(c.id)
        ttl_remaining = int(in_memory.ttl_remaining) if in_memory and in_memory.ttl_remaining else None

        return {
            "container_id": c.id,
            "short_id": c.short_id,
            "name": c.name,
            "blueprint_id": blueprint_id,
            "image": config.get("Image", ""),
            "status": state.get("Status", "unknown"),
            "running": state.get("Running", False),
            "exit_code": state.get("ExitCode") if not state.get("Running") else None,
            "started_at": state.get("StartedAt", ""),
            "finished_at": state.get("FinishedAt", "") if not state.get("Running") else None,
            "ip_address": ip_address,
            "network": list(networks.keys())[0] if networks else None,
            "mounts": mounts,
            "resource_limits": {
                "memory_mb": mem_mb,
                "cpu_count": cpu_count,
            },
            "ttl_remaining_seconds": ttl_remaining,
            "volume": labels.get("trion.volume", ""),
        }

    except Exception as e:
        logger.error(f"[Engine] Inspect container failed ({container_id}): {e}")
        return {"error": str(e), "container_id": container_id}


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
    """Set an auto-kill timer for a container. Idempotent: cancels any existing timer first."""
    # Cancel existing timer before arming (safe for recovery path / rearm)
    existing = _ttl_timers.pop(container_id, None)
    if existing:
        existing.cancel()

    def _timeout():
        logger.warning(f"[Engine] TTL expired for {container_id[:12]}, stopping...")

        # Write ttl_expired event to _container_events (same pattern as blueprint_store sync)
        try:
            from mcp.client import call_tool as _mcp_call
            import json as _json
            # Prefer Docker labels (durable, survives _active eviction) over in-memory registry
            _cli = get_client()
            _sess_id = ""
            _bp_id = "unknown"
            try:
                _c = _cli.containers.get(container_id)
                _c.reload()  # Refresh stale cached attrs
                _bp_id = _c.labels.get("trion.blueprint", "unknown")
                _sess_id = _c.labels.get("trion.session_id", "")
            except Exception:
                # Fallback to in-memory registry if container already removed
                in_mem = _active.get(container_id)
                if in_mem:
                    _bp_id = in_mem.blueprint_id
                    _sess_id = in_mem.session_id
            _mcp_call("workspace_event_save", {
                "conversation_id": "_container_events",
                "event_type": "container_ttl_expired",
                "event_data": {
                    "container_id": container_id,
                    "blueprint_id": _bp_id,
                    "session_id": _sess_id,
                    "expired_at": datetime.utcnow().isoformat() + "Z",
                    "reason": "ttl_expired",
                    "ttl_seconds": seconds,
                },
            })
        except Exception as _e:
            logger.error(f"[Engine] Failed to write TTL event: {_e}")

        stop_container(container_id)

    timer = threading.Timer(seconds, _timeout)
    timer.daemon = True
    timer.start()
    _ttl_timers[container_id] = timer


def recover_runtime_state() -> dict:
    """
    Scan Docker for running TRION containers and rebuild _active + TTL timers.

    Called once at startup to restore in-memory state after a service restart.
    Idempotent: containers already in _active are skipped.

    Decision rules per running container:
      TTL > 0 and remaining > 0  → register in _active, rearm timer with remaining time
      TTL > 0 and remaining <= 0 → emit container_ttl_expired event, stop + remove
      TTL = 0                    → register in _active, no timer
      not running                → skip (filtered by Docker query)

    Returns:
        dict with keys: recovered (int), expired_on_startup (int), error (str|None)
    """
    try:
        client = get_client()
    except Exception as e:
        logger.error(f"[Engine] Recovery: Docker client unavailable: {e}")
        return {"recovered": 0, "expired_on_startup": 0, "error": str(e)}

    recovered = 0
    expired_on_startup = 0

    try:
        containers = client.containers.list(
            filters={"label": TRION_LABEL, "status": "running"}
        )
    except Exception as e:
        logger.error(f"[Engine] Recovery: Docker scan failed: {e}")
        return {"recovered": 0, "expired_on_startup": 0, "error": str(e)}

    now_epoch = int(time.time())

    for c in containers:
        container_id = c.id

        # Idempotent: skip containers already registered in _active
        if container_id in _active:
            continue

        labels = c.labels
        bp_id       = labels.get("trion.blueprint", "unknown")
        started_at  = labels.get("trion.started", "")
        session_id  = labels.get("trion.session_id", "")
        vol_name    = labels.get("trion.volume", "")

        # Parse durable TTL metadata (written by Commit A)
        try:
            ttl_seconds     = int(labels.get("trion.ttl_seconds", "0") or "0")
            expires_at_epoch = int(labels.get("trion.expires_at", "0") or "0")
        except ValueError:
            ttl_seconds     = 0
            expires_at_epoch = 0

        remaining = max(0, expires_at_epoch - now_epoch) if expires_at_epoch > 0 else 0

        # Recover resource info from Docker host config for quota recalculation
        try:
            host_config = c.attrs.get("HostConfig", {})
            mem_bytes   = host_config.get("Memory", 0)
            mem_mb      = mem_bytes / (1024 * 1024) if mem_bytes else 512.0
            nano_cpus   = host_config.get("NanoCpus", 0)
            cpu_alloc   = round(nano_cpus / 1e9, 2) if nano_cpus else 1.0
        except Exception:
            mem_mb    = 512.0
            cpu_alloc = 1.0

        if ttl_seconds > 0 and remaining <= 0:
            # Container TTL already elapsed — emit expiry event and stop
            logger.warning(
                f"[Engine] Recovery: {container_id[:12]} TTL elapsed "
                f"(ttl={ttl_seconds}s) — stopping at startup"
            )
            try:
                from mcp.client import call_tool as _mcp_call
                _mcp_call("workspace_event_save", {
                    "conversation_id": "_container_events",
                    "event_type": "container_ttl_expired",
                    "event_data": {
                        "container_id": container_id,
                        "blueprint_id": bp_id,
                        "session_id": session_id,
                        "expired_at": datetime.utcnow().isoformat() + "Z",
                        "reason": "ttl_expired_at_startup",
                        "ttl_seconds": ttl_seconds,
                    },
                })
            except Exception as _e:
                logger.error(f"[Engine] Recovery: Failed to write TTL expiry event: {_e}")
            try:
                c.stop(timeout=5)
                c.remove(force=True)
            except Exception as _e:
                logger.error(f"[Engine] Recovery: Stop failed for {container_id[:12]}: {_e}")
            expired_on_startup += 1
            continue

        # Register in _active
        instance = ContainerInstance(
            container_id=container_id,
            blueprint_id=bp_id,
            name=c.name,
            status=ContainerStatus.RUNNING,
            started_at=started_at,
            ttl_remaining=remaining if ttl_seconds > 0 else 0,
            memory_limit_mb=mem_mb,
            cpu_limit_alloc=cpu_alloc,
            volume_name=vol_name,
            session_id=session_id,
        )
        _active[container_id] = instance

        # Rearm TTL timer with the remaining time (not the original TTL)
        if ttl_seconds > 0 and remaining > 0:
            _set_ttl_timer(container_id, remaining)

        logger.info(
            f"[Engine] Recovery: registered {bp_id}/{container_id[:12]} "
            f"ttl_remaining={remaining}s"
        )
        recovered += 1

    _update_quota_used()
    logger.info(
        f"[Engine] Recovery complete: "
        f"{recovered} recovered, {expired_on_startup} expired at startup"
    )
    return {"recovered": recovered, "expired_on_startup": expired_on_startup, "error": None}


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
