from __future__ import annotations

from typing import Any, Dict, Iterable, List


def _resource_ids(items: Iterable[Dict[str, Any]] | None) -> List[str]:
    values: List[str] = []
    seen: set[str] = set()
    for raw in list(items or []):
        item = dict(raw or {})
        resource_id = str(item.get("resource_id") or "").strip()
        if not resource_id or resource_id in seen:
            continue
        seen.add(resource_id)
        values.append(resource_id)
    return values


def build_hardware_resolution_preview_payload(resolution: Any) -> Dict[str, Any]:
    model_dump = getattr(resolution, "model_dump", None)
    payload = dict(model_dump() if callable(model_dump) else dict(resolution or {}))

    block_candidate_resource_ids = _resource_ids(payload.get("block_apply_candidates"))
    container_plan_resource_ids = _resource_ids(payload.get("block_apply_container_plans"))
    engine_handoff_resource_ids = _resource_ids(payload.get("block_apply_engine_handoffs"))

    return {
        "supported": bool(payload.get("supported")),
        "resolved_count": int(payload.get("resolved_count") or 0),
        "requires_restart": bool(payload.get("requires_restart")),
        "requires_approval": bool(payload.get("requires_approval")),
        "device_override_count": len(list(payload.get("device_overrides") or [])),
        "mount_override_count": len(list(payload.get("mount_overrides") or [])),
        "block_candidate_resource_ids": block_candidate_resource_ids,
        "container_plan_resource_ids": container_plan_resource_ids,
        "engine_handoff_resource_ids": engine_handoff_resource_ids,
        "block_apply_handoff_resource_ids_hint": list(engine_handoff_resource_ids),
        "engine_opt_in_available": bool(engine_handoff_resource_ids),
        "unresolved_resource_ids": [str(item or "").strip() for item in list(payload.get("unresolved_resource_ids") or []) if str(item or "").strip()],
        "warnings": [str(item or "").strip() for item in list(payload.get("warnings") or []) if str(item or "").strip()],
    }
