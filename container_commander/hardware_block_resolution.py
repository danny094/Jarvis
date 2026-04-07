from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(slots=True)
class BlockDeviceResolutionDecision:
    block_device_refs: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    unresolved_resource_ids: List[str] = field(default_factory=list)


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def resolve_block_device_ref(
    *,
    resource_id: str,
    action: Dict[str, Any] | None = None,
    action_metadata: Dict[str, Any] | None = None,
    policy: Dict[str, Any] | None = None,
) -> BlockDeviceResolutionDecision:
    resource_key = str(resource_id or "").strip()
    if not resource_key:
        return BlockDeviceResolutionDecision()

    metadata = dict(action_metadata or {})
    resource_metadata = dict(metadata.get("resource_metadata") or {})
    requested_mode = str((policy or {}).get("mode") or "").strip().lower()
    policy_state = _normalize_text(resource_metadata.get("policy_state"))
    zone = _normalize_text(resource_metadata.get("zone"))
    disk_type = _normalize_text(resource_metadata.get("disk_type"))
    allowed_operations = {
        _normalize_text(item) for item in list(resource_metadata.get("allowed_operations") or []) if _normalize_text(item)
    }
    host_path = str(metadata.get("host_path") or "").strip()
    is_system = bool(resource_metadata.get("is_system")) or zone == "system"

    if host_path and not host_path.startswith("/dev/"):
        return BlockDeviceResolutionDecision(
            warnings=[f"invalid_block_device_host_path:{resource_key}"],
            unresolved_resource_ids=[resource_key],
        )

    if is_system:
        return BlockDeviceResolutionDecision(
            warnings=[f"system_block_device_ref_forbidden:{resource_key}"],
            unresolved_resource_ids=[resource_key],
        )

    if policy_state == "blocked":
        return BlockDeviceResolutionDecision(
            warnings=[f"storage_broker_policy_blocked:{resource_key}"],
            unresolved_resource_ids=[resource_key],
        )

    if requested_mode == "rw" and policy_state == "read_only":
        return BlockDeviceResolutionDecision(
            warnings=[f"storage_broker_policy_read_only:{resource_key}"],
            unresolved_resource_ids=[resource_key],
        )

    if allowed_operations and "assign_to_container" not in allowed_operations:
        return BlockDeviceResolutionDecision(
            warnings=[f"storage_broker_operation_not_allowed:{resource_key}"],
            unresolved_resource_ids=[resource_key],
        )

    decision = BlockDeviceResolutionDecision(
        block_device_refs=[resource_key],
        warnings=[f"storage_review_required:{resource_key}"],
    )
    if disk_type == "disk":
        decision.warnings.append(f"whole_disk_review_required:{resource_key}")
    if requested_mode == "rw":
        decision.warnings.append(f"block_device_write_review_required:{resource_key}")

    explanation = str(((action or {}).get("explanation")) or "").strip()
    if explanation and explanation.startswith(("storage_", "block_device_")):
        decision.warnings.append(explanation)

    return decision
