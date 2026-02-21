"""
Settings API Routes
"""
from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
from typing import Dict, Any, Optional
import json
import os

from utils.settings import settings

router = APIRouter(tags=["settings"])

# Master Orchestrator Settings File
MASTER_SETTINGS_FILE = "/tmp/settings_master.json"

class MasterSettings(BaseModel):
    """Master Orchestrator Configuration"""
    enabled: bool = True
    use_thinking_layer: bool = False  # Default: OFF for speed
    max_loops: int = 10
    completion_threshold: int = 2

# Default Master Settings
DEFAULT_MASTER_SETTINGS = {
    "enabled": True,
    "use_thinking_layer": False,
    "max_loops": 10,
    "completion_threshold": 2
}

def load_master_settings() -> dict:
    """Load Master Orchestrator settings from file"""
    if os.path.exists(MASTER_SETTINGS_FILE):
        try:
            with open(MASTER_SETTINGS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Failed to load master settings: {e}")
            return DEFAULT_MASTER_SETTINGS
    return DEFAULT_MASTER_SETTINGS

def save_master_settings(settings_dict: dict):
    """Save Master Orchestrator settings to file"""
    try:
        os.makedirs(os.path.dirname(MASTER_SETTINGS_FILE), exist_ok=True)
        with open(MASTER_SETTINGS_FILE, 'w') as f:
            json.dump(settings_dict, f, indent=2)
    except Exception as e:
        print(f"Failed to save master settings: {e}")
        raise

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

@router.get("/compression")
async def get_compression_settings():
    """Get context compression settings."""
    return {
        "enabled": settings.get("CONTEXT_COMPRESSION_ENABLED", True),
        "mode": settings.get("CONTEXT_COMPRESSION_MODE", "sync"),
        "threshold": settings.get("COMPRESSION_THRESHOLD", 100000),
        "phase2_threshold": settings.get("COMPRESSION_PHASE2_THRESHOLD", 150000),
        "keep_messages": settings.get("COMPRESSION_KEEP_MESSAGES", 20),
    }

@router.post("/compression")
async def update_compression_settings(updates: Dict[str, Any] = Body(...)):
    """
    Update context compression settings.
    Keys: enabled (bool), mode ('sync'|'async'), threshold (int)
    """
    key_map = {
        "enabled": "CONTEXT_COMPRESSION_ENABLED",
        "mode": "CONTEXT_COMPRESSION_MODE",
        "threshold": "COMPRESSION_THRESHOLD",
        "phase2_threshold": "COMPRESSION_PHASE2_THRESHOLD",
        "keep_messages": "COMPRESSION_KEEP_MESSAGES",
    }
    for ui_key, setting_key in key_map.items():
        if ui_key in updates:
            settings.set(setting_key, updates[ui_key])
    return {"success": True, "compression": await get_compression_settings()}

@router.get("/master")
async def get_master_settings():
    """Get current Master Orchestrator settings"""
    return load_master_settings()

@router.post("/master")
async def update_master_settings(master_settings: MasterSettings):
    """Update Master Orchestrator settings"""
    settings_dict = master_settings.model_dump()
    save_master_settings(settings_dict)
    return {"success": True, "settings": settings_dict}
