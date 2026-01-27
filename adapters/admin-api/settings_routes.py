"""
Settings API Routes
"""
from fastapi import APIRouter, HTTPException, Body
from typing import Dict, Any

from utils.settings import settings

router = APIRouter(tags=["settings"])

@router.get("/")
async def get_settings():
    """Get all current setting overrides."""
    return settings.settings

@router.post("/")
async def update_settings(updates: Dict[str, Any] = Body(...)):
    """
    Update settings.
    Example: {"THINKING_MODEL": "deepseek-r1:14b"}
    """
    for key, value in updates.items():
        settings.set(key, value)
    
    return {"success": True, "settings": settings.settings}
