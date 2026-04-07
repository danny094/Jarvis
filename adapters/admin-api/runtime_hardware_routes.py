"""
Admin API — Runtime Hardware Gateway Routes
═══════════════════════════════════════════
Provides a stable admin-api gateway in front of the standalone
`jarvis-runtime-hardware` service.

Endpoints:
  GET  /api/runtime-hardware/health
  GET  /api/runtime-hardware/connectors
  GET  /api/runtime-hardware/capabilities
  GET  /api/runtime-hardware/resources
  GET  /api/runtime-hardware/targets/{target_type}/{target_id}/state
  POST /api/runtime-hardware/plan
  POST /api/runtime-hardware/validate
"""

from __future__ import annotations

import os
import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from utils.service_endpoint_resolver import candidate_service_endpoints


router = APIRouter(tags=["runtime-hardware"])
log = logging.getLogger(__name__)

def _base_urls() -> list[str]:
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


async def _proxy(
    *,
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> Any:
    last_error: Exception | None = None
    for base_url in _base_urls():
        url = f"{base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers={"Accept": "application/json"},
                )
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                payload: Any = response.json()
            else:
                payload = {"ok": response.is_success, "text": response.text}
            if response.status_code >= 400:
                return JSONResponse(payload, status_code=response.status_code)
            return payload
        except httpx.HTTPError as exc:
            last_error = exc
            log.warning("[RuntimeHardwareGateway] %s %s failed via %s: %s", method, path, base_url, exc)
            continue

    detail = f"runtime_hardware_unreachable:{last_error}" if last_error else "runtime_hardware_unreachable"
    raise HTTPException(status_code=503, detail=detail)


async def proxy_runtime_hardware_request(
    *,
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> Any:
    return await _proxy(
        method=method,
        path=path,
        params=params,
        json_body=json_body,
        timeout=timeout,
    )


@router.get("/health")
async def runtime_hardware_health():
    return await proxy_runtime_hardware_request(method="GET", path="/health")


@router.get("/connectors")
async def runtime_hardware_connectors():
    return await proxy_runtime_hardware_request(method="GET", path="/hardware/connectors")


@router.get("/capabilities")
async def runtime_hardware_capabilities():
    return await proxy_runtime_hardware_request(method="GET", path="/hardware/capabilities")


@router.get("/resources")
async def runtime_hardware_resources(connector: str = "container"):
    return await proxy_runtime_hardware_request(
        method="GET",
        path="/hardware/resources",
        params={"connector": connector},
    )


@router.get("/targets/{target_type}/{target_id}/state")
async def runtime_hardware_target_state(target_type: str, target_id: str, connector: str = "container"):
    return await proxy_runtime_hardware_request(
        method="GET",
        path=f"/hardware/targets/{target_type}/{target_id}/state",
        params={"connector": connector},
    )


@router.post("/plan")
async def runtime_hardware_plan(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    return await proxy_runtime_hardware_request(method="POST", path="/hardware/plan", json_body=body)


@router.post("/validate")
async def runtime_hardware_validate(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    return await proxy_runtime_hardware_request(method="POST", path="/hardware/validate", json_body=body)
