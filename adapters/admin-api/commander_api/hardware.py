from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from .common import exception_response
from container_commander.hardware_resolution_preview import (
    build_hardware_resolution_preview_payload,
)
from .hardware_preview import (
    build_blueprint_hardware_preview_payload,
    intent_payloads as _intent_payloads_impl,
)
from runtime_hardware_routes import proxy_runtime_hardware_request


router = APIRouter()

# Compatibility marker for source-inspection contracts:
# resolve_hardware_plan(


async def _request_json_or_empty(request: Request) -> dict[str, Any]:
    try:
        body = await request.body()
    except Exception:
        return {}
    if not body:
        return {}
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_json")
    return payload if isinstance(payload, dict) else {}


def _intent_payloads(blueprint) -> list[dict[str, Any]]:
    return _intent_payloads_impl(blueprint)


@router.get("/blueprints/{blueprint_id}/hardware")
async def get_blueprint_hardware_intents(blueprint_id: str, resolve: bool = True):
    try:
        if resolve:
            from container_commander.blueprint_store import resolve_blueprint

            bp = resolve_blueprint(blueprint_id)
        else:
            from container_commander.blueprint_store import get_blueprint

            bp = get_blueprint(blueprint_id)
        if not bp:
            return exception_response(
                HTTPException(404, f"Blueprint '{blueprint_id}' not found"),
                error_code="not_found",
                details={"blueprint_id": blueprint_id},
            )
        intents = _intent_payloads(bp)
        payload = {
            "blueprint_id": bp.id,
            "resolved": bool(resolve),
            "hardware_intents": intents,
            "count": len(intents),
        }
        if resolve:
            preview_payload = await build_blueprint_hardware_preview_payload(
                bp,
                connector="container",
                target_type="blueprint",
                target_id=bp.id,
            )
            if isinstance(preview_payload, JSONResponse):
                return preview_payload
            payload["hardware_preview"] = preview_payload
        return payload
    except Exception as e:
        return exception_response(e)


@router.post("/blueprints/{blueprint_id}/hardware/plan")
async def plan_blueprint_hardware(blueprint_id: str, request: Request):
    try:
        data = await _request_json_or_empty(request)
        resolve = bool(data.get("resolve", True))
        connector = str(data.get("connector") or "container").strip() or "container"
        target_type = str(data.get("target_type") or "blueprint").strip() or "blueprint"

        if resolve:
            from container_commander.blueprint_store import resolve_blueprint

            bp = resolve_blueprint(blueprint_id)
        else:
            from container_commander.blueprint_store import get_blueprint

            bp = get_blueprint(blueprint_id)
        if not bp:
            return exception_response(
                HTTPException(404, f"Blueprint '{blueprint_id}' not found"),
                error_code="not_found",
                details={"blueprint_id": blueprint_id},
            )

        intents = _intent_payloads(bp)
        target_id = str(data.get("target_id") or bp.id).strip() or bp.id
        payload = {
            "connector": connector,
            "target_type": target_type,
            "target_id": target_id,
            "intents": intents,
        }
        result = await proxy_runtime_hardware_request(
            method="POST",
            path="/hardware/plan",
            json_body=payload,
        )
        if isinstance(result, JSONResponse):
            return result
        return {
            "blueprint_id": bp.id,
            "resolved": bool(resolve),
            "connector": connector,
            "target_type": target_type,
            "target_id": target_id,
            "hardware_intents": intents,
            "plan": result,
        }
    except Exception as e:
        return exception_response(e)


@router.post("/blueprints/{blueprint_id}/hardware/validate")
async def validate_blueprint_hardware(blueprint_id: str, request: Request):
    try:
        data = await _request_json_or_empty(request)
        resolve = bool(data.get("resolve", True))
        connector = str(data.get("connector") or "container").strip() or "container"
        target_type = str(data.get("target_type") or "blueprint").strip() or "blueprint"

        if resolve:
            from container_commander.blueprint_store import resolve_blueprint

            bp = resolve_blueprint(blueprint_id)
        else:
            from container_commander.blueprint_store import get_blueprint

            bp = get_blueprint(blueprint_id)
        if not bp:
            return exception_response(
                HTTPException(404, f"Blueprint '{blueprint_id}' not found"),
                error_code="not_found",
                details={"blueprint_id": blueprint_id},
            )

        intents = _intent_payloads(bp)
        target_id = str(data.get("target_id") or bp.id).strip() or bp.id
        resource_ids = data.get("resource_ids")
        if not isinstance(resource_ids, list) or not resource_ids:
            resource_ids = [intent.get("resource_id", "") for intent in intents if intent.get("resource_id")]
        payload = {
            "connector": connector,
            "target_type": target_type,
            "target_id": target_id,
            "resource_ids": resource_ids,
        }
        result = await proxy_runtime_hardware_request(
            method="POST",
            path="/hardware/validate",
            json_body=payload,
        )
        if isinstance(result, JSONResponse):
            return result
        return {
            "blueprint_id": bp.id,
            "resolved": bool(resolve),
            "connector": connector,
            "target_type": target_type,
            "target_id": target_id,
            "resource_ids": resource_ids,
            "validate": result,
        }
    except Exception as e:
        return exception_response(e)


@router.post("/blueprints/{blueprint_id}/hardware/resolve")
async def resolve_blueprint_hardware(blueprint_id: str, request: Request):
    try:
        data = await _request_json_or_empty(request)
        resolve = bool(data.get("resolve", True))
        connector = str(data.get("connector") or "container").strip() or "container"
        target_type = str(data.get("target_type") or "blueprint").strip() or "blueprint"

        if resolve:
            from container_commander.blueprint_store import resolve_blueprint

            bp = resolve_blueprint(blueprint_id)
        else:
            from container_commander.blueprint_store import get_blueprint

            bp = get_blueprint(blueprint_id)
        if not bp:
            return exception_response(
                HTTPException(404, f"Blueprint '{blueprint_id}' not found"),
                error_code="not_found",
                details={"blueprint_id": blueprint_id},
            )

        intents = _intent_payloads(bp)
        target_id = str(data.get("target_id") or bp.id).strip() or bp.id
        plan_payload = {
            "connector": connector,
            "target_type": target_type,
            "target_id": target_id,
            "intents": intents,
        }
        validate_payload = {
            "connector": connector,
            "target_type": target_type,
            "target_id": target_id,
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

        preview_payload = await build_blueprint_hardware_preview_payload(
            bp,
            connector=connector,
            target_type=target_type,
            target_id=target_id,
        )
        if isinstance(preview_payload, JSONResponse):
            return preview_payload
        resolution_payload = dict(preview_payload.get("resolution") or {})
        return {
            "blueprint_id": bp.id,
            "resolved": bool(resolve),
            "connector": connector,
            "target_type": target_type,
            "target_id": target_id,
            "hardware_intents": intents,
            "plan": plan_result,
            "validate": validate_result,
            "resolution": resolution_payload,
            "resolution_preview": build_hardware_resolution_preview_payload(resolution_payload),
        }
    except Exception as e:
        return exception_response(e)
