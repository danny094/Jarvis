"""
adapters/admin-api/runtime_routes.py — Runtime telemetry API (Phase 8 Operational).

Endpoints:
    GET /api/runtime/compute/instances
        List managed Ollama compute instances (cpu/gpuN) with status + health.
    POST /api/runtime/compute/instances/{id}/start
        Start a managed instance from strict templates.
    POST /api/runtime/compute/instances/{id}/stop
        Stop a managed instance (idempotent).
    GET /api/runtime/compute/routing
        Get persisted layer routing + effective targets.
    POST /api/runtime/compute/routing
        Update persisted layer routing (strict validation).

    GET /api/runtime/digest-state
        Returns digest pipeline runtime state (last run, status, locking, JIT telemetry).
        Always returns a stable JSON structure even if the pipeline has never run.

API versions:
    v2 (default, DIGEST_RUNTIME_API_V2=true):
        Flat shape: {jit_only, daily_digest, weekly_digest, archive_digest,
                     locking, catch_up, flags}
        locking: {status: FREE|LOCKED, owner, since, timeout_s, stale}
        No stacktraces: all exceptions → {"error": "brief description"}
    v1 (legacy, DIGEST_RUNTIME_API_V2=false):
        Shape: {state, flags, lock}

Rollback: DIGEST_RUNTIME_API_V2=false
Logging marker: [DigestRuntime]
"""
from typing import Optional, Dict, Any
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from utils import ollama_endpoint_manager as _compute

router = APIRouter(tags=["runtime"])


def _ratio(remaining: int | None, limit: int | None) -> float | None:
    if remaining is None or limit is None:
        return None
    try:
        limit_val = float(limit)
        rem_val = float(remaining)
        if limit_val <= 0:
            return None
        used = max(0.0, min(limit_val, limit_val - rem_val))
        return round(used / limit_val, 6)
    except Exception:
        return None


# ── Lock helpers ──────────────────────────────────────────────────────────────

def _build_locking(lock_info) -> dict:
    """Build structured locking block from raw lock_info dict or None."""
    if lock_info is None:
        return {
            "status":    "FREE",
            "owner":     None,
            "since":     None,
            "timeout_s": _get_timeout_s(),
            "stale":     None,
        }
    owner     = lock_info.get("owner")
    since     = lock_info.get("acquired_at")
    timeout_s = _get_timeout_s()
    stale     = None
    if since:
        try:
            dt = datetime.fromisoformat(since.rstrip("Z"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age_s = (datetime.now(tz=timezone.utc) - dt).total_seconds()
            stale = age_s > timeout_s
        except Exception:
            pass
    return {
        "status":    "LOCKED",
        "owner":     owner,
        "since":     since,
        "timeout_s": timeout_s,
        "stale":     stale,
    }


def _get_timeout_s() -> int:
    try:
        import config
        return config.get_digest_lock_timeout_s()
    except Exception:
        return 300


# ── Endpoint ──────────────────────────────────────────────────────────────────

class LayerRoutingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thinking: Optional[str] = None
    control: Optional[str] = None
    output: Optional[str] = None
    tool_selector: Optional[str] = None
    embedding: Optional[str] = None


class ComputeRoutingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    layer_routing: Optional[LayerRoutingUpdate] = None


def _raise_compute_http(exc: Exception) -> None:
    if isinstance(exc, _compute.ComputeValidationError):
        raise HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, _compute.ComputeConflictError):
        raise HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, _compute.ComputeDependencyError):
        raise HTTPException(status_code=503, detail=str(exc))
    raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/runtime/compute/instances")
async def get_compute_instances():
    """List managed Ollama compute instances + health + capability."""
    try:
        return _compute.list_instances()
    except Exception as exc:
        _raise_compute_http(exc)


@router.post("/api/runtime/compute/instances/{instance_id}/start")
async def start_compute_instance(instance_id: str):
    """
    Start instance from strict template whitelist.
    Idempotent: already running returns started=true,idempotent=true.
    """
    try:
        return _compute.start_instance(instance_id)
    except Exception as exc:
        _raise_compute_http(exc)


@router.post("/api/runtime/compute/instances/{instance_id}/stop")
async def stop_compute_instance(instance_id: str):
    """Stop managed instance. Idempotent if already stopped/missing."""
    try:
        return _compute.stop_instance(instance_id)
    except Exception as exc:
        _raise_compute_http(exc)


@router.get("/api/runtime/compute/routing")
async def get_compute_routing():
    """
    Return persisted layer routing + effective target resolution snapshot.
    """
    try:
        instances = _compute.list_instances()
        layer_routing = _compute.get_layer_routing()
        effective = _compute.resolve_layer_routing(
            layer_routing=layer_routing,
            instances_snapshot=instances,
        )
        return {
            "layer_routing": layer_routing,
            "allowed_targets": instances.get("allowed_targets", ["auto", "cpu"]),
            "effective": effective,
        }
    except Exception as exc:
        _raise_compute_http(exc)


@router.post("/api/runtime/compute/routing")
async def post_compute_routing(update: ComputeRoutingUpdate):
    """
    Persist layer routing (thinking/control/output/tool_selector/embedding).
    Unknown fields rejected by Pydantic (extra=forbid).
    """
    try:
        payload = update.model_dump(exclude_none=True)
        layer_update = payload.get("layer_routing", {}) or {}
        next_routing = _compute.update_layer_routing(layer_update)
        instances = _compute.list_instances()
        effective = _compute.resolve_layer_routing(
            layer_routing=next_routing,
            instances_snapshot=instances,
        )
        return {
            "success": True,
            "saved": next_routing,
            "allowed_targets": instances.get("allowed_targets", ["auto", "cpu"]),
            "effective": effective,
        }
    except Exception as exc:
        _raise_compute_http(exc)


@router.get("/api/runtime/digest-state")
async def get_digest_state():
    """
    Digest pipeline runtime telemetry.

    V2 response (DIGEST_RUNTIME_API_V2=true, default):
        {
          "jit_only": bool,
          "daily_digest":  { status, last_run, duration_s, input_events,
                             digest_written, digest_key, reason },
          "weekly_digest": { ... same ... },
          "archive_digest":{ ... same ... },
          "locking": { status: FREE|LOCKED, owner, since, timeout_s, stale },
          "catch_up": { status, last_run, missed_runs, recovered,
                        generated, processed, mode },
          "flags": { digest_enable, daily_enable, ..., catchup_max_days }
        }

    V1 response (DIGEST_RUNTIME_API_V2=false):
        { "state": {...}, "flags": {...}, "lock": {...}|null }
    """
    # ── Check API version ────────────────────────────────────────────────────
    try:
        import config as _cfg
        api_v2 = _cfg.get_digest_runtime_api_v2()
    except Exception:
        api_v2 = True

    # ── Runtime state ────────────────────────────────────────────────────────
    try:
        import sys, os
        _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if _root not in sys.path:
            sys.path.insert(0, _root)
        from core.digest import runtime_state
        state = runtime_state.get_state()
    except Exception as exc:
        state = {"error": str(exc), "schema_version": 0}

    # ── Config flags ─────────────────────────────────────────────────────────
    try:
        import config
        flags = {
            "digest_enable":         config.get_digest_enable(),
            "digest_daily_enable":   config.get_digest_daily_enable(),
            "digest_weekly_enable":  config.get_digest_weekly_enable(),
            "digest_archive_enable": config.get_digest_archive_enable(),
            "digest_run_mode":       config.get_digest_run_mode(),
            "jit_only":              config.get_typedstate_csv_jit_only(),
            "filters_enable":        config.get_digest_filters_enable(),
            "catchup_max_days":      config.get_digest_catchup_max_days(),
            "min_events_daily":      config.get_digest_min_events_daily(),
            "min_daily_per_week":    config.get_digest_min_daily_per_week(),
            "digest_ui_enable":      config.get_digest_ui_enable(),
        }
    except Exception as exc:
        flags = {"error": str(exc)}

    # ── Lock state ───────────────────────────────────────────────────────────
    try:
        from core.digest.locking import get_lock_info
        lock_info = get_lock_info()
    except Exception:
        lock_info = None

    # ── V1 legacy shape ──────────────────────────────────────────────────────
    if not api_v2:
        return JSONResponse({
            "state": state,
            "flags": flags,
            "lock":  lock_info,
        })

    # ── V2 flat shape ────────────────────────────────────────────────────────
    # Extract cycle blocks from state
    def _cycle(key: str) -> dict:
        c = state.get(key, {}) if isinstance(state, dict) else {}
        return {
            "status":         c.get("status", "never"),
            "last_run":       c.get("last_run"),
            "duration_s":     c.get("duration_s"),
            "input_events":   c.get("input_events"),
            "digest_written": c.get("digest_written"),
            "digest_key":     c.get("digest_key"),
            "reason":         c.get("reason"),
            "retry_policy":   c.get("retry_policy"),
        }

    cu_raw = state.get("catch_up", {}) if isinstance(state, dict) else {}
    catch_up = {
        "status":         cu_raw.get("status", "never"),
        "last_run":       cu_raw.get("last_run"),
        "missed_runs":    cu_raw.get("missed_runs", 0),
        "recovered":      cu_raw.get("recovered"),
        "generated":      cu_raw.get("generated", 0),
        "processed":      cu_raw.get("days_processed", 0),
        "mode":           cu_raw.get("mode", "off"),
    }

    # Structured jit block (v2 state uses jit.{trigger,rows,ts})
    jit_raw = state.get("jit", {}) if isinstance(state, dict) else {}

    return JSONResponse({
        "jit_only":       flags.get("jit_only", False) if isinstance(flags, dict) else False,
        "daily_digest":   _cycle("daily"),
        "weekly_digest":  _cycle("weekly"),
        "archive_digest": _cycle("archive"),
        "locking":        _build_locking(lock_info),
        "catch_up":       catch_up,
        "jit":            {
            "trigger": jit_raw.get("trigger"),
            "rows":    jit_raw.get("rows"),
            "ts":      jit_raw.get("ts"),
        },
        "flags":          flags,
    })


@router.get("/api/runtime/session")
async def get_runtime_session():
    """
    Session telemetry for UI dashboards.
    Includes request/tokens/latency aggregates and latest cloud rate-limit snapshots.
    """
    from core.llm_provider_client import get_rate_limit_snapshot
    from core.session_metrics import get_session_snapshot

    session = get_session_snapshot()
    rate_limits = get_rate_limit_snapshot()
    provider_rows = {
        str((row or {}).get("provider", "")).strip().lower(): (row or {})
        for row in (session.get("providers", []) if isinstance(session, dict) else [])
        if isinstance(row, dict)
    }

    cloud_budget: Dict[str, Any] = {}
    for provider in ("openai", "anthropic", "ollama_cloud"):
        snap = rate_limits.get(provider, {}) if isinstance(rate_limits, dict) else {}
        observed = provider_rows.get(provider, {})
        req_limit = snap.get("request_limit")
        req_remaining = snap.get("request_remaining")
        tok_limit = snap.get("token_limit")
        tok_remaining = snap.get("token_remaining")
        has_limit_headers = any(
            v is not None and str(v).strip() != ""
            for v in (
                req_limit,
                req_remaining,
                tok_limit,
                tok_remaining,
                snap.get("request_reset"),
                snap.get("token_reset"),
            )
        )
        cloud_budget[provider] = {
            "requests": {
                "limit": req_limit,
                "remaining": req_remaining,
                "used_ratio": _ratio(req_remaining, req_limit),
                "reset": snap.get("request_reset"),
            },
            "tokens": {
                "limit": tok_limit,
                "remaining": tok_remaining,
                "used_ratio": _ratio(tok_remaining, tok_limit),
                "reset": snap.get("token_reset"),
            },
            "status_code": snap.get("status_code"),
            "request_id": snap.get("request_id"),
            "updated_at": snap.get("updated_at"),
            "has_limit_headers": has_limit_headers,
            "observed": {
                "requests": int(observed.get("requests", 0) or 0),
                "errors": int(observed.get("errors", 0) or 0),
                "tokens_in_est": int(observed.get("tokens_in_est", 0) or 0),
                "tokens_out_est": int(observed.get("tokens_out_est", 0) or 0),
                "last_model": observed.get("last_model"),
            },
        }

    return JSONResponse(
        {
            **session,
            "rate_limits": rate_limits,
            "cloud_budget": cloud_budget,
        }
    )


@router.get("/api/runtime/autonomy-status")
async def get_autonomy_status():
    """
    Runtime readiness snapshot for autonomous planning.
    Includes:
      - master settings (/api/settings/master source of truth)
      - sequential/planning tool availability from MCP hub
      - home container connectivity status
    """
    checked_at = datetime.now(tz=timezone.utc).isoformat()

    # Master settings
    try:
        from settings_routes import load_master_settings
        master_settings = load_master_settings()
    except Exception as exc:
        master_settings = {
            "enabled": True,
            "use_thinking_layer": False,
            "max_loops": 10,
            "completion_threshold": 2,
            "_error": str(exc),
        }

    # MCP tool readiness
    tools: Dict[str, Any] = {
        "sequential_thinking": False,
        "think": False,
        "workspace_event_save": False,
        "workspace_event_list": False,
    }
    required_aliases: Dict[str, list[str]] = {
        # Sequential capability may be exposed as sequential_thinking or think/think_simple.
        "sequential_thinking": ["sequential_thinking", "think", "think_simple"],
        "think": ["think", "think_simple", "sequential_thinking"],
        "workspace_event_save": ["workspace_event_save"],
        "workspace_event_list": ["workspace_event_list"],
    }
    mcp_error = ""
    total_tools = 0
    try:
        from mcp.hub import get_hub

        hub = get_hub()
        available = hub.list_tools()
        total_tools = len(available) if isinstance(available, list) else 0
        names = {
            str(t.get("name", "")).strip()
            for t in (available or [])
            if isinstance(t, dict) and str(t.get("name", "")).strip()
        }
        for key in list(tools.keys()):
            aliases = required_aliases.get(key, [key])
            tools[key] = any(alias in names for alias in aliases)
    except Exception as exc:
        mcp_error = str(exc)

    # Home container readiness
    home = {"status": "offline", "error_code": "home_status_unavailable"}
    try:
        from container_commander.engine import list_containers
        from utils.trion_home_identity import evaluate_home_status

        home = evaluate_home_status(list_containers())
    except Exception as exc:
        home = {"status": "offline", "error_code": "home_status_unavailable", "error": str(exc)}

    return {
        "checked_at": checked_at,
        "master": {
            "enabled": bool(master_settings.get("enabled", True)),
            "use_thinking_layer": bool(master_settings.get("use_thinking_layer", False)),
            "max_loops": int(master_settings.get("max_loops", 10) or 10),
            "completion_threshold": int(master_settings.get("completion_threshold", 2) or 2),
            "raw": master_settings,
        },
        "planning_tools": {
            "available": tools,
            "all_required_available": all(bool(v) for v in tools.values()),
            "required_aliases": required_aliases,
            "total_discovered_tools": total_tools,
            "error": mcp_error,
        },
        "home": {
            "status": str(home.get("status", "offline")),
            "error_code": str(home.get("error_code", "")),
            "home_container_id": str(home.get("home_container_id", "")),
            "identity_path": str(home.get("identity_path", "")),
        },
    }
