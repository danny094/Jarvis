from fastapi import APIRouter, HTTPException, Request, WebSocket as WS

from .common import exception_response, logger

router = APIRouter()


def _approval_error_meta(message: str) -> tuple[str, int]:
    msg = str(message or "").strip().lower()
    if msg.startswith("healthcheck_timeout_auto_stopped"):
        return "healthcheck_timeout", 504
    if msg.startswith("healthcheck_unhealthy_auto_stopped"):
        return "healthcheck_unhealthy", 409
    if msg.startswith("container_exited_before_ready_auto_stopped"):
        return "container_not_ready", 409
    return "approval_failed", 409


@router.get("/approvals")
async def api_get_pending_approvals():
    """Get all pending approval requests."""
    try:
        from container_commander.approval import get_pending

        pending = get_pending()
        return {"approvals": pending, "count": len(pending)}
    except Exception as e:
        return exception_response(e)


@router.get("/approvals/history")
async def api_approval_history(limit: int = 20):
    """Get approval history including resolved entries."""
    try:
        from container_commander.approval import get_history

        history = get_history(limit=limit)
        return {"history": history, "count": len(history)}
    except Exception as e:
        return exception_response(e)


@router.get("/approvals/{approval_id}")
async def api_get_approval(approval_id: str):
    """Get a specific approval request."""
    try:
        from container_commander.approval import get_approval

        a = get_approval(approval_id)
        if not a:
            return exception_response(
                HTTPException(404, f"Approval '{approval_id}' not found"),
                error_code="not_found",
                details={"approval_id": approval_id},
            )
        return a
    except Exception as e:
        return exception_response(e)


@router.post("/approvals/{approval_id}/approve")
async def api_approve(approval_id: str):
    """Approve a pending request — starts the container."""
    try:
        from container_commander.approval import approve

        result = approve(approval_id, approved_by="user")
        if result is None:
            return exception_response(
                HTTPException(404, "Approval not found, expired, or already resolved"),
                error_code="not_found",
                details={"approved": False, "approval_id": approval_id},
            )
        if "error" in result:
            runtime_code, runtime_status = _approval_error_meta(result["error"])
            return exception_response(
                RuntimeError(result["error"]),
                status_code=runtime_status,
                error_code=runtime_code,
                details={"approved": False},
            )
        return {"approved": True, "container": result}
    except Exception as e:
        return exception_response(e)


@router.post("/approvals/{approval_id}/reject")
async def api_reject(approval_id: str, request: Request):
    """Reject a pending approval request."""
    try:
        from container_commander.approval import reject

        is_json = request.headers.get("content-type", "").startswith("application/json")
        data = await request.json() if is_json else {}
        reason = data.get("reason", "")
        rejected = reject(approval_id, rejected_by="user", reason=reason)
        if not rejected:
            return exception_response(
                HTTPException(404, "Approval not found or already resolved"),
                error_code="not_found",
                details={"rejected": False, "approval_id": approval_id},
            )
        return {"rejected": True, "approval_id": approval_id}
    except Exception as e:
        return exception_response(e)


@router.websocket("/ws")
async def websocket_terminal(websocket: WS):
    """WebSocket endpoint for live terminal streaming."""
    try:
        from container_commander.ws_stream import ws_handler

        await ws_handler(websocket)
    except Exception as e:
        logger.error(f"[Commander] WebSocket error: {e}")


@router.post("/proxy/start")
async def api_start_proxy():
    """Start the Squid whitelist proxy."""
    try:
        from container_commander.proxy import ensure_proxy_running

        ok = ensure_proxy_running()
        return {"started": ok}
    except Exception as e:
        return exception_response(e)


@router.post("/proxy/stop")
async def api_stop_proxy():
    """Stop the Squid proxy."""
    try:
        from container_commander.proxy import stop_proxy

        stop_proxy()
        return {"stopped": True}
    except Exception as e:
        return exception_response(e)


@router.get("/proxy/whitelist/{blueprint_id}")
async def api_get_whitelist(blueprint_id: str):
    try:
        from container_commander.proxy import get_whitelist

        domains = get_whitelist(blueprint_id)
        return {"blueprint_id": blueprint_id, "domains": domains}
    except Exception as e:
        return exception_response(e)


@router.post("/proxy/whitelist/{blueprint_id}")
async def api_set_whitelist(blueprint_id: str, request: Request):
    try:
        from container_commander.proxy import set_whitelist

        data = await request.json()
        domains = data.get("domains", [])
        ok = set_whitelist(blueprint_id, domains)
        return {"updated": ok, "blueprint_id": blueprint_id, "domains": domains}
    except Exception as e:
        return exception_response(e)


@router.get("/marketplace/bundles")
async def api_list_bundles():
    try:
        from container_commander.marketplace import list_bundles

        bundles = list_bundles()
        return {"bundles": bundles, "count": len(bundles)}
    except Exception as e:
        return exception_response(e)


@router.get("/marketplace/starters")
async def api_list_starters():
    try:
        from container_commander.marketplace import get_starters

        starters = get_starters()
        return {"starters": starters, "count": len(starters)}
    except Exception as e:
        return exception_response(e)


@router.get("/marketplace/catalog")
async def api_marketplace_catalog(category: str = "", trusted_only: bool = False):
    try:
        from container_commander.marketplace import list_catalog

        return list_catalog(category=category, trusted_only=trusted_only)
    except Exception as e:
        return exception_response(e)


@router.post("/marketplace/catalog/sync")
async def api_marketplace_catalog_sync(request: Request):
    try:
        from container_commander.marketplace import sync_remote_catalog

        data = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        repo_url = str((data or {}).get("repo_url", "")).strip()
        branch = str((data or {}).get("branch", "main")).strip() or "main"
        return sync_remote_catalog(repo_url=repo_url, branch=branch)
    except Exception as e:
        return exception_response(e, error_code="marketplace_sync_failed")


@router.post("/marketplace/catalog/install/{blueprint_id}")
async def api_marketplace_catalog_install(blueprint_id: str, request: Request):
    try:
        from container_commander.marketplace import install_catalog_blueprint

        data = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        overwrite = bool((data or {}).get("overwrite", False))
        return install_catalog_blueprint(blueprint_id=blueprint_id, overwrite=overwrite)
    except Exception as e:
        return exception_response(e, error_code="marketplace_install_failed")


@router.post("/marketplace/starters/{starter_id}/install")
async def api_install_starter(starter_id: str):
    try:
        from container_commander.marketplace import install_starter

        return install_starter(starter_id)
    except Exception as e:
        return exception_response(e)


@router.post("/marketplace/export/{blueprint_id}")
async def api_export_bundle(blueprint_id: str):
    try:
        from container_commander.marketplace import export_bundle

        filename = export_bundle(blueprint_id)
        if not filename:
            return exception_response(
                HTTPException(404, "Blueprint not found"),
                error_code="not_found",
                details={"exported": False, "blueprint_id": blueprint_id},
            )
        return {"exported": True, "filename": filename}
    except Exception as e:
        return exception_response(e)


@router.post("/marketplace/import")
async def api_import_bundle(request: Request):
    try:
        from container_commander.marketplace import import_bundle

        body = await request.body()
        result = import_bundle(body)
        if not result:
            return exception_response(RuntimeError("Import failed"), error_code="import_failed")
        return result
    except Exception as e:
        return exception_response(e)


@router.get("/dashboard")
async def api_dashboard():
    """Full system dashboard with health, resources, alerts, events."""
    try:
        from container_commander.dashboard import get_dashboard_overview

        return get_dashboard_overview()
    except Exception as e:
        return exception_response(e)
