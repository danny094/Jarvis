from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from .common import exception_response

router = APIRouter()


@router.get("/secrets")
async def api_list_secrets(scope: Optional[str] = None, blueprint_id: Optional[str] = None):
    try:
        from container_commander.secret_store import list_secrets
        from container_commander.models import SecretScope

        sec_scope = SecretScope(scope) if scope else None
        secs = list_secrets(scope=sec_scope, blueprint_id=blueprint_id)
        return {"secrets": [s.model_dump() for s in secs], "count": len(secs)}
    except Exception as e:
        return exception_response(e)


@router.post("/secrets")
async def api_store_secret(request: Request):
    try:
        from container_commander.secret_store import store_secret
        from container_commander.models import SecretScope

        data = await request.json()
        name = data.get("name", "").strip()
        value = data.get("value", "")
        if not name or not value:
            return exception_response(
                HTTPException(400, "'name' and 'value' are required"),
                error_code="bad_request",
                details={"stored": False},
            )
        scope = SecretScope(data.get("scope", "global"))
        entry = store_secret(name, value, scope, data.get("blueprint_id"), data.get("expires_at"))
        return {"stored": True, "secret": entry.model_dump()}
    except Exception as e:
        return exception_response(e)


@router.delete("/secrets/{secret_name}")
async def api_delete_secret(secret_name: str, scope: str = "global", blueprint_id: Optional[str] = None):
    try:
        from container_commander.secret_store import delete_secret
        from container_commander.models import SecretScope

        deleted = delete_secret(secret_name, SecretScope(scope), blueprint_id)
        if not deleted:
            return exception_response(
                HTTPException(404, f"Secret '{secret_name}' not found"),
                error_code="not_found",
                details={"deleted": False, "name": secret_name},
            )
        return {"deleted": True, "name": secret_name}
    except Exception as e:
        return exception_response(e)
