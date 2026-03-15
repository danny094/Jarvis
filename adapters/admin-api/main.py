"""
Jarvis Admin API
Management API for Jarvis WebUI

Provides:
- Persona Management (/api/personas/*)
- Memory Maintenance (/api/maintenance/*)
- Chat Endpoint (/api/chat) - For WebUI chat functionality
- System Health (/health)
"""

import json
import asyncio
import os
import re
import time
import traceback
import uuid
import httpx
from typing import Any, Dict, List
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
import logging

# Import routers
from maintenance.persona_routes import router as persona_router
from maintenance.routes import router as maintenance_router
# from sequential_routes import router as sequential_router  # REMOVED - old system

# Import for chat functionality
from adapters.lobechat.adapter import get_adapter
from core.bridge import get_bridge
from core.session_metrics import count_input_chars, record_chat_turn
from utils.logger import log_info, log_error, log_debug, log_warning
from config import (
    get_deep_job_max_concurrency,
    get_deep_job_timeout_s,
    get_autonomy_job_max_concurrency,
    get_autonomy_job_timeout_s,
    get_autonomy_cron_state_path,
    get_autonomy_cron_tick_s,
    get_autonomy_cron_max_concurrency,
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
from core.autonomy.cron_scheduler import AutonomyCronScheduler, CronPolicyError
from core.autonomy.cron_runtime import (
    get_scheduler as get_autonomy_cron_runtime_scheduler,
    set_scheduler as set_autonomy_cron_runtime_scheduler,
    clear_scheduler as clear_autonomy_cron_runtime_scheduler,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Jarvis Admin API",
    description="Management API for Jarvis WebUI - Personas, Maintenance, Chat & MCP Hub (inkl. Skill-Server)",
    version="1.2.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS Configuration for WebUI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development/local network
    allow_credentials=False,  # Must be False when using wildcard
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
# Persona router has its own prefix defined in persona_routes.py
# Maintenance router needs explicit prefix
app.include_router(persona_router)
app.include_router(maintenance_router, prefix="/api/maintenance")

# Settings Router
from settings_routes import router as settings_router
app.include_router(settings_router, prefix="/api/settings")

# MCP Management (Installer, List, Toggle)
from mcp.installer import router as mcp_installer_router
app.include_router(mcp_installer_router, prefix="/api/mcp")

# MCP Hub Endpoint (tools/list, tools/call) - für KI Tool-Aufrufe inkl. Skill-Server
from mcp.endpoint import router as mcp_hub_router
app.include_router(mcp_hub_router)  # Exposes /mcp, /mcp/status, /mcp/tools

# Daily Protocol (Tagesprotokoll)
from protocol_routes import router as protocol_router

# Container Commander
from commander_routes import router as commander_router
app.include_router(protocol_router, prefix="/api/protocol")
app.include_router(commander_router, prefix="/api/commander")

from secrets_routes import router as secrets_router
app.include_router(secrets_router, prefix="/api/secrets")

# TRION Home Memory API (optional to avoid hard boot-fail on stale container images)
try:
    from trion_memory_routes import router as trion_memory_router
except ModuleNotFoundError as e:
    trion_memory_router = None
    logger.warning("TRION memory routes unavailable (%s) - /api/trion/memory disabled", e)

if trion_memory_router is not None:
    app.include_router(trion_memory_router, prefix="/api/trion/memory")

# Runtime telemetry (Phase 8 Operational — digest pipeline state)
from runtime_routes import router as runtime_router
app.include_router(runtime_router)

# Storage Broker Settings (frontend policy config + proxy to storage-broker MCP)
try:
    from storage_broker_routes import router as storage_broker_router
    app.include_router(storage_broker_router, prefix="/api/storage-broker")
except ModuleNotFoundError as e:
    logger.warning("Storage broker routes unavailable (%s) - /api/storage-broker disabled", e)

# ============================================================
# DEEP JOBS (async long-running chat execution)
# ============================================================

_DEEP_JOB_MAX_ITEMS = 200
_DEEP_JOB_RETENTION_S = 6 * 60 * 60
_DEEP_JOB_MAX_CONCURRENCY = get_deep_job_max_concurrency()
_DEEP_JOB_TIMEOUT_S = get_deep_job_timeout_s()
_deep_jobs: Dict[str, Dict[str, Any]] = {}
_deep_jobs_lock = asyncio.Lock()
_deep_job_slots = asyncio.Semaphore(_DEEP_JOB_MAX_CONCURRENCY)
_deep_job_tasks: Dict[str, asyncio.Task] = {}

# ============================================================
# AUTONOMY JOBS (async autonomous objective execution)
# ============================================================

_AUTONOMY_JOB_MAX_ITEMS = 200
_AUTONOMY_JOB_RETENTION_S = 6 * 60 * 60
_AUTONOMY_JOB_MAX_CONCURRENCY = get_autonomy_job_max_concurrency()
_AUTONOMY_JOB_TIMEOUT_S = get_autonomy_job_timeout_s()
_autonomy_jobs: Dict[str, Dict[str, Any]] = {}
_autonomy_jobs_lock = asyncio.Lock()
_autonomy_job_slots = asyncio.Semaphore(_AUTONOMY_JOB_MAX_CONCURRENCY)
_autonomy_job_tasks: Dict[str, asyncio.Task] = {}
_autonomy_cron_scheduler: AutonomyCronScheduler | None = None


def _iso_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


async def _hub_call_tool(tool_name: str, args: Dict[str, Any]) -> Any:
    """Async-safe MCPHub call helper."""
    from mcp.hub import get_hub

    hub = get_hub()
    hub.initialize()
    call_tool_async = getattr(hub, "call_tool_async", None)
    if callable(call_tool_async):
        return await call_tool_async(tool_name, args)
    return await asyncio.to_thread(hub.call_tool, tool_name, args)


async def _prune_deep_jobs() -> None:
    now = time.time()
    expired = [
        job_id
        for job_id, job in _deep_jobs.items()
        if (now - float(job.get("created_ts", now))) > _DEEP_JOB_RETENTION_S
    ]
    for job_id in expired:
        _deep_jobs.pop(job_id, None)

    if len(_deep_jobs) > _DEEP_JOB_MAX_ITEMS:
        ordered = sorted(
            _deep_jobs.items(),
            key=lambda kv: float(kv[1].get("created_ts", 0.0)),
        )
        remove_count = len(_deep_jobs) - _DEEP_JOB_MAX_ITEMS
        for job_id, _ in ordered[:remove_count]:
            _deep_jobs.pop(job_id, None)
            _deep_job_tasks.pop(job_id, None)


def _set_job_phase(job: Dict[str, Any], phase: str, now_ts: float) -> None:
    """Track current deep-job phase and update timestamp."""
    if not isinstance(job, dict):
        return
    job["phase"] = phase
    job["last_update_at"] = datetime.utcnow().isoformat() + "Z"
    job["last_update_ts"] = now_ts


def _deep_jobs_runtime_stats(target_job_id: str = "") -> tuple[int, int, int | None]:
    """Return (running_jobs, queued_jobs, queue_position_for_target)."""
    running = sum(1 for j in _deep_jobs.values() if j.get("status") == "running")
    queued = sorted(
        (
            (jid, float(j.get("created_ts", 0.0)))
            for jid, j in _deep_jobs.items()
            if j.get("status") == "queued"
        ),
        key=lambda item: item[1],
    )
    position = None
    if target_job_id:
        for idx, (jid, _) in enumerate(queued, start=1):
            if jid == target_job_id:
                position = idx
                break
    return running, len(queued), position


async def _run_deep_job(job_id: str, raw_data: dict) -> None:
    adapter = get_adapter()
    bridge = get_bridge()

    async with _deep_jobs_lock:
        job = _deep_jobs.get(job_id)
        if not job:
            return
        if job.get("status") in {"cancelled", "failed", "succeeded"}:
            return
        now_ts = time.time()
        job["status"] = "queued"
        created_ts = float(job.get("created_ts", time.time()))
        _set_job_phase(job, "queued", now_ts)

    try:
        async with _deep_job_slots:
            started_ts = time.time()
            async with _deep_jobs_lock:
                job = _deep_jobs.get(job_id)
                if not job:
                    return
                if job.get("status") in {"cancelled", "cancel_requested"}:
                    return
                queue_wait_ms = max(0.0, (started_ts - created_ts) * 1000.0)
                job["status"] = "running"
                job["started_at"] = _iso_now()
                job["started_ts"] = started_ts
                job["queue_wait_ms"] = round(queue_wait_ms, 2)
                _set_job_phase(job, "running", started_ts)

            force_data = dict(raw_data)
            force_data["stream"] = False
            force_data["response_mode"] = "deep"
            force_data["deep_job_id"] = job_id

            t_req = time.time()
            core_request = adapter.transform_request(force_data)
            t_req_done = time.time()
            async with _deep_jobs_lock:
                job = _deep_jobs.get(job_id)
                if job:
                    job["phase_timings_ms"]["transform_request_ms"] = round(
                        (t_req_done - t_req) * 1000.0, 2
                    )
                    _set_job_phase(job, "bridge_process", t_req_done)

            t_bridge = time.time()
            async with asyncio.timeout(float(_DEEP_JOB_TIMEOUT_S)):
                core_response = await bridge.process(core_request)
            t_bridge_done = time.time()
            async with _deep_jobs_lock:
                job = _deep_jobs.get(job_id)
                if job:
                    job["phase_timings_ms"]["bridge_process_ms"] = round(
                        (t_bridge_done - t_bridge) * 1000.0, 2
                    )
                    _set_job_phase(job, "transform_response", t_bridge_done)

            t_resp = time.time()
            response_data = adapter.transform_response(core_response)
            t_resp_done = time.time()

            finished_ts = t_resp_done
            async with _deep_jobs_lock:
                job = _deep_jobs.get(job_id)
                if not job:
                    return
                job["status"] = "succeeded"
                job["phase"] = "done"
                job["finished_at"] = _iso_now()
                job["finished_ts"] = finished_ts
                job["duration_ms"] = round((finished_ts - started_ts) * 1000.0, 2)
                job["phase_timings_ms"]["transform_response_ms"] = round(
                    (t_resp_done - t_resp) * 1000.0, 2
                )
                job["result"] = response_data
                job["error"] = None
                job["error_code"] = None
                await _prune_deep_jobs()
    except TimeoutError:
        finished_ts = time.time()
        async with _deep_jobs_lock:
            job = _deep_jobs.get(job_id)
            if not job:
                return
            started_ts = float(job.get("started_ts") or finished_ts)
            job["status"] = "failed"
            job["phase"] = "timeout"
            job["finished_at"] = _iso_now()
            job["finished_ts"] = finished_ts
            job["duration_ms"] = round((finished_ts - started_ts) * 1000.0, 2)
            job["error"] = f"deep_job_timeout_after_{int(_DEEP_JOB_TIMEOUT_S)}s"
            job["error_code"] = "deep_job_timeout"
            await _prune_deep_jobs()
        log_error(f"[Admin-API-Chat] Deep job timeout job_id={job_id} timeout_s={_DEEP_JOB_TIMEOUT_S}")
    except asyncio.CancelledError:
        finished_ts = time.time()
        async with _deep_jobs_lock:
            job = _deep_jobs.get(job_id)
            if not job:
                return
            started_ts = float(job.get("started_ts") or finished_ts)
            job["status"] = "cancelled"
            job["phase"] = "cancelled"
            job["finished_at"] = _iso_now()
            job["finished_ts"] = finished_ts
            job["duration_ms"] = round((finished_ts - started_ts) * 1000.0, 2)
            job["error"] = "cancelled_by_user"
            job["error_code"] = "cancelled"
            await _prune_deep_jobs()
        log_info(f"[Admin-API-Chat] Deep job cancelled job_id={job_id}")
    except Exception as e:
        finished_ts = time.time()
        async with _deep_jobs_lock:
            job = _deep_jobs.get(job_id)
            if not job:
                return
            started_ts = float(job.get("started_ts") or finished_ts)
            job["status"] = "failed"
            job["phase"] = "failed"
            job["finished_at"] = _iso_now()
            job["finished_ts"] = finished_ts
            job["duration_ms"] = round((finished_ts - started_ts) * 1000.0, 2)
            job["error"] = str(e)
            job["error_code"] = "deep_job_error"
            job["traceback"] = traceback.format_exc(limit=12)
            await _prune_deep_jobs()
        log_error(f"[Admin-API-Chat] Deep job failed job_id={job_id}: {e}")
    finally:
        _deep_job_tasks.pop(job_id, None)


def _deep_jobs_status_summary() -> Dict[str, int]:
    by_status: Dict[str, int] = {}
    for job in _deep_jobs.values():
        status = str(job.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
    return by_status


def _deep_jobs_oldest_queue_age_s(now_ts: float) -> float:
    oldest = None
    for job in _deep_jobs.values():
        if job.get("status") != "queued":
            continue
        created_ts = float(job.get("created_ts", now_ts))
        if oldest is None or created_ts < oldest:
            oldest = created_ts
    if oldest is None:
        return 0.0
    return max(0.0, now_ts - oldest)


def _deep_jobs_longest_running_s(now_ts: float) -> float:
    longest = 0.0
    for job in _deep_jobs.values():
        if job.get("status") != "running":
            continue
        started_ts = float(job.get("started_ts", now_ts))
        longest = max(longest, max(0.0, now_ts - started_ts))
    return longest


async def _cancel_deep_job_locked(job: Dict[str, Any]) -> Dict[str, Any]:
    """Cancel/mark a deep job while lock is held. Returns public view."""
    status = str(job.get("status") or "")
    now_ts = time.time()
    job_id = str(job.get("job_id") or "")

    if status in {"succeeded", "failed", "cancelled"}:
        return _public_job_view(job)

    if status == "queued":
        job["status"] = "cancelled"
        job["phase"] = "cancelled_before_start"
        job["finished_at"] = _iso_now()
        job["finished_ts"] = now_ts
        job["duration_ms"] = 0.0
        job["error"] = "cancelled_by_user"
        job["error_code"] = "cancelled"
    else:
        job["status"] = "cancel_requested"
        job["phase"] = "cancel_requested"
        job["cancel_requested_at"] = _iso_now()
        _set_job_phase(job, "cancel_requested", now_ts)

    task = _deep_job_tasks.get(job_id)
    if task and not task.done():
        task.cancel()
    await _prune_deep_jobs()
    return _public_job_view(job)


def _public_job_view(job: dict) -> dict:
    running_jobs, queued_jobs, queue_position = _deep_jobs_runtime_stats(job.get("job_id", ""))
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "model": job.get("model", ""),
        "conversation_id": job.get("conversation_id"),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "duration_ms": job.get("duration_ms"),
        "queue_wait_ms": job.get("queue_wait_ms"),
        "timeout_s": _DEEP_JOB_TIMEOUT_S,
        "phase": job.get("phase", ""),
        "phase_timings_ms": job.get("phase_timings_ms", {}),
        "cancel_requested_at": job.get("cancel_requested_at"),
        "error_code": job.get("error_code"),
        "queue_position": queue_position,
        "queued_jobs": queued_jobs,
        "running_jobs": running_jobs,
        "max_concurrency": _DEEP_JOB_MAX_CONCURRENCY,
        "last_update_at": job.get("last_update_at"),
        "error": job.get("error"),
        "result": job.get("result"),
    }


def _normalize_autonomy_request(data: Any) -> tuple[Dict[str, Any], str, str]:
    """Validate and normalize autonomy request payload."""
    if not isinstance(data, dict):
        return {}, "invalid_request_body", "Request body must be a JSON object"

    objective = str(data.get("objective") or "").strip()
    if not objective:
        return {}, "missing_objective", "Missing 'objective' in request body"

    conversation_id = str(data.get("conversation_id") or "").strip()
    if not conversation_id:
        return {}, "missing_conversation_id", "Missing 'conversation_id' in request body"

    if "max_loops" in data:
        try:
            max_loops = int(data.get("max_loops"))
        except Exception:
            return {}, "invalid_max_loops", "max_loops must be an integer"
    else:
        try:
            from settings_routes import load_master_settings as _lms
            max_loops = int((_lms() or {}).get("max_loops", 10) or 10)
        except Exception:
            max_loops = 10

    if max_loops < 1 or max_loops > 200:
        return {}, "invalid_max_loops_range", "max_loops must be between 1 and 200"

    payload = {
        "objective": objective,
        "conversation_id": conversation_id,
        "max_loops": max_loops,
    }
    return payload, "", ""


async def _prune_autonomy_jobs() -> None:
    now = time.time()
    expired = [
        job_id
        for job_id, job in _autonomy_jobs.items()
        if (now - float(job.get("created_ts", now))) > _AUTONOMY_JOB_RETENTION_S
    ]
    for job_id in expired:
        _autonomy_jobs.pop(job_id, None)
        _autonomy_job_tasks.pop(job_id, None)

    if len(_autonomy_jobs) > _AUTONOMY_JOB_MAX_ITEMS:
        ordered = sorted(
            _autonomy_jobs.items(),
            key=lambda kv: float(kv[1].get("created_ts", 0.0)),
        )
        remove_count = len(_autonomy_jobs) - _AUTONOMY_JOB_MAX_ITEMS
        for job_id, _ in ordered[:remove_count]:
            _autonomy_jobs.pop(job_id, None)
            _autonomy_job_tasks.pop(job_id, None)


def _set_autonomy_job_phase(job: Dict[str, Any], phase: str, now_ts: float) -> None:
    if not isinstance(job, dict):
        return
    job["phase"] = phase
    job["last_update_at"] = _iso_now()
    job["last_update_ts"] = now_ts


def _autonomy_jobs_runtime_stats(target_job_id: str = "") -> tuple[int, int, int | None]:
    running = sum(1 for j in _autonomy_jobs.values() if j.get("status") == "running")
    queued = sorted(
        (
            (jid, float(j.get("created_ts", 0.0)))
            for jid, j in _autonomy_jobs.items()
            if j.get("status") == "queued"
        ),
        key=lambda item: item[1],
    )
    position = None
    if target_job_id:
        for idx, (jid, _) in enumerate(queued, start=1):
            if jid == target_job_id:
                position = idx
                break
    return running, len(queued), position


def _autonomy_jobs_status_summary() -> Dict[str, int]:
    by_status: Dict[str, int] = {}
    for job in _autonomy_jobs.values():
        status = str(job.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
    return by_status


def _autonomy_jobs_oldest_queue_age_s(now_ts: float) -> float:
    oldest = None
    for job in _autonomy_jobs.values():
        if job.get("status") != "queued":
            continue
        created_ts = float(job.get("created_ts", now_ts))
        if oldest is None or created_ts < oldest:
            oldest = created_ts
    if oldest is None:
        return 0.0
    return max(0.0, now_ts - oldest)


def _autonomy_jobs_longest_running_s(now_ts: float) -> float:
    longest = 0.0
    for job in _autonomy_jobs.values():
        if job.get("status") != "running":
            continue
        started_ts = float(job.get("started_ts", now_ts))
        longest = max(longest, max(0.0, now_ts - started_ts))
    return longest


def _public_autonomy_job_view(job: Dict[str, Any]) -> Dict[str, Any]:
    running_jobs, queued_jobs, queue_position = _autonomy_jobs_runtime_stats(job.get("job_id", ""))
    return {
        "job_id": job.get("job_id"),
        "status": job.get("status"),
        "phase": job.get("phase"),
        "objective": job.get("objective"),
        "conversation_id": job.get("conversation_id"),
        "max_loops": job.get("max_loops"),
        "retry_of": job.get("retry_of"),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "duration_ms": job.get("duration_ms"),
        "queue_wait_ms": job.get("queue_wait_ms"),
        "timeout_s": _AUTONOMY_JOB_TIMEOUT_S,
        "cancel_requested_at": job.get("cancel_requested_at"),
        "error_code": job.get("error_code"),
        "queue_position": queue_position,
        "queued_jobs": queued_jobs,
        "running_jobs": running_jobs,
        "max_concurrency": _AUTONOMY_JOB_MAX_CONCURRENCY,
        "last_update_at": job.get("last_update_at"),
        "error": job.get("error"),
        "result": job.get("result"),
    }


def _create_autonomy_job(payload: Dict[str, Any], retry_of: str | None = None) -> Dict[str, Any]:
    job_id = uuid.uuid4().hex
    now_ts = time.time()
    return {
        "job_id": job_id,
        "status": "queued",
        "phase": "queued",
        "objective": payload.get("objective"),
        "conversation_id": payload.get("conversation_id"),
        "max_loops": payload.get("max_loops"),
        "created_at": _iso_now(),
        "created_ts": now_ts,
        "started_at": None,
        "started_ts": None,
        "finished_at": None,
        "finished_ts": None,
        "duration_ms": None,
        "queue_wait_ms": None,
        "cancel_requested_at": None,
        "last_update_at": _iso_now(),
        "last_update_ts": now_ts,
        "timeout_s": _AUTONOMY_JOB_TIMEOUT_S,
        "result": None,
        "error": None,
        "error_code": None,
        "traceback": None,
        "payload": dict(payload),
        "retry_of": str(retry_of or ""),
    }


def _is_direct_cron_reminder_objective(objective: str) -> bool:
    txt = str(objective or "").strip().lower()
    if not txt:
        return False
    return txt.startswith("user_reminder::") or txt == "status summary reminder check"


def _looks_like_self_state_request(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if "wie dein tag war" in low or "wie dein tag ist" in low:
        return True
    if "wie es dir geht" in low:
        return True
    if "wie du dich" in low and ("fühl" in low or "fuehl" in low or "feel" in low):
        return True
    return False


def _is_direct_cron_self_state_objective(objective: str) -> bool:
    raw = str(objective or "").strip()
    txt = raw.lower()
    if not raw:
        return False
    if txt.startswith("self_state_report::"):
        return True
    if txt.startswith("user_request::"):
        detail = raw.split("::", 1)[1].strip()
        return _looks_like_self_state_request(detail)
    return False


def _extract_direct_cron_reminder_text(objective: str) -> str:
    raw = str(objective or "").strip()
    low = raw.lower()
    if low.startswith("user_reminder::"):
        text = raw.split("::", 1)[1].strip()
        if text:
            return text[:280]
    # Legacy fallback from earlier objective builder.
    return "Cronjob funktioniert?"


def _build_direct_cron_self_state_message(objective: str) -> str:
    raw = str(objective or "").strip()
    detail = ""
    low = raw.lower()
    if low.startswith("self_state_report::") or low.startswith("user_request::"):
        detail = raw.split("::", 1)[1].strip()
    if detail:
        detail = detail[:180]
    suffix = f" Anfrage: \"{detail}\"." if detail else ""
    return (
        "Ich habe keine menschlichen Gefühle, aber mein Trigger-Status war stabil: "
        f"bereit, verbunden und ausführungsfähig.{suffix}"
    )


def _extract_autonomy_result_summary(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    nested = result.get("result")
    if isinstance(nested, dict):
        direct = str(nested.get("message", "")).strip()
        if direct:
            return direct[:320]
        steps = nested.get("steps")
        if isinstance(steps, list) and steps:
            last = steps[-1] if isinstance(steps[-1], dict) else {}
            step_result = str(last.get("result", "")).strip()
            if step_result:
                return step_result[:320]
    top = str(result.get("error", "") or result.get("stop_reason", "")).strip()
    return top[:320] if top else ""


def _build_cron_chat_feedback_message(job: Dict[str, Any]) -> str:
    meta = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    cron_name = str(meta.get("cron_job_name") or meta.get("cron_job_id") or "cron-job").strip()
    status = str(job.get("status") or "").strip().lower()
    result = job.get("result")
    objective = str(job.get("objective") or "").strip()

    if status == "succeeded":
        if _is_direct_cron_reminder_objective(objective):
            text = _extract_direct_cron_reminder_text(objective)
            return f"⏰ {text}"
        if _is_direct_cron_self_state_objective(objective):
            summary = _extract_autonomy_result_summary(result)
            if summary:
                return f"⏰ {summary}"
            return "⏰ Ich habe keine menschlichen Gefühle, aber mein Systemstatus ist stabil."
        summary = _extract_autonomy_result_summary(result)
        if summary:
            return f"⏰ Cronjob `{cron_name}` ausgeführt: {summary}"
        return f"⏰ Cronjob `{cron_name}` wurde erfolgreich ausgeführt."

    error_code = str(job.get("error_code") or "autonomy_job_failed").strip()
    error = str(job.get("error") or "").strip()
    if error_code == "max_loops_reached":
        limit = ""
        m = re.search(r"max_loops_reached[:=](\d+)", error, flags=re.IGNORECASE)
        if m:
            limit = m.group(1)
        if limit:
            return (
                f"⏰ Cronjob `{cron_name}` beendet: Lauflimit erreicht "
                f"(max_loops={limit})."
            )
        return f"⏰ Cronjob `{cron_name}` beendet: Lauflimit erreicht (max_loops_reached)."
    if error:
        return f"⏰ Cronjob `{cron_name}` fehlgeschlagen ({error_code}): {error}"
    return f"⏰ Cronjob `{cron_name}` fehlgeschlagen ({error_code})."


async def _emit_cron_chat_feedback_event(job: Dict[str, Any]) -> None:
    if not isinstance(job, dict):
        return
    meta = job.get("metadata")
    if not isinstance(meta, dict):
        return
    if str(meta.get("source") or "").strip().lower() != "autonomy_cron":
        return
    conversation_id = str(job.get("conversation_id") or "").strip()
    if not conversation_id:
        return

    message = _build_cron_chat_feedback_message(job)
    if not message:
        return

    event_data = {
        "content": message,
        "source_layer": "autonomy_cron",
        "status": str(job.get("status") or ""),
        "autonomy_job_id": str(job.get("job_id") or ""),
        "cron_job_id": str(meta.get("cron_job_id") or ""),
        "cron_run_id": str(meta.get("cron_run_id") or ""),
        "cron_reason": str(meta.get("reason") or ""),
        "error_code": str(job.get("error_code") or ""),
    }
    try:
        await _hub_call_tool(
            "workspace_event_save",
            {
                "conversation_id": conversation_id,
                "event_type": "cron_chat_feedback",
                "event_data": event_data,
            },
        )
    except Exception as exc:
        log_warning(f"[Admin-API-Autonomy] cron_chat_feedback emit failed: {exc}")


async def _run_autonomy_job(job_id: str) -> None:
    bridge = get_bridge()

    async with _autonomy_jobs_lock:
        job = _autonomy_jobs.get(job_id)
        if not job:
            return
        if job.get("status") in {"cancelled", "failed", "succeeded"}:
            return
        now_ts = time.time()
        job["status"] = "queued"
        _set_autonomy_job_phase(job, "queued", now_ts)
        created_ts = float(job.get("created_ts", now_ts))

    try:
        async with _autonomy_job_slots:
            started_ts = time.time()
            async with _autonomy_jobs_lock:
                job = _autonomy_jobs.get(job_id)
                if not job:
                    return
                if job.get("status") in {"cancelled", "cancel_requested"}:
                    return
                queue_wait_ms = max(0.0, (started_ts - created_ts) * 1000.0)
                job["status"] = "running"
                job["started_at"] = _iso_now()
                job["started_ts"] = started_ts
                job["queue_wait_ms"] = round(queue_wait_ms, 2)
                _set_autonomy_job_phase(job, "running", started_ts)

                payload = dict(job.get("payload") or {})
                objective = str(payload.get("objective", ""))
                conversation_id = str(payload.get("conversation_id", ""))
                max_loops = int(payload.get("max_loops", 10))
                metadata = dict(job.get("metadata") or {})

            if _is_direct_cron_reminder_objective(objective):
                reminder_text = _extract_direct_cron_reminder_text(objective)
                result = {
                    "success": True,
                    "objective": objective,
                    "steps_completed": 1,
                    "elapsed_time": 0.0,
                    "final_state": "completed",
                    "result": {
                        "mode": "direct_reminder",
                        "message": reminder_text,
                    },
                    "stop_reason": "completed",
                }
            elif _is_direct_cron_self_state_objective(objective):
                state_text = _build_direct_cron_self_state_message(objective)
                result = {
                    "success": True,
                    "objective": objective,
                    "steps_completed": 1,
                    "elapsed_time": 0.0,
                    "final_state": "completed",
                    "result": {
                        "mode": "direct_self_state_report",
                        "message": state_text,
                    },
                    "stop_reason": "completed",
                }
            else:
                async with asyncio.timeout(float(_AUTONOMY_JOB_TIMEOUT_S)):
                    result = await bridge.orchestrator.execute_autonomous_objective(
                        objective=objective,
                        conversation_id=conversation_id,
                        max_loops=max_loops,
                    )

            finished_ts = time.time()
            feedback_job: Dict[str, Any] | None = None
            async with _autonomy_jobs_lock:
                job = _autonomy_jobs.get(job_id)
                if not job:
                    return
                started_job_ts = float(job.get("started_ts") or finished_ts)
                is_success = bool((result or {}).get("success", False))
                job["status"] = "succeeded" if is_success else "failed"
                job["phase"] = "done" if is_success else "failed"
                job["finished_at"] = _iso_now()
                job["finished_ts"] = finished_ts
                job["duration_ms"] = round((finished_ts - started_job_ts) * 1000.0, 2)
                job["result"] = result
                if is_success:
                    job["error"] = None
                    job["error_code"] = None
                else:
                    job["error_code"] = str(
                        (result or {}).get("error_code")
                        or "autonomous_objective_failed"
                    )
                    job["error"] = str(
                        (result or {}).get("error")
                        or (result or {}).get("stop_reason")
                        or "autonomous_objective_failed"
                    )
                feedback_job = dict(job)
                if metadata and not isinstance(feedback_job.get("metadata"), dict):
                    feedback_job["metadata"] = metadata
                await _prune_autonomy_jobs()
            if feedback_job is not None:
                await _emit_cron_chat_feedback_event(feedback_job)
    except TimeoutError:
        finished_ts = time.time()
        feedback_job: Dict[str, Any] | None = None
        async with _autonomy_jobs_lock:
            job = _autonomy_jobs.get(job_id)
            if not job:
                return
            started_ts = float(job.get("started_ts") or finished_ts)
            job["status"] = "failed"
            job["phase"] = "timeout"
            job["finished_at"] = _iso_now()
            job["finished_ts"] = finished_ts
            job["duration_ms"] = round((finished_ts - started_ts) * 1000.0, 2)
            job["error"] = f"autonomy_job_timeout_after_{int(_AUTONOMY_JOB_TIMEOUT_S)}s"
            job["error_code"] = "autonomy_job_timeout"
            feedback_job = dict(job)
            await _prune_autonomy_jobs()
        if feedback_job is not None:
            await _emit_cron_chat_feedback_event(feedback_job)
        log_error(
            f"[Admin-API-Autonomy] Job timeout job_id={job_id} timeout_s={_AUTONOMY_JOB_TIMEOUT_S}"
        )
    except asyncio.CancelledError:
        finished_ts = time.time()
        async with _autonomy_jobs_lock:
            job = _autonomy_jobs.get(job_id)
            if not job:
                return
            started_ts = float(job.get("started_ts") or finished_ts)
            job["status"] = "cancelled"
            job["phase"] = "cancelled"
            job["finished_at"] = _iso_now()
            job["finished_ts"] = finished_ts
            job["duration_ms"] = round((finished_ts - started_ts) * 1000.0, 2)
            job["error"] = "cancelled_by_user"
            job["error_code"] = "cancelled"
            await _prune_autonomy_jobs()
        log_info(f"[Admin-API-Autonomy] Job cancelled job_id={job_id}")
    except Exception as e:
        finished_ts = time.time()
        feedback_job: Dict[str, Any] | None = None
        async with _autonomy_jobs_lock:
            job = _autonomy_jobs.get(job_id)
            if not job:
                return
            started_ts = float(job.get("started_ts") or finished_ts)
            job["status"] = "failed"
            job["phase"] = "failed"
            job["finished_at"] = _iso_now()
            job["finished_ts"] = finished_ts
            job["duration_ms"] = round((finished_ts - started_ts) * 1000.0, 2)
            job["error"] = str(e)
            job["error_code"] = "autonomy_job_error"
            job["traceback"] = traceback.format_exc(limit=12)
            feedback_job = dict(job)
            await _prune_autonomy_jobs()
        if feedback_job is not None:
            await _emit_cron_chat_feedback_event(feedback_job)
        log_error(f"[Admin-API-Autonomy] Job failed job_id={job_id}: {e}")
    finally:
        _autonomy_job_tasks.pop(job_id, None)


async def _cancel_autonomy_job_locked(job: Dict[str, Any]) -> Dict[str, Any]:
    status = str(job.get("status") or "")
    now_ts = time.time()
    job_id = str(job.get("job_id") or "")

    if status in {"succeeded", "failed", "cancelled"}:
        return _public_autonomy_job_view(job)

    if status == "queued":
        job["status"] = "cancelled"
        job["phase"] = "cancelled_before_start"
        job["finished_at"] = _iso_now()
        job["finished_ts"] = now_ts
        job["duration_ms"] = 0.0
        job["error"] = "cancelled_by_user"
        job["error_code"] = "cancelled"
    else:
        job["status"] = "cancel_requested"
        job["phase"] = "cancel_requested"
        job["cancel_requested_at"] = _iso_now()
        _set_autonomy_job_phase(job, "cancel_requested", now_ts)

    task = _autonomy_job_tasks.get(job_id)
    if task and not task.done():
        task.cancel()
    await _prune_autonomy_jobs()
    return _public_autonomy_job_view(job)


async def _submit_autonomy_job_from_payload(
    payload: Dict[str, Any],
    retry_of: str | None = None,
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Create and enqueue autonomy job from normalized payload."""
    job = _create_autonomy_job(payload, retry_of=retry_of)
    if isinstance(metadata, dict) and metadata:
        job["metadata"] = dict(metadata)
    job_id = str(job.get("job_id"))

    async with _autonomy_jobs_lock:
        _autonomy_jobs[job_id] = job
        await _prune_autonomy_jobs()
        running_jobs, queued_jobs, queue_position = _autonomy_jobs_runtime_stats(job_id)

    task = asyncio.create_task(_run_autonomy_job(job_id))
    _autonomy_job_tasks[job_id] = task

    out = {
        "job_id": job_id,
        "status": "queued",
        "queue_position": queue_position,
        "queued_jobs": queued_jobs,
        "running_jobs": running_jobs,
        "max_concurrency": _AUTONOMY_JOB_MAX_CONCURRENCY,
        "timeout_s": _AUTONOMY_JOB_TIMEOUT_S,
        "poll_url": f"/api/autonomous/jobs/{job_id}",
        "cancel_url": f"/api/autonomous/jobs/{job_id}/cancel",
    }
    if retry_of:
        out["retry_of"] = str(retry_of)
    else:
        out["objective"] = payload.get("objective")
        out["conversation_id"] = payload.get("conversation_id")
        out["max_loops"] = payload.get("max_loops")
        out["retry_url"] = f"/api/autonomous/jobs/{job_id}/retry"
    return out


# ============================================================
# WORKSPACE ENDPOINTS — editierbare Einträge (sql-memory, workspace_entries)
# ============================================================

@app.get("/api/workspace")
async def workspace_list(conversation_id: str = None, limit: int = 50):
    """List editable workspace entries from sql-memory (workspace_entries table)."""
    try:
        args = {"limit": limit}
        if conversation_id:
            args["conversation_id"] = conversation_id
        # workspace_list routes to sql-memory (not Fast-Lane after Commit 1)
        result = await _hub_call_tool("workspace_list", args)
        if isinstance(result, dict):
            sc = result.get("structuredContent", result)
            entries = sc.get("entries", [])
            return JSONResponse({"entries": entries, "count": len(entries)})
        return JSONResponse({"entries": [], "count": 0})
    except Exception as e:
        log_error(f"[Workspace] List error: {e}")
        return JSONResponse({"error": str(e), "entries": [], "count": 0}, status_code=500)


@app.get("/api/workspace/{entry_id}")
async def workspace_get(entry_id: int):
    """Get a single workspace entry from sql-memory."""
    try:
        result = await _hub_call_tool("workspace_get", {"entry_id": entry_id})
        if isinstance(result, dict) and result.get("error"):
            return JSONResponse(result, status_code=404)
        return JSONResponse(result if isinstance(result, dict) else {"error": "Not found"})
    except Exception as e:
        log_error(f"[Workspace] Get error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.put("/api/workspace/{entry_id}")
async def workspace_update(entry_id: int, request: Request):
    """Update a workspace entry's content in sql-memory."""
    try:
        data = await request.json()
        content = data.get("content", "")
        if not content:
            return JSONResponse({"error": "content is required"}, status_code=400)
        result = await _hub_call_tool("workspace_update", {"entry_id": entry_id, "content": content})
        if isinstance(result, dict):
            sc = result.get("structuredContent", result)
            return JSONResponse({"updated": bool(sc.get("updated", sc.get("success", False)))})
        return JSONResponse({"updated": False})
    except Exception as e:
        log_error(f"[Workspace] Update error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/api/workspace/{entry_id}")
async def workspace_delete(entry_id: int):
    """Delete a workspace entry from sql-memory."""
    try:
        result = await _hub_call_tool("workspace_delete", {"entry_id": entry_id})
        if isinstance(result, dict):
            sc = result.get("structuredContent", result)
            return JSONResponse({"deleted": bool(sc.get("deleted", sc.get("success", False)))})
        return JSONResponse({"deleted": False})
    except Exception as e:
        log_error(f"[Workspace] Delete error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ============================================================
# WORKSPACE-EVENTS ENDPOINT — read-only telemetry (Fast-Lane, workspace_events)
# ============================================================

@app.get("/api/workspace-events")
async def workspace_events_list(
    conversation_id: str = None,
    event_type: str = None,
    limit: int = 50,
):
    """List internal workspace events (read-only telemetry from workspace_events table)."""

    def _extract_events_payload(result_obj):
        # Fast-Lane ToolResult path
        if hasattr(result_obj, "content"):
            content = result_obj.content
            if isinstance(content, list):
                return content
            if isinstance(content, dict):
                return (
                    content.get("events")
                    or content.get("content")
                    or content.get("structuredContent", {}).get("events", [])
                )
            if isinstance(content, str):
                try:
                    parsed = json.loads(content)
                except Exception:
                    parsed = None
                if isinstance(parsed, list):
                    return parsed
                if isinstance(parsed, dict):
                    return (
                        parsed.get("events")
                        or parsed.get("content")
                        or parsed.get("structuredContent", {}).get("events", [])
                    )

        # Generic dict payload path (MCP HTTP/SSE adapters)
        if isinstance(result_obj, dict):
            structured = result_obj.get("structuredContent", {})
            payload = (
                result_obj.get("events")
                or result_obj.get("content")
                or (structured.get("events") if isinstance(structured, dict) else None)
                or []
            )
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    payload = []
            return payload

        # Legacy direct list path
        if isinstance(result_obj, list):
            return result_obj

        return []

    try:
        args: dict = {"limit": limit}
        if conversation_id:
            args["conversation_id"] = conversation_id
        if event_type:
            args["event_type"] = event_type
        result = await _hub_call_tool("workspace_event_list", args)
        events = _extract_events_payload(result)
        if not isinstance(events, list):
            events = []
        return JSONResponse({"events": events, "count": len(events)})
    except Exception as e:
        log_error(f"[WorkspaceEvents] List error: {e}")
        return JSONResponse({"error": str(e), "events": [], "count": 0}, status_code=500)


# ============================================================
# CHAT ENDPOINT (From lobechat-adapter)
# ============================================================


@app.post("/api/chat/deep-jobs")
async def chat_deep_jobs(request: Request):
    """
    Submit a deep-mode chat request as async background job.
    Always forces:
      - response_mode=deep
      - stream=false
    """
    raw_data = await request.json()
    messages = raw_data.get("messages")
    if not isinstance(messages, list) or not messages:
        return JSONResponse({"error": "messages[] is required"}, status_code=400)

    job_id = uuid.uuid4().hex
    job = {
        "job_id": job_id,
        "status": "queued",
        "model": raw_data.get("model", ""),
        "conversation_id": raw_data.get("conversation_id") or raw_data.get("session_id") or "global",
        "created_at": _iso_now(),
        "created_ts": time.time(),
        "started_at": None,
        "finished_at": None,
        "duration_ms": None,
        "queue_wait_ms": None,
        "timeout_s": _DEEP_JOB_TIMEOUT_S,
        "phase": "queued",
        "phase_timings_ms": {},
        "last_update_at": _iso_now(),
        "last_update_ts": time.time(),
        "cancel_requested_at": None,
        "result": None,
        "error": None,
        "error_code": None,
        "traceback": None,
    }

    async with _deep_jobs_lock:
        _deep_jobs[job_id] = job
        await _prune_deep_jobs()
        running_jobs, queued_jobs, queue_position = _deep_jobs_runtime_stats(job_id)

    task = asyncio.create_task(_run_deep_job(job_id, raw_data))
    _deep_job_tasks[job_id] = task
    return JSONResponse(
        {
            "job_id": job_id,
            "status": "queued",
            "queue_position": queue_position,
            "queued_jobs": queued_jobs,
            "running_jobs": running_jobs,
            "max_concurrency": _DEEP_JOB_MAX_CONCURRENCY,
            "timeout_s": _DEEP_JOB_TIMEOUT_S,
            "poll_url": f"/api/chat/deep-jobs/{job_id}",
        },
        status_code=202,
    )


@app.get("/api/chat/deep-jobs/{job_id}")
async def chat_deep_job_status(job_id: str):
    """Get status/result of an async deep-mode chat job."""
    async with _deep_jobs_lock:
        job = _deep_jobs.get(job_id)
        if not job:
            return JSONResponse({"error": "job_not_found", "job_id": job_id}, status_code=404)
        return JSONResponse(_public_job_view(job))


@app.post("/api/chat/deep-jobs/{job_id}/cancel")
async def chat_deep_job_cancel(job_id: str):
    """Cancel queued/running deep job. Idempotent for terminal jobs."""
    async with _deep_jobs_lock:
        job = _deep_jobs.get(job_id)
        if not job:
            return JSONResponse({"error": "job_not_found", "job_id": job_id}, status_code=404)
        view = await _cancel_deep_job_locked(job)
    return JSONResponse(view)


@app.get("/api/chat/deep-jobs-stats")
async def chat_deep_jobs_stats():
    """Runtime telemetry snapshot for deep-job queue and execution state."""
    async with _deep_jobs_lock:
        now_ts = time.time()
        running_jobs, queued_jobs, _ = _deep_jobs_runtime_stats()
        by_status = _deep_jobs_status_summary()
        oldest_queue_age_s = round(_deep_jobs_oldest_queue_age_s(now_ts), 3)
        longest_running_s = round(_deep_jobs_longest_running_s(now_ts), 3)
        total_jobs = len(_deep_jobs)
    return JSONResponse(
        {
            "total_jobs": total_jobs,
            "running_jobs": running_jobs,
            "queued_jobs": queued_jobs,
            "max_concurrency": _DEEP_JOB_MAX_CONCURRENCY,
            "timeout_s": _DEEP_JOB_TIMEOUT_S,
            "oldest_queue_age_s": oldest_queue_age_s,
            "longest_running_s": longest_running_s,
            "by_status": by_status,
        }
    )

@app.post("/api/chat")
async def chat(request: Request):
    """
    Chat endpoint for Jarvis WebUI.
    
    Accepts LobeChat-compatible format:
    {
        "model": "llama3.1:8b",
        "messages": [...],
        "stream": true,
        "conversation_id": "user_1"
    }
    
    Returns streaming NDJSON with thinking process and response.
    """
    adapter = get_adapter()
    bridge = get_bridge()
    model = ""
    stream_requested = False
    input_chars = 0
    request_started_ts = time.time()
    output_provider = "unknown"
    
    try:
        raw_data = await request.json()
        model = str(raw_data.get('model', '') or "").strip()
        stream_requested = bool(raw_data.get('stream', False))
        input_chars = count_input_chars(raw_data.get("messages", []))
        request_started_ts = time.time()
        try:
            from config import get_output_provider

            output_provider = str(get_output_provider() or "unknown").strip().lower() or "unknown"
        except Exception:
            output_provider = "unknown"
        
        log_info(f"[Admin-API-Chat] /api/chat → model={model}, stream={stream_requested}")
        log_debug(f"[Admin-API-Chat] Raw request: {raw_data}")
        
        # 1. Transform Request using LobeChat adapter
        core_request = adapter.transform_request(raw_data)
        
        # 2. STREAMING MODE
        if stream_requested:
            async def stream_generator():
                """Generates NDJSON chunks for WebUI with Live Thinking."""
                import json as _json
                output_chars = 0
                done_reason = "stop"
                status_code = 200
                try:
                    async for chunk, is_done, metadata in bridge.process_stream(core_request):
                        created_at = datetime.utcnow().isoformat() + "Z"
                        chunk_type = metadata.get("type", "content")
                        
                        # Final stream event must remain terminal for clients/harness.
                        if is_done:
                            response_data = {
                                "model": model,
                                "created_at": created_at,
                                "message": {"role": "assistant", "content": ""},
                                "done": True,
                                "done_reason": metadata.get("done_reason", "stop"),
                                "memory_used": metadata.get("memory_used", False),
                            }
                            done_reason = str(metadata.get("done_reason", "stop") or "stop")
                            status_code = 500 if done_reason == "error" else 200
                            # Keep event type if present (e.g. {"type":"done"}).
                            if metadata.get("type"):
                                response_data["type"] = metadata.get("type")

                        # Live Thinking Stream
                        elif chunk_type == "thinking_stream":
                            response_data = {
                                "model": model,
                                "created_at": created_at,
                                "thinking_stream": metadata.get("thinking_chunk", ""),
                                "done": False,
                            }
                        
                        # Thinking Done (with Plan)
                        elif chunk_type == "thinking_done":
                            response_data = {
                                "model": model,
                                "created_at": created_at,
                                "thinking": metadata.get("thinking", {}),
                                "done": False,
                            }
                        
                        # Generic Event Handler (for all events with metadata)
                        elif chunk_type and chunk_type != "content" and metadata:
                            # Pass through events with all their metadata
                            response_data = {
                                "model": model,
                                "created_at": created_at,
                                **metadata,  # Include all metadata fields
                                "done": bool(metadata.get("done", False)),
                            }

                        # Content Chunk
                        else:
                            piece = str(chunk or "")
                            if piece:
                                output_chars += len(piece)
                            response_data = {
                                "model": model,
                                "created_at": created_at,
                                "message": {"role": "assistant", "content": piece},
                                "done": False,
                            }
                        
                        yield (_json.dumps(response_data) + "\n").encode("utf-8")
                        
                except Exception as e:
                    log_error(f"[Admin-API-Chat] Stream error: {e}")
                    done_reason = "error"
                    status_code = 500
                    error_data = {
                        "model": model,
                        "message": {"role": "assistant", "content": f"Fehler: {str(e)}"},
                        "done": True,
                        "done_reason": "error",
                    }
                    yield (_json.dumps(error_data) + "\n").encode("utf-8")
                finally:
                    try:
                        record_chat_turn(
                            model=model,
                            provider=output_provider,
                            input_chars=input_chars,
                            output_chars=output_chars,
                            latency_ms=(time.time() - request_started_ts) * 1000.0,
                            stream=True,
                            done_reason=done_reason,
                            status_code=status_code,
                        )
                    except Exception as metric_err:
                        log_warning(f"[Admin-API-Chat] session metrics update failed (stream): {metric_err}")
            
            return StreamingResponse(
                stream_generator(),
                media_type="application/x-ndjson"
            )
        
        # 3. NON-STREAMING MODE
        else:
            core_response = await bridge.process(core_request)
            response_data = adapter.transform_response(core_response)
            out_text = str(getattr(core_response, "content", "") or "")
            done_reason = str(getattr(core_response, "done_reason", "") or response_data.get("done_reason") or "stop")
            status_code = 500 if done_reason == "error" else 200
            try:
                record_chat_turn(
                    model=model,
                    provider=output_provider,
                    input_chars=input_chars,
                    output_chars=len(out_text),
                    latency_ms=(time.time() - request_started_ts) * 1000.0,
                    stream=False,
                    done_reason=done_reason,
                    status_code=status_code,
                )
            except Exception as metric_err:
                log_warning(f"[Admin-API-Chat] session metrics update failed (non-stream): {metric_err}")
            
            def iter_response():
                import json as _json
                yield (_json.dumps(response_data) + "\n").encode("utf-8")
            
            return StreamingResponse(
                iter_response(),
                media_type="application/x-ndjson"
            )
            
    except Exception as e:
        log_error(f"[Admin-API-Chat] Error: {e}")
        try:
            record_chat_turn(
                model=model or "unknown",
                provider=output_provider,
                input_chars=input_chars,
                output_chars=0,
                latency_ms=(time.time() - request_started_ts) * 1000.0,
                stream=stream_requested,
                done_reason="error",
                status_code=500,
            )
        except Exception as metric_err:
            log_warning(f"[Admin-API-Chat] session metrics update failed (error): {metric_err}")
        error_response = {
            "model": model if 'model' in locals() else "unknown",
            "message": {"role": "assistant", "content": f"Server-Fehler: {str(e)}"},
            "done": True,
            "done_reason": "error",
        }
        
        def iter_error():
            import json as _json
            yield (_json.dumps(error_response) + "\n").encode("utf-8")
        
        return StreamingResponse(
            iter_error(),
            media_type="application/x-ndjson"
        )


# ============================================================
# HEALTH & ROOT
# ============================================================

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": "jarvis-admin-api",
        "version": "1.1.0",
        "features": ["personas", "maintenance", "chat"]
    }


# ============================================================
# MODEL LIST ENDPOINT
# ============================================================

_MODEL_PROVIDER_ORDER = {"ollama": 0, "ollama_cloud": 1, "openai": 2, "anthropic": 3}
_OPENAI_MODEL_PRESETS = [
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4o",
    "gpt-4o-mini",
    "o3",
    "o3-mini",
]
_ANTHROPIC_MODEL_PRESETS = [
    "claude-sonnet-4-5",
    "claude-3-7-sonnet-latest",
    "claude-3-5-haiku-latest",
]
_OLLAMA_CLOUD_MODEL_PRESETS = [
    "llama3.3",
    "llama3.2",
    "qwen2.5",
    "mistral-small3.1",
    "deepseek-r1",
]


def _dedupe_model_names(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in items:
        name = str(raw or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def _parse_model_list_env(env_key: str, defaults: List[str]) -> List[str]:
    raw = str(os.getenv(env_key, "")).strip()
    if not raw:
        return _dedupe_model_names(defaults)
    values = [part.strip() for part in raw.split(",")]
    parsed = _dedupe_model_names(values)
    return parsed or _dedupe_model_names(defaults)


async def _fetch_tags_models(endpoint: str, headers: Dict[str, str] | None = None) -> List[Dict[str, Any]]:
    base = str(endpoint or "").strip().rstrip("/")
    if not base:
        return []
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(f"{base}/api/tags", headers=headers or None)
            resp.raise_for_status()
            payload = resp.json() if resp.content else {}
    except Exception:
        return []
    rows = payload.get("models", []) if isinstance(payload, dict) else []
    return rows if isinstance(rows, list) else []


def _normalize_provider_name(raw: str) -> str:
    value = str(raw or "").strip().lower()
    if value in _MODEL_PROVIDER_ORDER:
        return value
    return "ollama"


@app.get("/api/models/catalog")
async def models_catalog():
    """
    Provider-aware model catalog for the chat quick selector.
    """
    from config import OLLAMA_BASE
    from core.llm_provider_client import _resolve_cloud_api_key
    from utils.model_settings import ALLOWED_MODEL_KEYS, get_effective_model_settings
    from utils.role_endpoint_resolver import resolve_ollama_base_endpoint
    from utils.settings import settings as runtime_settings

    persisted = {
        k: v
        for k, v in getattr(runtime_settings, "settings", {}).items()
        if k in ALLOWED_MODEL_KEYS
    }
    effective = get_effective_model_settings(persisted)
    selected_model = str(effective.get("OUTPUT_MODEL", {}).get("value") or "").strip()
    selected_provider = _normalize_provider_name(
        effective.get("OUTPUT_PROVIDER", {}).get("value") or "ollama"
    )

    rows: List[Dict[str, Any]] = []
    seen = set()

    def add_entry(
        *,
        name: str,
        provider: str,
        source: str,
        size: int | None = None,
    ) -> None:
        model_name = str(name or "").strip()
        provider_name = _normalize_provider_name(provider)
        if not model_name:
            return
        key = f"{provider_name}::{model_name.lower()}"
        if key in seen:
            return
        seen.add(key)
        item: Dict[str, Any] = {
            "name": model_name,
            "provider": provider_name,
            "source": str(source or "").strip() or "unknown",
            "selected": bool(
                model_name.lower() == selected_model.lower()
                and provider_name == selected_provider
            ),
        }
        if size is not None and int(size) > 0:
            item["size"] = int(size)
        rows.append(item)

    local_endpoint = resolve_ollama_base_endpoint(default_endpoint=OLLAMA_BASE)
    local_models = await _fetch_tags_models(local_endpoint)
    for item in local_models:
        if isinstance(item, dict):
            add_entry(
                name=str(item.get("name") or "").strip(),
                provider="ollama",
                source="local",
                size=int(item.get("size") or 0),
            )
        else:
            add_entry(name=str(item), provider="ollama", source="local")

    cloud_base = str(
        os.getenv("OLLAMA_CLOUD_BASE", os.getenv("OLLAMA_API_BASE", "https://ollama.com"))
    ).strip().rstrip("/")
    cloud_key = await _resolve_cloud_api_key("ollama_cloud")
    cloud_headers = {"Authorization": f"Bearer {cloud_key}"} if cloud_key else {}
    cloud_models = await _fetch_tags_models(cloud_base, headers=cloud_headers)
    for item in cloud_models:
        if isinstance(item, dict):
            add_entry(
                name=str(item.get("name") or "").strip(),
                provider="ollama_cloud",
                source="cloud",
                size=int(item.get("size") or 0),
            )
        else:
            add_entry(name=str(item), provider="ollama_cloud", source="cloud")

    for model_name in _parse_model_list_env("OLLAMA_CLOUD_MODEL_PRESETS", _OLLAMA_CLOUD_MODEL_PRESETS):
        add_entry(name=model_name, provider="ollama_cloud", source="preset")

    for model_name in _parse_model_list_env("OPENAI_MODEL_PRESETS", _OPENAI_MODEL_PRESETS):
        add_entry(name=model_name, provider="openai", source="preset")

    for model_name in _parse_model_list_env("ANTHROPIC_MODEL_PRESETS", _ANTHROPIC_MODEL_PRESETS):
        add_entry(name=model_name, provider="anthropic", source="preset")

    if selected_model:
        add_entry(name=selected_model, provider=selected_provider, source="configured")

    rows.sort(
        key=lambda item: (
            0 if item.get("selected") else 1,
            _MODEL_PROVIDER_ORDER.get(str(item.get("provider") or ""), 99),
            str(item.get("name") or "").lower(),
        )
    )

    return JSONResponse(
        {
            "models": rows,
            "effective": {
                "OUTPUT_MODEL": selected_model,
                "OUTPUT_PROVIDER": selected_provider,
            },
            "providers": list(_MODEL_PROVIDER_ORDER.keys()),
        }
    )


@app.get("/api/tags")
async def tags():
    """
    Ollama /api/tags Endpoint.
    Returns available models from Ollama.
    
    WebUI queries this to display the model list.
    We forward the request to the actual Ollama server.
    """
    from config import OLLAMA_BASE
    from utils.role_endpoint_resolver import resolve_ollama_base_endpoint
    
    try:
        endpoint = resolve_ollama_base_endpoint(default_endpoint=OLLAMA_BASE)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{endpoint}/api/tags")
            resp.raise_for_status()
            return JSONResponse(resp.json())
    except Exception as e:
        log_error(f"[Admin-API-Tags] Error fetching models: {e}")
        # Fallback: Empty list
        return JSONResponse({"models": []})


@app.get("/api/tools")
async def tools():
    """
    WebUI-friendly tools overview endpoint.

    Response shape:
    {
      "total_tools": int,
      "total_mcps": int,
      "mcps": [{name, online, transport, tools_count, description, enabled, detected_format, url}],
      "tools": [{name, description, mcp_name, inputSchema}]
    }
    """
    from mcp.hub import get_hub

    try:
        hub = get_hub()
        hub.initialize()

        mcps = hub.list_mcps() or []
        tools = hub.list_tools() or []

        normalized_mcps = []
        for mcp in mcps:
            if not isinstance(mcp, dict):
                continue
            normalized_mcps.append({
                "name": str(mcp.get("name", "")).strip(),
                "online": bool(mcp.get("online", False)),
                "transport": str(mcp.get("transport", "")).strip(),
                "tools_count": int(mcp.get("tools_count", 0) or 0),
                "description": str(mcp.get("description", "")).strip(),
                "enabled": bool(mcp.get("enabled", False)),
                "detected_format": mcp.get("detected_format"),
                "url": str(mcp.get("url", "")).strip(),
            })

        normalized_tools = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            name = str(tool.get("name", "")).strip()
            if not name:
                continue
            normalized_tools.append({
                "name": name,
                "description": str(tool.get("description", "")).strip(),
                "mcp_name": hub.get_mcp_for_tool(name) or "unknown",
                "inputSchema": tool.get("inputSchema", {}) if isinstance(tool.get("inputSchema", {}), dict) else {},
            })

        normalized_mcps.sort(key=lambda x: x.get("name", ""))
        normalized_tools.sort(key=lambda x: x.get("name", ""))

        return JSONResponse({
            "total_tools": len(normalized_tools),
            "total_mcps": len(normalized_mcps),
            "mcps": normalized_mcps,
            "tools": normalized_tools,
        })
    except Exception as e:
        log_error(f"[Admin-API-Tools] Error fetching tools: {e}")
        return JSONResponse(
            {
                "total_tools": 0,
                "total_mcps": 0,
                "mcps": [],
                "tools": [],
                "error": str(e),
            },
            status_code=500,
        )


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Jarvis Admin API",
        "version": "1.2.0",
        "docs": "/docs",
        "health": "/health",
        "endpoints": {
            "personas": "/api/personas",
            "maintenance": "/api/maintenance",
            "chat": "/api/chat",
            "autonomous": "/api/autonomous",
            "autonomous_jobs": "/api/autonomous/jobs",
            "autonomy_cron": "/api/autonomy/cron/jobs",
            "models": "/api/tags",
            "model_catalog": "/api/models/catalog",
            "tools": "/api/tools",
            "runtime_session": "/api/runtime/session",
            "mcp_hub": {
                "tools_call": "/mcp (POST tools/call)",
                "tools_list": "/mcp (POST tools/list)",
                "status": "/mcp/status",
                "tools": "/mcp/tools",
                "refresh": "/mcp/refresh"
            },
            "mcp_installer": "/api/mcp"
        }
    }


@app.post("/api/autonomous/jobs")
async def autonomous_job_submit(request: Request):
    """
    Submit autonomous objective as async background job.
    Body: {objective, conversation_id, max_loops?}
    """
    data = await request.json()
    payload, error_code, error = _normalize_autonomy_request(data)
    if error_code:
        return JSONResponse({"error_code": error_code, "error": error}, status_code=400)
    result = await _submit_autonomy_job_from_payload(payload)
    return JSONResponse(result, status_code=202)


@app.get("/api/autonomous/jobs/{job_id}")
async def autonomous_job_status(job_id: str):
    """Get status/result of autonomous async job."""
    async with _autonomy_jobs_lock:
        job = _autonomy_jobs.get(job_id)
        if not job:
            return JSONResponse({"error": "job_not_found", "job_id": job_id}, status_code=404)
        return JSONResponse(_public_autonomy_job_view(job))


@app.post("/api/autonomous/jobs/{job_id}/cancel")
async def autonomous_job_cancel(job_id: str):
    """Cancel queued/running autonomous job. Idempotent for terminal jobs."""
    async with _autonomy_jobs_lock:
        job = _autonomy_jobs.get(job_id)
        if not job:
            return JSONResponse({"error": "job_not_found", "job_id": job_id}, status_code=404)
        view = await _cancel_autonomy_job_locked(job)
    return JSONResponse(view)


@app.post("/api/autonomous/jobs/{job_id}/retry")
async def autonomous_job_retry(job_id: str):
    """Retry failed/cancelled autonomous job by cloning original payload."""
    async with _autonomy_jobs_lock:
        old = _autonomy_jobs.get(job_id)
        if not old:
            return JSONResponse({"error": "job_not_found", "job_id": job_id}, status_code=404)

        old_status = str(old.get("status") or "")
        if old_status not in {"failed", "cancelled"}:
            return JSONResponse(
                {
                    "error_code": "job_not_retryable",
                    "error": "Only failed or cancelled jobs can be retried",
                    "job_id": job_id,
                    "status": old_status,
                },
                status_code=409,
            )

        payload = dict(old.get("payload") or {})

    result = await _submit_autonomy_job_from_payload(payload, retry_of=job_id)
    return JSONResponse(result, status_code=202)


@app.get("/api/autonomous/jobs-stats")
async def autonomous_jobs_stats():
    """Runtime telemetry snapshot for autonomous job queue and execution state."""
    async with _autonomy_jobs_lock:
        now_ts = time.time()
        running_jobs, queued_jobs, _ = _autonomy_jobs_runtime_stats()
        by_status = _autonomy_jobs_status_summary()
        oldest_queue_age_s = round(_autonomy_jobs_oldest_queue_age_s(now_ts), 3)
        longest_running_s = round(_autonomy_jobs_longest_running_s(now_ts), 3)
        total_jobs = len(_autonomy_jobs)
    return JSONResponse(
        {
            "total_jobs": total_jobs,
            "running_jobs": running_jobs,
            "queued_jobs": queued_jobs,
            "max_concurrency": _AUTONOMY_JOB_MAX_CONCURRENCY,
            "timeout_s": _AUTONOMY_JOB_TIMEOUT_S,
            "oldest_queue_age_s": oldest_queue_age_s,
            "longest_running_s": longest_running_s,
            "by_status": by_status,
        }
    )


def _get_autonomy_cron_scheduler() -> AutonomyCronScheduler | None:
    if _autonomy_cron_scheduler is not None:
        return _autonomy_cron_scheduler
    runtime = get_autonomy_cron_runtime_scheduler()
    if runtime is None:
        return None
    return runtime


async def _submit_autonomy_job_from_cron(
    payload: Dict[str, Any],
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    normalized, error_code, error = _normalize_autonomy_request(payload)
    if error_code:
        raise RuntimeError(f"invalid_cron_payload:{error_code}:{error}")
    return await _submit_autonomy_job_from_payload(normalized, metadata=metadata)


def _cron_exception_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, CronPolicyError):
        body: Dict[str, Any] = {"error_code": exc.error_code, "error": str(exc)}
        if exc.details:
            body["details"] = exc.details
        return JSONResponse(body, status_code=exc.status_code)
    if isinstance(exc, ValueError):
        return JSONResponse(
            {"error_code": "invalid_cron_job_payload", "error": str(exc)},
            status_code=400,
        )
    return JSONResponse(
        {"error_code": "cron_internal_error", "error": "Cron operation failed"},
        status_code=500,
    )


@app.get("/api/autonomy/cron/status")
async def autonomy_cron_status():
    scheduler = _get_autonomy_cron_scheduler()
    if not scheduler:
        return JSONResponse(
            {"error_code": "autonomy_cron_unavailable", "error": "Autonomy cron scheduler is not initialized"},
            status_code=503,
        )
    return JSONResponse(await scheduler.get_status())


@app.get("/api/autonomy/cron/jobs")
async def autonomy_cron_jobs_list():
    scheduler = _get_autonomy_cron_scheduler()
    if not scheduler:
        return JSONResponse(
            {"error_code": "autonomy_cron_unavailable", "error": "Autonomy cron scheduler is not initialized"},
            status_code=503,
        )
    jobs = await scheduler.list_jobs()
    return JSONResponse({"jobs": jobs, "count": len(jobs)})


@app.post("/api/autonomy/cron/validate")
async def autonomy_cron_validate(request: Request):
    data = await request.json()
    cron_expr = str((data or {}).get("cron") or "").strip()
    if not cron_expr:
        return JSONResponse({"valid": False, "error_code": "missing_cron", "error": "cron is required"}, status_code=400)
    try:
        from core.autonomy.cron_scheduler import validate_cron_expression

        validated = validate_cron_expression(cron_expr)
        return JSONResponse(validated)
    except Exception as exc:
        return JSONResponse(
            {"valid": False, "error_code": "invalid_cron_expression", "error": str(exc)},
            status_code=400,
        )


@app.post("/api/autonomy/cron/jobs")
async def autonomy_cron_jobs_create(request: Request):
    scheduler = _get_autonomy_cron_scheduler()
    if not scheduler:
        return JSONResponse(
            {"error_code": "autonomy_cron_unavailable", "error": "Autonomy cron scheduler is not initialized"},
            status_code=503,
        )
    data = await request.json()
    try:
        created = await scheduler.create_job(data if isinstance(data, dict) else {})
        return JSONResponse(created, status_code=201)
    except Exception as exc:
        return _cron_exception_response(exc)


@app.get("/api/autonomy/cron/jobs/{cron_job_id}")
async def autonomy_cron_job_get(cron_job_id: str):
    scheduler = _get_autonomy_cron_scheduler()
    if not scheduler:
        return JSONResponse(
            {"error_code": "autonomy_cron_unavailable", "error": "Autonomy cron scheduler is not initialized"},
            status_code=503,
        )
    job = await scheduler.get_job(cron_job_id)
    if not job:
        return JSONResponse({"error_code": "cron_job_not_found", "error": "Cron job not found"}, status_code=404)
    return JSONResponse(job)


@app.put("/api/autonomy/cron/jobs/{cron_job_id}")
async def autonomy_cron_job_update(cron_job_id: str, request: Request):
    scheduler = _get_autonomy_cron_scheduler()
    if not scheduler:
        return JSONResponse(
            {"error_code": "autonomy_cron_unavailable", "error": "Autonomy cron scheduler is not initialized"},
            status_code=503,
        )
    data = await request.json()
    try:
        updated = await scheduler.update_job(cron_job_id, data if isinstance(data, dict) else {})
    except Exception as exc:
        return _cron_exception_response(exc)
    if not updated:
        return JSONResponse({"error_code": "cron_job_not_found", "error": "Cron job not found"}, status_code=404)
    return JSONResponse(updated)


@app.delete("/api/autonomy/cron/jobs/{cron_job_id}")
async def autonomy_cron_job_delete(cron_job_id: str):
    scheduler = _get_autonomy_cron_scheduler()
    if not scheduler:
        return JSONResponse(
            {"error_code": "autonomy_cron_unavailable", "error": "Autonomy cron scheduler is not initialized"},
            status_code=503,
        )
    deleted = await scheduler.delete_job(cron_job_id)
    if not deleted:
        return JSONResponse({"error_code": "cron_job_not_found", "error": "Cron job not found"}, status_code=404)
    return JSONResponse({"deleted": True, "cron_job_id": cron_job_id})


@app.post("/api/autonomy/cron/jobs/{cron_job_id}/pause")
async def autonomy_cron_job_pause(cron_job_id: str):
    scheduler = _get_autonomy_cron_scheduler()
    if not scheduler:
        return JSONResponse(
            {"error_code": "autonomy_cron_unavailable", "error": "Autonomy cron scheduler is not initialized"},
            status_code=503,
        )
    paused = await scheduler.pause_job(cron_job_id)
    if not paused:
        return JSONResponse({"error_code": "cron_job_not_found", "error": "Cron job not found"}, status_code=404)
    return JSONResponse(paused)


@app.post("/api/autonomy/cron/jobs/{cron_job_id}/resume")
async def autonomy_cron_job_resume(cron_job_id: str):
    scheduler = _get_autonomy_cron_scheduler()
    if not scheduler:
        return JSONResponse(
            {"error_code": "autonomy_cron_unavailable", "error": "Autonomy cron scheduler is not initialized"},
            status_code=503,
        )
    resumed = await scheduler.resume_job(cron_job_id)
    if not resumed:
        return JSONResponse({"error_code": "cron_job_not_found", "error": "Cron job not found"}, status_code=404)
    return JSONResponse(resumed)


@app.post("/api/autonomy/cron/jobs/{cron_job_id}/run-now")
async def autonomy_cron_job_run_now(cron_job_id: str):
    scheduler = _get_autonomy_cron_scheduler()
    if not scheduler:
        return JSONResponse(
            {"error_code": "autonomy_cron_unavailable", "error": "Autonomy cron scheduler is not initialized"},
            status_code=503,
        )
    try:
        scheduled = await scheduler.run_now(cron_job_id, reason="manual")
    except Exception as exc:
        return _cron_exception_response(exc)
    if not scheduled:
        return JSONResponse({"error_code": "cron_job_not_found", "error": "Cron job not found"}, status_code=404)
    return JSONResponse(scheduled, status_code=202)


@app.get("/api/autonomy/cron/queue")
async def autonomy_cron_queue():
    scheduler = _get_autonomy_cron_scheduler()
    if not scheduler:
        return JSONResponse(
            {"error_code": "autonomy_cron_unavailable", "error": "Autonomy cron scheduler is not initialized"},
            status_code=503,
        )
    return JSONResponse(await scheduler.get_queue_snapshot())


# ============================================================
# STARTUP & SHUTDOWN
# ============================================================
@app.post("/api/autonomous")
async def autonomous_objective(request: Request):
    """
    Execute autonomous objective via Master Orchestrator
    
    Request body:
    {
        "objective": "Analyze user feedback and create summary report",
        "conversation_id": "conv_123",
        "max_loops": 5  // optional, default: 10
    }
    """
    try:
        data = await request.json()
        payload, error_code, error = _normalize_autonomy_request(data)
        if error_code:
            return {"success": False, "error_code": error_code, "error": error}

        objective = payload.get("objective")
        conversation_id = payload.get("conversation_id")
        max_loops = payload.get("max_loops")
        
        log_info(f"[API] Autonomous objective requested: {objective}")
        
        # Call Master Orchestrator via Pipeline
        bridge = get_bridge()
        result = await bridge.orchestrator.execute_autonomous_objective(
            objective=objective,
            conversation_id=conversation_id,
            max_loops=max_loops
        )
        
        log_info(f"[API] Autonomous objective completed: {result['success']}")
        
        return result
        
    except Exception as e:
        log_error(f"[API] Autonomous objective failed: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            "success": False,
            "error_code": "autonomous_endpoint_error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }

@app.on_event("startup")
async def startup_event():
    global _autonomy_cron_scheduler
    import asyncio
    logger.info("=" * 60)
    logger.info("Jarvis Admin API Starting...")
    logger.info("=" * 60)
    logger.info("Service: jarvis-admin-api")
    logger.info("Port: 8200")
    logger.info("Features: Personas, Maintenance, Chat, MCP Hub, Skill-Server")
    logger.info("MCP Hub: /mcp (tools/list, tools/call)")
    logger.info("Docs: http://localhost:8200/docs")
    logger.info("=" * 60)

    # Daily Auto-Summarize: läuft täglich um 04:00 Uhr
    from core.context_compressor import run_daily_summary_loop, summarize_yesterday
    asyncio.create_task(run_daily_summary_loop())
    # Catch-up run on startup (idempotent via .daily_summary_status.json)
    async def _daily_summary_catchup():
        try:
            ran = await summarize_yesterday(force=False)
            logger.info(f"[Startup] Daily summary catch-up ran={ran}")
        except Exception as e:
            logger.warning(f"[Startup] Daily summary catch-up failed: {e}")
    asyncio.create_task(_daily_summary_catchup())

    # Digest Worker — inline mode (Finding #3: wire DIGEST_RUN_MODE=inline)
    # Double-start guard: check for an existing digest-inline thread before spawning.
    # Mutual exclusion between pipeline runs is enforced by DigestLock regardless.
    # Rollback: DIGEST_RUN_MODE=off (default) → no thread started.
    try:
        import config as _cfg
        if _cfg.get_digest_run_mode() == "inline":
            import threading as _threading
            from core.digest.worker import DigestWorker as _DigestWorker
            _existing = [
                _t for _t in _threading.enumerate()
                if _t.name == "digest-inline" and _t.is_alive()
            ]
            if _existing:
                logger.warning("[DigestWorker] inline already running — skip double-start")
            else:
                _w = _DigestWorker()
                _t = _threading.Thread(
                    target=_w.run_loop, daemon=True, name="digest-inline"
                )
                _t.start()
                logger.info(
                    "[DigestWorker] inline mode starting — mutual exclusion via DigestLock"
                )
    except Exception as _e:
        logger.warning(f"[DigestWorker] inline startup error (fail-open): {_e}")

    # JIT-only hardening: warn if active digest pipeline loads CSV on every build
    try:
        if _cfg.get_digest_enable() and not _cfg.get_typedstate_csv_jit_only():
            if _cfg.get_digest_jit_warn_on_disabled():
                logger.warning(
                    "[DigestWorker] WARNING: TYPEDSTATE_CSV_JIT_ONLY=false with "
                    "active digest pipeline — CSV loaded on every context build; "
                    "set TYPEDSTATE_CSV_JIT_ONLY=true for production"
                )
    except Exception:
        pass

    logger.info("[Startup] Daily summary loop scheduled")

    # Explicit Commander store init (no import side effects in blueprint_store anymore).
    try:
        from container_commander.blueprint_store import ensure_store_initialized
        await asyncio.to_thread(ensure_store_initialized)
    except Exception as e:
        logger.warning(f"[Startup] Commander store init fehlgeschlagen (non-critical): {e}")

    # Phase 2: Backfill exec policies for existing blueprints (idempotent)
    try:
        from container_commander.blueprint_store import backfill_exec_policies
        await asyncio.to_thread(backfill_exec_policies)
    except Exception as e:
        logger.warning(f"[Startup] Exec policy backfill fehlgeschlagen (non-critical): {e}")

    # Blueprint Graph Sync: Blueprints aus SQLite → memory graph (_blueprints conv_id)
    async def _sync_blueprints():
        try:
            from container_commander.blueprint_store import sync_blueprints_to_graph
            count = await asyncio.to_thread(sync_blueprints_to_graph)
            logger.info(f"[Startup] {count} Blueprints in Graph gesynct")
        except Exception as e:
            logger.warning(f"[Startup] Blueprint-Graph-Sync fehlgeschlagen (non-critical): {e}")

    asyncio.create_task(_sync_blueprints())

    # Phase 4: Container Runtime Recovery — rebuild _active + rearm TTL timers
    # Runs in a background thread so Docker unavailability doesn't block startup.
    async def _recover_containers():
        try:
            from container_commander.engine import recover_runtime_state
            result = await asyncio.to_thread(recover_runtime_state)
            logger.info(f"[Startup] Container recovery: {result}")
        except Exception as e:
            logger.warning(f"[Startup] Container recovery failed (non-critical): {e}")

    asyncio.create_task(_recover_containers())

    # Home identity bootstrap + deterministic status check.
    async def _check_home_identity():
        try:
            from container_commander.engine import list_containers
            from utils.trion_home_identity import (
                load_home_identity,
                evaluate_home_status,
            )

            await asyncio.to_thread(load_home_identity, create_if_missing=True)
            containers = await asyncio.to_thread(list_containers)
            status = await asyncio.to_thread(evaluate_home_status, containers)
            logger.info(
                "[Startup] Home identity status=%s error_code=%s home_container=%s",
                status.get("status", "unknown"),
                status.get("error_code", ""),
                status.get("home_container_id", ""),
            )
        except Exception as e:
            logger.warning(f"[Startup] Home identity check failed (non-critical): {e}")

    asyncio.create_task(_check_home_identity())

    # Autonomy Cron Scheduler (user/TRION managed cron jobs -> autonomy queue)
    try:
        _autonomy_cron_scheduler = AutonomyCronScheduler(
            state_path=get_autonomy_cron_state_path(),
            tick_s=get_autonomy_cron_tick_s(),
            max_concurrency=get_autonomy_cron_max_concurrency(),
            submit_cb=_submit_autonomy_job_from_cron,
            max_jobs=get_autonomy_cron_max_jobs(),
            max_jobs_per_conversation=get_autonomy_cron_max_jobs_per_conversation(),
            min_interval_s=get_autonomy_cron_min_interval_s(),
            max_pending_runs=get_autonomy_cron_max_pending_runs(),
            max_pending_runs_per_job=get_autonomy_cron_max_pending_runs_per_job(),
            manual_run_cooldown_s=get_autonomy_cron_manual_run_cooldown_s(),
            trion_safe_mode=get_autonomy_cron_trion_safe_mode(),
            trion_min_interval_s=get_autonomy_cron_trion_min_interval_s(),
            trion_max_loops=get_autonomy_cron_trion_max_loops(),
            trion_require_approval_for_risky=get_autonomy_cron_trion_require_approval_for_risky(),
            hardware_guard_enabled=get_autonomy_cron_hardware_guard_enabled(),
            hardware_cpu_max_percent=get_autonomy_cron_hardware_cpu_max_percent(),
            hardware_mem_max_percent=get_autonomy_cron_hardware_mem_max_percent(),
        )
        set_autonomy_cron_runtime_scheduler(_autonomy_cron_scheduler)
        await _autonomy_cron_scheduler.start()
        logger.info(
            "[Startup] Autonomy cron scheduler started tick_s=%s workers=%s state=%s "
            "max_jobs=%s min_interval_s=%s hw_guard=%s cpu_max=%s mem_max=%s",
            get_autonomy_cron_tick_s(),
            get_autonomy_cron_max_concurrency(),
            get_autonomy_cron_state_path(),
            get_autonomy_cron_max_jobs(),
            get_autonomy_cron_min_interval_s(),
            get_autonomy_cron_hardware_guard_enabled(),
            get_autonomy_cron_hardware_cpu_max_percent(),
            get_autonomy_cron_hardware_mem_max_percent(),
        )
    except Exception as e:
        _autonomy_cron_scheduler = None
        clear_autonomy_cron_runtime_scheduler()
        logger.warning(f"[Startup] Autonomy cron scheduler init failed (non-critical): {e}")

@app.on_event("shutdown")
async def shutdown_event():
    global _autonomy_cron_scheduler
    if _autonomy_cron_scheduler is not None:
        try:
            await _autonomy_cron_scheduler.stop()
        except Exception as e:
            logger.warning(f"[Shutdown] Autonomy cron scheduler stop failed: {e}")
        _autonomy_cron_scheduler = None
    clear_autonomy_cron_runtime_scheduler()
    logger.info("Jarvis Admin API Shutting down...")
