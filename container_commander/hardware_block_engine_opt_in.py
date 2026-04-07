from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List


@dataclass(slots=True)
class BlockEngineOptInDecision:
    requested_resource_ids: List[str] = field(default_factory=list)
    device_overrides: List[str] = field(default_factory=list)
    selected_resource_ids: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def select_block_engine_handoffs(
    handoffs: List[Dict[str, Any]] | None,
    requested_resource_ids: Iterable[Any] | None,
) -> BlockEngineOptInDecision:
    requested: List[str] = []
    seen_requested: set[str] = set()
    for raw in list(requested_resource_ids or []):
        item = str(raw or "").strip()
        if not item or item in seen_requested:
            continue
        seen_requested.add(item)
        requested.append(item)

    if not requested:
        return BlockEngineOptInDecision()

    handoff_index: Dict[str, Dict[str, Any]] = {}
    for raw in list(handoffs or []):
        handoff = dict(raw or {})
        resource_id = str(handoff.get("resource_id") or "").strip()
        if resource_id and resource_id not in handoff_index:
            handoff_index[resource_id] = handoff

    device_overrides: List[str] = []
    selected_resource_ids: List[str] = []
    warnings: List[str] = []
    seen_overrides: set[str] = set()

    for resource_id in requested:
        handoff = dict(handoff_index.get(resource_id) or {})
        if not handoff:
            warnings.append(f"block_engine_handoff_opt_in_unmatched:{resource_id}")
            continue
        selected_resource_ids.append(resource_id)
        warnings.append(f"block_engine_handoff_opt_in_applied:{resource_id}")
        for raw_override in list(handoff.get("device_overrides") or []):
            override = str(raw_override or "").strip()
            if not override or override in seen_overrides:
                continue
            seen_overrides.add(override)
            device_overrides.append(override)

    return BlockEngineOptInDecision(
        requested_resource_ids=requested,
        device_overrides=device_overrides,
        selected_resource_ids=selected_resource_ids,
        warnings=warnings,
    )
