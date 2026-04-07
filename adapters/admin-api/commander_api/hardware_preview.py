from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from container_commander.hardware_resolution import resolve_hardware_payloads_for_blueprint
from container_commander.hardware_resolution_preview import (
    build_hardware_resolution_preview_payload,
)
from runtime_hardware_routes import proxy_runtime_hardware_request


def intent_payloads(blueprint) -> list[dict[str, Any]]:
    return [intent.model_dump() for intent in list(getattr(blueprint, "hardware_intents", []) or [])]


async def build_blueprint_hardware_preview_payload(
    blueprint,
    *,
    connector: str = "container",
    target_type: str = "blueprint",
    target_id: str = "",
) -> JSONResponse | dict[str, Any]:
    intents = intent_payloads(blueprint)
    effective_target_id = str(target_id or getattr(blueprint, "id", "")).strip() or str(getattr(blueprint, "id", "")).strip()
    if not intents:
        return {
            "available": False,
            "connector": connector,
            "target_type": target_type,
            "target_id": effective_target_id,
            "summary": {
                "supported": False,
                "resolved_count": 0,
                "requires_restart": False,
                "requires_approval": False,
                "device_override_count": 0,
                "mount_override_count": 0,
                "block_candidate_resource_ids": [],
                "container_plan_resource_ids": [],
                "engine_handoff_resource_ids": [],
                "block_apply_handoff_resource_ids_hint": [],
                "engine_opt_in_available": False,
                "unresolved_resource_ids": [],
                "warnings": [],
            },
            "resolution": None,
        }

    plan_payload = {
        "connector": connector,
        "target_type": target_type,
        "target_id": effective_target_id,
        "intents": intents,
    }
    validate_payload = {
        "connector": connector,
        "target_type": target_type,
        "target_id": effective_target_id,
        "resource_ids": [intent.get("resource_id", "") for intent in intents if intent.get("resource_id")],
    }

    plan_result = await proxy_runtime_hardware_request(
        method="POST",
        path="/hardware/plan",
        json_body=plan_payload,
    )
    if isinstance(plan_result, JSONResponse):
        return plan_result
    validate_result = await proxy_runtime_hardware_request(
        method="POST",
        path="/hardware/validate",
        json_body=validate_payload,
    )
    if isinstance(validate_result, JSONResponse):
        return validate_result

    resolution = resolve_hardware_payloads_for_blueprint(
        blueprint_id=str(getattr(blueprint, "id", "")).strip(),
        intents=intents,
        plan_payload=dict(plan_result or {}),
        validate_payload=dict(validate_result or {}),
        connector=connector,
        target_type=target_type,
        target_id=effective_target_id,
    )
    return {
        "available": True,
        "connector": connector,
        "target_type": target_type,
        "target_id": effective_target_id,
        "summary": build_hardware_resolution_preview_payload(resolution),
        "resolution": resolution.model_dump(),
    }
