"""
Container Commander — REST API Routes (modularized)
════════════════════════════════════════════════════
Main router keeps blueprint lifecycle + deploy path and composes specialized
subrouters from `commander_api/*`.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from commander_api.common import exception_response

try:
    from container_commander.engine import PendingApprovalError
except ImportError:
    class PendingApprovalError(Exception):
        approval_id = ""
        reason = ""

logger = logging.getLogger(__name__)
router = APIRouter()


def _runtime_deploy_error_meta(message: str) -> tuple[str, int]:
    msg = str(message or "").strip().lower()
    if msg.startswith("healthcheck_timeout_auto_stopped"):
        return "healthcheck_timeout", 504
    if msg.startswith("healthcheck_unhealthy_auto_stopped"):
        return "healthcheck_unhealthy", 409
    if msg.startswith("container_exited_before_ready_auto_stopped"):
        return "container_not_ready", 409
    return "deploy_conflict", 409


# ═══════════════════════════════════════════════════════════
# BLUEPRINT ENDPOINTS (kept local: includes tombstone logic)
# ═══════════════════════════════════════════════════════════

@router.get("/blueprints")
async def api_list_blueprints(tag: Optional[str] = None):
    try:
        from container_commander.blueprint_store import list_blueprints

        bps = list_blueprints(tag=tag)
        return {"blueprints": [bp.model_dump() for bp in bps], "count": len(bps)}
    except Exception as e:
        logger.error(f"[Commander] List blueprints: {e}")
        return exception_response(e)


@router.get("/blueprints/{blueprint_id}")
async def api_get_blueprint(blueprint_id: str, resolve: bool = True, hardware_preview: bool = False):
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
        payload = bp.model_dump()
        if hardware_preview:
            try:
                from commander_api.hardware_preview import build_blueprint_hardware_preview_payload

                preview_payload = await build_blueprint_hardware_preview_payload(
                    bp,
                    connector="container",
                    target_type="blueprint",
                    target_id=bp.id,
                )
                if isinstance(preview_payload, JSONResponse):
                    return preview_payload
                payload["hardware_preview"] = preview_payload
            except Exception as exc:
                payload["hardware_preview_error"] = str(exc)
        return payload
    except Exception as e:
        return exception_response(e)


@router.post("/blueprints")
async def api_create_blueprint(request: Request):
    try:
        from container_commander.blueprint_store import create_blueprint, sync_blueprint_to_graph
        from container_commander.models import Blueprint, ResourceLimits, SecretRequirement, MountDef, NetworkMode
        from container_commander.trust import evaluate_blueprint_trust
        import asyncio

        data = await request.json()
        resources = ResourceLimits(**(data.pop("resources", {})))
        secrets = [SecretRequirement(**s) for s in data.pop("secrets_required", [])]
        mounts = [MountDef(**m) for m in data.pop("mounts", [])]
        network = NetworkMode(data.pop("network", "internal"))
        bp = Blueprint(
            resources=resources,
            secrets_required=secrets,
            mounts=mounts,
            network=network,
            **{k: v for k, v in data.items() if k in Blueprint.model_fields},
        )
        created = create_blueprint(bp)
        try:
            _trust = evaluate_blueprint_trust(created)["level"]
            asyncio.create_task(asyncio.to_thread(sync_blueprint_to_graph, created, trust_level=_trust))
        except Exception:
            pass
        return {"created": True, "blueprint": created.model_dump()}
    except Exception as e:
        return exception_response(e)


@router.put("/blueprints/{blueprint_id}")
async def api_update_blueprint(blueprint_id: str, request: Request):
    try:
        from container_commander.blueprint_store import update_blueprint, sync_blueprint_to_graph
        from container_commander.trust import evaluate_blueprint_trust
        import asyncio

        data = await request.json()
        updated = update_blueprint(blueprint_id, data)
        if not updated:
            return exception_response(
                HTTPException(404, f"Blueprint '{blueprint_id}' not found"),
                error_code="not_found",
                details={"updated": False, "blueprint_id": blueprint_id},
            )
        try:
            _trust = evaluate_blueprint_trust(updated)["level"]
            asyncio.create_task(asyncio.to_thread(sync_blueprint_to_graph, updated, _trust, True))
        except Exception:
            pass
        return {"updated": True, "blueprint": updated.model_dump()}
    except Exception as e:
        return exception_response(e)


@router.delete("/blueprints/{blueprint_id}")
async def api_delete_blueprint(blueprint_id: str):
    try:
        from container_commander.blueprint_store import delete_blueprint

        deleted = delete_blueprint(blueprint_id)
        if not deleted:
            return exception_response(
                HTTPException(404, f"Blueprint '{blueprint_id}' not found"),
                error_code="not_found",
                details={"deleted": False, "blueprint_id": blueprint_id},
            )

        # Primary delete consistency is SQLite truth (fail-closed in graph hygiene).
        # Tombstone graph node asynchronously so reconcile jobs can clean stale nodes.
        import asyncio as _asyncio

        async def _tombstone():
            try:
                from container_commander.blueprint_store import remove_blueprint_from_graph
                await _asyncio.to_thread(remove_blueprint_from_graph, blueprint_id)
            except Exception as _e:
                logger.warning(
                    f"[Blueprint] Graph tombstone failed for '{blueprint_id}' (non-critical): {_e}"
                )

        _asyncio.create_task(_tombstone())
        return {"deleted": True, "blueprint_id": blueprint_id}
    except Exception as e:
        return exception_response(e)


@router.post("/blueprints/import")
async def api_import_blueprint(request: Request):
    try:
        from container_commander.blueprint_store import import_from_yaml, sync_blueprint_to_graph
        from container_commander.trust import evaluate_blueprint_trust
        import asyncio

        data = await request.json()
        yaml_content = data.get("yaml", "")
        if not yaml_content:
            return exception_response(
                HTTPException(400, "'yaml' field is required"),
                error_code="bad_request",
                details={"imported": False},
            )
        bp = import_from_yaml(yaml_content)
        try:
            _trust = evaluate_blueprint_trust(bp)["level"]
            asyncio.create_task(asyncio.to_thread(sync_blueprint_to_graph, bp, trust_level=_trust))
        except Exception:
            pass
        return {"imported": True, "blueprint": bp.model_dump()}
    except Exception as e:
        return exception_response(e)


@router.get("/blueprints/{blueprint_id}/yaml")
async def api_export_yaml(blueprint_id: str):
    try:
        from container_commander.blueprint_store import export_to_yaml

        yaml_str = export_to_yaml(blueprint_id)
        if not yaml_str:
            return exception_response(
                HTTPException(404, f"Blueprint '{blueprint_id}' not found"),
                error_code="not_found",
                details={"blueprint_id": blueprint_id},
            )
        return {"blueprint_id": blueprint_id, "yaml": yaml_str}
    except Exception as e:
        return exception_response(e)


# ═══════════════════════════════════════════════════════════
# CONTAINER DEPLOY (kept local for explicit parity checks)
# ═══════════════════════════════════════════════════════════

@router.post("/containers/deploy")
async def api_deploy_container(request: Request):
    """Deploy a container from a blueprint via Docker Engine."""
    try:
        from container_commander.engine import start_container
        from container_commander.models import ResourceLimits

        data = await request.json()
        blueprint_id = data.get("blueprint_id", "")
        if not blueprint_id:
            return exception_response(
                HTTPException(400, "'blueprint_id' is required"),
                error_code="bad_request",
                details={"deployed": False},
            )

        # P6-C: Accept tracking IDs — not silently dropped.
        conversation_id = data.get("conversation_id", "") or ""
        session_id = data.get("session_id", "") or ""
        if conversation_id or session_id:
            logger.debug(
                "[Commander] Deploy blueprint=%s conversation_id=%s session_id=%s",
                blueprint_id, conversation_id or "(none)", session_id or "(none)",
            )

        override = None
        if data.get("override_resources"):
            override = ResourceLimits(**data["override_resources"])
        mount_overrides = data.get("mount_overrides")
        storage_scope_override = data.get("storage_scope_override")
        device_overrides = data.get("device_overrides")
        block_apply_handoff_resource_ids = data.get("block_apply_handoff_resource_ids")

        instance = start_container(
            blueprint_id,
            override,
            data.get("environment"),
            data.get("resume_volume"),
            mount_overrides=mount_overrides,
            storage_scope_override=storage_scope_override,
            device_overrides=device_overrides,
            block_apply_handoff_resource_ids=block_apply_handoff_resource_ids,
            session_id=session_id,
            conversation_id=conversation_id,
        )
        return {
            "deployed": True,
            "container": instance.model_dump(),
            "hardware_deploy": {
                "block_apply_handoff_resource_ids_requested": list(instance.block_apply_handoff_resource_ids_requested or []),
                "block_apply_handoff_resource_ids_applied": list(instance.block_apply_handoff_resource_ids_applied or []),
                "hardware_resolution_preview": dict(instance.hardware_resolution_preview or {}),
            },
        }
    except PendingApprovalError as e:
        # P6-C parity: response must include correlation IDs.
        return JSONResponse(
            {
                "deployed": False,
                "pending_approval": True,
                "approval_id": e.approval_id,
                "reason": e.reason,
                "block_apply_handoff_resource_ids_requested": list(block_apply_handoff_resource_ids or []),
                "conversation_id": conversation_id or None,
                "session_id": session_id or None,
            },
            status_code=202,
        )
    except RuntimeError as e:
        runtime_code, runtime_status = _runtime_deploy_error_meta(str(e))
        return exception_response(
            e,
            status_code=runtime_status,
            error_code=runtime_code,
            details={"deployed": False},
        )
    except ValueError as e:
        return exception_response(
            e,
            status_code=404,
            error_code="not_found",
            details={"deployed": False},
        )
    except Exception as e:
        logger.error(f"[Commander] Deploy: {e}")
        return exception_response(e, details={"deployed": False})


# ═══════════════════════════════════════════════════════════
# COMPOSE MODULAR SUBROUTERS
# ═══════════════════════════════════════════════════════════

from commander_api.secrets import router as secrets_router
from commander_api.containers import router as containers_router
from commander_api.audit import router as audit_router
from commander_api.hardware import router as hardware_router
from commander_api.storage import router as storage_router
from commander_api.operations import router as operations_router
try:
    from trion_memory_routes import router as trion_memory_router
except ModuleNotFoundError as e:
    trion_memory_router = None
    logger.warning("[Commander] trion_memory_routes unavailable (%s) - TRION memory subroutes disabled", e)

router.include_router(secrets_router)
router.include_router(containers_router)
router.include_router(audit_router)
router.include_router(hardware_router)
router.include_router(storage_router)
router.include_router(operations_router)
if trion_memory_router is not None:
    router.include_router(trion_memory_router, prefix="/trion/memory")
