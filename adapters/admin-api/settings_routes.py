"""
Settings API Routes
"""
from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel, ConfigDict
from typing import Dict, Any, Optional, Literal
import json
import os

from utils.settings import settings
from utils.model_settings import ALLOWED_MODEL_KEYS, MODEL_DEFAULTS, get_effective_model_settings
from config import (
    get_embedding_execution_mode, get_embedding_fallback_policy,
    get_embedding_gpu_endpoint, get_embedding_cpu_endpoint,
    get_embedding_endpoint_mode, get_embedding_runtime_policy,
)
from utils.embedding_resolver import resolve_embedding_target
from utils.role_endpoint_resolver import resolve_ollama_base_endpoint

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


# ─────────────────────────────────────────────────────────────────────────────
# Model Settings  (Single Source of Truth)
# ─────────────────────────────────────────────────────────────────────────────

class ModelSettingsUpdate(BaseModel):
    """Typed request for model settings. Unknown fields rejected with 422."""
    model_config = ConfigDict(extra="forbid")

    THINKING_MODEL:  Optional[str] = None
    CONTROL_MODEL:   Optional[str] = None
    OUTPUT_MODEL:    Optional[str] = None
    EMBEDDING_MODEL: Optional[str] = None


@router.get("/models")
async def get_model_overrides():
    """Return only persisted model setting overrides (no defaults, no env)."""
    return {k: v for k, v in settings.settings.items() if k in ALLOWED_MODEL_KEYS}


@router.get("/models/effective")
async def get_model_settings_effective():
    """
    Return effective model settings with source tracking.
    Precedence: persisted override > env var > code default.
    Response shape:
      {
        "effective": {
          "THINKING_MODEL": {"value": "...", "source": "override"|"env"|"default"},
          ...
        },
        "defaults": {"THINKING_MODEL": "...", ...}
      }
    """
    persisted = {k: v for k, v in settings.settings.items() if k in ALLOWED_MODEL_KEYS}
    effective = get_effective_model_settings(persisted)
    return {"effective": effective, "defaults": dict(MODEL_DEFAULTS)}


@router.post("/models")
async def update_model_settings(update: ModelSettingsUpdate):
    """
    Typed, validated model settings update.
    - Only fields in ALLOWED_MODEL_KEYS accepted (enforced by Pydantic model).
    - Empty strings rejected with 422.
    - Values are stripped before saving.
    """
    payload = update.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(status_code=422, detail="No valid fields provided")

    for key, value in payload.items():
        stripped = value.strip()
        if not stripped:
            raise HTTPException(status_code=422, detail=f"{key}: empty string not allowed")
        settings.set(key, stripped)

    return {"success": True, "saved": {k: v.strip() for k, v in payload.items()}}


# ─────────────────────────────────────────────────────────────────────────────
# Embedding Runtime Settings  (Phase 4 — GPU/CPU routing)
# ─────────────────────────────────────────────────────────────────────────────

_EMBED_RUNTIME_DEFAULTS: Dict[str, str] = {
    "embedding_runtime_policy": "auto",
    "EMBEDDING_EXECUTION_MODE": "auto",
    "EMBEDDING_FALLBACK_POLICY": "best_effort",
    "EMBEDDING_GPU_ENDPOINT": "",
    "EMBEDDING_CPU_ENDPOINT": "",
    "EMBEDDING_ENDPOINT_MODE": "single",
}


def _embed_source_for(key: str, default_val: str) -> Dict[str, str]:
    """Return {value, source} for a single embedding runtime key."""
    if key in settings.settings:
        return {"value": str(settings.settings[key]), "source": "override"}
    env_val = os.getenv(key, "")
    if env_val:
        return {"value": env_val, "source": "env"}
    return {"value": default_val, "source": "default"}


class EmbeddingRuntimeUpdate(BaseModel):
    """Typed request for embedding runtime settings. Unknown fields rejected with 422."""
    model_config = ConfigDict(extra="forbid")

    embedding_runtime_policy: Optional[Literal["auto", "prefer_gpu", "cpu_only"]] = None
    EMBEDDING_EXECUTION_MODE: Optional[Literal["auto", "prefer_gpu", "cpu_only"]] = None
    EMBEDDING_FALLBACK_POLICY: Optional[Literal["best_effort", "strict"]] = None
    EMBEDDING_GPU_ENDPOINT: Optional[str] = None
    EMBEDDING_CPU_ENDPOINT: Optional[str] = None
    EMBEDDING_ENDPOINT_MODE: Optional[Literal["single", "dual"]] = None


@router.get("/embeddings/runtime")
async def get_embedding_runtime():
    """
    Return effective embedding runtime settings with source tracking.

    Response shape:
      {
        "effective": {
          "EMBEDDING_MODEL": {"value": "...", "source": "override|env|default"},
          "embedding_runtime_policy": {"value": "auto", "source": "override|env|default"},
          "EMBEDDING_EXECUTION_MODE": {"value": "auto", "source": "default"},
          ...
        },
        "defaults": {"EMBEDDING_EXECUTION_MODE": "auto", ...},
        "runtime": {
          "endpoint": "...", "target": "gpu|cpu", "reason": "...", "options": {},
          "active_policy": "auto"
        }
      }
    """
    # Model source tracking (re-uses model_settings logic)
    persisted = {k: v for k, v in settings.settings.items() if k in ALLOWED_MODEL_KEYS}
    model_eff = get_effective_model_settings(persisted)
    embed_model_entry = model_eff.get(
        "EMBEDDING_MODEL",
        {"value": MODEL_DEFAULTS.get("EMBEDDING_MODEL", "hellord/mxbai-embed-large-v1:f16"), "source": "default"},
    )

    # Canonical policy value (persisted embedding_runtime_policy -> legacy execution_mode -> env -> default)
    active_policy = get_embedding_runtime_policy()

    # Source tracking mirrors canonical precedence, including persisted legacy key.
    if "embedding_runtime_policy" in settings.settings:
        policy_entry = {"value": active_policy, "source": "override"}
    elif "EMBEDDING_EXECUTION_MODE" in settings.settings:
        policy_entry = {"value": active_policy, "source": "override"}
    elif os.getenv("EMBEDDING_EXECUTION_MODE", ""):
        policy_entry = {"value": active_policy, "source": "env"}
    else:
        policy_entry = {"value": active_policy, "source": "default"}

    # Runtime settings source tracking
    effective: Dict[str, Any] = {
        "EMBEDDING_MODEL": embed_model_entry,
        "embedding_runtime_policy": policy_entry,
    }
    for key, default_val in _EMBED_RUNTIME_DEFAULTS.items():
        if key != "embedding_runtime_policy":
            effective[key] = _embed_source_for(key, default_val)

    defaults = dict(_EMBED_RUNTIME_DEFAULTS)
    defaults["EMBEDDING_MODEL"] = MODEL_DEFAULTS.get("EMBEDDING_MODEL", "hellord/mxbai-embed-large-v1:f16")

    # Capability snapshot (uses canonical policy getter + admin-api's OLLAMA_BASE)
    base_ep = resolve_ollama_base_endpoint(
        default_endpoint=os.getenv("OLLAMA_BASE", "http://host.docker.internal:11434")
    )
    rt = resolve_embedding_target(
        mode=active_policy,
        endpoint_mode=effective["EMBEDDING_ENDPOINT_MODE"]["value"],
        base_endpoint=base_ep,
        gpu_endpoint=effective["EMBEDDING_GPU_ENDPOINT"]["value"],
        cpu_endpoint=effective["EMBEDDING_CPU_ENDPOINT"]["value"],
        fallback_policy=effective["EMBEDDING_FALLBACK_POLICY"]["value"],
    )
    snapshot = {k: rt[k] for k in ("endpoint", "target", "reason", "options")}
    snapshot["active_policy"] = active_policy

    return {"effective": effective, "defaults": defaults, "runtime": snapshot}


@router.post("/embeddings/runtime")
async def update_embedding_runtime(update: EmbeddingRuntimeUpdate):
    """
    Typed, validated embedding runtime settings update.
    - Enum fields validated by Pydantic (Literal types).
    - Extra fields rejected with 422.
    - Endpoint fields accept empty strings (clears the override).
    """
    payload = update.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(status_code=422, detail="No valid fields provided")

    endpoint_keys = {"EMBEDDING_GPU_ENDPOINT", "EMBEDDING_CPU_ENDPOINT"}
    for key, value in payload.items():
        if isinstance(value, str):
            stripped = value.strip()
            if key not in endpoint_keys and not stripped:
                raise HTTPException(status_code=422, detail=f"{key}: empty string not allowed")
            settings.set(key, stripped)
        else:
            settings.set(key, value)

    return {"success": True, "saved": payload, "active_policy": get_embedding_runtime_policy()}
