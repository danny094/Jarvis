from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(slots=True)
class BlockApplyPreviewDecision:
    previews: List[Dict[str, Any]] = field(default_factory=list)


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_container_device_path(raw_path: Any) -> str:
    path = str(raw_path or "").strip()
    if not path or not path.startswith("/dev/") or ".." in path or any(ch.isspace() for ch in path):
        return ""
    return path


def build_block_apply_preview(
    *,
    resource_id: str,
    action_metadata: Dict[str, Any] | None = None,
    policy: Dict[str, Any] | None = None,
    unresolved: bool = False,
    warnings: List[str] | None = None,
) -> BlockApplyPreviewDecision:
    metadata = dict(action_metadata or {})
    resource_metadata = dict(metadata.get("resource_metadata") or {})
    host_path = str(metadata.get("host_path") or "").strip()
    requested_mode = _normalize_text((policy or {}).get("mode")) or "ro"
    disk_type = _normalize_text(resource_metadata.get("disk_type")) or "unknown"
    zone = _normalize_text(resource_metadata.get("zone")) or "unzoned"
    policy_state = _normalize_text(resource_metadata.get("policy_state")) or "unknown"
    raw_requested_runtime_path = (policy or {}).get("runtime_path") or (policy or {}).get("container_path") or (policy or {}).get("device_path")
    requested_runtime_path = _normalize_container_device_path(raw_requested_runtime_path)
    explicit_runtime_path_invalid = bool(str(raw_requested_runtime_path or "").strip()) and not requested_runtime_path
    target_runtime_path = requested_runtime_path or host_path
    allowed_operations = [
        _normalize_text(item)
        for item in list(resource_metadata.get("allowed_operations") or [])
        if _normalize_text(item)
    ]

    reason = "review_only"
    eligible = False
    apply_mode = "review_only"
    blockers: List[str] = []

    if unresolved:
        reason = "policy_blocked"
        blockers.append("policy_blocked")
    elif disk_type != "part":
        reason = "whole_disk_or_unknown_review_only"
        blockers.append("whole_disk_or_unknown_review_only")
    elif requested_mode not in {"ro", "rw"}:
        reason = "invalid_requested_mode"
        blockers.append("invalid_requested_mode")
    elif policy_state not in {"managed_rw", "read_only"}:
        reason = "unsupported_policy_state"
        blockers.append("unsupported_policy_state")
    elif requested_mode == "rw" and policy_state != "managed_rw":
        reason = "write_not_permitted"
        blockers.append("write_not_permitted")
    elif allowed_operations and "assign_to_container" not in allowed_operations:
        reason = "operation_not_allowed"
        blockers.append("operation_not_allowed")
    elif not host_path.startswith("/dev/"):
        reason = "invalid_host_path"
        blockers.append("invalid_host_path")
    elif explicit_runtime_path_invalid:
        reason = "invalid_container_device_path"
        blockers.append("invalid_container_device_path")
        target_runtime_path = ""
    elif not target_runtime_path:
        reason = "invalid_container_device_path"
        blockers.append("invalid_container_device_path")
    else:
        eligible = True
        apply_mode = "stage_device_passthrough_candidate"
        reason = "candidate_for_explicit_container_apply"

    candidate_device_override = ""
    if host_path.startswith("/dev/") and target_runtime_path:
        candidate_device_override = host_path if target_runtime_path == host_path else f"{host_path}:{target_runtime_path}"

    requirements = [
        "explicit_user_approval",
        "container_recreate_required",
        "future_engine_block_apply_enablement",
    ]
    if requested_mode == "rw":
        requirements.append("write_access_review")
    if eligible:
        requirements.append("device_path_must_remain_visible_on_host")

    preview = {
        "resource_id": str(resource_id or "").strip(),
        "host_path": host_path,
        "disk_type": disk_type,
        "zone": zone,
        "policy_state": policy_state,
        "requested_mode": requested_mode,
        "target_runtime": "container",
        "target_runtime_path": target_runtime_path,
        "candidate_runtime_binding": {
            "kind": "device_path",
            "source_path": host_path,
            "target_path": target_runtime_path,
            "binding_expression": candidate_device_override,
        },
        "apply_strategy": "runtime_device_binding",
        "allowed_operations": allowed_operations,
        "eligible": eligible,
        "apply_mode": apply_mode,
        "reason": reason,
        "requirements": requirements,
        "blockers": blockers,
        "requires_restart": True,
        "requires_approval": True,
        "warnings": [str(item or "").strip() for item in list(warnings or []) if str(item or "").strip()],
        "runtime_parameters": {
            "container": {
                "candidate_container_path": target_runtime_path,
                "candidate_device_override": candidate_device_override,
                "device_override_mode": "docker_devices",
            }
        },
    }
    return BlockApplyPreviewDecision(previews=[preview] if preview["resource_id"] else [])
