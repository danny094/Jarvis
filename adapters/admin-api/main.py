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
import requests
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
# WORKSPACE ENDPOINTS — editierbare Einträge (sql-memory, workspace_entries)
# ============================================================

@app.get("/api/workspace")
async def workspace_list(conversation_id: str = None, limit: int = 50):
    """List editable workspace entries from sql-memory (workspace_entries table)."""
    from mcp.hub import get_hub
    try:
        hub = get_hub()
        hub.initialize()
        args = {"limit": limit}
        if conversation_id:
            args["conversation_id"] = conversation_id
        # workspace_list routes to sql-memory (not Fast-Lane after Commit 1)
        result = hub.call_tool("workspace_list", args)
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
    from mcp.hub import get_hub
    try:
        hub = get_hub()
        hub.initialize()
        result = hub.call_tool("workspace_get", {"entry_id": entry_id})
        if isinstance(result, dict) and result.get("error"):
            return JSONResponse(result, status_code=404)
        return JSONResponse(result if isinstance(result, dict) else {"error": "Not found"})
    except Exception as e:
        log_error(f"[Workspace] Get error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.put("/api/workspace/{entry_id}")
async def workspace_update(entry_id: int, request: Request):
    """Update a workspace entry's content in sql-memory."""
    from mcp.hub import get_hub
    try:
        data = await request.json()
        content = data.get("content", "")
        if not content:
            return JSONResponse({"error": "content is required"}, status_code=400)
        hub = get_hub()
        hub.initialize()
        result = hub.call_tool("workspace_update", {"entry_id": entry_id, "content": content})
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
    from mcp.hub import get_hub
    try:
        hub = get_hub()
        hub.initialize()
        result = hub.call_tool("workspace_delete", {"entry_id": entry_id})
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
    from mcp.hub import get_hub
    try:
        hub = get_hub()
        hub.initialize()
        args: dict = {"limit": limit}
        if conversation_id:
            args["conversation_id"] = conversation_id
        if event_type:
            args["event_type"] = event_type
        result = hub.call_tool("workspace_event_list", args)
        # Fast-Lane ToolResult: .content is the list
        if hasattr(result, "content"):
            events = result.content if isinstance(result.content, list) else []
            return JSONResponse({"events": events, "count": len(events)})
        if isinstance(result, list):
            return JSONResponse({"events": result, "count": len(result)})
        return JSONResponse({"events": [], "count": 0})
    except Exception as e:
        log_error(f"[WorkspaceEvents] List error: {e}")
        return JSONResponse({"error": str(e), "events": [], "count": 0}, status_code=500)


# ============================================================
# CHAT ENDPOINT (From lobechat-adapter)
# ============================================================

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
                        
                        # Live Thinking Stream
                        if chunk_type == "thinking_stream":
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
                                "done": False,
                            }
                        
                        elif is_done:
                            response_data = {
                                "model": model,
                                "created_at": created_at,
                                "message": {"role": "assistant", "content": ""},
                                "done": True,
                                "done_reason": metadata.get("done_reason", "stop"),
                                "memory_used": metadata.get("memory_used", False),
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
    
    try:
        resp = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=10)
        resp.raise_for_status()
        return JSONResponse(resp.json())
    except Exception as e:
        log_error(f"[Admin-API-Tags] Error fetching models: {e}")
        # Fallback: Empty list
        return JSONResponse({"models": []})


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
    from core.context_compressor import run_daily_summary_loop
    asyncio.create_task(run_daily_summary_loop())

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
