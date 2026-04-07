from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import APIRouter, HTTPException

from .connectors import ContainerConnector
from .models import (
    HealthResponse,
    PlanRequest,
    ValidateRequest,
)
from .store import StateStore


router = APIRouter()
logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _store() -> StateStore:
    return StateStore.from_env()


@lru_cache(maxsize=1)
def _connectors() -> dict:
    return {"container": ContainerConnector()}


def _connector_or_404(connector_name: str):
    connector = _connectors().get(connector_name)
    if connector is None:
        raise HTTPException(status_code=404, detail=f"connector_not_found:{connector_name}")
    return connector


def _write_state_snapshot(name: str, payload: dict) -> None:
    try:
        _store().write_json(name, payload)
    except Exception as exc:
        logger.warning("runtime-hardware state snapshot skipped for %s: %s", name, exc)


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    store = _store()
    return HealthResponse(
        service="jarvis-runtime-hardware",
        status="ok",
        connectors=sorted(_connectors().keys()),
        config_dir=str(store.config_dir),
        state_dir=str(store.state_dir),
    )


@router.get("/hardware/connectors")
def connectors() -> dict:
    return {"connectors": [connector.info().model_dump() for connector in _connectors().values()]}


@router.get("/hardware/capabilities")
def capabilities() -> dict:
    items = []
    for connector in _connectors().values():
        items.extend(cap.model_dump() for cap in connector.get_capabilities())
    return {"capabilities": items, "count": len(items)}


@router.get("/hardware/resources")
def resources(connector: str = "container") -> dict:
    selected = _connector_or_404(connector)
    items = [resource.model_dump() for resource in selected.list_resources()]
    _write_state_snapshot("last_resources.json", {"connector": connector, "count": len(items), "resources": items})
    return {"resources": items, "count": len(items), "connector": connector}


@router.get("/hardware/targets/{target_type}/{target_id}/state")
def target_state(target_type: str, target_id: str, connector: str = "container") -> dict:
    selected = _connector_or_404(connector)
    return selected.get_target_state(target_type=target_type, target_id=target_id).model_dump()


@router.post("/hardware/plan")
def plan(request: PlanRequest) -> dict:
    selected = _connector_or_404(request.connector)
    plan_obj = selected.plan(
        target_type=request.target_type,
        target_id=request.target_id,
        intents=list(request.intents),
    )
    payload = plan_obj.model_dump()
    _write_state_snapshot("last_plan.json", payload)
    return payload


@router.post("/hardware/validate")
def validate(request: ValidateRequest) -> dict:
    selected = _connector_or_404(request.connector)
    result = selected.validate(
        target_type=request.target_type,
        target_id=request.target_id,
        resource_ids=list(request.resource_ids),
    )
    payload = result.model_dump()
    _write_state_snapshot("last_validate.json", payload)
    return payload
