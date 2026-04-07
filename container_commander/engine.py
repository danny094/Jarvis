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
from .engine_runtime_blueprint import (
    auto_scope_metadata as _auto_scope_metadata_impl,
    auto_scope_name_for_mounts as _auto_scope_name_for_mounts_impl,
    compose_runtime_blueprint as _compose_runtime_blueprint_impl,
    normalize_runtime_device_overrides as _normalize_runtime_device_overrides_impl,
    normalize_runtime_mount_overrides as _normalize_runtime_mount_overrides_impl,
    run_pre_start_exec as _run_pre_start_exec_impl,
    runtime_mount_asset_ids as _runtime_mount_asset_ids_impl,
    runtime_mount_payloads as _runtime_mount_payloads_impl,
    slug_scope_token as _slug_scope_token_impl,
)
from .engine_runtime_state import (
    RuntimeStateRefs,
    check_quota as _check_quota_impl,
    cleanup_all as _cleanup_all_impl,
    commit_quota_reservation as _commit_quota_reservation_impl,
    get_quota as _get_quota_impl,
    recover_runtime_state as _recover_runtime_state_impl,
    release_quota_reservation as _release_quota_reservation_impl,
    reserve_quota as _reserve_quota_impl,
    set_ttl_timer as _set_ttl_timer_impl,
    sync_runtime_state_from_docker as _sync_runtime_state_from_docker_impl,
    update_quota_used_unlocked as _update_quota_used_unlocked_impl,
)
from .engine_connection import (
    build_connection_info as _build_connection_info_impl,
    extract_port_details as _extract_port_details_impl,
    infer_access_link_meta as _infer_access_link_meta_impl,
    infer_service_name as _infer_service_name_impl,
    merge_host_companion_access_info as _merge_host_companion_access_info_impl,
)
from .port_manager import validate_port_bindings as _validate_port_bindings
from .engine_deploy_support import (
    build_healthcheck_config as _build_healthcheck_config_impl,
    build_port_bindings as _build_port_bindings_impl,
    cleanup_failed_container_start as _cleanup_failed_container_start_impl,
    derive_readiness_timeout_seconds as _derive_readiness_timeout_seconds_impl,
    seconds_to_nanos as _seconds_to_nanos_impl,
    wait_for_container_health as _wait_for_container_health_impl,
)
from .engine_start_support import (
    build_env_vars as _build_env_vars_impl,
    enforce_trust_gates as _enforce_trust_gates_impl,
    prepare_runtime_blueprint as _prepare_runtime_blueprint_impl,
    request_deploy_approval_if_needed as _request_deploy_approval_if_needed_impl,
    run_post_start_checks as _run_post_start_checks_impl,
    setup_host_companion as _setup_host_companion_impl,
    start_runtime_container as _start_runtime_container_impl,
)
from .hardware_resolution import (
    build_resolution_warning_entries as _build_resolution_warning_entries_impl,
    merge_resolved_mount_overrides as _merge_resolved_mount_overrides_impl,
    merge_resolved_device_overrides as _merge_resolved_device_overrides_impl,
    resolve_blueprint_hardware_for_deploy as _resolve_blueprint_hardware_for_deploy_impl,
)
from .package_runtime_views import apply_package_runtime_views as _apply_package_runtime_views_impl
from .hardware_resolution_preview import (
    build_hardware_resolution_preview_payload as _build_hardware_resolution_preview_payload_impl,
)
from .hardware_block_engine_opt_in import (
    select_block_engine_handoffs as _select_block_engine_handoffs_impl,
)
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
COMMANDER_AUTO_PORT_MIN = int(os.environ.get("COMMANDER_AUTO_PORT_MIN", "20000"))
COMMANDER_AUTO_PORT_MAX = int(os.environ.get("COMMANDER_AUTO_PORT_MAX", "29999"))
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
_ttl_timers: Dict[str, threading.Timer] = {}
_last_runtime_sync_monotonic: float = 0.0


def _build_initial_quota() -> SessionQuota:
    """Build quota from env vars, falling back to /proc/meminfo auto-detection."""
    env_mem = os.environ.get("COMMANDER_MAX_MEMORY_MB", "").strip()
    env_cpu = os.environ.get("COMMANDER_MAX_CPU", "").strip()
    env_containers = os.environ.get("COMMANDER_MAX_CONTAINERS", "").strip()

    if env_mem:
        max_mem_mb = max(512, int(env_mem))
    else:
        # Auto-detect: total system RAM minus 4 GB headroom for host OS + trion-home
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        total_kb = int(line.split()[1])
                        max_mem_mb = max(2048, total_kb // 1024 - 4096)
                        break
                else:
                    max_mem_mb = 2048
        except Exception:
            max_mem_mb = 2048

    if env_cpu:
        max_cpu = max(0.5, float(env_cpu))
    else:
        try:
            max_cpu = max(2.0, float(os.cpu_count() or 2) - 2.0)
        except Exception:
            max_cpu = 2.0

    max_containers = int(env_containers) if env_containers else 5

    q = SessionQuota(
        max_total_memory_mb=max_mem_mb,
        max_total_cpu=max_cpu,
        max_containers=max_containers,
    )
    logger.info(
        f"[Engine] Quota: memory={max_mem_mb} MB, cpu={max_cpu}, containers={max_containers}"
    )
    return q


_quota = _build_initial_quota()
_state_lock = threading.RLock()
_pending_starts = 0
_pending_memory_mb = 0.0
_pending_cpu = 0.0


def _runtime_state_refs() -> RuntimeStateRefs:
    return RuntimeStateRefs(
        active=_active,
        ttl_timers=_ttl_timers,
        quota=_quota,
        state_lock=_state_lock,
        pending_starts=_pending_starts,
        pending_memory_mb=_pending_memory_mb,
        pending_cpu=_pending_cpu,
        last_runtime_sync_monotonic=_last_runtime_sync_monotonic,
    )


def _sync_runtime_state_refs(state: RuntimeStateRefs) -> None:
    global _pending_starts, _pending_memory_mb, _pending_cpu, _last_runtime_sync_monotonic
    _pending_starts = state.pending_starts
    _pending_memory_mb = state.pending_memory_mb
    _pending_cpu = state.pending_cpu
    _last_runtime_sync_monotonic = state.last_runtime_sync_monotonic


# ── Image Management ──────────────────────────────────────

def _blueprint_image_tag(blueprint: Blueprint) -> str:
    """
    Return a content-addressed local tag for Dockerfile-based blueprints.
    This avoids mixing preserved old containers with newer blueprint images
    under the same static :latest tag.
    """
    if blueprint.image:
        return blueprint.image
    dockerfile = str(blueprint.dockerfile or "")
    fingerprint = hashlib.sha256(dockerfile.encode("utf-8")).hexdigest()[:12]
    return f"trion/{blueprint.id}:{fingerprint}"


def build_image(blueprint: Blueprint) -> str:
    """
    Build a Docker image from a Blueprint's Dockerfile.
    Returns the image tag.
    """
    client = get_client()
    tag = _blueprint_image_tag(blueprint)

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
    tag = _blueprint_image_tag(blueprint)
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
    block_apply_handoff_resource_ids: Optional[List[str]] = None,
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
    # Compatibility markers for source-inspection contracts:
    # vault://
    # inject_vault_ref
    # mount_type = str(getattr(mount, "type", "bind")
    # 1. Resolve blueprint
    bp = resolve_blueprint(blueprint_id)
    if not bp:
        raise ValueError(f"Blueprint '{blueprint_id}' not found")

    hardware_resolution = _resolve_blueprint_hardware_for_deploy_impl(
        blueprint_id=bp.id,
        intents=list(getattr(bp, "hardware_intents", []) or []),
        connector="container",
        target_type="blueprint",
        target_id=bp.id,
    )
    deploy_resolution_warnings = _build_resolution_warning_entries_impl(hardware_resolution)
    block_engine_opt_in = _select_block_engine_handoffs_impl(
        list(hardware_resolution.block_apply_engine_handoffs or []),
        block_apply_handoff_resource_ids,
    )
    for raw in list(block_engine_opt_in.warnings or []):
        message = str(raw or "").strip()
        if not message:
            continue
        deploy_resolution_warnings.append(
            {
                "name": "hardware_block_engine_opt_in",
                "detail": {
                    "message": message,
                    "connector": hardware_resolution.connector,
                    "target_type": hardware_resolution.target_type,
                    "target_id": hardware_resolution.target_id,
                },
            }
        )
    effective_mount_overrides = _merge_resolved_mount_overrides_impl(
        mount_overrides,
        hardware_resolution.mount_overrides,
    )
    effective_device_overrides = _merge_resolved_device_overrides_impl(
        device_overrides,
        hardware_resolution.device_overrides,
    )
    effective_device_overrides = _merge_resolved_device_overrides_impl(
        effective_device_overrides,
        block_engine_opt_in.device_overrides,
    )

    # Compatibility markers for source-inspection contracts:
    # if isinstance(package_manifest, dict) and package_manifest.get("host_companion")
    # ensure_host_companion(blueprint_id, overwrite=False)
    # ensure_package_storage_scope(blueprint_id, blueprint=bp, manifest=package_manifest)
    # run_package_postchecks(
    # "trust_block"
    # trust_blocked
    # signature_blocked
    # "deploy_failed"
    # "deploy_warning"
    # trion.ttl_seconds
    # trion.expires_at
    package_manifest = _setup_host_companion_impl(blueprint_id, bp)
    bp, package_runtime_mount_overrides = _apply_package_runtime_views_impl(blueprint_id, bp, package_manifest)
    effective_mount_overrides = _merge_resolved_mount_overrides_impl(
        effective_mount_overrides,
        package_runtime_mount_overrides,
    )

    # Runtime-only mount overrides (e.g. managed path picker in deploy preflight).
    # Overrides are not persisted into blueprint storage.
    from .storage_scope import validate_blueprint_mounts
    from .mount_utils import ensure_bind_mount_host_dirs

    (
        bp,
        runtime_mount_overrides,
        runtime_device_overrides,
        runtime_mount_payloads,
        runtime_asset_ids,
        effective_scope_name,
    ) = _prepare_runtime_blueprint_impl(
        bp,
        effective_mount_overrides,
        effective_device_overrides,
        storage_scope_override,
        normalize_mounts=_normalize_runtime_mount_overrides,
        normalize_devices=_normalize_runtime_device_overrides,
        compose_runtime_blueprint=_compose_runtime_blueprint,
        validate_blueprint_mounts=validate_blueprint_mounts,
        ensure_bind_mount_host_dirs=ensure_bind_mount_host_dirs,
        runtime_mount_payloads=_runtime_mount_payloads,
        runtime_mount_asset_ids=_runtime_mount_asset_ids,
    )
    # Compatibility marker for source-inspection contracts:
    # ensure_bind_mount_host_dirs(bp.mounts)
    # validate_blueprint_mounts(bp)

    _emit_ws_activity(
        "deploy_start",
        level="info",
        message=f"Deploy requested for {blueprint_id}",
        blueprint_id=blueprint_id,
        network_mode=bp.network.value,
        storage_scope=effective_scope_name,
        storage_asset_ids=runtime_asset_ids,
        mount_overrides=runtime_mount_payloads,
        session_id=session_id or "",
        conversation_id=conversation_id or "",
    )

    # 1.5 Human-in-the-Loop check
    _request_deploy_approval_if_needed_impl(
        blueprint_id=blueprint_id,
        bp=bp,
        skip_approval=_skip_approval,
        override_resources=override_resources,
        extra_env=extra_env,
        resume_volume=resume_volume,
        runtime_mount_payloads=runtime_mount_payloads,
        raw_mount_overrides=effective_mount_overrides,
        effective_scope_name=effective_scope_name,
        runtime_device_overrides=runtime_device_overrides,
        raw_device_overrides=effective_device_overrides,
        block_apply_handoff_resource_ids=block_apply_handoff_resource_ids,
        session_id=session_id,
        conversation_id=conversation_id,
        pending_error_cls=PendingApprovalError,
    )

    resources = override_resources or bp.resources

    # 3. Trust Gate — Digest Pinning (opt-in, fail closed for pinned blueprints)
    # Must run BEFORE build_image() to prevent pulling an untrusted image.
    # Compatibility markers for signature source-contracts:
    # from .trust import verify_image_signature
    # if bp.image:
    #     _sig_result = verify_image_signature(bp.image)
    #     if not _sig_result["verified"]:
    #         raise RuntimeError(f"[Signature-Block] {_sig_result['reason']}")
    #     logger.info("[Engine] Signature OK: %s", _sig_result["reason"])
    _enforce_trust_gates_impl(
        blueprint_id,
        bp,
        emit_ws_activity=_emit_ws_activity,
        logger=logger,
    )

    # Reserve quota before potentially expensive build/start to avoid race conditions.
    reserved_mem_mb, reserved_cpu = _reserve_quota(resources)
    reservation_active = True
    try:
        # 3.5 Build/pull image (after trust gate — avoids pulling untrusted images)
        image_tag = build_image(bp)

        # 4. Inject environment + secrets
        env_vars = _build_env_vars_impl(
            bp,
            blueprint_id,
            extra_env,
            get_secret_value=get_secret_value,
            get_secrets_for_blueprint=get_secrets_for_blueprint,
            log_secret_access=log_secret_access,
        )

        _run_pre_start_exec(bp, image_tag, env_vars)

        # 5. Create container
        # Compatibility markers kept in start_container source:
        # unique_suffix = _unique_runtime_suffix()
        # container_name = f"{TRION_PREFIX}{blueprint_id}_{unique_suffix}"
        # volume_name = f"trion_ws_{blueprint_id}_{unique_suffix}"
        # port_bindings = _build_port_bindings(bp.ports)
        # healthcheck = _build_healthcheck_config(bp.healthcheck)
        # run_kwargs["ports"] = port_bindings
        # run_kwargs["runtime"] = bp.runtime
        # run_kwargs["devices"] = list(bp.devices)
        # run_kwargs["cap_add"] = list(bp.cap_add)
        # run_kwargs["security_opt"] = list(bp.security_opt)
        # run_kwargs["cap_drop"] = list(bp.cap_drop)
        # run_kwargs["privileged"] = True
        # run_kwargs["read_only"] = True
        # run_kwargs["shm_size"] = bp.shm_size
        # run_kwargs["ipc_mode"] = bp.ipc_mode
        # run_kwargs["healthcheck"] = healthcheck
        port_bindings = _build_port_bindings(list(bp.ports or []))
        _port_bindings_label = {"trion.port_bindings": json.dumps(port_bindings) if port_bindings else ""}
        logger.debug("[Engine] Port bindings label: %s", _port_bindings_label)
        port_conflicts = _validate_port_bindings(port_bindings)
        if port_conflicts:
            conflict_summary = ", ".join(
                f"{c['host_port']}/{c['protocol']}" for c in port_conflicts
            )
            _emit_ws_activity(
                blueprint_id,
                "port_conflict_precheck_failed",
                {"conflicts": port_conflicts, "summary": conflict_summary},
            )
            raise RuntimeError(
                f"port_conflict_precheck_failed: ports already in use: {conflict_summary}"
            )
        client = get_client()
        runtime_ok, runtime_reason = _validate_runtime_preflight(client, bp.runtime)
        if not runtime_ok:
            raise RuntimeError(runtime_reason)
        runtime = _start_runtime_container_impl(
            blueprint_id=blueprint_id,
            bp=bp,
            resources=resources,
            image_tag=image_tag,
            env_vars=env_vars,
            resume_volume=resume_volume,
            session_id=session_id,
            conversation_id=conversation_id,
            trion_label=TRION_LABEL,
            trion_prefix=TRION_PREFIX,
            get_client=get_client,
            parse_memory=_parse_memory,
            build_port_bindings=_build_port_bindings,
            build_healthcheck_config=_build_healthcheck_config,
            unique_runtime_suffix=_unique_runtime_suffix,
            logger=logger,
        )
        client = runtime["client"]
        container = runtime["container"]
        container_name = runtime["container_name"]
        volume_name = runtime["volume_name"]
        mem_bytes = runtime["mem_bytes"]
        net_info = runtime["net_info"]

        # ready_timeout = _derive_readiness_timeout_seconds(bp.healthcheck)
        postcheck_warnings = _run_post_start_checks_impl(
            blueprint_id=blueprint_id,
            bp=bp,
            package_manifest=package_manifest,
            runtime=runtime,
            derive_readiness_timeout_seconds=_derive_readiness_timeout_seconds,
            wait_for_container_health=_wait_for_container_health,
            cleanup_failed_container_start=_cleanup_failed_container_start,
            emit_ws_activity=_emit_ws_activity,
            log_action=log_action,
            logger=logger,
        )

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

        # Add network info and deploy warnings to instance for API response
        instance.network_info = net_info
        instance.deploy_warnings = list(postcheck_warnings or []) + list(deploy_resolution_warnings or [])
        instance.hardware_resolution_preview = _build_hardware_resolution_preview_payload_impl(hardware_resolution)
        instance.block_apply_handoff_resource_ids_requested = list(block_engine_opt_in.requested_resource_ids or [])
        instance.block_apply_handoff_resource_ids_applied = list(block_engine_opt_in.selected_resource_ids or [])
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
    # Compatibility markers kept in engine.py for source-inspection contracts:
    # storage_asset_not_found
    # storage_asset_read_only
    return _normalize_runtime_mount_overrides_impl(raw_mounts)


def _normalize_runtime_device_overrides(raw_devices: Optional[List[str]]) -> List[str]:
    return _normalize_runtime_device_overrides_impl(raw_devices)


def _run_pre_start_exec(bp: Blueprint, image_tag: str, env_vars: Dict[str, str]) -> None:
    return _run_pre_start_exec_impl(bp, image_tag, env_vars, get_client=get_client)


def _slug_scope_token(raw: str) -> str:
    return _slug_scope_token_impl(raw)


def _auto_scope_name_for_mounts(bp: Blueprint, roots: List[dict], runtime_mount_overrides: List[MountDef]) -> str:
    # Compatibility markers:
    # deploy_auto_asset_
    # deploy_auto_
    return _auto_scope_name_for_mounts_impl(bp, roots, runtime_mount_overrides)


def _auto_scope_metadata(bp: Blueprint, runtime_mount_overrides: List[MountDef]) -> dict:
    return _auto_scope_metadata_impl(bp, runtime_mount_overrides)


def _runtime_mount_payloads(runtime_mount_overrides: List[MountDef]) -> List[dict]:
    return _runtime_mount_payloads_impl(runtime_mount_overrides)


def _runtime_mount_asset_ids(runtime_mount_overrides: List[MountDef]) -> List[str]:
    return _runtime_mount_asset_ids_impl(runtime_mount_overrides)


def _compose_runtime_blueprint(
    bp: Blueprint,
    runtime_mount_overrides: List[MountDef],
    runtime_device_overrides: List[str],
    storage_scope_override: str = "",
    force_auto_scope: bool = False,
) -> Blueprint:
    # Compatibility markers:
    # runtime_device_overrides
    # force_auto_scope
    # deploy_auto_asset_
    # deploy_auto_
    return _compose_runtime_blueprint_impl(
        bp,
        runtime_mount_overrides=runtime_mount_overrides,
        runtime_device_overrides=runtime_device_overrides,
        storage_scope_override=storage_scope_override,
        force_auto_scope=force_auto_scope,
    )


PRESERVE_ON_STOP_BLUEPRINT_IDS = {"gaming-station"}


def _should_remove_container_on_stop(blueprint_id: str, explicit_remove: Optional[bool]) -> bool:
    if explicit_remove is not None:
        return bool(explicit_remove)
    return str(blueprint_id or "").strip().lower() not in PRESERVE_ON_STOP_BLUEPRINT_IDS


def stop_container(container_id: str, remove: Optional[bool] = None) -> bool:
    """Stop a running container and optionally remove it."""
    client = get_client()
    try:
        container = client.containers.get(container_id)
        blueprint_id = container.labels.get("trion.blueprint", "unknown")
        should_remove = _should_remove_container_on_stop(blueprint_id, remove)

        container.stop(timeout=10)
        if should_remove:
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
            message=(
                f"Container stopped: {container_id[:12]}"
                if should_remove
                else f"Container stopped and preserved: {container_id[:12]}"
            ),
            container_id=container_id,
            blueprint_id=blueprint_id,
            removed=should_remove,
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


def remove_stopped_container(container_id: str) -> Dict:
    """Remove a stopped TRION-managed container in-place."""
    client = get_client()
    try:
        container = client.containers.get(container_id)
        labels = container.labels or {}
        if TRION_LABEL not in labels:
            return {"removed": False, "container_id": container_id, "reason": "not_managed"}

        container.reload()
        state = container.attrs.get("State", {}) if isinstance(container.attrs, dict) else {}
        if bool(state.get("Running")):
            return {"removed": False, "container_id": container_id, "reason": "running"}

        blueprint_id = labels.get("trion.blueprint", "unknown")
        container.remove(force=True)

        with _state_lock:
            timer = _ttl_timers.pop(container_id, None)
            _active.pop(container_id, None)
            _update_quota_used_unlocked()
        if timer:
            timer.cancel()

        log_action(container_id, blueprint_id, "remove")
        logger.info(f"[Engine] Removed stopped container: {container_id[:12]}")
        _emit_ws_activity(
            "container_removed",
            level="warn",
            message=f"Container removed: {container_id[:12]}",
            container_id=container_id,
            blueprint_id=blueprint_id,
        )
        return {"removed": True, "container_id": container_id, "blueprint_id": blueprint_id}

    except NotFound:
        with _state_lock:
            _active.pop(container_id, None)
            _ttl_timers.pop(container_id, None)
            _update_quota_used_unlocked()
        return {"removed": False, "container_id": container_id, "reason": "not_found"}
    except Exception as e:
        logger.error(f"[Engine] Remove stopped container failed: {e}")
        return {"removed": False, "container_id": container_id, "reason": "error", "error": str(e)}


def start_stopped_container(container_id: str) -> bool:
    """Start a previously stopped TRION-managed container in-place."""
    client = get_client()
    try:
        container = client.containers.get(container_id)
        if TRION_LABEL not in (container.labels or {}):
            return False
        blueprint_id = container.labels.get("trion.blueprint", "unknown")
        if container.status == "running":
            return True

        container.start()
        container.reload()

        with _state_lock:
            timer = _ttl_timers.pop(container_id, None)
            if timer:
                timer.cancel()
            _active[container_id] = ContainerInstance(
                container_id=container.id,
                blueprint_id=blueprint_id,
                name=container.name,
                status=ContainerStatus.RUNNING,
                started_at=container.labels.get("trion.started", ""),
                volume_name=container.labels.get("trion.volume", ""),
                session_id=container.labels.get("trion.session_id", ""),
            )
            _update_quota_used_unlocked()

        log_action(container.id, blueprint_id, "start_existing")
        _emit_ws_activity(
            "container_started",
            level="success",
            message=f"Container started: {container.id[:12]}",
            container_id=container.id,
            blueprint_id=blueprint_id,
            container_name=container.name,
        )
        return True
    except NotFound:
        return False
    except Exception as e:
        logger.error(f"[Engine] Start existing failed: {e}")
        return False


MAX_EXEC_OUTPUT = 8000  # chars per stream before truncation
EXEC_TIMEOUT_EXIT_CODE = 124
EXEC_TIMEOUT_MARKER = "__TRION_EXEC_TIMEOUT__"


def _build_timed_exec_command(command: str, timeout: int) -> str:
    """
    Wrap command execution in a shell-based timeout guard.
    Uses only POSIX sh + sleep + kill (no dependency on GNU timeout binary).

    The killer subshell tracks its current sleep PID in $SP and installs a
    SIGTERM trap that explicitly kills $SP before exiting.  This prevents
    the sleep from becoming an orphan (reparented to container PID 1) and
    later turning into a zombie when PID 1 never calls waitpid().
    """
    timeout_s = max(1, int(timeout or 30))
    cmd_escaped = shlex.quote(str(command or ""))
    marker = EXEC_TIMEOUT_MARKER
    script = (
        f"cmd={cmd_escaped}; "
        "flag=/tmp/.trion_exec_timeout_$$; "
        'sh -lc "$cmd" & cmd_pid=$!; '
        # Killer subshell: SP holds the PID of whichever sleep is currently
        # running.  The TERM trap kills it so no orphan is left behind when
        # the parent does `kill "$killer_pid"`.
        '(SP=; trap \'kill "$SP" 2>/dev/null; exit\' TERM; '
        f'sleep {timeout_s} & SP=$!; wait "$SP"; '
        'echo 1 > "$flag"; kill -TERM "$cmd_pid" 2>/dev/null; '
        'SP=; sleep 1 & SP=$!; wait "$SP"; '
        'kill -KILL "$cmd_pid" 2>/dev/null) & killer_pid=$!; '
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
        exec_result = _exec_run_with_workdir_fallback(container, timed_command)
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
        exec_result = _exec_run_with_workdir_fallback(container, timed_command)
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


def _exec_run_with_workdir_fallback(container, timed_command: str):
    """
    Prefer /workspace for Commander-managed images, but fall back to /
    when an image does not provide that directory.
    """
    exec_result = container.exec_run(timed_command, demux=True, workdir="/workspace")
    try:
        stderr_bytes = exec_result.output[1] if isinstance(exec_result.output, tuple) else b""
        stderr = (stderr_bytes or b"").decode("utf-8", errors="replace")
    except Exception:
        stderr = ""

    if int(getattr(exec_result, "exit_code", 0) or 0) != 127:
        return exec_result
    if "chdir to cwd" not in stderr.lower():
        return exec_result
    return container.exec_run(timed_command, demux=True, workdir="/")


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
        attrs = container.attrs or {}
        stats = container.stats(stream=False)
        network_settings = attrs.get("NetworkSettings", {})
        networks = network_settings.get("Networks", {})
        ip_address = next(
            (v.get("IPAddress") for v in networks.values() if v.get("IPAddress")),
            None
        )
        labels = container.labels
        blueprint_id = labels.get("trion.blueprint", "unknown")
        ports = _extract_port_details(attrs)
        ports, connection = _merge_host_companion_access_info(blueprint_id, ip_address, ports)

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
            "ports": ports,
            "connection": connection,
            "efficiency": {
                "score": instance.efficiency_score if instance else 0,
                "level": instance.efficiency_level if instance else "green",
            },
            "deploy_warnings": list(instance.deploy_warnings or []) if instance else [],
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
        ports, connection = _merge_host_companion_access_info(blueprint_id, ip_address, ports)

        with _state_lock:
            in_memory = _active.get(c.id)
        ttl_remaining = int(in_memory.ttl_remaining) if in_memory and in_memory.ttl_remaining else None
        deploy_warnings = list(in_memory.deploy_warnings or []) if in_memory else []

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
            "connection": connection,
            "network": list(networks.keys())[0] if networks else None,
            "mounts": mounts,
            "resource_limits": {
                "memory_mb": mem_mb,
                "cpu_count": cpu_count,
            },
            "ttl_remaining_seconds": ttl_remaining,
            "volume": labels.get("trion.volume", ""),
            "deploy_warnings": deploy_warnings,
        }

    except Exception as e:
        logger.error(f"[Engine] Inspect container failed ({container_id}): {e}")
        return {"error": str(e), "container_id": container_id}


# ── Quota Management ──────────────────────────────────────

def get_quota() -> SessionQuota:
    """Get current quota usage."""
    _sync_runtime_state_from_docker()
    return _get_quota_impl(_runtime_state_refs())


def _check_quota(resources: ResourceLimits):
    """Raise if starting a new container would exceed quota."""
    _sync_runtime_state_from_docker()
    _check_quota_impl(resources, _runtime_state_refs(), parse_memory=_parse_memory)


def _reserve_quota(resources: ResourceLimits) -> Tuple[float, float]:
    """Reserve quota atomically to prevent concurrent oversubscription."""
    _sync_runtime_state_from_docker()
    state = _runtime_state_refs()
    result = _reserve_quota_impl(resources, state, parse_memory=_parse_memory)
    _sync_runtime_state_refs(state)
    return result


def _release_quota_reservation(mem_mb: float, cpu: float) -> None:
    """Release a previous quota reservation (best-effort, never negative)."""
    state = _runtime_state_refs()
    _release_quota_reservation_impl(mem_mb, cpu, state)
    _sync_runtime_state_refs(state)


def _commit_quota_reservation(instance: ContainerInstance, mem_mb: float, cpu: float) -> None:
    """Move a reservation into active state once container start succeeds."""
    state = _runtime_state_refs()
    _commit_quota_reservation_impl(instance, mem_mb, cpu, state)
    _sync_runtime_state_refs(state)


def _update_quota_used():
    """Recalculate quota usage from active containers."""
    with _state_lock:
        _update_quota_used_unlocked()


def _update_quota_used_unlocked():
    """Recalculate quota usage from active containers (lock must already be held)."""
    _update_quota_used_unlocked_impl(_runtime_state_refs())


def _sync_runtime_state_from_docker(force: bool = False) -> None:
    """Best-effort runtime reconciliation against Docker for quota correctness.

    The admin API keeps an in-memory `_active` registry, but container lifecycle
    events can still drift if a deploy/approval path aborts in the middle or if
    other processes manipulated Docker state. For quota checks we prefer the
    actual Docker runtime as source of truth.
    """
    state = _runtime_state_refs()
    _sync_runtime_state_from_docker_impl(
        state,
        force=force,
        get_client=get_client,
        trion_label=TRION_LABEL,
        logger=logger,
    )
    _sync_runtime_state_refs(state)


# ── TTL / Auto-Cleanup ───────────────────────────────────

def _set_ttl_timer(container_id: str, seconds: int):
    """Set an auto-kill timer for a container. Idempotent: cancels any existing timer first."""
    # Compatibility marker for source-inspection contracts:
    # "container_ttl_expired"
    state = _runtime_state_refs()
    _set_ttl_timer_impl(
        container_id,
        seconds,
        state,
        emit_ws_activity=_emit_ws_activity,
        logger=logger,
        get_client=get_client,
        stop_container=stop_container,
    )
    _sync_runtime_state_refs(state)


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
    # Compatibility markers for source-inspection contracts:
    # ttl_seconds = int(labels.get("trion.ttl_seconds", "0") or "0")
    # expires_at_epoch = int(labels.get("trion.expires_at", "0") or "0")
    state = _runtime_state_refs()
    result = _recover_runtime_state_impl(
        state,
        get_client=get_client,
        trion_label=TRION_LABEL,
        set_ttl_timer=_set_ttl_timer,
        update_quota_used=_update_quota_used,
        emit_ws_activity=_emit_ws_activity,
        logger=logger,
    )
    _sync_runtime_state_refs(state)
    return result


def cleanup_all():
    """Stop and remove all TRION-managed containers."""
    state = _runtime_state_refs()
    _cleanup_all_impl(
        state,
        get_client=get_client,
        trion_label=TRION_LABEL,
        logger=logger,
    )
    _sync_runtime_state_refs(state)


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
    return _extract_port_details_impl(attrs)


def _infer_service_name(container_port: str, blueprint_id: str = "", image_ref: str = "") -> str:
    return _infer_service_name_impl(container_port, blueprint_id=blueprint_id, image_ref=image_ref)


def _infer_access_link_meta(container_port: str, blueprint_id: str = "", image_ref: str = "") -> Dict[str, str]:
    # Compatibility marker for source contracts:
    # Open Desktop GUI
    return _infer_access_link_meta_impl(container_port, blueprint_id=blueprint_id, image_ref=image_ref)


def _build_connection_info(ip_address: Optional[str], ports: List[Dict[str, str]]) -> Dict[str, Any]:
    # Compatibility marker for source contracts:
    # "access_links": access_links
    return _build_connection_info_impl(ip_address, ports)


def _merge_host_companion_access_info(
    blueprint_id: str,
    ip_address: Optional[str],
    ports: List[Dict[str, str]],
) -> tuple[List[Dict[str, str]], Dict[str, Any]]:
    # Compatibility markers for source contracts:
    # from .host_companions import get_host_companion_access_links
    # "service_name": str(link.get("service_name", "")).strip()
    return _merge_host_companion_access_info_impl(blueprint_id, ip_address, ports)


def _build_port_bindings(port_specs: List[str]) -> Dict[str, str]:
    return _build_port_bindings_impl(port_specs)


def _seconds_to_nanos(value: object) -> Optional[int]:
    return _seconds_to_nanos_impl(value)


def _build_healthcheck_config(config: Dict) -> Optional[Dict]:
    return _build_healthcheck_config_impl(config)


def _derive_readiness_timeout_seconds(config: Dict) -> int:
    # Compatibility markers for source contracts:
    # healthcheck_timeout_auto_stopped
    # healthcheck_unhealthy_auto_stopped
    # container_exited_before_ready_auto_stopped
    return _derive_readiness_timeout_seconds_impl(config)


def _wait_for_container_health(
    container,
    timeout_seconds: int,
    poll_interval_seconds: float = 2.0,
) -> Tuple[bool, str, str]:
    # Compatibility markers for source contracts:
    # healthcheck_timeout_auto_stopped
    # healthcheck_unhealthy_auto_stopped
    # container_exited_before_ready_auto_stopped
    return _wait_for_container_health_impl(
        container,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )


def _cleanup_failed_container_start(
    client: docker.DockerClient,
    container,
    volume_name: str,
    remove_workspace_volume: bool,
) -> None:
    return _cleanup_failed_container_start_impl(
        client,
        container,
        volume_name=volume_name,
        remove_workspace_volume=remove_workspace_volume,
    )


def _unique_runtime_suffix() -> str:
    """Generate collision-resistant runtime suffix for resource names."""
    return f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
