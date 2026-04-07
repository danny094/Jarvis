from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(slots=True)
class BlockEngineHandoffDecision:
    handoffs: List[Dict[str, Any]] = field(default_factory=list)


def build_disabled_container_block_engine_handoffs(
    plans: List[Dict[str, Any]] | None,
) -> BlockEngineHandoffDecision:
    handoffs: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for raw in list(plans or []):
        plan = dict(raw or {})
        resource_id = str(plan.get("resource_id") or "").strip()
        target_runtime = str(plan.get("target_runtime") or "").strip()
        container_path = str(plan.get("container_path") or "").strip()
        device_overrides = [str(item or "").strip() for item in list(plan.get("device_overrides") or []) if str(item or "").strip()]
        runtime_binding = dict(plan.get("runtime_binding") or {})
        binding_expression = str(runtime_binding.get("binding_expression") or "").strip()
        if not resource_id or resource_id in seen:
            continue
        seen.add(resource_id)
        if target_runtime != "container":
            continue
        if not container_path or not device_overrides or not binding_expression:
            continue
        handoffs.append(
            {
                "resource_id": resource_id,
                "target_runtime": "container",
                "engine_handoff_state": "disabled_until_engine_support",
                "engine_handoff_reason": "explicit_engine_opt_in_required",
                "engine_target": "start_container",
                "device_overrides": list(device_overrides),
                "container_path": container_path,
                "runtime_binding": {
                    "kind": str(runtime_binding.get("kind") or "device_path").strip() or "device_path",
                    "source_path": str(runtime_binding.get("source_path") or "").strip(),
                    "target_path": str(runtime_binding.get("target_path") or "").strip(),
                    "binding_expression": binding_expression,
                },
                "requirements": [str(item or "").strip() for item in list(plan.get("requirements") or []) if str(item or "").strip()],
                "warnings": [str(item or "").strip() for item in list(plan.get("warnings") or []) if str(item or "").strip()],
            }
        )

    return BlockEngineHandoffDecision(handoffs=handoffs)
