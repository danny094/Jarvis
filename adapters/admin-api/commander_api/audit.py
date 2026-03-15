from typing import Optional

from fastapi import APIRouter

from .common import exception_response

router = APIRouter()


@router.get("/audit")
async def api_audit_log(blueprint_id: Optional[str] = None, limit: int = 50):
    try:
        from container_commander.blueprint_store import get_audit_log

        entries = get_audit_log(blueprint_id=blueprint_id, limit=limit)
        return {"entries": entries, "count": len(entries)}
    except Exception as e:
        return exception_response(e)


@router.get("/audit/secrets")
async def api_secret_audit_log(limit: int = 50):
    try:
        from container_commander.secret_store import get_access_log

        entries = get_access_log(limit=limit)
        return {"entries": entries, "count": len(entries)}
    except Exception as e:
        return exception_response(e)
