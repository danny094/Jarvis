from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(slots=True)
class ContainerBlockAdapterDecision:
    plans: List[Dict[str, Any]] = field(default_factory=list)


def build_container_block_apply_adapter_plan(
    candidates: List[Dict[str, Any]] | None,
) -> ContainerBlockAdapterDecision:
    plans: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for raw in list(candidates or []):
        candidate = dict(raw or {})
        resource_id = str(candidate.get("resource_id") or "").strip()
        target_runtime = str(candidate.get("target_runtime") or "").strip()
        runtime_binding = dict(candidate.get("runtime_binding") or {})
        binding_expression = str(runtime_binding.get("binding_expression") or "").strip()
        runtime_parameters = dict(candidate.get("runtime_parameters") or {})
        container_params = dict(runtime_parameters.get("container") or {})
        candidate_device_override = str(container_params.get("candidate_device_override") or "").strip()
        candidate_container_path = str(container_params.get("candidate_container_path") or "").strip()
        if not resource_id or resource_id in seen:
            continue
        seen.add(resource_id)
        if target_runtime != "container":
            continue
        if not binding_expression or not candidate_device_override or not candidate_container_path:
            continue
        plans.append(
            {
                "resource_id": resource_id,
                "target_runtime": "container",
                "adapter_state": "disabled_until_engine_support",
                "adapter_reason": "future_engine_block_apply_enablement",
                "device_overrides": [candidate_device_override],
                "container_path": candidate_container_path,
                "runtime_binding": {
                    "kind": str(runtime_binding.get("kind") or "device_path").strip() or "device_path",
                    "source_path": str(runtime_binding.get("source_path") or "").strip(),
                    "target_path": str(runtime_binding.get("target_path") or "").strip(),
                    "binding_expression": binding_expression,
                },
                "requirements": [str(item or "").strip() for item in list(candidate.get("requirements") or []) if str(item or "").strip()],
                "warnings": [str(item or "").strip() for item in list(candidate.get("warnings") or []) if str(item or "").strip()],
            }
        )

    return ContainerBlockAdapterDecision(plans=plans)
