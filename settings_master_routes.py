"""
Master Orchestrator Settings Model
Add to: maintenance/routes.py or create new settings_master.py
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import json
import os

router = APIRouter()

# Settings file path
SETTINGS_FILE = "/DATA/AppData/MCP/Jarvis/settings_master.json"

class MasterSettings(BaseModel):
    """Master Orchestrator Configuration"""
    enabled: bool = True
    use_thinking_layer: bool = False  # Default: OFF for speed
    max_loops: int = 10
    completion_threshold: int = 2  # Steps before "done"

# Default settings
DEFAULT_SETTINGS = {
    "enabled": True,
    "use_thinking_layer": False,
    "max_loops": 10,
    "completion_threshold": 2
}

def load_settings() -> dict:
    """Load settings from file"""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return DEFAULT_SETTINGS
    return DEFAULT_SETTINGS

def save_settings(settings: dict):
    """Save settings to file"""
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)

@router.get("/api/settings/master")
async def get_master_settings():
    """Get current Master Orchestrator settings"""
    return load_settings()

@router.post("/api/settings/master")
async def update_master_settings(settings: MasterSettings):
    """Update Master Orchestrator settings"""
    save_settings(settings.dict())
    return {"success": True, "settings": settings}
