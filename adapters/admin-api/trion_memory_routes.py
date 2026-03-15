from fastapi import APIRouter, Request

from commander_api.common import exception_response

router = APIRouter(tags=["trion-memory"])


def _memory_error_status(error_code: str) -> int:
    code = str(error_code or "").strip().lower()
    if code == "bad_request":
        return 400
    if code == "policy_denied":
        return 403
    if code in {
        "home_container_missing",
        "home_container_not_running",
        "home_container_ambiguous",
        "home_container_unavailable",
    }:
        return 409
    return 500


@router.post("/remember")
async def api_trion_memory_remember(request: Request):
    try:
        from container_commander.home_memory import remember_note

        data = await request.json()
        return remember_note(
            content=str(data.get("content", "")),
            category=str(data.get("category", "note")),
            importance=float(data.get("importance", 0.5)),
            trigger=str(data.get("trigger", "auto")),
            context=str(data.get("context", "")),
            why=str(data.get("why", "")),
            identity_path=(str(data.get("identity_path", "")).strip() or None),
        )
    except Exception as e:
        from container_commander.home_memory import MemoryPolicyError

        if isinstance(e, MemoryPolicyError):
            return exception_response(
                e,
                status_code=_memory_error_status(e.error_code),
                error_code=e.error_code,
                details=e.details,
            )
        return exception_response(e)


@router.get("/recent")
async def api_trion_memory_recent(limit: int = 20, identity_path: str = ""):
    try:
        from container_commander.home_memory import recent_notes

        return recent_notes(limit=limit, identity_path=(identity_path.strip() or None))
    except Exception as e:
        from container_commander.home_memory import MemoryPolicyError

        if isinstance(e, MemoryPolicyError):
            return exception_response(
                e,
                status_code=_memory_error_status(e.error_code),
                error_code=e.error_code,
                details=e.details,
            )
        return exception_response(e)


@router.get("/recall")
async def api_trion_memory_recall(
    query: str = "",
    limit: int = 10,
    category: str = "",
    identity_path: str = "",
):
    try:
        from container_commander.home_memory import recall_notes

        return recall_notes(
            query=query,
            limit=limit,
            category=category,
            identity_path=(identity_path.strip() or None),
        )
    except Exception as e:
        from container_commander.home_memory import MemoryPolicyError

        if isinstance(e, MemoryPolicyError):
            return exception_response(
                e,
                status_code=_memory_error_status(e.error_code),
                error_code=e.error_code,
                details=e.details,
            )
        return exception_response(e)


@router.get("/status")
async def api_trion_memory_status(identity_path: str = ""):
    try:
        from container_commander.home_memory import memory_status

        return memory_status(identity_path=(identity_path.strip() or None))
    except Exception as e:
        from container_commander.home_memory import MemoryPolicyError

        if isinstance(e, MemoryPolicyError):
            return exception_response(
                e,
                status_code=_memory_error_status(e.error_code),
                error_code=e.error_code,
                details=e.details,
            )
        return exception_response(e)
