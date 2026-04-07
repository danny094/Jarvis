from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(slots=True)
class BlockApplyCandidateDecision:
    candidates: List[Dict[str, Any]] = field(default_factory=list)


def build_block_apply_candidates(
    previews: List[Dict[str, Any]] | None,
) -> BlockApplyCandidateDecision:
    candidates: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for raw in list(previews or []):
        preview = dict(raw or {})
        if not bool(preview.get("eligible")):
            continue
        resource_id = str(preview.get("resource_id") or "").strip()
        host_path = str(preview.get("host_path") or "").strip()
        runtime_target = str(preview.get("target_runtime") or "").strip() or "container"
        runtime_path = str(preview.get("target_runtime_path") or "").strip()
        runtime_binding = dict(preview.get("candidate_runtime_binding") or {})
        binding_expression = str(runtime_binding.get("binding_expression") or "").strip()
        if not resource_id or not binding_expression or not runtime_path or not host_path:
            continue
        if resource_id in seen:
            continue
        seen.add(resource_id)
        candidates.append(
            {
                "resource_id": resource_id,
                "host_path": host_path,
                "target_runtime": runtime_target,
                "target_runtime_path": runtime_path,
                "runtime_binding": {
                    "kind": str(runtime_binding.get("kind") or "device_path").strip() or "device_path",
                    "source_path": str(runtime_binding.get("source_path") or host_path).strip() or host_path,
                    "target_path": str(runtime_binding.get("target_path") or runtime_path).strip() or runtime_path,
                    "binding_expression": binding_expression,
                },
                "requested_mode": str(preview.get("requested_mode") or "").strip() or "ro",
                "apply_strategy": str(preview.get("apply_strategy") or "runtime_device_binding").strip(),
                "activation_state": "disabled_until_engine_support",
                "activation_reason": "future_engine_block_apply_enablement",
                "requires_restart": bool(preview.get("requires_restart")),
                "requires_approval": bool(preview.get("requires_approval")),
                "requirements": [str(item or "").strip() for item in list(preview.get("requirements") or []) if str(item or "").strip()],
                "warnings": [str(item or "").strip() for item in list(preview.get("warnings") or []) if str(item or "").strip()],
                "runtime_parameters": dict(preview.get("runtime_parameters") or {}),
            }
        )

    return BlockApplyCandidateDecision(candidates=candidates)
