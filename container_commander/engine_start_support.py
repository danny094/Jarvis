"""
Internal helpers for the start-container orchestration flow.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from docker.errors import APIError

from .models import Blueprint, ResourceLimits, SecretScope


def setup_host_companion(blueprint_id: str, bp: Blueprint) -> Optional[Dict[str, Any]]:
    try:
        from .host_companions import (
            ensure_host_companion,
            ensure_package_storage_scope,
            get_package_manifest,
        )

        package_manifest = get_package_manifest(blueprint_id)
        if isinstance(package_manifest, dict) and package_manifest.get("host_companion"):
            host_companion = package_manifest.get("host_companion") if isinstance(package_manifest.get("host_companion"), dict) else {}
            companion_mode = str(host_companion.get("mode", "materialize") or "materialize").strip().lower()
            if companion_mode not in {"discovery_only", "readonly", "read_only"}:
                ensure_host_companion(blueprint_id, overwrite=False)
        if isinstance(package_manifest, dict):
            ensure_package_storage_scope(blueprint_id, blueprint=bp, manifest=package_manifest)
        return package_manifest if isinstance(package_manifest, dict) else None
    except Exception as exc:
        raise RuntimeError(f"host_companion_setup_failed: {blueprint_id}: {exc}") from exc


def prepare_runtime_blueprint(
    bp: Blueprint,
    mount_overrides: Optional[List[Dict[str, Any]]],
    device_overrides: Optional[List[str]],
    storage_scope_override: Optional[str],
    *,
    normalize_mounts: Callable[[Optional[List[Dict[str, Any]]]], List[Any]],
    normalize_devices: Callable[[Optional[List[str]]], List[str]],
    compose_runtime_blueprint: Callable[..., Blueprint],
    validate_blueprint_mounts: Callable[[Blueprint], Tuple[bool, str]],
    ensure_bind_mount_host_dirs: Callable[[List[Any]], None],
    runtime_mount_payloads: Callable[[List[Any]], List[dict]],
    runtime_mount_asset_ids: Callable[[List[Any]], List[str]],
) -> Tuple[Blueprint, List[Any], List[str], List[dict], List[str], str]:
    runtime_mount_overrides = normalize_mounts(mount_overrides)
    runtime_device_overrides = normalize_devices(device_overrides)
    scope_override = str(storage_scope_override or "").strip()
    force_auto_scope = scope_override.lower() in {"__auto__", "auto"}
    asset_backed_runtime_mounts = any(
        str(getattr(mount, "asset_id", "") or "").strip()
        for mount in list(runtime_mount_overrides or [])
    )
    if asset_backed_runtime_mounts and not scope_override:
        force_auto_scope = True
    if force_auto_scope:
        scope_override = ""
    if runtime_mount_overrides or runtime_device_overrides or scope_override:
        bp = compose_runtime_blueprint(
            bp,
            runtime_mount_overrides=runtime_mount_overrides,
            runtime_device_overrides=runtime_device_overrides,
            storage_scope_override=scope_override,
            force_auto_scope=force_auto_scope,
        )

    mounts_ok, mounts_reason = validate_blueprint_mounts(bp)
    if not mounts_ok:
        raise RuntimeError(mounts_reason)

    ensure_bind_mount_host_dirs(bp.mounts)
    mount_payloads = runtime_mount_payloads(runtime_mount_overrides)
    asset_ids = runtime_mount_asset_ids(runtime_mount_overrides)
    effective_scope_name = str(getattr(bp, "storage_scope", "") or "").strip()
    return bp, runtime_mount_overrides, runtime_device_overrides, mount_payloads, asset_ids, effective_scope_name


def request_deploy_approval_if_needed(
    *,
    blueprint_id: str,
    bp: Blueprint,
    skip_approval: bool,
    override_resources: Optional[ResourceLimits],
    extra_env: Optional[Dict[str, str]],
    resume_volume: Optional[str],
    runtime_mount_payloads: List[dict],
    raw_mount_overrides: Optional[List[Dict[str, Any]]],
    effective_scope_name: str,
    runtime_device_overrides: List[str],
    raw_device_overrides: Optional[List[str]],
    block_apply_handoff_resource_ids: Optional[List[str]],
    session_id: str,
    conversation_id: str,
    pending_error_cls: type[Exception],
) -> None:
    if skip_approval:
        return

    from .approval import evaluate_deploy_risk, request_approval

    risk = evaluate_deploy_risk(bp)
    if not bool((risk or {}).get("requires_approval")):
        return

    risk_reasons = [str(item).strip() for item in list((risk or {}).get("reasons") or []) if str(item).strip()]
    approval_reason = "; ".join(risk_reasons[:3]) or "Container requests elevated runtime privileges"
    pending = request_approval(
        blueprint_id=blueprint_id,
        reason=approval_reason,
        network_mode=bp.network,
        risk_flags=list((risk or {}).get("risk_flags") or []),
        risk_reasons=risk_reasons,
        requested_cap_add=list((risk or {}).get("cap_add") or []),
        requested_security_opt=list((risk or {}).get("security_opt") or []),
        requested_cap_drop=list((risk or {}).get("cap_drop") or []),
        read_only_rootfs=bool((risk or {}).get("read_only_rootfs", False)),
        override_resources=override_resources,
        extra_env=extra_env,
        resume_volume=resume_volume,
        mount_overrides=runtime_mount_payloads or raw_mount_overrides,
        storage_scope_override=effective_scope_name,
        device_overrides=runtime_device_overrides or raw_device_overrides,
        block_apply_handoff_resource_ids=block_apply_handoff_resource_ids,
        session_id=session_id,
        conversation_id=conversation_id,
    )
    raise pending_error_cls(pending.id, approval_reason)


def enforce_trust_gates(
    blueprint_id: str,
    bp: Blueprint,
    *,
    emit_ws_activity: Callable[..., None],
    logger: Any,
) -> None:
    from .trust import check_digest_policy, verify_image_signature

    digest_policy = check_digest_policy(bp)
    if not digest_policy["allowed"]:
        try:
            from mcp.client import call_tool as mcp_call

            mcp_call(
                "workspace_event_save",
                {
                    "conversation_id": "_container_events",
                    "event_type": "trust_blocked",
                    "event_data": {
                        "blueprint_id": blueprint_id,
                        "image": bp.image or "",
                        "pinned_digest": bp.image_digest,
                        "actual_digest": digest_policy.get("actual_digest"),
                        "reason": digest_policy["reason"],
                        "blocked_at": datetime.utcnow().isoformat() + "Z",
                    },
                },
            )
        except Exception:
            pass
        emit_ws_activity(
            "trust_block",
            level="error",
            message=digest_policy["reason"],
            blueprint_id=blueprint_id,
            image=bp.image or "",
            pinned_digest=bp.image_digest or "",
            actual_digest=digest_policy.get("actual_digest"),
        )
        raise RuntimeError(digest_policy["reason"])
    if digest_policy["mode"] == "unpinned_warn":
        logger.warning(f"[Engine] {digest_policy['reason']}")

    if not bp.image:
        return

    sig_result = verify_image_signature(bp.image)
    if not sig_result["verified"]:
        try:
            from mcp.client import call_tool as mcp_call

            mcp_call(
                "workspace_event_save",
                {
                    "conversation_id": "_container_events",
                    "event_type": "signature_blocked",
                    "event_data": {
                        "blueprint_id": blueprint_id,
                        "image": bp.image,
                        "mode": sig_result["mode"],
                        "reason": sig_result["reason"],
                        "tool": sig_result.get("tool"),
                        "blocked_at": datetime.utcnow().isoformat() + "Z",
                    },
                },
            )
        except Exception:
            pass
        emit_ws_activity(
            "trust_block",
            level="error",
            message=sig_result["reason"],
            blueprint_id=blueprint_id,
            image=bp.image,
            mode=sig_result.get("mode", ""),
            source="signature",
        )
        raise RuntimeError(f"[Signature-Block] {sig_result['reason']}")
    if sig_result["mode"] != "off":
        logger.info("[Engine] Signature OK: %s", sig_result["reason"])


def build_env_vars(
    bp: Blueprint,
    blueprint_id: str,
    extra_env: Optional[Dict[str, str]],
    *,
    get_secret_value: Callable[..., Optional[str]],
    get_secrets_for_blueprint: Callable[[str, List[dict]], Dict[str, str]],
    log_secret_access: Callable[[str, str, str, str], None],
) -> Dict[str, str]:
    env_vars: Dict[str, str] = {}
    for key, value in dict(bp.environment or {}).items():
        env_name = str(key)
        env_value = str(value)
        if env_value.startswith("vault://"):
            secret_name = env_value[len("vault://") :].strip()
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
        secrets_list = [secret.model_dump() for secret in bp.secrets_required]
        secret_env_vars = get_secrets_for_blueprint(blueprint_id, secrets_list)
        env_vars.update(secret_env_vars)
        for name in secret_env_vars:
            log_secret_access(name, "inject", "", blueprint_id)

    if extra_env:
        env_vars.update(extra_env)
    return env_vars


def start_runtime_container(
    *,
    blueprint_id: str,
    bp: Blueprint,
    resources: ResourceLimits,
    image_tag: str,
    env_vars: Dict[str, str],
    resume_volume: Optional[str],
    session_id: str,
    conversation_id: str,
    trion_label: str,
    trion_prefix: str,
    get_client: Callable[[], Any],
    parse_memory: Callable[[str], int],
    build_port_bindings: Callable[[List[str]], Dict[str, str]],
    build_healthcheck_config: Callable[[Dict], Optional[Dict]],
    unique_runtime_suffix: Callable[[], str],
    logger: Any,
) -> Dict[str, Any]:
    client = get_client()
    unique_suffix = unique_runtime_suffix()
    container_name = f"{trion_prefix}{blueprint_id}_{unique_suffix}"
    if resume_volume:
        volume_name = resume_volume
        logger.info(f"[Engine] Resuming with existing volume: {volume_name}")
    else:
        volume_name = f"trion_ws_{blueprint_id}_{unique_suffix}"

    created_workspace_volume = not bool(resume_volume)
    if created_workspace_volume:
        client.volumes.create(name=volume_name, labels={trion_label: "true"})

    volumes = {volume_name: {"bind": "/workspace", "mode": "rw"}}
    for mount in bp.mounts:
        mount_type = str(getattr(mount, "type", "bind") or "bind").strip().lower()
        host_path = mount.host if mount_type == "volume" else os.path.abspath(mount.host)
        volumes[host_path] = {"bind": mount.container, "mode": mount.mode}

    from .network import resolve_network as net_resolve

    net_info = net_resolve(bp.network, container_name)
    network_mode = net_info["network"]

    mem_bytes = parse_memory(resources.memory_limit)
    swap_bytes = parse_memory(resources.memory_swap)
    try:
        port_bindings = build_port_bindings(bp.ports)
    except ValueError as exc:
        raise RuntimeError(f"invalid_port_mapping: {exc}") from exc
    healthcheck = build_healthcheck_config(bp.healthcheck)
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
        ttl_secs = resources.timeout_seconds
        expires_epoch = (int(time.time()) + ttl_secs) if ttl_secs > 0 else 0
        run_kwargs = {
            "image": image_tag,
            "detach": True,
            "name": container_name,
            "environment": env_vars,
            "volumes": volumes,
            "network": network_mode,
            "labels": {
                trion_label: "true",
                "trion.blueprint": blueprint_id,
                "trion.image_tag": image_tag,
                "trion.volume": volume_name,
                "trion.started": datetime.utcnow().isoformat(),
                "trion.session_id": session_id or "",
                "trion.conversation_id": conversation_id or "",
                "trion.port_bindings": json.dumps(port_bindings) if port_bindings else "",
                "trion.ttl_seconds": str(ttl_secs),
                "trion.expires_at": str(expires_epoch),
            },
            "cpu_period": 100000,
            "cpu_quota": int(float(resources.cpu_limit) * 100000),
            "mem_limit": mem_bytes,
            "memswap_limit": swap_bytes,
            "pids_limit": resources.pids_limit,
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
        if bp.security_opt:
            run_kwargs["security_opt"] = list(bp.security_opt)
        if bp.cap_drop:
            run_kwargs["cap_drop"] = list(bp.cap_drop)
        if bp.privileged:
            run_kwargs["privileged"] = True
        if bp.read_only_rootfs:
            run_kwargs["read_only"] = True
        if bp.shm_size:
            run_kwargs["shm_size"] = bp.shm_size
        if bp.ipc_mode:
            run_kwargs["ipc_mode"] = bp.ipc_mode
        if healthcheck:
            run_kwargs["healthcheck"] = healthcheck

        container = client.containers.run(**run_kwargs)
    except APIError as exc:
        if created_workspace_volume:
            try:
                client.volumes.get(volume_name).remove()
            except Exception:
                pass
        raise RuntimeError(f"Container start failed: {exc}") from exc

    return {
        "client": client,
        "container": container,
        "container_name": container_name,
        "volume_name": volume_name,
        "created_workspace_volume": created_workspace_volume,
        "mem_bytes": mem_bytes,
        "net_info": net_info,
        "healthcheck": healthcheck,
    }


def run_post_start_checks(
    *,
    blueprint_id: str,
    bp: Blueprint,
    package_manifest: Optional[Dict[str, Any]],
    runtime: Dict[str, Any],
    derive_readiness_timeout_seconds: Callable[[Dict], int],
    wait_for_container_health: Callable[..., Tuple[bool, str, str]],
    cleanup_failed_container_start: Callable[..., None],
    emit_ws_activity: Callable[..., None],
    log_action: Callable[[str, str, str, str], None],
    logger: Any,
) -> List[dict]:
    container = runtime["container"]
    client = runtime["client"]
    volume_name = runtime["volume_name"]
    created_workspace_volume = bool(runtime["created_workspace_volume"])
    healthcheck = runtime["healthcheck"]

    if healthcheck:
        ready_timeout = derive_readiness_timeout_seconds(bp.healthcheck)
        ready, ready_error_code, ready_reason = wait_for_container_health(
            container,
            timeout_seconds=ready_timeout,
            poll_interval_seconds=2.0,
        )
        if not ready:
            try:
                tail_logs = container.logs(tail=80, timestamps=True).decode("utf-8", errors="replace")
                logger.error(
                    "[Engine] Container '%s' (%s) failed — last logs:\n%s",
                    blueprint_id,
                    container.short_id,
                    tail_logs,
                )
            except Exception as log_err:
                logger.warning("[Engine] Could not capture container logs before cleanup: %s", log_err)
            cleanup_failed_container_start(
                client=client,
                container=container,
                volume_name=volume_name,
                remove_workspace_volume=created_workspace_volume,
            )
            log_action("", blueprint_id, "deploy_failed", ready_reason)
            emit_ws_activity(
                "deploy_failed",
                level="error",
                message=ready_reason,
                blueprint_id=blueprint_id,
                container_id=container.id,
                error_code=ready_error_code,
            )
            raise RuntimeError(ready_reason)

    postcheck_warnings: List[dict] = []
    host_runtime_infos: List[dict] = []
    if isinstance(package_manifest, dict):
        from .package_runtime_post_start import run_package_runtime_post_start

        try:
            postcheck_warnings.extend(
                list(
                    run_package_runtime_post_start(
                        blueprint_id,
                        bp,
                        package_manifest,
                        container,
                    )
                    or []
                )
            )
        except Exception as exc:
            reason = f"package_runtime_post_start_failed: {exc}"
            try:
                tail_logs = container.logs(tail=80, timestamps=True).decode("utf-8", errors="replace")
                logger.error(
                    "[Engine] Container '%s' (%s) failed runtime post-start configuration — last logs:\n%s",
                    blueprint_id,
                    container.short_id,
                    tail_logs,
                )
            except Exception:
                pass
            cleanup_failed_container_start(
                client=client,
                container=container,
                volume_name=volume_name,
                remove_workspace_volume=created_workspace_volume,
            )
            log_action("", blueprint_id, "deploy_failed", reason)
            emit_ws_activity(
                "deploy_failed",
                level="error",
                message=reason,
                blueprint_id=blueprint_id,
                error_code="package_runtime_post_start_failed",
            )
            raise RuntimeError(reason)
    if isinstance(package_manifest, dict) and list(package_manifest.get("postchecks") or []):
        from .host_companions import run_package_postchecks

        postcheck_result = run_package_postchecks(
            blueprint_id,
            blueprint=bp,
            container=container,
            manifest=package_manifest,
        )
        postcheck_warnings = list(postcheck_result.get("warnings") or [])
        if not bool(postcheck_result.get("ok")):
            failed = [item for item in list(postcheck_result.get("checks") or []) if not bool(item.get("ok"))]
            failed_names = ", ".join(str(item.get("name", "?")) for item in failed[:3]) or "package_postchecks_failed"
            reason = f"package_postchecks_failed: {failed_names}"
            try:
                tail_logs = container.logs(tail=80, timestamps=True).decode("utf-8", errors="replace")
                logger.error(
                    "[Engine] Container '%s' (%s) failed package postchecks — last logs:\n%s",
                    blueprint_id,
                    container.short_id,
                    tail_logs,
                )
            except Exception:
                pass
            cleanup_failed_container_start(
                client=client,
                container=container,
                volume_name=volume_name,
                remove_workspace_volume=created_workspace_volume,
            )
            log_action("", blueprint_id, "deploy_failed", reason)
            emit_ws_activity(
                "deploy_failed",
                level="error",
                message=reason,
                blueprint_id=blueprint_id,
                error_code="package_postchecks_failed",
            )
            raise RuntimeError(reason)
        if postcheck_warnings:
            warning_names = ", ".join(str(w.get("name", "?")) for w in postcheck_warnings)
            logger.warning(
                "[Engine] Container '%s' deployed with advisory warnings: %s",
                blueprint_id,
                warning_names,
            )
            emit_ws_activity(
                "deploy_warning",
                level="warning",
                message=f"Deploy erfolgreich, aber: {warning_names}",
                blueprint_id=blueprint_id,
                warnings=postcheck_warnings,
            )
    if isinstance(package_manifest, dict) and isinstance(package_manifest.get("host_runtime_requirements"), dict):
        from .host_runtime_discovery import run_package_host_runtime_checks

        runtime_result = run_package_host_runtime_checks(blueprint_id, manifest=package_manifest)
        host_runtime_infos = list(runtime_result.get("infos") or [])
        runtime_warnings = list(runtime_result.get("warnings") or [])
        postcheck_warnings.extend(runtime_warnings)
        if not bool(runtime_result.get("ok")):
            failed = [item for item in list(runtime_result.get("checks") or []) if not bool(item.get("ok"))]
            failed_names = ", ".join(str(item.get("name", "?")) for item in failed[:3]) or "host_runtime_requirements_failed"
            reason = f"host_runtime_requirements_failed: {failed_names}"
            try:
                tail_logs = container.logs(tail=80, timestamps=True).decode("utf-8", errors="replace")
                logger.error(
                    "[Engine] Container '%s' (%s) failed host runtime requirements — last logs:\n%s",
                    blueprint_id,
                    container.short_id,
                    tail_logs,
                )
            except Exception:
                pass
            cleanup_failed_container_start(
                client=client,
                container=container,
                volume_name=volume_name,
                remove_workspace_volume=created_workspace_volume,
            )
            log_action("", blueprint_id, "deploy_failed", reason)
            emit_ws_activity(
                "deploy_failed",
                level="error",
                message=reason,
                blueprint_id=blueprint_id,
                error_code="host_runtime_requirements_failed",
            )
            raise RuntimeError(reason)
        if host_runtime_infos:
            info_messages = [
                str((item.get("detail") or {}).get("message") or item.get("name", "")).strip()
                for item in host_runtime_infos
                if str((item.get("detail") or {}).get("message") or item.get("name", "")).strip()
            ]
            if info_messages:
                emit_ws_activity(
                    "deploy_info",
                    level="info",
                    message="; ".join(info_messages),
                    blueprint_id=blueprint_id,
                    host_runtime=host_runtime_infos,
                )
        if runtime_warnings:
            warning_names = ", ".join(str(w.get("name", "?")) for w in runtime_warnings)
            logger.warning(
                "[Engine] Container '%s' deployed with host runtime warnings: %s",
                blueprint_id,
                warning_names,
            )
            emit_ws_activity(
                "deploy_warning",
                level="warning",
                message="; ".join(
                    str((item.get("detail") or {}).get("message") or item.get("name", "")).strip()
                    for item in runtime_warnings
                    if str((item.get("detail") or {}).get("message") or item.get("name", "")).strip()
                ) or f"Deploy erfolgreich, aber: {warning_names}",
                blueprint_id=blueprint_id,
                warnings=runtime_warnings,
            )
    return postcheck_warnings
