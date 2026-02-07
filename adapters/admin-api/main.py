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


# ============================================================
# WORKSPACE ENDPOINTS (Agent Workspace CRUD)
# ============================================================

@app.get("/api/workspace")
async def workspace_list(conversation_id: str = None, limit: int = 50):
    """List workspace entries, optionally filtered by conversation."""
    from mcp.hub import get_hub
    try:
        hub = get_hub()
        hub.initialize()
        args = {"limit": limit}
        if conversation_id:
            args["conversation_id"] = conversation_id
        result = hub.call_tool("workspace_list", args)
        return JSONResponse(result if isinstance(result, dict) else {"entries": [], "count": 0})
    except Exception as e:
        log_error(f"[Workspace] List error: {e}")
        return JSONResponse({"error": str(e), "entries": [], "count": 0}, status_code=500)


@app.get("/api/workspace/{entry_id}")
async def workspace_get(entry_id: int):
    """Get a single workspace entry."""
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
    """Update a workspace entry's content."""
    from mcp.hub import get_hub
    try:
        data = await request.json()
        content = data.get("content", "")
        if not content:
            return JSONResponse({"error": "content is required"}, status_code=400)
        hub = get_hub()
        hub.initialize()
        result = hub.call_tool("workspace_update", {"entry_id": entry_id, "content": content})
        return JSONResponse(result if isinstance(result, dict) else {"updated": False})
    except Exception as e:
        log_error(f"[Workspace] Update error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/api/workspace/{entry_id}")
async def workspace_delete(entry_id: int):
    """Delete a workspace entry."""
    from mcp.hub import get_hub
    try:
        hub = get_hub()
        hub.initialize()
        result = hub.call_tool("workspace_delete", {"entry_id": entry_id})
        return JSONResponse(result if isinstance(result, dict) else {"deleted": False})
    except Exception as e:
        log_error(f"[Workspace] Delete error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


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

@app.on_event("startup")
async def startup_event():
    logger.info("=" * 60)
    logger.info("Jarvis Admin API Starting...")
    logger.info("=" * 60)
    logger.info("Service: jarvis-admin-api")
    logger.info("Port: 8200")
    logger.info("Features: Personas, Maintenance, Chat, MCP Hub, Skill-Server")
    logger.info("MCP Hub: /mcp (tools/list, tools/call)")
    logger.info("Docs: http://localhost:8200/docs")
    logger.info("=" * 60)

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Jarvis Admin API Shutting down...")
