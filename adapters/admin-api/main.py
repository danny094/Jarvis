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
import time
import traceback
import uuid
import httpx
from typing import Any, Dict
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
from utils.logger import log_info, log_error, log_debug
from config import get_deep_job_max_concurrency, get_deep_job_timeout_s

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

# Runtime telemetry (Phase 8 Operational — digest pipeline state)
from runtime_routes import router as runtime_router
app.include_router(runtime_router)

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
    
    try:
        raw_data = await request.json()
        model = raw_data.get('model', '')
        stream_requested = raw_data.get('stream', False)
        
        log_info(f"[Admin-API-Chat] /api/chat → model={model}, stream={stream_requested}")
        log_debug(f"[Admin-API-Chat] Raw request: {raw_data}")
        
        # 1. Transform Request using LobeChat adapter
        core_request = adapter.transform_request(raw_data)
        
        # 2. STREAMING MODE
        if stream_requested:
            async def stream_generator():
                """Generates NDJSON chunks for WebUI with Live Thinking."""
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
                            response_data = {
                                "model": model,
                                "created_at": created_at,
                                "message": {"role": "assistant", "content": chunk},
                                "done": False,
                            }
                        
                        yield (json.dumps(response_data) + "\n").encode("utf-8")
                        
                except Exception as e:
                    log_error(f"[Admin-API-Chat] Stream error: {e}")
                    error_data = {
                        "model": model,
                        "message": {"role": "assistant", "content": f"Fehler: {str(e)}"},
                        "done": True,
                        "done_reason": "error",
                    }
                    yield (json.dumps(error_data) + "\n").encode("utf-8")
            
            return StreamingResponse(
                stream_generator(),
                media_type="application/x-ndjson"
            )
        
        # 3. NON-STREAMING MODE
        else:
            core_response = await bridge.process(core_request)
            response_data = adapter.transform_response(core_response)
            
            def iter_response():
                yield (json.dumps(response_data) + "\n").encode("utf-8")
            
            return StreamingResponse(
                iter_response(),
                media_type="application/x-ndjson"
            )
            
    except Exception as e:
        log_error(f"[Admin-API-Chat] Error: {e}")
        error_response = {
            "model": model if 'model' in locals() else "unknown",
            "message": {"role": "assistant", "content": f"Server-Fehler: {str(e)}"},
            "done": True,
            "done_reason": "error",
        }
        
        def iter_error():
            yield (json.dumps(error_response) + "\n").encode("utf-8")
        
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
            "models": "/api/tags",
            "tools": "/api/tools",
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
        
        objective = data.get("objective")
        conversation_id = data.get("conversation_id")
        # Use stored master-settings default when caller omits max_loops
        if "max_loops" in data:
            max_loops = data["max_loops"]
        else:
            try:
                from settings_routes import load_master_settings as _lms
                max_loops = _lms().get("max_loops", 10)
            except Exception:
                max_loops = 10
        
        # Validation
        if not objective:
            return {"success": False, "error": "Missing 'objective' in request body"}
        
        if not conversation_id:
            return {"success": False, "error": "Missing 'conversation_id' in request body"}
        
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
            "error": str(e),
            "traceback": traceback.format_exc()
        }

@app.on_event("startup")
async def startup_event():
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

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Jarvis Admin API Shutting down...")
