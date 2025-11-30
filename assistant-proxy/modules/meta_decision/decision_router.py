from fastapi import APIRouter
from .decision import run_decision_layer

router = APIRouter()


@router.post("/decision")
async def meta_decision_route(payload: dict):
    """
    Externer Entry-Point für den Meta-Decision-Layer.
    """
    result = await run_decision_layer(payload)
    return result