# adapters/lobechat/main.py
"""
Standalone FastAPI Server für den LobeChat-Adapter.

Dieser Server emuliert die Ollama-API für LobeChat.
LobeChat trägt diese URL als "Ollama-Server" ein.

Endpoints:
- POST /api/chat     → Chat-Completion (wie Ollama)
- POST /api/generate → Text-Generation (wie Ollama)
- GET  /api/tags     → Model-Liste (wie Ollama)
- GET  /health       → Health-Check
"""

import json
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

import sys
import os

# Path-Setup für Imports aus dem Hauptprojekt
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from adapters.lobechat.adapter import get_adapter
from core.bridge import get_bridge
from mcp.endpoint import router as mcp_router
from utils.logger import log_info, log_error, log_debug


# FastAPI App
app = FastAPI(
    title="LobeChat Adapter + MCP Hub",
    description="Ollama-kompatible API für LobeChat → Core-Bridge + MCP Hub",
    version="1.1.0"
)

# CORS (LobeChat braucht das)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MCP Hub Endpoint einbinden
app.include_router(mcp_router)


@app.get("/health")
async def health():
    """Health-Check Endpoint."""
    return {"status": "ok", "adapter": "lobechat"}


@app.post("/api/chat")
async def chat(request: Request):
    """
    LobeChat /api/chat Endpoint.
    
    Empfängt Ollama-Format, transformiert zu CoreChatRequest,
    ruft Core-Bridge auf, transformiert Response zurück.
    
    Unterstützt echtes Streaming wenn stream=true!
    """
    adapter = get_adapter()
    bridge = get_bridge()
    
    try:
        raw_data = await request.json()
        model = raw_data.get('model', '')
        stream_requested = raw_data.get('stream', False)
        
        log_info(f"[LobeChat-Adapter] /api/chat → model={model}, stream={stream_requested}")
        log_debug(f"[LobeChat-Adapter] Raw request: {raw_data}")
        
        # 1. Transform Request
        core_request = adapter.transform_request(raw_data)
        
        # 2. STREAMING MODE
        if stream_requested:
            from datetime import datetime
            
            async def stream_generator():
                """Generiert NDJSON-Chunks für LobeChat."""
                try:
                    async for chunk, is_done, metadata in bridge.process_stream(core_request):
                        created_at = datetime.utcnow().isoformat() + "Z"
                        
                        if is_done:
                            # Final message
                            response_data = {
                                "model": model,
                                "created_at": created_at,
                                "message": {"role": "assistant", "content": ""},
                                "done": True,
                                "done_reason": metadata.get("done_reason", "stop"),
                            }
                        else:
                            # Chunk message
                            response_data = {
                                "model": model,
                                "created_at": created_at,
                                "message": {"role": "assistant", "content": chunk},
                                "done": False,
                            }
                        
                        yield (json.dumps(response_data) + "\n").encode("utf-8")
                        
                except Exception as e:
                    log_error(f"[LobeChat-Adapter] Stream error: {e}")
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
        
        # 3. NON-STREAMING MODE (original)
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
        log_error(f"[LobeChat-Adapter] Error: {e}")
        error_response = adapter.transform_error(e)
        
        def iter_error():
            yield (json.dumps(error_response) + "\n").encode("utf-8")
        
        return StreamingResponse(
            iter_error(),
            media_type="application/x-ndjson",
            status_code=500
        )


@app.post("/api/generate")
async def generate(request: Request):
    """
    Ollama /api/generate Endpoint.
    Für direkte Prompt-Completion (ohne Chat-History).
    """
    adapter = get_adapter()
    bridge = get_bridge()
    
    try:
        raw_data = await request.json()
        log_info(f"[LobeChat-Adapter] /api/generate → model={raw_data.get('model')}")
        
        # Generate-Format zu Chat-Format konvertieren
        prompt = raw_data.get("prompt", "")
        chat_data = {
            "model": raw_data.get("model"),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": raw_data.get("temperature"),
            "top_p": raw_data.get("top_p"),
            "max_tokens": raw_data.get("max_tokens"),
            "stream": raw_data.get("stream", False),
        }
        
        core_request = adapter.transform_request(chat_data)
        core_response = await bridge.process(core_request)
        
        # Generate-Response-Format (leicht anders als Chat)
        response_data = {
            "model": core_response.model,
            "response": core_response.content,
            "done": core_response.done,
        }
        
        if raw_data.get("stream", False):
            def iter_response():
                yield (json.dumps(response_data) + "\n").encode("utf-8")
            return StreamingResponse(iter_response(), media_type="application/x-ndjson")
        else:
            return JSONResponse(response_data)
            
    except Exception as e:
        log_error(f"[LobeChat-Adapter] Generate error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/tags")
async def tags():
    """
    Ollama /api/tags Endpoint.
    Gibt die verfügbaren Modelle zurück.
    
    LobeChat fragt das ab, um die Model-Liste anzuzeigen.
    Wir leiten das an den echten Ollama-Server weiter.
    """
    import requests
    from config import OLLAMA_BASE
    
    try:
        resp = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=10)
        resp.raise_for_status()
        return JSONResponse(resp.json())
    except Exception as e:
        log_error(f"[LobeChat-Adapter] Tags error: {e}")
        # Fallback: Leere Liste
        return JSONResponse({"models": []})


@app.get("/")
async def root():
    """Root-Endpoint für Debugging."""
    from mcp.hub import get_hub
    hub = get_hub()
    
    return {
        "service": "LobeChat Adapter + MCP Hub",
        "status": "running",
        "endpoints": {
            "ollama": [
                "/api/chat",
                "/api/generate", 
                "/api/tags",
            ],
            "mcp": [
                "/mcp",           # Hauptendpoint für WebUIs
                "/mcp/status",    # Status aller MCPs
                "/mcp/tools",     # Tool-Liste
                "/mcp/refresh",   # Tools neu laden
            ],
            "health": "/health",
        },
        "mcp_hub": {
            "mcps": len(hub.list_mcps()),
            "tools": len(hub.list_tools()),
        }
    }


# ============================================================
# Server starten
# ============================================================
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="LobeChat Adapter Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=8100, help="Port to bind")
    args = parser.parse_args()
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║                    LOBECHAT ADAPTER                          ║
╠══════════════════════════════════════════════════════════════╣
║  Host: {args.host:<52} ║
║  Port: {args.port:<52} ║
║                                                              ║
║  In LobeChat eintragen als Ollama-URL:                       ║
║  → http://<server-ip>:{args.port}                              ║
╚══════════════════════════════════════════════════════════════╝
""")
    
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=False,
    )
