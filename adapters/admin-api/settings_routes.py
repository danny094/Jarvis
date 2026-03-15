"""
Settings API Routes
"""
from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel, ConfigDict
from typing import Dict, Any, Optional, Literal
import json
import os
from urllib.parse import urlparse

from utils.settings import settings
from utils.model_settings import ALLOWED_MODEL_KEYS, MODEL_DEFAULTS, get_effective_model_settings
from config import (
    get_embedding_execution_mode, get_embedding_fallback_policy,
    get_embedding_gpu_endpoint, get_embedding_cpu_endpoint,
    get_embedding_endpoint_mode, get_embedding_runtime_policy,
    get_default_response_mode,
    get_response_mode_sequential_threshold,
    get_sequential_timeout_s,
    get_query_budget_enable,
    get_query_budget_embedding_enable,
    get_query_budget_skip_thinking_enable,
    get_query_budget_skip_thinking_min_confidence,
    get_query_budget_max_tools_factual_low,
    get_loop_engine_trigger_complexity,
    get_loop_engine_min_tools,
    get_loop_engine_max_predict,
    get_loop_engine_output_char_cap,
    get_autonomy_cron_max_jobs,
    get_autonomy_cron_max_jobs_per_conversation,
    get_autonomy_cron_min_interval_s,
    get_autonomy_cron_max_pending_runs,
    get_autonomy_cron_max_pending_runs_per_job,
    get_autonomy_cron_manual_run_cooldown_s,
    get_autonomy_cron_trion_safe_mode,
    get_autonomy_cron_trion_min_interval_s,
    get_autonomy_cron_trion_max_loops,
    get_autonomy_cron_trion_require_approval_for_risky,
    get_autonomy_cron_hardware_guard_enabled,
    get_autonomy_cron_hardware_cpu_max_percent,
    get_autonomy_cron_hardware_mem_max_percent,
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
    THINKING_PROVIDER: Optional[str] = None
    CONTROL_PROVIDER: Optional[str] = None
    OUTPUT_PROVIDER: Optional[str] = None


_MODEL_PROVIDER_KEYS = {"THINKING_PROVIDER", "CONTROL_PROVIDER", "OUTPUT_PROVIDER"}
_ALLOWED_MODEL_PROVIDERS = {"ollama", "ollama_cloud", "openai", "anthropic"}


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

    saved: Dict[str, str] = {}
    for key, value in payload.items():
        stripped = value.strip()
        if not stripped:
            raise HTTPException(status_code=422, detail=f"{key}: empty string not allowed")
        if key in _MODEL_PROVIDER_KEYS:
            normalized = stripped.lower()
            if normalized not in _ALLOWED_MODEL_PROVIDERS:
                raise HTTPException(
                    status_code=422,
                    detail=f"{key}: unsupported provider '{stripped}'",
                )
            settings.set(key, normalized)
            saved[key] = normalized
            continue
        settings.set(key, stripped)
        saved[key] = stripped

    return {"success": True, "saved": saved}


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


# ─────────────────────────────────────────────────────────────────────────────
# Sequential Runtime Policy Settings
# ─────────────────────────────────────────────────────────────────────────────

_SEQUENTIAL_RUNTIME_SPECS: Dict[str, Dict[str, Any]] = {
    "DEFAULT_RESPONSE_MODE": {"type": "enum", "default": "interactive", "choices": {"interactive", "deep"}},
    "RESPONSE_MODE_SEQUENTIAL_THRESHOLD": {"type": "int", "default": 6, "min": 1, "max": 10},
    "SEQUENTIAL_TIMEOUT_S": {"type": "int", "default": 25, "min": 5, "max": 300},
    "QUERY_BUDGET_ENABLE": {"type": "bool", "default": True},
    "QUERY_BUDGET_EMBEDDING_ENABLE": {"type": "bool", "default": True},
    "QUERY_BUDGET_SKIP_THINKING_ENABLE": {"type": "bool", "default": True},
    "QUERY_BUDGET_SKIP_THINKING_MIN_CONFIDENCE": {"type": "float", "default": 0.90, "min": 0.0, "max": 1.0},
    "QUERY_BUDGET_MAX_TOOLS_FACTUAL_LOW": {"type": "int", "default": 1, "min": 0, "max": 5},
    "LOOP_ENGINE_TRIGGER_COMPLEXITY": {"type": "int", "default": 8, "min": 1, "max": 10},
    "LOOP_ENGINE_MIN_TOOLS": {"type": "int", "default": 1, "min": 0, "max": 10},
    "LOOP_ENGINE_MAX_PREDICT": {"type": "int", "default": 700, "min": 0, "max": 8192},
    "LOOP_ENGINE_OUTPUT_CHAR_CAP": {"type": "int", "default": 2400, "min": 0, "max": 200000},
}


class SequentialRuntimeUpdate(BaseModel):
    """Typed update for sequential/planning runtime policy values."""
    model_config = ConfigDict(extra="forbid")

    DEFAULT_RESPONSE_MODE: Optional[Literal["interactive", "deep"]] = None
    RESPONSE_MODE_SEQUENTIAL_THRESHOLD: Optional[int] = None
    SEQUENTIAL_TIMEOUT_S: Optional[int] = None
    QUERY_BUDGET_ENABLE: Optional[bool] = None
    QUERY_BUDGET_EMBEDDING_ENABLE: Optional[bool] = None
    QUERY_BUDGET_SKIP_THINKING_ENABLE: Optional[bool] = None
    QUERY_BUDGET_SKIP_THINKING_MIN_CONFIDENCE: Optional[float] = None
    QUERY_BUDGET_MAX_TOOLS_FACTUAL_LOW: Optional[int] = None
    LOOP_ENGINE_TRIGGER_COMPLEXITY: Optional[int] = None
    LOOP_ENGINE_MIN_TOOLS: Optional[int] = None
    LOOP_ENGINE_MAX_PREDICT: Optional[int] = None
    LOOP_ENGINE_OUTPUT_CHAR_CAP: Optional[int] = None


def _sequential_policy_value_and_source(key: str, spec: Dict[str, Any], effective_value: Any) -> Dict[str, Any]:
    value_type = str(spec.get("type", "str"))
    default_val = spec.get("default")

    source = "default"
    raw: Any = default_val
    if key in settings.settings:
        source = "override"
        raw = settings.settings.get(key, default_val)
    else:
        raw_env = os.getenv(key, "")
        if str(raw_env).strip() != "":
            source = "env"
            raw = raw_env

    if value_type == "bool":
        parsed = bool(raw) if isinstance(raw, bool) else str(raw).strip().lower() == "true"
    elif value_type == "int":
        try:
            parsed = int(raw)
        except Exception:
            parsed = int(default_val)
    elif value_type == "float":
        try:
            parsed = float(raw)
        except Exception:
            parsed = float(default_val)
    elif value_type == "enum":
        parsed = str(raw or "").strip().lower() or str(default_val)
        choices = set(spec.get("choices", set()))
        if choices and parsed not in choices:
            parsed = str(default_val)
    else:
        parsed = str(raw or "")

    # Canonical runtime value takes precedence (already clamped/validated by config getters)
    parsed = effective_value
    return {"value": parsed, "source": source}


@router.get("/sequential/runtime")
async def get_sequential_runtime_policy():
    """Return effective sequential/planning runtime policy values with source tracking."""
    effective_values = {
        "DEFAULT_RESPONSE_MODE": get_default_response_mode(),
        "RESPONSE_MODE_SEQUENTIAL_THRESHOLD": get_response_mode_sequential_threshold(),
        "SEQUENTIAL_TIMEOUT_S": get_sequential_timeout_s(),
        "QUERY_BUDGET_ENABLE": get_query_budget_enable(),
        "QUERY_BUDGET_EMBEDDING_ENABLE": get_query_budget_embedding_enable(),
        "QUERY_BUDGET_SKIP_THINKING_ENABLE": get_query_budget_skip_thinking_enable(),
        "QUERY_BUDGET_SKIP_THINKING_MIN_CONFIDENCE": get_query_budget_skip_thinking_min_confidence(),
        "QUERY_BUDGET_MAX_TOOLS_FACTUAL_LOW": get_query_budget_max_tools_factual_low(),
        "LOOP_ENGINE_TRIGGER_COMPLEXITY": get_loop_engine_trigger_complexity(),
        "LOOP_ENGINE_MIN_TOOLS": get_loop_engine_min_tools(),
        "LOOP_ENGINE_MAX_PREDICT": get_loop_engine_max_predict(),
        "LOOP_ENGINE_OUTPUT_CHAR_CAP": get_loop_engine_output_char_cap(),
    }
    defaults = {k: spec.get("default") for k, spec in _SEQUENTIAL_RUNTIME_SPECS.items()}
    effective: Dict[str, Any] = {}
    for key, spec in _SEQUENTIAL_RUNTIME_SPECS.items():
        effective[key] = _sequential_policy_value_and_source(key, spec, effective_values.get(key))

    return {
        "effective": effective,
        "defaults": defaults,
        "restart_required": False,
    }


@router.post("/sequential/runtime")
async def update_sequential_runtime_policy(update: SequentialRuntimeUpdate):
    """Persist sequential/planning runtime policy overrides."""
    payload = update.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(status_code=422, detail="No valid fields provided")

    saved: Dict[str, Any] = {}
    for key, value in payload.items():
        spec = _SEQUENTIAL_RUNTIME_SPECS.get(key)
        if not spec:
            raise HTTPException(status_code=422, detail=f"{key}: unsupported key")
        value_type = str(spec.get("type", "str"))
        if value_type == "bool":
            bvalue = bool(value)
            settings.set(key, bvalue)
            saved[key] = bvalue
            continue
        if value_type == "enum":
            sval = str(value or "").strip().lower()
            if sval not in set(spec.get("choices", set())):
                raise HTTPException(status_code=422, detail=f"{key}: invalid value '{value}'")
            settings.set(key, sval)
            saved[key] = sval
            continue
        if value_type == "float":
            fvalue = float(value)
            lo = float(spec.get("min", 0.0))
            hi = float(spec.get("max", 1.0))
            if fvalue < lo or fvalue > hi:
                raise HTTPException(status_code=422, detail=f"{key}: must be between {lo} and {hi}")
            settings.set(key, fvalue)
            saved[key] = fvalue
            continue
        if value_type == "int":
            ivalue = int(value)
            lo = int(spec.get("min", -2147483648))
            hi = int(spec.get("max", 2147483647))
            if ivalue < lo or ivalue > hi:
                raise HTTPException(status_code=422, detail=f"{key}: must be between {lo} and {hi}")
            settings.set(key, ivalue)
            saved[key] = ivalue
            continue
        settings.set(key, value)
        saved[key] = value

    return {
        "success": True,
        "saved": saved,
        "restart_required": False,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Autonomy Cron Policy Settings
# ─────────────────────────────────────────────────────────────────────────────

_AUTONOMY_CRON_POLICY_SPECS: Dict[str, Dict[str, Any]] = {
    "AUTONOMY_CRON_MAX_JOBS": {"type": "int", "default": 200, "min": 1, "max": 2000},
    "AUTONOMY_CRON_MAX_JOBS_PER_CONVERSATION": {"type": "int", "default": 30, "min": 1, "max": 500},
    "AUTONOMY_CRON_MIN_INTERVAL_S": {"type": "int", "default": 60, "min": 60, "max": 86400},
    "AUTONOMY_CRON_MAX_PENDING_RUNS": {"type": "int", "default": 500, "min": 1, "max": 5000},
    "AUTONOMY_CRON_MAX_PENDING_RUNS_PER_JOB": {"type": "int", "default": 2, "min": 1, "max": 100},
    "AUTONOMY_CRON_MANUAL_RUN_COOLDOWN_S": {"type": "int", "default": 30, "min": 0, "max": 3600},
    "AUTONOMY_CRON_TRION_SAFE_MODE": {"type": "bool", "default": True},
    "AUTONOMY_CRON_TRION_MIN_INTERVAL_S": {"type": "int", "default": 300, "min": 60, "max": 86400},
    "AUTONOMY_CRON_TRION_MAX_LOOPS": {"type": "int", "default": 12, "min": 1, "max": 200},
    "AUTONOMY_CRON_TRION_REQUIRE_APPROVAL_FOR_RISKY": {"type": "bool", "default": True},
    "AUTONOMY_CRON_HARDWARE_GUARD_ENABLED": {"type": "bool", "default": True},
    "AUTONOMY_CRON_HARDWARE_CPU_MAX_PERCENT": {"type": "int", "default": 90, "min": 50, "max": 99},
    "AUTONOMY_CRON_HARDWARE_MEM_MAX_PERCENT": {"type": "int", "default": 92, "min": 50, "max": 99},
}


class AutonomyCronPolicyUpdate(BaseModel):
    """Typed update for cron scheduler guardrail policy values."""
    model_config = ConfigDict(extra="forbid")

    AUTONOMY_CRON_MAX_JOBS: Optional[int] = None
    AUTONOMY_CRON_MAX_JOBS_PER_CONVERSATION: Optional[int] = None
    AUTONOMY_CRON_MIN_INTERVAL_S: Optional[int] = None
    AUTONOMY_CRON_MAX_PENDING_RUNS: Optional[int] = None
    AUTONOMY_CRON_MAX_PENDING_RUNS_PER_JOB: Optional[int] = None
    AUTONOMY_CRON_MANUAL_RUN_COOLDOWN_S: Optional[int] = None
    AUTONOMY_CRON_TRION_SAFE_MODE: Optional[bool] = None
    AUTONOMY_CRON_TRION_MIN_INTERVAL_S: Optional[int] = None
    AUTONOMY_CRON_TRION_MAX_LOOPS: Optional[int] = None
    AUTONOMY_CRON_TRION_REQUIRE_APPROVAL_FOR_RISKY: Optional[bool] = None
    AUTONOMY_CRON_HARDWARE_GUARD_ENABLED: Optional[bool] = None
    AUTONOMY_CRON_HARDWARE_CPU_MAX_PERCENT: Optional[int] = None
    AUTONOMY_CRON_HARDWARE_MEM_MAX_PERCENT: Optional[int] = None


def _cron_policy_value_and_source(key: str, default_val: Any, value_type: str) -> Dict[str, Any]:
    if key in settings.settings:
        raw = settings.settings[key]
        if value_type == "bool":
            value = bool(raw) if isinstance(raw, bool) else str(raw).lower() == "true"
        else:
            try:
                value = int(raw)
            except Exception:
                value = int(default_val)
        return {"value": value, "source": "override"}

    raw_env = os.getenv(key, "")
    if str(raw_env).strip():
        if value_type == "bool":
            value = str(raw_env).lower() == "true"
        else:
            try:
                value = int(raw_env)
            except Exception:
                value = int(default_val)
        return {"value": value, "source": "env"}

    return {"value": default_val if value_type == "bool" else int(default_val), "source": "default"}


@router.get("/autonomy/cron-policy")
async def get_autonomy_cron_policy():
    """
    Return effective cron guardrail policy values with source tracking.
    Note: changes require admin-api restart to affect active scheduler workers.
    """
    # runtime-canonical effective values (clamped via config getters)
    effective_values = {
        "AUTONOMY_CRON_MAX_JOBS": get_autonomy_cron_max_jobs(),
        "AUTONOMY_CRON_MAX_JOBS_PER_CONVERSATION": get_autonomy_cron_max_jobs_per_conversation(),
        "AUTONOMY_CRON_MIN_INTERVAL_S": get_autonomy_cron_min_interval_s(),
        "AUTONOMY_CRON_MAX_PENDING_RUNS": get_autonomy_cron_max_pending_runs(),
        "AUTONOMY_CRON_MAX_PENDING_RUNS_PER_JOB": get_autonomy_cron_max_pending_runs_per_job(),
        "AUTONOMY_CRON_MANUAL_RUN_COOLDOWN_S": get_autonomy_cron_manual_run_cooldown_s(),
        "AUTONOMY_CRON_TRION_SAFE_MODE": get_autonomy_cron_trion_safe_mode(),
        "AUTONOMY_CRON_TRION_MIN_INTERVAL_S": get_autonomy_cron_trion_min_interval_s(),
        "AUTONOMY_CRON_TRION_MAX_LOOPS": get_autonomy_cron_trion_max_loops(),
        "AUTONOMY_CRON_TRION_REQUIRE_APPROVAL_FOR_RISKY": get_autonomy_cron_trion_require_approval_for_risky(),
        "AUTONOMY_CRON_HARDWARE_GUARD_ENABLED": get_autonomy_cron_hardware_guard_enabled(),
        "AUTONOMY_CRON_HARDWARE_CPU_MAX_PERCENT": get_autonomy_cron_hardware_cpu_max_percent(),
        "AUTONOMY_CRON_HARDWARE_MEM_MAX_PERCENT": get_autonomy_cron_hardware_mem_max_percent(),
    }

    defaults = {k: spec["default"] for k, spec in _AUTONOMY_CRON_POLICY_SPECS.items()}
    effective: Dict[str, Any] = {}
    for key, spec in _AUTONOMY_CRON_POLICY_SPECS.items():
        default_val = spec["default"]
        value_type = str(spec.get("type", "int"))
        entry = _cron_policy_value_and_source(key, default_val, value_type)
        # expose currently effective clamped value, but preserve source.
        current = effective_values.get(key, entry["value"])
        if value_type == "bool":
            entry["value"] = bool(current)
        else:
            entry["value"] = int(current)
        effective[key] = entry

    return {
        "effective": effective,
        "defaults": defaults,
        "restart_required": True,
    }


@router.post("/autonomy/cron-policy")
async def update_autonomy_cron_policy(update: AutonomyCronPolicyUpdate):
    """
    Persist cron guardrail policy overrides.
    Changes are applied on next admin-api restart.
    """
    payload = update.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(status_code=422, detail="No valid fields provided")

    saved: Dict[str, Any] = {}
    for key, value in payload.items():
        spec = _AUTONOMY_CRON_POLICY_SPECS.get(key)
        if not spec:
            raise HTTPException(status_code=422, detail=f"{key}: unsupported key")
        value_type = str(spec.get("type", "int"))
        if value_type == "bool":
            bvalue = bool(value)
            settings.set(key, bvalue)
            saved[key] = bvalue
            continue
        ivalue = int(value)
        lo = int(spec["min"])
        hi = int(spec["max"])
        if ivalue < lo or ivalue > hi:
            raise HTTPException(status_code=422, detail=f"{key}: must be between {lo} and {hi}")
        settings.set(key, ivalue)
        saved[key] = ivalue

    return {
        "success": True,
        "saved": saved,
        "restart_required": True,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Reference Links (GitHub read-only inspiration collections)
# ─────────────────────────────────────────────────────────────────────────────

REFERENCE_LINKS_SETTINGS_KEY = "TRION_REFERENCE_LINK_COLLECTIONS"
REFERENCE_LINKS_CATEGORIES = ("cronjobs", "skills", "blueprints")
REFERENCE_LINKS_ALLOWED_HOSTS = (
    "github.com",
    "www.github.com",
    "raw.githubusercontent.com",
    "gist.github.com",
)


class ReferenceLinkItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    url: str
    description: Optional[str] = ""
    enabled: bool = True
    read_only: bool = True


class ReferenceLinksUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cronjobs: Optional[list[ReferenceLinkItem]] = None
    skills: Optional[list[ReferenceLinkItem]] = None
    blueprints: Optional[list[ReferenceLinkItem]] = None


def _normalize_reference_link(item: Dict[str, Any], category: str, idx: int) -> Dict[str, Any]:
    name = str((item or {}).get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail=f"{category}[{idx}].name: required")
    if len(name) > 120:
        raise HTTPException(status_code=422, detail=f"{category}[{idx}].name: max length is 120")

    url = str((item or {}).get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=422, detail=f"{category}[{idx}].url: required")
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise HTTPException(status_code=422, detail=f"{category}[{idx}].url: https required")
    if (parsed.netloc or "").lower() not in REFERENCE_LINKS_ALLOWED_HOSTS:
        raise HTTPException(
            status_code=422,
            detail=f"{category}[{idx}].url: host not allowed (allowed: {', '.join(REFERENCE_LINKS_ALLOWED_HOSTS)})",
        )
    if not (parsed.path or "").strip("/"):
        raise HTTPException(status_code=422, detail=f"{category}[{idx}].url: path required")

    description = str((item or {}).get("description") or "").strip()
    if len(description) > 300:
        raise HTTPException(status_code=422, detail=f"{category}[{idx}].description: max length is 300")

    return {
        "name": name,
        "url": url,
        "description": description,
        "enabled": bool((item or {}).get("enabled", True)),
        # hard-enforce read-only mode for TRION consumption
        "read_only": True,
    }


def _normalize_reference_links_payload(raw: Any) -> Dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    out: Dict[str, Any] = {}
    for category in REFERENCE_LINKS_CATEGORIES:
        entries = data.get(category) or []
        if not isinstance(entries, list):
            continue
        normalized = [_normalize_reference_link(entry, category, idx) for idx, entry in enumerate(entries)]
        # de-duplicate by URL while preserving order
        deduped: list[Dict[str, Any]] = []
        seen_urls: set[str] = set()
        for entry in normalized:
            key = entry["url"].lower()
            if key in seen_urls:
                continue
            seen_urls.add(key)
            deduped.append(entry)
        out[category] = deduped
    return out


def _reference_links_defaults() -> Dict[str, Any]:
    return {category: [] for category in REFERENCE_LINKS_CATEGORIES}


def _reference_links_load_effective() -> Dict[str, Any]:
    defaults = _reference_links_defaults()
    raw = settings.get(REFERENCE_LINKS_SETTINGS_KEY, defaults)
    normalized = _normalize_reference_links_payload(raw)
    return {category: normalized.get(category, []) for category in REFERENCE_LINKS_CATEGORIES}


@router.get("/reference-links")
async def get_reference_links():
    collections = _reference_links_load_effective()
    return {
        "collections": collections,
        "categories": list(REFERENCE_LINKS_CATEGORIES),
        "allowed_hosts": list(REFERENCE_LINKS_ALLOWED_HOSTS),
        "mode": "read_only_for_trion",
    }


@router.post("/reference-links")
async def update_reference_links(update: ReferenceLinksUpdate):
    payload = update.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(status_code=422, detail="No valid fields provided")

    current = _reference_links_load_effective()
    incoming = _normalize_reference_links_payload(payload)
    for category in REFERENCE_LINKS_CATEGORIES:
        if category in incoming:
            current[category] = incoming[category]

    settings.set(REFERENCE_LINKS_SETTINGS_KEY, current)
    return {
        "success": True,
        "collections": current,
        "categories": list(REFERENCE_LINKS_CATEGORIES),
        "mode": "read_only_for_trion",
    }
