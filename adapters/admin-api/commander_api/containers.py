from fastapi import APIRouter, HTTPException, Request

from .common import exception_response, logger

router = APIRouter()


@router.get("/containers")
async def api_list_containers():
    """List all TRION-managed containers with live status."""
    try:
        from container_commander.engine import list_containers

        cts = list_containers()
        return {"containers": [c.model_dump() for c in cts], "count": len(cts)}
    except Exception as e:
        logger.error(f"[Commander] List containers: {e}")
        return exception_response(e, details={"containers": [], "count": 0})


@router.get("/home/status")
async def api_home_status():
    """Return TRION home identity + runtime health status."""
    try:
        from container_commander.engine import list_containers
        from utils.trion_home_identity import evaluate_home_status

        containers = list_containers()
        return evaluate_home_status(containers)
    except Exception as e:
        return exception_response(e, details={"status": "offline"})


@router.post("/containers/{container_id}/exec")
async def api_exec_in_container(container_id: str, request: Request):
    """Execute a command inside a running container."""
    try:
        from container_commander.engine import exec_in_container

        data = await request.json()
        command = data.get("command", "")
        if not command:
            return exception_response(
                HTTPException(400, "'command' is required"),
                error_code="bad_request",
                details={"executed": False, "container_id": container_id},
            )
        timeout = data.get("timeout", 30)
        exit_code, output = exec_in_container(container_id, command, timeout)
        return {"executed": True, "exit_code": exit_code, "output": output}
    except Exception as e:
        return exception_response(e, details={"executed": False})


@router.post("/containers/{container_id}/stop")
async def api_stop_container(container_id: str):
    """Stop and remove a running container."""
    try:
        from container_commander.engine import stop_container

        stopped = stop_container(container_id)
        if not stopped:
            return exception_response(
                HTTPException(404, "Container not found or already stopped"),
                error_code="not_found",
                details={"stopped": False, "container_id": container_id},
            )
        return {"stopped": True, "container_id": container_id}
    except Exception as e:
        return exception_response(e, details={"stopped": False})


@router.get("/containers/{container_id}/logs")
async def api_container_logs(container_id: str, tail: int = 100):
    """Get logs from a container."""
    try:
        from container_commander.engine import get_container_logs

        logs = get_container_logs(container_id, tail)
        return {"container_id": container_id, "logs": logs}
    except Exception as e:
        return exception_response(e)


@router.get("/containers/{container_id}/stats")
async def api_container_stats(container_id: str):
    """Get live resource stats + efficiency score."""
    try:
        from container_commander.engine import get_container_stats

        return get_container_stats(container_id)
    except Exception as e:
        return exception_response(e)


@router.get("/quota")
async def api_get_quota():
    """Get current session quota usage."""
    try:
        from container_commander.engine import get_quota

        q = get_quota()
        return q.model_dump()
    except Exception as e:
        return exception_response(e)


@router.post("/cleanup")
async def api_cleanup_all():
    """Emergency: stop and remove ALL TRION containers."""
    try:
        from container_commander.engine import cleanup_all

        cleanup_all()
        return {"cleaned": True}
    except Exception as e:
        return exception_response(e)
