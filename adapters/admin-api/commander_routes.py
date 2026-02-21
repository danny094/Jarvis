"""
Container Commander — REST API Routes (Phase 2: Live Engine)
═══════════════════════════════════════════════════════════════
FastAPI router for Blueprint CRUD, Secret Vault, Container lifecycle.
Mounted at /api/commander in admin-api main.py
"""

import logging
from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

try:
    from container_commander.engine import PendingApprovalError
except ImportError:
    class PendingApprovalError(Exception):
        approval_id = ""
        reason = ""

logger = logging.getLogger(__name__)
router = APIRouter()


# ═══════════════════════════════════════════════════════════
# BLUEPRINT ENDPOINTS
# ═══════════════════════════════════════════════════════════

@router.get("/blueprints")
async def api_list_blueprints(tag: Optional[str] = None):
    try:
        from container_commander.blueprint_store import list_blueprints
        bps = list_blueprints(tag=tag)
        return {"blueprints": [bp.model_dump() for bp in bps], "count": len(bps)}
    except Exception as e:
        logger.error(f"[Commander] List blueprints: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/blueprints/{blueprint_id}")
async def api_get_blueprint(blueprint_id: str, resolve: bool = True):
    try:
        if resolve:
            from container_commander.blueprint_store import resolve_blueprint
            bp = resolve_blueprint(blueprint_id)
        else:
            from container_commander.blueprint_store import get_blueprint
            bp = get_blueprint(blueprint_id)
        if not bp:
            raise HTTPException(404, f"Blueprint '{blueprint_id}' not found")
        return bp.model_dump()
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/blueprints")
async def api_create_blueprint(request: Request):
    try:
        from container_commander.blueprint_store import create_blueprint
        from container_commander.models import Blueprint, ResourceLimits, SecretRequirement, MountDef, NetworkMode
        data = await request.json()
        resources = ResourceLimits(**(data.pop("resources", {})))
        secrets = [SecretRequirement(**s) for s in data.pop("secrets_required", [])]
        mounts = [MountDef(**m) for m in data.pop("mounts", [])]
        network = NetworkMode(data.pop("network", "internal"))
        bp = Blueprint(resources=resources, secrets_required=secrets, mounts=mounts, network=network,
                       **{k: v for k, v in data.items() if k in Blueprint.model_fields})
        created = create_blueprint(bp)
        # Sync new blueprint to graph immediately — trust via trust.py (single source of truth)
        try:
            import asyncio
            from container_commander.blueprint_store import _sync_single_blueprint_to_graph
            from container_commander.trust import evaluate_blueprint_trust
            _trust = evaluate_blueprint_trust(created)["level"]
            asyncio.create_task(asyncio.to_thread(_sync_single_blueprint_to_graph, created, trust_level=_trust))
        except Exception:
            pass  # Non-critical, will be picked up on next restart
        return {"created": True, "blueprint": created.model_dump()}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.put("/blueprints/{blueprint_id}")
async def api_update_blueprint(blueprint_id: str, request: Request):
    try:
        from container_commander.blueprint_store import update_blueprint
        data = await request.json()
        updated = update_blueprint(blueprint_id, data)
        if not updated:
            raise HTTPException(404, f"Blueprint '{blueprint_id}' not found")
        # Sync updated blueprint to graph immediately — force_update=True overwrites stale graph data
        try:
            import asyncio
            from container_commander.blueprint_store import _sync_single_blueprint_to_graph
            from container_commander.trust import evaluate_blueprint_trust
            _trust = evaluate_blueprint_trust(updated)["level"]
            asyncio.create_task(asyncio.to_thread(
                _sync_single_blueprint_to_graph, updated, _trust, True  # force_update=True
            ))
        except Exception:
            pass
        return {"updated": True, "blueprint": updated.model_dump()}
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.delete("/blueprints/{blueprint_id}")
async def api_delete_blueprint(blueprint_id: str):
    try:
        from container_commander.blueprint_store import delete_blueprint
        deleted = delete_blueprint(blueprint_id)
        if not deleted:
            raise HTTPException(404, f"Blueprint '{blueprint_id}' not found")

        # Phase 5 — Graph tombstone (non-critical, non-blocking):
        # Primary tombstone is the SQLite cross-check in core/graph_hygiene.py (fail-closed):
        # the deleted blueprint is immediately invisible in Router/Context.
        # Additionally tombstone the graph node so reconcile_graph_index.py can clean it up.
        import asyncio as _asyncio
        async def _tombstone():
            try:
                from container_commander.blueprint_store import remove_blueprint_from_graph
                await _asyncio.to_thread(remove_blueprint_from_graph, blueprint_id)
            except Exception as _e:
                logger.warning(f"[Blueprint] Graph tombstone failed for '{blueprint_id}' (non-critical): {_e}")
        _asyncio.create_task(_tombstone())

        return {"deleted": True, "blueprint_id": blueprint_id}
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/blueprints/import")
async def api_import_blueprint(request: Request):
    try:
        from container_commander.blueprint_store import import_from_yaml
        data = await request.json()
        yaml_content = data.get("yaml", "")
        if not yaml_content:
            raise HTTPException(400, "'yaml' field is required")
        bp = import_from_yaml(yaml_content)
        return {"imported": True, "blueprint": bp.model_dump()}
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/blueprints/{blueprint_id}/yaml")
async def api_export_yaml(blueprint_id: str):
    try:
        from container_commander.blueprint_store import export_to_yaml
        yaml_str = export_to_yaml(blueprint_id)
        if not yaml_str:
            raise HTTPException(404, f"Blueprint '{blueprint_id}' not found")
        return {"blueprint_id": blueprint_id, "yaml": yaml_str}
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════
# SECRET ENDPOINTS
# ═══════════════════════════════════════════════════════════

@router.get("/secrets")
async def api_list_secrets(scope: Optional[str] = None, blueprint_id: Optional[str] = None):
    try:
        from container_commander.secret_store import list_secrets
        from container_commander.models import SecretScope
        sec_scope = SecretScope(scope) if scope else None
        secs = list_secrets(scope=sec_scope, blueprint_id=blueprint_id)
        return {"secrets": [s.model_dump() for s in secs], "count": len(secs)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/secrets")
async def api_store_secret(request: Request):
    try:
        from container_commander.secret_store import store_secret
        from container_commander.models import SecretScope
        data = await request.json()
        name = data.get("name", "").strip()
        value = data.get("value", "")
        if not name or not value:
            raise HTTPException(400, "'name' and 'value' are required")
        scope = SecretScope(data.get("scope", "global"))
        entry = store_secret(name, value, scope, data.get("blueprint_id"), data.get("expires_at"))
        return {"stored": True, "secret": entry.model_dump()}
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.delete("/secrets/{secret_name}")
async def api_delete_secret(secret_name: str, scope: str = "global", blueprint_id: Optional[str] = None):
    try:
        from container_commander.secret_store import delete_secret
        from container_commander.models import SecretScope
        deleted = delete_secret(secret_name, SecretScope(scope), blueprint_id)
        if not deleted:
            raise HTTPException(404, f"Secret '{secret_name}' not found")
        return {"deleted": True, "name": secret_name}
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════
# CONTAINER ENDPOINTS (Phase 2: Live Docker Engine)
# ═══════════════════════════════════════════════════════════

@router.get("/containers")
async def api_list_containers():
    """List all TRION-managed containers with live status."""
    try:
        from container_commander.engine import list_containers
        cts = list_containers()
        return {"containers": [c.model_dump() for c in cts], "count": len(cts)}
    except Exception as e:
        logger.error(f"[Commander] List containers: {e}")
        return JSONResponse({"error": str(e), "containers": [], "count": 0}, status_code=500)


@router.post("/containers/deploy")
async def api_deploy_container(request: Request):
    """Deploy a container from a blueprint via Docker Engine."""
    try:
        from container_commander.engine import start_container
        from container_commander.models import ResourceLimits
        data = await request.json()
        blueprint_id = data.get("blueprint_id", "")
        if not blueprint_id:
            raise HTTPException(400, "'blueprint_id' is required")

        # P6-C: Accept tracking IDs — not silently dropped
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

        instance = start_container(
            blueprint_id, override, data.get("environment"), data.get("resume_volume"),
            session_id=session_id,
            conversation_id=conversation_id,
        )
        return {"deployed": True, "container": instance.model_dump()}
    except HTTPException:
        raise
    except PendingApprovalError as e:
        # Human-in-the-Loop: container needs user approval
        # P6-C: Echo back tracking IDs so the frontend can correlate approval with its session
        return JSONResponse({
            "deployed": False, "pending_approval": True,
            "approval_id": e.approval_id, "reason": e.reason,
            "conversation_id": conversation_id or None,
            "session_id": session_id or None,
        }, status_code=202)
    except RuntimeError as e:
        # Quota exceeded or start failed
        return JSONResponse({"deployed": False, "error": str(e)}, status_code=409)
    except ValueError as e:
        return JSONResponse({"deployed": False, "error": str(e)}, status_code=404)
    except Exception as e:
        logger.error(f"[Commander] Deploy: {e}")
        return JSONResponse({"deployed": False, "error": str(e)}, status_code=500)


@router.post("/containers/{container_id}/exec")
async def api_exec_in_container(container_id: str, request: Request):
    """Execute a command inside a running container."""
    try:
        from container_commander.engine import exec_in_container
        data = await request.json()
        command = data.get("command", "")
        if not command:
            raise HTTPException(400, "'command' is required")
        timeout = data.get("timeout", 30)
        exit_code, output = exec_in_container(container_id, command, timeout)
        return {"executed": True, "exit_code": exit_code, "output": output}
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"executed": False, "error": str(e)}, status_code=500)


@router.post("/containers/{container_id}/stop")
async def api_stop_container(container_id: str):
    """Stop and remove a running container."""
    try:
        from container_commander.engine import stop_container
        stopped = stop_container(container_id)
        if not stopped:
            raise HTTPException(404, "Container not found or already stopped")
        return {"stopped": True, "container_id": container_id}
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"stopped": False, "error": str(e)}, status_code=500)


@router.get("/containers/{container_id}/logs")
async def api_container_logs(container_id: str, tail: int = 100):
    """Get logs from a container."""
    try:
        from container_commander.engine import get_container_logs
        logs = get_container_logs(container_id, tail)
        return {"container_id": container_id, "logs": logs}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/containers/{container_id}/stats")
async def api_container_stats(container_id: str):
    """Get live resource stats + efficiency score."""
    try:
        from container_commander.engine import get_container_stats
        stats = get_container_stats(container_id)
        return stats
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════
# QUOTA
# ═══════════════════════════════════════════════════════════

@router.get("/quota")
async def api_get_quota():
    """Get current session quota usage."""
    try:
        from container_commander.engine import get_quota
        q = get_quota()
        return q.model_dump()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════
# CLEANUP
# ═══════════════════════════════════════════════════════════

@router.post("/cleanup")
async def api_cleanup_all():
    """Emergency: stop and remove ALL TRION containers."""
    try:
        from container_commander.engine import cleanup_all
        cleanup_all()
        return {"cleaned": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════
# AUDIT LOG
# ═══════════════════════════════════════════════════════════

@router.get("/audit")
async def api_audit_log(blueprint_id: Optional[str] = None, limit: int = 50):
    try:
        from container_commander.blueprint_store import get_audit_log
        entries = get_audit_log(blueprint_id=blueprint_id, limit=limit)
        return {"entries": entries, "count": len(entries)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/audit/secrets")
async def api_secret_audit_log(limit: int = 50):
    try:
        from container_commander.secret_store import get_access_log
        entries = get_access_log(limit=limit)
        return {"entries": entries, "count": len(entries)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════
# VOLUME ENDPOINTS
# ═══════════════════════════════════════════════════════════

@router.get("/volumes")
async def api_list_volumes(blueprint_id: Optional[str] = None):
    """List all TRION workspace volumes."""
    try:
        from container_commander.volumes import list_volumes
        vols = list_volumes(blueprint_id=blueprint_id)
        return {"volumes": vols, "count": len(vols)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/volumes/{volume_name}")
async def api_get_volume(volume_name: str):
    """Get details of a specific volume including its snapshots."""
    try:
        from container_commander.volumes import get_volume
        vol = get_volume(volume_name)
        if not vol:
            raise HTTPException(404, f"Volume '{volume_name}' not found")
        return vol
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.delete("/volumes/{volume_name}")
async def api_remove_volume(volume_name: str, force: bool = False):
    """Remove a workspace volume."""
    try:
        from container_commander.volumes import remove_volume
        removed = remove_volume(volume_name, force=force)
        if not removed:
            raise HTTPException(404, f"Volume '{volume_name}' not found or in use")
        return {"removed": True, "volume": volume_name}
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/volumes/cleanup")
async def api_cleanup_volumes(dry_run: bool = True):
    """Find and optionally remove orphaned volumes."""
    try:
        from container_commander.volumes import cleanup_orphaned_volumes
        orphaned = cleanup_orphaned_volumes(dry_run=dry_run)
        return {"orphaned": orphaned, "count": len(orphaned), "dry_run": dry_run}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════
# SNAPSHOT ENDPOINTS
# ═══════════════════════════════════════════════════════════

@router.get("/snapshots")
async def api_list_snapshots(volume_name: Optional[str] = None):
    """List all snapshots, optionally filtered by volume."""
    try:
        from container_commander.volumes import list_snapshots
        snaps = list_snapshots(volume_name=volume_name)
        return {"snapshots": snaps, "count": len(snaps)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/snapshots/create")
async def api_create_snapshot(request: Request):
    """Create a tarball snapshot of a volume."""
    try:
        from container_commander.volumes import create_snapshot
        data = await request.json()
        volume_name = data.get("volume_name", "")
        tag = data.get("tag", "")
        if not volume_name:
            raise HTTPException(400, "'volume_name' is required")
        filename = create_snapshot(volume_name, tag=tag or None)
        if not filename:
            return JSONResponse({"created": False, "error": "Snapshot failed"}, status_code=500)
        return {"created": True, "filename": filename}
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/snapshots/restore")
async def api_restore_snapshot(request: Request):
    """Restore a snapshot into a new or existing volume."""
    try:
        from container_commander.volumes import restore_snapshot
        data = await request.json()
        filename = data.get("filename", "")
        target = data.get("target_volume")
        if not filename:
            raise HTTPException(400, "'filename' is required")
        vol_name = restore_snapshot(filename, target_volume=target)
        if not vol_name:
            return JSONResponse({"restored": False, "error": "Restore failed"}, status_code=500)
        return {"restored": True, "volume": vol_name}
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.delete("/snapshots/{filename}")
async def api_delete_snapshot(filename: str):
    """Delete a snapshot file."""
    try:
        from container_commander.volumes import delete_snapshot
        deleted = delete_snapshot(filename)
        if not deleted:
            raise HTTPException(404, f"Snapshot '{filename}' not found")
        return {"deleted": True, "filename": filename}
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════
# NETWORK ENDPOINTS
# ═══════════════════════════════════════════════════════════

@router.get("/networks")
async def api_list_networks():
    """List all TRION-managed Docker networks."""
    try:
        from container_commander.network import list_networks
        nets = list_networks()
        return {"networks": nets, "count": len(nets)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/networks/{container_id}/info")
async def api_network_info(container_id: str):
    """Get network details for a specific container."""
    try:
        from container_commander.network import get_network_info
        info = get_network_info(container_id)
        if info is None:
            raise HTTPException(404, "Container not found")
        return {"container_id": container_id, "networks": info}
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/networks/cleanup")
async def api_cleanup_networks():
    """Remove empty isolated TRION networks."""
    try:
        from container_commander.network import cleanup_networks
        removed = cleanup_networks()
        return {"removed": removed, "count": len(removed)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════
# APPROVAL ENDPOINTS (Human-in-the-Loop)
# ═══════════════════════════════════════════════════════════

@router.get("/approvals")
async def api_get_pending_approvals():
    """Get all pending approval requests."""
    try:
        from container_commander.approval import get_pending
        pending = get_pending()
        return {"approvals": pending, "count": len(pending)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/approvals/history")
async def api_approval_history(limit: int = 20):
    """Get approval history including resolved entries."""
    try:
        from container_commander.approval import get_history
        history = get_history(limit=limit)
        return {"history": history, "count": len(history)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/approvals/{approval_id}")
async def api_get_approval(approval_id: str):
    """Get a specific approval request."""
    try:
        from container_commander.approval import get_approval
        a = get_approval(approval_id)
        if not a:
            raise HTTPException(404, f"Approval '{approval_id}' not found")
        return a
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/approvals/{approval_id}/approve")
async def api_approve(approval_id: str):
    """Approve a pending request — starts the container."""
    try:
        from container_commander.approval import approve
        result = approve(approval_id, approved_by="user")
        if result is None:
            raise HTTPException(404, "Approval not found, expired, or already resolved")
        if "error" in result:
            return JSONResponse({"approved": False, "error": result["error"]}, status_code=500)
        return {"approved": True, "container": result}
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/approvals/{approval_id}/reject")
async def api_reject(approval_id: str, request: Request):
    """Reject a pending approval request."""
    try:
        from container_commander.approval import reject
        data = await request.json() if request.headers.get("content-type") == "application/json" else {}
        reason = data.get("reason", "")
        rejected = reject(approval_id, rejected_by="user", reason=reason)
        if not rejected:
            raise HTTPException(404, "Approval not found or already resolved")
        return {"rejected": True, "approval_id": approval_id}
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════
# WEBSOCKET ENDPOINT
# ═══════════════════════════════════════════════════════════

from fastapi import WebSocket as WS

@router.websocket("/ws")
async def websocket_terminal(websocket: WS):
    """WebSocket endpoint for live terminal streaming."""
    try:
        from container_commander.ws_stream import ws_handler
        await ws_handler(websocket)
    except Exception as e:
        logger.error(f"[Commander] WebSocket error: {e}")


# ═══════════════════════════════════════════════════════════
# PROXY ENDPOINTS
# ═══════════════════════════════════════════════════════════

@router.post("/proxy/start")
async def api_start_proxy():
    """Start the Squid whitelist proxy."""
    try:
        from container_commander.proxy import ensure_proxy_running
        ok = ensure_proxy_running()
        return {"started": ok}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@router.post("/proxy/stop")
async def api_stop_proxy():
    """Stop the Squid proxy."""
    try:
        from container_commander.proxy import stop_proxy
        stop_proxy()
        return {"stopped": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@router.get("/proxy/whitelist/{blueprint_id}")
async def api_get_whitelist(blueprint_id: str):
    try:
        from container_commander.proxy import get_whitelist
        domains = get_whitelist(blueprint_id)
        return {"blueprint_id": blueprint_id, "domains": domains}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@router.post("/proxy/whitelist/{blueprint_id}")
async def api_set_whitelist(blueprint_id: str, request: Request):
    try:
        from container_commander.proxy import set_whitelist
        data = await request.json()
        domains = data.get("domains", [])
        ok = set_whitelist(blueprint_id, domains)
        return {"updated": ok, "blueprint_id": blueprint_id, "domains": domains}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════
# MARKETPLACE ENDPOINTS
# ═══════════════════════════════════════════════════════════

@router.get("/marketplace/bundles")
async def api_list_bundles():
    try:
        from container_commander.marketplace import list_bundles
        bundles = list_bundles()
        return {"bundles": bundles, "count": len(bundles)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@router.get("/marketplace/starters")
async def api_list_starters():
    try:
        from container_commander.marketplace import get_starters
        return {"starters": get_starters(), "count": len(get_starters())}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@router.post("/marketplace/starters/{starter_id}/install")
async def api_install_starter(starter_id: str):
    try:
        from container_commander.marketplace import install_starter
        result = install_starter(starter_id)
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@router.post("/marketplace/export/{blueprint_id}")
async def api_export_bundle(blueprint_id: str):
    try:
        from container_commander.marketplace import export_bundle
        filename = export_bundle(blueprint_id)
        if not filename:
            raise HTTPException(404, "Blueprint not found")
        return {"exported": True, "filename": filename}
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@router.post("/marketplace/import")
async def api_import_bundle(request: Request):
    try:
        from container_commander.marketplace import import_bundle
        body = await request.body()
        result = import_bundle(body)
        return result or {"error": "Import failed"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════
# DASHBOARD ENDPOINT
# ═══════════════════════════════════════════════════════════

@router.get("/dashboard")
async def api_dashboard():
    """Full system dashboard with health, resources, alerts, events."""
    try:
        from container_commander.dashboard import get_dashboard_overview
        return get_dashboard_overview()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
