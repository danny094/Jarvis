from __future__ import annotations

import json
import logging
import os
import posixpath
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import httpx
from pydantic import BaseModel, Field
from utils.service_endpoint_resolver import candidate_service_endpoints

from .hardware_block_apply import build_block_apply_preview as _build_block_apply_preview_impl
from .hardware_block_container_adapter import (
    build_container_block_apply_adapter_plan as _build_container_block_apply_adapter_plan_impl,
)
from .hardware_block_engine_handoff import (
    build_disabled_container_block_engine_handoffs as _build_disabled_container_block_engine_handoffs_impl,
)
from .hardware_block_apply_plan import build_block_apply_candidates as _build_block_apply_candidates_impl
from .hardware_block_resolution import resolve_block_device_ref as _resolve_block_device_ref_impl

_RESOLVABLE_DEVICE_KINDS = {"device", "input", "usb"}
_STORAGE_REFERENCE_KINDS = {"block_device_ref", "mount_ref"}
_DEFAULT_CONNECTOR = "container"
_DEFAULT_TARGET_TYPE = "blueprint"
_DEFAULT_TIMEOUT = 10.0
_BLOCKED_CONTAINER_TARGETS = {
    "/",
    "/boot",
    "/dev",
    "/etc",
    "/proc",
    "/run",
    "/sys",
    "/usr",
    "/var/run",
    "/workspace",
}
_BLOCKED_CONTAINER_TARGET_PREFIXES = (
    "/boot/",
    "/dev/",
    "/etc/",
    "/proc/",
    "/run/",
    "/sys/",
    "/usr/",
    "/var/run/",
    "/workspace/",
)

logger = logging.getLogger(__name__)


def _input_mount_override_for_host_path(host_path: str) -> Dict[str, Any]:
    normalized = str(host_path or "").strip()
    if normalized.startswith("/dev/input/"):
        normalized = "/dev/input"
    return {
        "host": normalized or "/dev/input",
        "container": "/dev/input",
        "type": "bind",
        "mode": "rw",
    }

class HardwareResolution(BaseModel):
    blueprint_id: str
    connector: str = "container"
    target_type: str = "blueprint"
    target_id: str = ""
    supported: bool = False
    resolved_count: int = 0
    requires_restart: bool = False
    requires_approval: bool = False
    device_overrides: List[str] = Field(default_factory=list)
    mount_overrides: List[Dict[str, Any]] = Field(default_factory=list)
    block_device_refs: List[str] = Field(default_factory=list)
    block_apply_previews: List[Dict[str, Any]] = Field(default_factory=list)
    block_apply_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    block_apply_container_plans: List[Dict[str, Any]] = Field(default_factory=list)
    block_apply_engine_handoffs: List[Dict[str, Any]] = Field(default_factory=list)
    mount_refs: List[str] = Field(default_factory=list)
    stage_only_resource_ids: List[str] = Field(default_factory=list)
    unresolved_resource_ids: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


def _resolution_defaults(
    *,
    blueprint_id: str,
    connector: str = _DEFAULT_CONNECTOR,
    target_type: str = _DEFAULT_TARGET_TYPE,
    target_id: str = "",
) -> Dict[str, Any]:
    return {
        "blueprint_id": str(blueprint_id or "").strip(),
        "connector": str(connector or _DEFAULT_CONNECTOR).strip() or _DEFAULT_CONNECTOR,
        "target_type": str(target_type or _DEFAULT_TARGET_TYPE).strip() or _DEFAULT_TARGET_TYPE,
        "target_id": str(target_id or blueprint_id).strip() or str(blueprint_id or "").strip(),
    }


def empty_hardware_resolution(
    *,
    blueprint_id: str,
    connector: str = _DEFAULT_CONNECTOR,
    target_type: str = _DEFAULT_TARGET_TYPE,
    target_id: str = "",
    warnings: Iterable[str] | None = None,
) -> HardwareResolution:
    payload = _resolution_defaults(
        blueprint_id=blueprint_id,
        connector=connector,
        target_type=target_type,
        target_id=target_id,
    )
    resolution = HardwareResolution(**payload)
    for raw in list(warnings or []):
        warning = str(raw or "").strip()
        if warning:
            resolution.warnings.append(warning)
    return resolution


def _intent_payloads(intents: Iterable[Any]) -> List[Dict[str, Any]]:
    payloads: List[Dict[str, Any]] = []
    for raw in list(intents or []):
        if isinstance(raw, dict):
            payloads.append(dict(raw))
            continue
        model_dump = getattr(raw, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump()
            if isinstance(dumped, dict):
                payloads.append(dict(dumped))
    return payloads


def _intent_index(intents: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for raw in list(intents or []):
        item = dict(raw or {})
        resource_id = str(item.get("resource_id") or "").strip()
        if resource_id:
            index[resource_id] = item
    return index


def _base_urls() -> List[str]:
    return candidate_service_endpoints(
        configured=(os.environ.get("RUNTIME_HARDWARE_URL") or "").strip(),
        port=8420,
        scheme="http",
        service_name=os.environ.get("RUNTIME_HARDWARE_SERVICE_NAME", "").strip(),
        prefer_container_service=True,
        include_gateway=True,
        include_host_docker=True,
        include_loopback=True,
        include_localhost=True,
    )


def _request_runtime_hardware(
    *,
    method: str,
    path: str,
    json_body: Dict[str, Any],
    timeout: float = _DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    last_error: Exception | None = None
    for base_url in _base_urls():
        url = f"{base_url}{path}"
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.request(
                    method,
                    url,
                    json=json_body,
                    headers={"Accept": "application/json"},
                )
            content_type = response.headers.get("content-type", "")
            payload: Any
            if "application/json" in content_type:
                payload = response.json()
            else:
                payload = {"text": response.text}
            if response.status_code >= 400:
                raise RuntimeError(f"runtime_hardware_http_{response.status_code}:{payload}")
            return dict(payload or {}) if isinstance(payload, dict) else {}
        except Exception as exc:
            last_error = exc
            logger.warning("[HardwareResolution] %s %s failed via %s: %s", method, path, base_url, exc)
            continue
    raise RuntimeError(f"runtime_hardware_unreachable:{last_error}" if last_error else "runtime_hardware_unreachable")


def _runtime_hardware_local_support_dir() -> str:
    root = Path(__file__).resolve().parents[1]
    support_dir = root / "adapters" / "runtime-hardware"
    if support_dir.is_dir():
        return str(support_dir)
    app_support_dir = Path("/app/adapters/runtime-hardware")
    if app_support_dir.is_dir():
        return str(app_support_dir)
    return ""


def _local_runtime_hardware_has_host_visibility() -> bool:
    host_proc_visible = Path("/host_proc").exists()
    udev_visible = Path("/run/udev/data").exists()
    host_device_visible = any(
        Path(candidate).exists()
        for candidate in (
            "/dev/dri",
            "/dev/input",
            "/dev/uinput",
            "/dev/vfio/vfio",
        )
    )
    return host_proc_visible and udev_visible and host_device_visible


def _should_prefer_local_runtime_hardware() -> bool:
    forced = str(os.environ.get("RUNTIME_HARDWARE_LOCAL_FIRST") or "").strip().lower()
    if forced in {"1", "true", "yes", "on"}:
        return True
    if forced in {"0", "false", "no", "off"}:
        return False
    return Path("/app/adapters/runtime-hardware").is_dir() and _local_runtime_hardware_has_host_visibility()


def _request_runtime_hardware_local_fallback(
    *,
    path: str,
    json_body: Dict[str, Any],
) -> Dict[str, Any]:
    support_dir = _runtime_hardware_local_support_dir()
    if not support_dir:
        raise RuntimeError("runtime_hardware_local_support_unavailable")
    if support_dir not in sys.path:
        sys.path.insert(0, support_dir)

    try:
        from runtime_hardware.connectors import ContainerConnector
        from runtime_hardware.models import AttachmentIntent
        from runtime_hardware.connectors import container_storage_discovery as _container_storage_discovery
    except Exception as exc:
        raise RuntimeError(f"runtime_hardware_local_import_failed:{exc}") from exc

    connector_name = str(json_body.get("connector") or _DEFAULT_CONNECTOR).strip() or _DEFAULT_CONNECTOR
    if connector_name != "container":
        raise RuntimeError(f"runtime_hardware_local_connector_unsupported:{connector_name}")

    def _storage_broker_disks_payload(timeout: float = 8.0) -> Dict[str, Any]:
        broker_url = str(os.environ.get("STORAGE_BROKER_URL") or "http://storage-broker:8089").strip().rstrip("/")
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": "storage_list_disks", "arguments": {}},
            "id": 1,
        }
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                f"{broker_url}/mcp",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "mcp-session-id": "runtime-hardware-local-fallback",
                },
            )
        if response.status_code not in (200, 202):
            raise RuntimeError(f"storage_broker_http_{response.status_code}")
        for line in response.text.splitlines():
            if not line.startswith("data:"):
                continue
            envelope = json.loads(line[5:].strip())
            result = envelope.get("result", {})
            content = list(result.get("content") or [])
            if content:
                return dict(json.loads(content[0].get("text", "{}")) or {})
            return dict(result or {})
        return {}

    def _local_admin_equivalent(path_value: str, params: Dict[str, Any] | None = None, timeout: float = 8.0) -> Dict[str, Any]:
        normalized = str(path_value or "").strip()
        if normalized == "/api/storage-broker/disks":
            return _storage_broker_disks_payload(timeout=timeout)
        if normalized == "/api/commander/storage/assets":
            from container_commander.storage_assets import list_assets

            published_only = str((params or {}).get("published_only") or "").strip().lower() == "true"
            return {"assets": list_assets(published_only=published_only)}
        raise RuntimeError(f"runtime_hardware_local_admin_equivalent_unsupported:{normalized}")

    connector = ContainerConnector()
    original_fetch = _container_storage_discovery._fetch_admin_api_json
    _container_storage_discovery._fetch_admin_api_json = _local_admin_equivalent
    try:
        if path == "/hardware/plan":
            intents = [AttachmentIntent.model_validate(item) for item in list(json_body.get("intents") or [])]
            plan_obj = connector.plan(
                target_type=str(json_body.get("target_type") or _DEFAULT_TARGET_TYPE).strip() or _DEFAULT_TARGET_TYPE,
                target_id=str(json_body.get("target_id") or "").strip(),
                intents=intents,
            )
            return dict(plan_obj.model_dump())
        if path == "/hardware/validate":
            validate_obj = connector.validate(
                target_type=str(json_body.get("target_type") or _DEFAULT_TARGET_TYPE).strip() or _DEFAULT_TARGET_TYPE,
                target_id=str(json_body.get("target_id") or "").strip(),
                resource_ids=list(json_body.get("resource_ids") or []),
            )
            return dict(validate_obj.model_dump())
        raise RuntimeError(f"runtime_hardware_local_path_unsupported:{path}")
    finally:
        _container_storage_discovery._fetch_admin_api_json = original_fetch


def _normalize_container_target_path(raw_path: str) -> str:
    path = str(raw_path or "").strip()
    if not path or not path.startswith("/"):
        return ""
    normalized = posixpath.normpath(path)
    if not normalized.startswith("/"):
        return ""
    return normalized


def _is_blocked_container_target(path: str) -> bool:
    normalized = _normalize_container_target_path(path)
    if not normalized:
        return True
    if normalized in _BLOCKED_CONTAINER_TARGETS:
        return True
    return any(normalized.startswith(prefix) for prefix in _BLOCKED_CONTAINER_TARGET_PREFIXES)


def _materialize_mount_ref_overrides(
    *,
    resolution: HardwareResolution,
    intents: List[Dict[str, Any]],
) -> HardwareResolution:
    if not list(resolution.mount_refs or []):
        return resolution

    try:
        from .storage_assets import get_asset
    except Exception as exc:
        updated = resolution.model_copy(deep=True)
        updated.warnings.append(f"storage_asset_registry_unavailable:{exc}")
        return updated

    intent_by_resource = _intent_index(intents)
    updated = resolution.model_copy(deep=True)
    kept_warnings: List[str] = []
    resolved_mounts: set[str] = set()
    explicit_mount_targets: set[str] = set()
    new_unresolved: set[str] = set(updated.unresolved_resource_ids or [])

    for resource_id in list(updated.mount_refs or []):
        resource_key = str(resource_id or "").strip()
        kind, asset_id = _parse_resource_id(resource_key)
        if kind != "mount_ref" or not asset_id:
            new_unresolved.add(resource_key)
            updated.warnings.append(f"invalid_mount_ref:{resource_key}")
            continue

        intent = dict(intent_by_resource.get(resource_key) or {})
        policy = dict(intent.get("policy") or {})
        container_path = _normalize_container_target_path(
            str(policy.get("container_path") or policy.get("container") or "").strip()
        )
        if not container_path:
            kept_warnings.append(f"storage_broker_materialization_required:{resource_key}")
            continue
        explicit_mount_targets.add(resource_key)
        if _is_blocked_container_target(container_path):
            new_unresolved.add(resource_key)
            updated.warnings.append(f"blocked_mount_ref_target:{resource_key}:{container_path}")
            continue

        asset = get_asset(asset_id)
        if not asset:
            new_unresolved.add(resource_key)
            updated.warnings.append(f"storage_asset_not_found:{asset_id}")
            continue
        if not bool((asset or {}).get("published_to_commander")):
            new_unresolved.add(resource_key)
            updated.warnings.append(f"storage_asset_not_published:{asset_id}")
            continue

        policy_state = str((asset or {}).get("policy_state", "managed_rw") or "managed_rw").strip().lower()
        if policy_state not in {"blocked", "read_only", "managed_rw"}:
            policy_state = "managed_rw"
        if policy_state == "blocked":
            new_unresolved.add(resource_key)
            updated.warnings.append(f"storage_asset_policy_blocked:{asset_id}")
            continue

        asset_mode = str((asset or {}).get("default_mode", "ro") or "ro").strip().lower()
        if asset_mode not in {"ro", "rw"}:
            asset_mode = "ro"
        raw_mode = str(policy.get("mode") or "").strip().lower()
        mode = raw_mode or asset_mode
        if mode not in {"ro", "rw"}:
            new_unresolved.add(resource_key)
            updated.warnings.append(f"invalid_mount_ref_mode:{resource_key}")
            continue
        if policy_state == "read_only" and mode == "rw":
            new_unresolved.add(resource_key)
            updated.warnings.append(f"storage_asset_policy_read_only:{asset_id}")
            continue
        if asset_mode == "ro" and mode == "rw":
            new_unresolved.add(resource_key)
            updated.warnings.append(f"storage_asset_read_only:{asset_id}")
            continue

        override = {
            "asset_id": asset_id,
            "container": container_path,
            "type": "bind",
            "mode": mode,
        }
        if override not in updated.mount_overrides:
            updated.mount_overrides.append(override)
        resolved_mounts.add(resource_key)

    deduped_warnings: List[str] = []
    seen_warnings: set[str] = set()
    for raw in list(updated.warnings or []):
        warning = str(raw or "").strip()
        if not warning:
            continue
        if warning.startswith("storage_broker_materialization_required:"):
            resource_key = warning.split(":", 1)[1].strip()
            if resource_key in resolved_mounts or resource_key in explicit_mount_targets:
                continue
        if warning in seen_warnings:
            continue
        seen_warnings.add(warning)
        deduped_warnings.append(warning)
    for warning in kept_warnings:
        if warning and warning not in seen_warnings:
            seen_warnings.add(warning)
            deduped_warnings.append(warning)
    updated.warnings = deduped_warnings
    updated.unresolved_resource_ids = [item for item in list(updated.unresolved_resource_ids or []) if item not in resolved_mounts]
    for item in sorted(new_unresolved):
        if item and item not in updated.unresolved_resource_ids:
            updated.unresolved_resource_ids.append(item)
    updated.supported = (
        bool(updated.device_overrides or updated.mount_overrides or updated.block_device_refs or updated.mount_refs)
        and not updated.unresolved_resource_ids
    )
    return updated


def _parse_resource_id(resource_id: str) -> Tuple[str, str]:
    text = str(resource_id or "").strip()
    parts = text.split("::", 2)
    if len(parts) != 3:
        return "", ""
    return parts[1].strip(), parts[2].strip()


def _validate_issue_index(validate_payload: Dict[str, Any]) -> Dict[str, List[str]]:
    issues = list((validate_payload or {}).get("issues") or [])
    issue_index: Dict[str, List[str]] = {}
    for raw in issues:
        issue = str(raw or "").strip()
        if not issue:
            continue
        matched = False
        for prefix in ("resource_not_found:", "unsupported_resource_kind:"):
            if issue.startswith(prefix):
                key = issue.split(":", 1)[1].strip()
                issue_index.setdefault(key, []).append(issue)
                matched = True
                break
        if not matched:
            issue_index.setdefault("_global", []).append(issue)
    return issue_index


def resolve_hardware_plan(
    *,
    blueprint_id: str,
    intents: List[Dict[str, Any]],
    plan_payload: Dict[str, Any],
    validate_payload: Dict[str, Any],
    connector: str = "container",
    target_type: str = "blueprint",
    target_id: str = "",
) -> HardwareResolution:
    actions = list((plan_payload or {}).get("actions") or [])
    action_by_resource = {
        str(item.get("resource_id") or "").strip(): item
        for item in actions
        if str(item.get("resource_id") or "").strip()
    }
    issue_index = _validate_issue_index(validate_payload or {})

    resolution = HardwareResolution(
        **_resolution_defaults(
            blueprint_id=blueprint_id,
            connector=connector,
            target_type=target_type,
            target_id=target_id,
        )
    )

    seen_device_overrides: set[str] = set()
    seen_stage_only: set[str] = set()
    seen_unresolved: set[str] = set()
    seen_warnings: set[str] = set()
    seen_block_refs: set[str] = set()
    seen_mount_refs: set[str] = set()

    for intent in list(intents or []):
        resource_id = str((intent or {}).get("resource_id") or "").strip()
        if not resource_id:
            continue
        action = action_by_resource.get(resource_id) or {}
        action_kind = str(action.get("action") or "").strip()
        kind, host_path = _parse_resource_id(resource_id)
        issues = list(issue_index.get(resource_id) or [])

        if issues:
            for issue in issues:
                if issue not in seen_warnings:
                    resolution.warnings.append(issue)
                    seen_warnings.add(issue)
            if resource_id not in seen_unresolved:
                resolution.unresolved_resource_ids.append(resource_id)
                seen_unresolved.add(resource_id)
            continue

        if action_kind in {"unsupported", "reject"} or not host_path or not kind:
            if resource_id not in seen_unresolved:
                resolution.unresolved_resource_ids.append(resource_id)
                seen_unresolved.add(resource_id)
            explanation = str(action.get("explanation") or "").strip()
            if explanation and explanation not in seen_warnings:
                resolution.warnings.append(explanation)
                seen_warnings.add(explanation)
            continue

        if bool(action.get("requires_restart")):
            resolution.requires_restart = True
        if bool(action.get("requires_approval")):
            resolution.requires_approval = True

        if action_kind == "stage_for_recreate" and resource_id not in seen_stage_only:
            resolution.stage_only_resource_ids.append(resource_id)
            seen_stage_only.add(resource_id)

        policy = dict((intent or {}).get("policy") or {})

        if kind == "input" and action_kind != "stage_for_recreate":
            override = _input_mount_override_for_host_path(host_path)
            if override not in resolution.mount_overrides:
                resolution.mount_overrides.append(override)
                resolution.resolved_count += 1
            continue

        if kind in _RESOLVABLE_DEVICE_KINDS:
            container_path = str(policy.get("container_path") or host_path).strip() or host_path
            if not container_path.startswith("/"):
                container_path = host_path
            device_override = host_path if container_path == host_path else f"{host_path}:{container_path}"
            if device_override not in seen_device_overrides:
                resolution.device_overrides.append(device_override)
                seen_device_overrides.add(device_override)
                resolution.resolved_count += 1
            continue

        if kind == "block_device_ref":
            decision = _resolve_block_device_ref_impl(
                resource_id=resource_id,
                action=action,
                action_metadata=dict(action.get("metadata") or {}),
                policy=policy,
            )
            for item in list(decision.block_device_refs or []):
                if item and item not in seen_block_refs:
                    resolution.block_device_refs.append(item)
                    seen_block_refs.add(item)
                    resolution.resolved_count += 1
            for warning in list(decision.warnings or []):
                text = str(warning or "").strip()
                if text and text not in seen_warnings:
                    resolution.warnings.append(text)
                    seen_warnings.add(text)
            for item in list(decision.unresolved_resource_ids or []):
                if item and item not in seen_unresolved:
                    resolution.unresolved_resource_ids.append(item)
                    seen_unresolved.add(item)
            preview_decision = _build_block_apply_preview_impl(
                resource_id=resource_id,
                action_metadata=dict(action.get("metadata") or {}),
                policy=policy,
                unresolved=bool(decision.unresolved_resource_ids),
                warnings=list(decision.warnings or []),
            )
            for preview in list(preview_decision.previews or []):
                if preview and preview not in resolution.block_apply_previews:
                    resolution.block_apply_previews.append(dict(preview))
            candidate_decision = _build_block_apply_candidates_impl(list(preview_decision.previews or []))
            for candidate in list(candidate_decision.candidates or []):
                if candidate and candidate not in resolution.block_apply_candidates:
                    resolution.block_apply_candidates.append(dict(candidate))
            container_adapter_decision = _build_container_block_apply_adapter_plan_impl(list(candidate_decision.candidates or []))
            for plan in list(container_adapter_decision.plans or []):
                if plan and plan not in resolution.block_apply_container_plans:
                    resolution.block_apply_container_plans.append(dict(plan))
            engine_handoff_decision = _build_disabled_container_block_engine_handoffs_impl(
                list(container_adapter_decision.plans or [])
            )
            for handoff in list(engine_handoff_decision.handoffs or []):
                if handoff and handoff not in resolution.block_apply_engine_handoffs:
                    resolution.block_apply_engine_handoffs.append(dict(handoff))
            continue

        if kind == "mount_ref":
            if resource_id not in seen_mount_refs:
                resolution.mount_refs.append(resource_id)
                seen_mount_refs.add(resource_id)
                resolution.resolved_count += 1
            warning = f"storage_broker_materialization_required:{resource_id}"
            if warning not in seen_warnings:
                resolution.warnings.append(warning)
                seen_warnings.add(warning)
            continue

        if resource_id not in seen_unresolved:
            resolution.unresolved_resource_ids.append(resource_id)
            seen_unresolved.add(resource_id)

    resolution.supported = bool(intents) and not bool(resolution.unresolved_resource_ids)
    return resolution


def resolve_hardware_payloads_for_blueprint(
    *,
    blueprint_id: str,
    intents: Iterable[Any],
    plan_payload: Dict[str, Any],
    validate_payload: Dict[str, Any],
    connector: str = _DEFAULT_CONNECTOR,
    target_type: str = _DEFAULT_TARGET_TYPE,
    target_id: str = "",
) -> HardwareResolution:
    payloads = _intent_payloads(intents)
    resolution = resolve_hardware_plan(
        blueprint_id=blueprint_id,
        intents=payloads,
        plan_payload=plan_payload,
        validate_payload=validate_payload,
        connector=connector,
        target_type=target_type,
        target_id=target_id,
    )
    return _materialize_mount_ref_overrides(resolution=resolution, intents=payloads)


def resolve_blueprint_hardware_for_deploy(
    *,
    blueprint_id: str,
    intents: Iterable[Any],
    connector: str = _DEFAULT_CONNECTOR,
    target_type: str = _DEFAULT_TARGET_TYPE,
    target_id: str = "",
    timeout: float = _DEFAULT_TIMEOUT,
) -> HardwareResolution:
    payloads = _intent_payloads(intents)
    if not payloads:
        return empty_hardware_resolution(
            blueprint_id=blueprint_id,
            connector=connector,
            target_type=target_type,
            target_id=target_id,
        )

    target_id_value = str(target_id or blueprint_id).strip() or str(blueprint_id or "").strip()
    plan_body = {
        "connector": connector,
        "target_type": target_type,
        "target_id": target_id_value,
        "intents": payloads,
    }
    validate_body = {
        "connector": connector,
        "target_type": target_type,
        "target_id": target_id_value,
        "resource_ids": [item.get("resource_id", "") for item in payloads if str(item.get("resource_id", "")).strip()],
    }

    if _should_prefer_local_runtime_hardware():
        try:
            plan_payload = _request_runtime_hardware_local_fallback(
                path="/hardware/plan",
                json_body=plan_body,
            )
            validate_payload = _request_runtime_hardware_local_fallback(
                path="/hardware/validate",
                json_body=validate_body,
            )
        except Exception as local_exc:
            return empty_hardware_resolution(
                blueprint_id=blueprint_id,
                connector=connector,
                target_type=target_type,
                target_id=target_id_value,
                warnings=[f"runtime_hardware_local_resolution_unavailable:{local_exc}"],
            )
    else:
        try:
            plan_payload = _request_runtime_hardware(
                method="POST",
                path="/hardware/plan",
                json_body=plan_body,
                timeout=timeout,
            )
            validate_payload = _request_runtime_hardware(
                method="POST",
                path="/hardware/validate",
                json_body=validate_body,
                timeout=timeout,
            )
        except Exception as exc:
            logger.warning("[HardwareResolution] HTTP resolution unavailable, trying local fallback: %s", exc)
            try:
                plan_payload = _request_runtime_hardware_local_fallback(
                    path="/hardware/plan",
                    json_body=plan_body,
                )
                validate_payload = _request_runtime_hardware_local_fallback(
                    path="/hardware/validate",
                    json_body=validate_body,
                )
            except Exception as local_exc:
                return empty_hardware_resolution(
                    blueprint_id=blueprint_id,
                    connector=connector,
                    target_type=target_type,
                    target_id=target_id_value,
                    warnings=[f"runtime_hardware_resolution_unavailable:{exc}", f"runtime_hardware_local_resolution_unavailable:{local_exc}"],
                )
            logger.info("[HardwareResolution] Using local runtime-hardware fallback for deploy resolution")
    if _should_prefer_local_runtime_hardware():
        logger.info("[HardwareResolution] Using local runtime-hardware support for deploy resolution")
    if not isinstance(plan_payload, dict) or not isinstance(validate_payload, dict):
        return empty_hardware_resolution(
            blueprint_id=blueprint_id,
            connector=connector,
            target_type=target_type,
            target_id=target_id_value,
            warnings=["runtime_hardware_resolution_invalid_payload"],
        )

    return resolve_hardware_payloads_for_blueprint(
        blueprint_id=blueprint_id,
        intents=payloads,
        plan_payload=plan_payload,
        validate_payload=validate_payload,
        connector=connector,
        target_type=target_type,
        target_id=target_id_value,
    )


def merge_resolved_device_overrides(
    explicit_device_overrides: Iterable[str] | None,
    resolved_device_overrides: Iterable[str] | None,
) -> List[str]:
    merged: List[str] = []
    seen: set[str] = set()
    for raw in list(explicit_device_overrides or []) + list(resolved_device_overrides or []):
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        merged.append(item)
    return merged


def merge_resolved_mount_overrides(
    explicit_mount_overrides: Iterable[Dict[str, Any]] | None,
    resolved_mount_overrides: Iterable[Dict[str, Any]] | None,
) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str, str, str]] = set()
    for raw in list(explicit_mount_overrides or []) + list(resolved_mount_overrides or []):
        item = dict(raw or {})
        asset_id = str(item.get("asset_id") or "").strip()
        host = str(item.get("host") or "").strip()
        container = str(item.get("container") or "").strip()
        mount_type = str(item.get("type") or "bind").strip().lower() or "bind"
        mode = str(item.get("mode") or "rw").strip().lower() or "rw"
        key = (asset_id, host, container, mode)
        if not container or key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def build_resolution_warning_entries(resolution: HardwareResolution) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    seen_messages: set[str] = set()
    for raw in list(resolution.warnings or []):
        message = str(raw or "").strip()
        if not message or message in seen_messages:
            continue
        seen_messages.add(message)
        entries.append(
            {
                "name": "hardware_resolution",
                "detail": {
                    "message": message,
                    "connector": resolution.connector,
                    "target_type": resolution.target_type,
                    "target_id": resolution.target_id,
                },
            }
        )
    for resource_id in list(resolution.unresolved_resource_ids or []):
        item = str(resource_id or "").strip()
        if not item:
            continue
        message = f"unresolved_hardware_intent:{item}"
        if message in seen_messages:
            continue
        seen_messages.add(message)
        entries.append(
            {
                "name": "hardware_resolution",
                "detail": {
                    "message": message,
                    "resource_id": item,
                    "connector": resolution.connector,
                    "target_type": resolution.target_type,
                    "target_id": resolution.target_id,
                },
            }
        )
    for raw in list(resolution.block_apply_engine_handoffs or []):
        handoff = dict(raw or {})
        resource_id = str(handoff.get("resource_id") or "").strip()
        if not resource_id:
            continue
        message = f"disabled_block_engine_handoff_available:{resource_id}"
        if message in seen_messages:
            continue
        seen_messages.add(message)
        entries.append(
            {
                "name": "hardware_block_engine_handoff",
                "detail": {
                    "message": message,
                    "resource_id": resource_id,
                    "connector": resolution.connector,
                    "target_type": resolution.target_type,
                    "target_id": resolution.target_id,
                    "handoff": handoff,
                },
            }
        )
    return entries
