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
import shlex
import uuid
import json
import hashlib
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple, Any

import docker
from docker.errors import (
    DockerException, NotFound, APIError, BuildError, ImageNotFound
)

from .models import (
    Blueprint, ContainerInstance, ContainerStatus,
    ResourceLimits, NetworkMode, SessionQuota, SecretScope, MountDef
)
from .blueprint_store import resolve_blueprint, log_action
from .secret_store import get_secrets_for_blueprint, get_secret_value, log_secret_access

logger = logging.getLogger(__name__)


def _emit_ws_activity(event: str, level: str = "info", message: str = "", **data):
    """Best-effort websocket activity event emitter (never blocks container flow)."""
    try:
        from .ws_stream import emit_activity

        emit_activity(event, level=level, message=message, **data)
    except Exception as e:
        logger.debug(f"[Engine] WS activity emit failed ({event}): {e}")


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
_state_lock = threading.RLock()
_pending_starts = 0
_pending_memory_mb = 0.0
_pending_cpu = 0.0


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
    mount_overrides: Optional[List[Dict[str, Any]]] = None,
    storage_scope_override: Optional[str] = None,
    device_overrides: Optional[List[str]] = None,
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

    # Runtime-only mount overrides (e.g. managed path picker in deploy preflight).
    # Overrides are not persisted into blueprint storage.
    runtime_mount_overrides = _normalize_runtime_mount_overrides(mount_overrides)
    runtime_device_overrides = _normalize_runtime_device_overrides(device_overrides)
    scope_override = str(storage_scope_override or "").strip()
    force_auto_scope = scope_override.lower() in {"__auto__", "auto"}
    if force_auto_scope:
        scope_override = ""
    if runtime_mount_overrides or runtime_device_overrides or scope_override:
        bp = _compose_runtime_blueprint(
            bp,
            runtime_mount_overrides=runtime_mount_overrides,
            runtime_device_overrides=runtime_device_overrides,
            storage_scope_override=scope_override,
            force_auto_scope=force_auto_scope,
        )

    # Storage scope enforcement for host bind mounts (fail closed).
    from .storage_scope import validate_blueprint_mounts

    mounts_ok, mounts_reason = validate_blueprint_mounts(bp)
    if not mounts_ok:
        raise RuntimeError(mounts_reason)

    _emit_ws_activity(
        "deploy_start",
        level="info",
        message=f"Deploy requested for {blueprint_id}",
        blueprint_id=blueprint_id,
        network_mode=bp.network.value,
        session_id=session_id or "",
        conversation_id=conversation_id or "",
    )

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
                mount_overrides=mount_overrides,
                storage_scope_override=storage_scope_override,
                device_overrides=device_overrides,
                session_id=session_id,
                conversation_id=conversation_id,
            )
            raise PendingApprovalError(pending.id, approval_reason)

    resources = override_resources or bp.resources

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
        _emit_ws_activity(
            "trust_block",
            level="error",
            message=_digest_policy["reason"],
            blueprint_id=blueprint_id,
            image=bp.image or "",
            pinned_digest=bp.image_digest or "",
            actual_digest=_digest_policy.get("actual_digest"),
        )
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
            _emit_ws_activity(
                "trust_block",
                level="error",
                message=_sig_result["reason"],
                blueprint_id=blueprint_id,
                image=bp.image,
                mode=_sig_result.get("mode", ""),
                source="signature",
            )
            raise RuntimeError(f"[Signature-Block] {_sig_result['reason']}")
        elif _sig_result["mode"] != "off":
            logger.info("[Engine] Signature OK: %s", _sig_result["reason"])

    # Reserve quota before potentially expensive build/start to avoid race conditions.
    reserved_mem_mb, reserved_cpu = _reserve_quota(resources)
    reservation_active = True
    try:
        # 3.5 Build/pull image (after trust gate — avoids pulling untrusted images)
        image_tag = build_image(bp)

        # 4. Inject environment + secrets
        env_vars = {}
        for key, value in dict(bp.environment or {}).items():
            env_name = str(key)
            env_value = str(value)
            if env_value.startswith("vault://"):
                secret_name = env_value[len("vault://"):].strip()
                if not secret_name:
                    raise RuntimeError(f"invalid_vault_ref: empty secret reference for env '{env_name}'")
                secret_value = get_secret_value(secret_name, SecretScope.BLUEPRINT, blueprint_id)
                if secret_value is None:
                    secret_value = get_secret_value(secret_name, SecretScope.GLOBAL)
                if secret_value is None:
                    raise RuntimeError(
                        f"vault_ref_not_found: '{secret_name}' for env '{env_name}' in blueprint '{blueprint_id}'"
                    )
                env_vars[env_name] = secret_value
                log_secret_access(secret_name, "inject_vault_ref", "", blueprint_id)
            else:
                env_vars[env_name] = env_value
        if bp.secrets_required:
            secrets_list = [s.model_dump() for s in bp.secrets_required]
            secret_env_vars = get_secrets_for_blueprint(blueprint_id, secrets_list)
            env_vars.update(secret_env_vars)
            for name in secret_env_vars:
                log_secret_access(name, "inject", "", blueprint_id)

        if extra_env:
            env_vars.update(extra_env)

        # 5. Create container
        client = get_client()
        runtime_ok, runtime_reason = _validate_runtime_preflight(client, bp.runtime)
        if not runtime_ok:
            raise RuntimeError(runtime_reason)
        unique_suffix = _unique_runtime_suffix()
        container_name = f"{TRION_PREFIX}{blueprint_id}_{unique_suffix}"
        # Volume: reuse existing or create new
        if resume_volume:
            volume_name = resume_volume
            logger.info(f"[Engine] Resuming with existing volume: {volume_name}")
        else:
            volume_name = f"trion_ws_{blueprint_id}_{unique_suffix}"

        # Create workspace volume (skip if resuming)
        created_workspace_volume = not bool(resume_volume)
        if created_workspace_volume:
            client.volumes.create(name=volume_name, labels={TRION_LABEL: "true"})

        # Build mount config
        volumes = {volume_name: {"bind": "/workspace", "mode": "rw"}}
        for mount in bp.mounts:
            mount_type = str(getattr(mount, "type", "bind") or "bind").strip().lower()
            host_path = mount.host if mount_type == "volume" else os.path.abspath(mount.host)
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
            port_bindings = _build_port_bindings(bp.ports)
        except ValueError as e:
            raise RuntimeError(f"invalid_port_mapping: {e}") from e
        healthcheck = _build_healthcheck_config(bp.healthcheck)
        if port_bindings:
            from .port_manager import validate_port_bindings

            conflicts = validate_port_bindings(port_bindings)
            if conflicts:
                details = ", ".join(
                    f"{c.get('host_port')}/{c.get('protocol')} ({c.get('reason', 'occupied')})"
                    for c in conflicts[:3]
                )
                raise RuntimeError(f"port_conflict_precheck_failed: {details}")

        try:
            # Compute durable TTL metadata (persisted in Docker labels for recovery)
            _ttl_secs = resources.timeout_seconds
            _expires_epoch = (int(time.time()) + _ttl_secs) if _ttl_secs > 0 else 0

            run_kwargs = {
                "image": image_tag,
                "detach": True,
                "name": container_name,
                "environment": env_vars,
                "volumes": volumes,
                "network": network_mode,
                "labels": {
                    TRION_LABEL: "true",
                    "trion.blueprint": blueprint_id,
                    "trion.volume": volume_name,
                    "trion.started": datetime.utcnow().isoformat(),
                    "trion.session_id": session_id or "",
                    "trion.conversation_id": conversation_id or "",
                    "trion.port_bindings": json.dumps(port_bindings) if port_bindings else "",
                    # Phase 4: Durable TTL — survives service restart
                    "trion.ttl_seconds": str(_ttl_secs),
                    "trion.expires_at": str(_expires_epoch),
                },
                # Resource limits
                "cpu_period": 100000,
                "cpu_quota": int(float(resources.cpu_limit) * 100000),
                "mem_limit": mem_bytes,
                "memswap_limit": swap_bytes,
                "pids_limit": resources.pids_limit,
                # Safety
                "stdin_open": True,
                "tty": False,
                "auto_remove": False,
            }
            if port_bindings:
                run_kwargs["ports"] = port_bindings
            if bp.runtime:
                run_kwargs["runtime"] = bp.runtime
            if bp.devices:
                run_kwargs["devices"] = list(bp.devices)
            if bp.cap_add:
                run_kwargs["cap_add"] = list(bp.cap_add)
            if bp.shm_size:
                run_kwargs["shm_size"] = bp.shm_size
            if healthcheck:
                run_kwargs["healthcheck"] = healthcheck

            container = client.containers.run(**run_kwargs)
        except APIError as e:
            # Cleanup volume on failure
            if created_workspace_volume:
                try:
                    client.volumes.get(volume_name).remove()
                except Exception:
                    pass
            raise RuntimeError(f"Container start failed: {e}")

        # Optional readiness gate: if a healthcheck is configured, wait for
        # Docker health status to become healthy before exposing container as running.
        if healthcheck:
            ready_timeout = _derive_readiness_timeout_seconds(bp.healthcheck)
            ready, ready_error_code, ready_reason = _wait_for_container_health(
                container,
                timeout_seconds=ready_timeout,
                poll_interval_seconds=2.0,
            )
            if not ready:
                _cleanup_failed_container_start(
                    client=client,
                    container=container,
                    volume_name=volume_name,
                    remove_workspace_volume=created_workspace_volume,
                )
                log_action("", blueprint_id, "deploy_failed", ready_reason)
                _emit_ws_activity(
                    "deploy_failed",
                    level="error",
                    message=ready_reason,
                    blueprint_id=blueprint_id,
                    container_id=container.id,
                    error_code=ready_error_code,
                )
                raise RuntimeError(ready_reason)

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

        _commit_quota_reservation(instance, reserved_mem_mb, reserved_cpu)
        reservation_active = False

        # 7. TTL timer
        if resources.timeout_seconds > 0:
            _set_ttl_timer(container.id, resources.timeout_seconds)

        # Add network info to instance for API response
        instance.network_info = net_info
        log_action(container.id, blueprint_id, "start",
                   f"image={image_tag}, mem={resources.memory_limit}, cpu={resources.cpu_limit}")

        logger.info(f"[Engine] Started: {container_name} ({container.short_id})")
        _emit_ws_activity(
            "container_started",
            level="success",
            message=f"Container started: {container.short_id}",
            container_id=container.id,
            blueprint_id=blueprint_id,
            container_name=container_name,
            network_mode=bp.network.value,
        )
        return instance
    finally:
        if reservation_active:
            _release_quota_reservation(reserved_mem_mb, reserved_cpu)


def _normalize_runtime_mount_overrides(raw_mounts: Optional[List[Dict[str, Any]]]) -> List[MountDef]:
    mounts: List[MountDef] = []
    for item in list(raw_mounts or []):
        if not isinstance(item, dict):
            raise RuntimeError("invalid_mount_override_entry: expected object")
        host = str(item.get("host", "")).strip()
        container = str(item.get("container", "")).strip()
        mount_type = str(item.get("type", "bind") or "bind").strip().lower()
        mode = str(item.get("mode", "rw") or "rw").strip().lower()
        if not host:
            raise RuntimeError("invalid_mount_override_host_empty")
        if not container or not container.startswith("/"):
            raise RuntimeError(f"invalid_mount_override_container: '{container or '?'}'")
        if mount_type not in {"bind", "volume"}:
            raise RuntimeError(f"invalid_mount_override_type: '{mount_type}'")
        if mode not in {"ro", "rw"}:
            raise RuntimeError(f"invalid_mount_override_mode: '{mode}'")
        mounts.append(
            MountDef(
                host=host,
                container=container,
                type=mount_type,
                mode=mode,
            )
        )
    return mounts


def _normalize_runtime_device_overrides(raw_devices: Optional[List[str]]) -> List[str]:
    devices: List[str] = []
    seen = set()
    for raw in list(raw_devices or []):
        value = str(raw or "").strip()
        if not value:
            continue
        if any(ch.isspace() for ch in value):
            raise RuntimeError(f"invalid_device_override_whitespace: '{value}'")
        host = value.split(":", 1)[0].strip()
        if not host.startswith("/dev/") or ".." in host:
            raise RuntimeError(f"invalid_device_override_host: '{value}'")
        if value in seen:
            continue
        seen.add(value)
        devices.append(value)
    return devices


def _compose_runtime_blueprint(
    bp: Blueprint,
    runtime_mount_overrides: List[MountDef],
    runtime_device_overrides: List[str],
    storage_scope_override: str = "",
    force_auto_scope: bool = False,
) -> Blueprint:
    from .storage_scope import get_scope, upsert_scope

    effective = bp.model_copy(deep=True)
    if runtime_mount_overrides:
        effective.mounts = list(effective.mounts) + list(runtime_mount_overrides)
    if runtime_device_overrides:
        merged_devices = list(effective.devices or []) + list(runtime_device_overrides)
        # keep order, remove duplicates
        deduped: List[str] = []
        seen = set()
        for dev in merged_devices:
            item = str(dev or "").strip()
            if not item or item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        effective.devices = deduped
    if storage_scope_override:
        effective.storage_scope = storage_scope_override

    # If mount overrides exist and no scope is set, auto-create a tight scope
    # limited to the exact host paths used by this deploy.
    if runtime_mount_overrides and (force_auto_scope or not str(effective.storage_scope or "").strip()):
        roots_by_path: Dict[str, str] = {}
        for m in list(effective.mounts or []):
            mount_type = str(getattr(m, "type", "bind") or "bind").strip().lower()
            if mount_type == "volume":
                continue
            host_abs = os.path.abspath(str(getattr(m, "host", "") or "").strip())
            if not host_abs:
                continue
            mode = str(getattr(m, "mode", "rw") or "rw").strip().lower()
            prev = roots_by_path.get(host_abs, "ro")
            roots_by_path[host_abs] = "rw" if mode == "rw" or prev == "rw" else "ro"
        roots = [{"path": p, "mode": roots_by_path[p]} for p in sorted(roots_by_path.keys())]
        if roots:
            digest_src = "|".join(f"{r['path']}:{r['mode']}" for r in roots)
            digest = hashlib.sha1(digest_src.encode("utf-8")).hexdigest()[:12]
            auto_scope_name = f"deploy_auto_{bp.id}_{digest}"
            scope = get_scope(auto_scope_name)
            if not scope:
                upsert_scope(name=auto_scope_name, roots=roots, approved_by="system:auto")
            effective.storage_scope = auto_scope_name
    return effective


def stop_container(container_id: str, remove: bool = True) -> bool:
    """Stop a running container and optionally remove it."""
    client = get_client()
    try:
        container = client.containers.get(container_id)
        blueprint_id = container.labels.get("trion.blueprint", "unknown")

        container.stop(timeout=10)
        if remove:
            container.remove(force=True)

        # Cancel TTL timer + in-memory registry updates
        with _state_lock:
            timer = _ttl_timers.pop(container_id, None)
            if container_id in _active:
                _active[container_id].status = ContainerStatus.STOPPED
                del _active[container_id]
            _update_quota_used_unlocked()
        if timer:
            timer.cancel()
        log_action(container_id, blueprint_id, "stop")
        logger.info(f"[Engine] Stopped: {container_id[:12]}")
        _emit_ws_activity(
            "container_stopped",
            level="warn",
            message=f"Container stopped: {container_id[:12]}",
            container_id=container_id,
            blueprint_id=blueprint_id,
        )
        return True

    except NotFound:
        with _state_lock:
            _active.pop(container_id, None)
            _ttl_timers.pop(container_id, None)
            _update_quota_used_unlocked()
        _emit_ws_activity(
            "container_stop_not_found",
            level="warn",
            message=f"Container not found: {container_id[:12]}",
            container_id=container_id,
        )
        return False
    except Exception as e:
        logger.error(f"[Engine] Stop failed: {e}")
        return False


MAX_EXEC_OUTPUT = 8000  # chars per stream before truncation
EXEC_TIMEOUT_EXIT_CODE = 124
EXEC_TIMEOUT_MARKER = "__TRION_EXEC_TIMEOUT__"


def _build_timed_exec_command(command: str, timeout: int) -> str:
    """
    Wrap command execution in a shell-based timeout guard.
    Uses only POSIX sh + sleep + kill (no dependency on GNU timeout binary).
    """
    timeout_s = max(1, int(timeout or 30))
    cmd_escaped = shlex.quote(str(command or ""))
    marker = EXEC_TIMEOUT_MARKER
    script = (
        f"cmd={cmd_escaped}; "
        "flag=/tmp/.trion_exec_timeout_$$; "
        'sh -lc "$cmd" & cmd_pid=$!; '
        f'(sleep {timeout_s}; echo 1 > \"$flag\"; kill -TERM \"$cmd_pid\" 2>/dev/null; '
        'sleep 1; kill -KILL "$cmd_pid" 2>/dev/null) & killer_pid=$!; '
        'wait "$cmd_pid"; rc=$?; '
        'if [ -f "$flag" ]; then rm -f "$flag"; '
        'kill "$killer_pid" 2>/dev/null || true; wait "$killer_pid" 2>/dev/null || true; '
        f'echo "{marker}" >&2; exit {EXEC_TIMEOUT_EXIT_CODE}; fi; '
        'kill "$killer_pid" 2>/dev/null || true; wait "$killer_pid" 2>/dev/null || true; '
        'exit "$rc"'
    )
    return f"sh -lc {shlex.quote(script)}"


def _extract_timeout_marker(stderr: str) -> Tuple[str, bool]:
    text = str(stderr or "")
    if EXEC_TIMEOUT_MARKER not in text:
        return text, False
    cleaned = text.replace(EXEC_TIMEOUT_MARKER, "").strip()
    return cleaned, True


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

        timed_command = _build_timed_exec_command(command, timeout)
        exec_result = container.exec_run(timed_command, demux=True, workdir="/workspace")
        stdout = (exec_result.output[0] or b"").decode("utf-8", errors="replace") if exec_result.output[0] else ""
        stderr = (exec_result.output[1] or b"").decode("utf-8", errors="replace") if exec_result.output[1] else ""
        stderr, timed_out = _extract_timeout_marker(stderr)
        exit_code = exec_result.exit_code
        if timed_out:
            exit_code = EXEC_TIMEOUT_EXIT_CODE
            if stderr:
                stderr = f"{stderr}\nCommand timed out after {max(1, int(timeout or 30))}s"
            else:
                stderr = f"Command timed out after {max(1, int(timeout or 30))}s"
        output = stdout + ("\n" + stderr if stderr else "")

        log_action(container_id, "", "exec", command[:200])
        return (exit_code, output.strip())

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

        timed_command = _build_timed_exec_command(command, timeout)
        exec_result = container.exec_run(timed_command, demux=True, workdir="/workspace")
        stdout = (exec_result.output[0] or b"").decode("utf-8", errors="replace") if exec_result.output[0] else ""
        stderr = (exec_result.output[1] or b"").decode("utf-8", errors="replace") if exec_result.output[1] else ""
        stderr, timed_out = _extract_timeout_marker(stderr)
        exit_code = exec_result.exit_code
        if timed_out:
            exit_code = EXEC_TIMEOUT_EXIT_CODE
            if stderr:
                stderr = f"{stderr}\nCommand timed out after {max(1, int(timeout or 30))}s"
            else:
                stderr = f"Command timed out after {max(1, int(timeout or 30))}s"

        truncated = len(stdout) > MAX_EXEC_OUTPUT or len(stderr) > MAX_EXEC_OUTPUT
        stdout = stdout[:MAX_EXEC_OUTPUT].strip()
        stderr = stderr[:MAX_EXEC_OUTPUT].strip()

        log_action(container_id, "", "exec", command[:200])
        return {
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "truncated": truncated,
            "timed_out": timed_out,
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
        with _state_lock:
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
        with _state_lock:
            active_snapshot = dict(_active)
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

            instance = active_snapshot.get(c.id, ContainerInstance(
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
        health_state = state.get("Health") or {}
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
        ports = _extract_port_details(attrs)

        mounts = [
            f"{m.get('Source', '?')}:{m.get('Destination', '?')}"
            for m in attrs.get("Mounts", [])
            if m.get("Type") == "volume"
        ]

        labels = c.labels
        blueprint_id = labels.get("trion.blueprint", "unknown")

        with _state_lock:
            in_memory = _active.get(c.id)
        ttl_remaining = int(in_memory.ttl_remaining) if in_memory and in_memory.ttl_remaining else None

        return {
            "container_id": c.id,
            "short_id": c.short_id,
            "name": c.name,
            "blueprint_id": blueprint_id,
            "image": config.get("Image", ""),
            "status": state.get("Status", "unknown"),
            "health_status": health_state.get("Status", ""),
            "running": state.get("Running", False),
            "exit_code": state.get("ExitCode") if not state.get("Running") else None,
            "started_at": state.get("StartedAt", ""),
            "finished_at": state.get("FinishedAt", "") if not state.get("Running") else None,
            "ip_address": ip_address,
            "ports": ports,
            "connection": _build_connection_info(ip_address, ports),
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
    with _state_lock:
        return _quota.model_copy(deep=True)


def _check_quota(resources: ResourceLimits):
    """Raise if starting a new container would exceed quota."""
    mem_mb = _parse_memory(resources.memory_limit) / (1024 * 1024)
    cpu = float(resources.cpu_limit)
    with _state_lock:
        containers_total = len(_active) + _pending_starts
        if containers_total >= _quota.max_containers:
            raise RuntimeError(
                f"Container quota exceeded: {containers_total}/{_quota.max_containers} running_or_pending"
            )

        mem_total = _quota.memory_used_mb + _pending_memory_mb + mem_mb
        if mem_total > _quota.max_total_memory_mb:
            raise RuntimeError(
                f"Memory quota exceeded: {int(mem_total)} > {_quota.max_total_memory_mb} MB (used+pending+requested)"
            )

        cpu_total = _quota.cpu_used + _pending_cpu + cpu
        if cpu_total > _quota.max_total_cpu:
            raise RuntimeError(
                f"CPU quota exceeded: {cpu_total} > {_quota.max_total_cpu} (used+pending+requested)"
            )


def _reserve_quota(resources: ResourceLimits) -> Tuple[float, float]:
    """Reserve quota atomically to prevent concurrent oversubscription."""
    mem_mb = _parse_memory(resources.memory_limit) / (1024 * 1024)
    cpu = float(resources.cpu_limit)
    global _pending_starts, _pending_memory_mb, _pending_cpu
    with _state_lock:
        containers_total = len(_active) + _pending_starts
        if containers_total >= _quota.max_containers:
            raise RuntimeError(
                f"Container quota exceeded: {containers_total}/{_quota.max_containers} running_or_pending"
            )

        mem_total = _quota.memory_used_mb + _pending_memory_mb + mem_mb
        if mem_total > _quota.max_total_memory_mb:
            raise RuntimeError(
                f"Memory quota exceeded: {int(mem_total)} > {_quota.max_total_memory_mb} MB (used+pending+requested)"
            )

        cpu_total = _quota.cpu_used + _pending_cpu + cpu
        if cpu_total > _quota.max_total_cpu:
            raise RuntimeError(
                f"CPU quota exceeded: {cpu_total} > {_quota.max_total_cpu} (used+pending+requested)"
            )

        _pending_starts += 1
        _pending_memory_mb += mem_mb
        _pending_cpu += cpu
    return mem_mb, cpu


def _release_quota_reservation(mem_mb: float, cpu: float) -> None:
    """Release a previous quota reservation (best-effort, never negative)."""
    global _pending_starts, _pending_memory_mb, _pending_cpu
    with _state_lock:
        _pending_starts = max(0, _pending_starts - 1)
        _pending_memory_mb = max(0.0, _pending_memory_mb - float(mem_mb or 0.0))
        _pending_cpu = max(0.0, _pending_cpu - float(cpu or 0.0))


def _commit_quota_reservation(instance: ContainerInstance, mem_mb: float, cpu: float) -> None:
    """Move a reservation into active state once container start succeeds."""
    global _pending_starts, _pending_memory_mb, _pending_cpu
    with _state_lock:
        _pending_starts = max(0, _pending_starts - 1)
        _pending_memory_mb = max(0.0, _pending_memory_mb - float(mem_mb or 0.0))
        _pending_cpu = max(0.0, _pending_cpu - float(cpu or 0.0))
        _active[instance.container_id] = instance
        _update_quota_used_unlocked()


def _update_quota_used():
    """Recalculate quota usage from active containers."""
    with _state_lock:
        _update_quota_used_unlocked()


def _update_quota_used_unlocked():
    """Recalculate quota usage from active containers (lock must already be held)."""
    _quota.containers_used = len(_active)
    _quota.memory_used_mb = sum(i.memory_limit_mb for i in _active.values())
    _quota.cpu_used = sum(i.cpu_limit_alloc for i in _active.values())


# ── TTL / Auto-Cleanup ───────────────────────────────────

def _set_ttl_timer(container_id: str, seconds: int):
    """Set an auto-kill timer for a container. Idempotent: cancels any existing timer first."""
    # Cancel existing timer before arming (safe for recovery path / rearm)
    with _state_lock:
        existing = _ttl_timers.pop(container_id, None)
    if existing:
        existing.cancel()

    def _timeout():
        logger.warning(f"[Engine] TTL expired for {container_id[:12]}, stopping...")
        _emit_ws_activity(
            "container_ttl_expired",
            level="warn",
            message=f"TTL expired for {container_id[:12]}",
            container_id=container_id,
            ttl_seconds=seconds,
        )

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
                with _state_lock:
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
    with _state_lock:
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
        with _state_lock:
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
            _emit_ws_activity(
                "container_ttl_expired",
                level="warn",
                message=f"TTL expired on startup for {container_id[:12]}",
                container_id=container_id,
                blueprint_id=bp_id,
                reason="ttl_expired_at_startup",
                ttl_seconds=ttl_seconds,
            )
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
        with _state_lock:
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
        with _state_lock:
            for _timer in list(_ttl_timers.values()):
                try:
                    _timer.cancel()
                except Exception:
                    pass
            _ttl_timers.clear()
            _active.clear()
            _update_quota_used_unlocked()
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


def _validate_runtime_preflight(client: Any, runtime: str) -> Tuple[bool, str]:
    """
    Validate optional runtime requirements before container start.
    Currently: runtime='nvidia' requires NVIDIA runtime on Docker daemon.
    """
    rt = str(runtime or "").strip().lower()
    if not rt:
        return True, "ok"
    if rt != "nvidia":
        return True, "ok"
    try:
        info = client.info() if hasattr(client, "info") else client.api.info()
    except Exception as e:
        return False, f"runtime_preflight_failed: cannot query docker info ({e})"
    runtimes = dict((info or {}).get("Runtimes") or {})
    if "nvidia" in runtimes:
        return True, "ok"
    return False, (
        "nvidia_runtime_unavailable: Docker runtime 'nvidia' not found. "
        "Install/enable NVIDIA Container Toolkit before starting this blueprint."
    )


def _extract_port_details(attrs: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Parse Docker inspect NetworkSettings.Ports into a stable list.
    """
    result: List[Dict[str, str]] = []
    ports_obj = (((attrs or {}).get("NetworkSettings") or {}).get("Ports") or {})
    for container_port, bindings in dict(ports_obj).items():
        if not bindings:
            continue
        for binding in bindings:
            result.append(
                {
                    "container_port": str(container_port or ""),
                    "host_ip": str((binding or {}).get("HostIp") or "0.0.0.0"),
                    "host_port": str((binding or {}).get("HostPort") or ""),
                }
            )
    return sorted(result, key=lambda p: (p.get("host_port", ""), p.get("container_port", "")))


def _build_connection_info(ip_address: Optional[str], ports: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Build user-facing connection hints for WebUI/MCP responses.
    """
    public_host = str(os.environ.get("TRION_PUBLIC_HOST", "")).strip() or "127.0.0.1"
    endpoints: List[str] = []
    for p in list(ports or []):
        host_port = str(p.get("host_port") or "").strip()
        container_port = str(p.get("container_port") or "").strip()
        if not host_port:
            continue
        proto = "tcp"
        if "/" in container_port:
            _, proto = container_port.rsplit("/", 1)
        endpoints.append(f"{public_host}:{host_port}/{proto}")
    return {
        "container_ip": str(ip_address or ""),
        "public_host": public_host,
        "endpoints": endpoints,
    }


def _build_port_bindings(port_specs: List[str]) -> Dict[str, str]:
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

        # Range mapping (e.g. 48100-48110:48100-48110/udp) is expanded one-by-one.
        host_parts = [p.strip() for p in host_port.split("-", 1)]
        container_parts = [p.strip() for p in container_port.split("-", 1)]
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


def _seconds_to_nanos(value: object) -> Optional[int]:
    try:
        seconds = float(value)  # type: ignore[arg-type]
    except Exception:
        return None
    if seconds <= 0:
        return None
    return int(seconds * 1_000_000_000)


def _build_healthcheck_config(config: Dict) -> Optional[Dict]:
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

    interval = _seconds_to_nanos(cfg.get("interval_seconds"))
    timeout = _seconds_to_nanos(cfg.get("timeout_seconds"))
    start_period = _seconds_to_nanos(cfg.get("start_period_seconds"))
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


def _derive_readiness_timeout_seconds(config: Dict) -> int:
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

    # Heuristic: wait through retry horizon + grace.
    derived = int(start_period + (interval * retries) + (timeout * 2) + 30)
    return max(30, min(900, derived))


def _wait_for_container_health(
    container,
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
        except Exception as e:
            return False, "container_not_ready", f"container_exited_before_ready_auto_stopped: reload_failed={e}"

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


def _cleanup_failed_container_start(
    client: docker.DockerClient,
    container,
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


def _unique_runtime_suffix() -> str:
    """Generate collision-resistant runtime suffix for resource names."""
    return f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
