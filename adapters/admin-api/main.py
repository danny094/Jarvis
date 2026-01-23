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
    description="Management API for Jarvis WebUI - Personas, Maintenance & Chat",
    version="1.1.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS Configuration for WebUI
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8400",
        "http://192.168.0.226:8400",
        "http://jarvis-webui:80"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
# Persona router has its own prefix defined in persona_routes.py
# Maintenance router needs explicit prefix
app.include_router(persona_router)
app.include_router(maintenance_router, prefix="/api/maintenance")
# app.include_router(sequential_router)  # REMOVED - old system  # 🆕 Sequential Thinking Live Monitoring


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
        "version": "1.1.0",
        "docs": "/docs",
        "health": "/health",
        "endpoints": {
            "personas": "/api/personas",
            "maintenance": "/api/maintenance",
            "chat": "/api/chat",
            "models": "/api/tags"
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
    logger.info("Features: Personas, Maintenance, Chat")
    logger.info("Docs: http://localhost:8200/docs")
    logger.info("=" * 60)

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Jarvis Admin API Shutting down...")
