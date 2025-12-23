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
import httpx
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
from maintenance.routes import router as maintenance_router
from utils.logger import log_info, log_error, log_debug
from utils.code_formatter import ensure_formatted


# FastAPI App
app = FastAPI(
    title="LobeChat Adapter + MCP Hub",
    description="Ollama-kompatible API für LobeChat → Core-Bridge + MCP Hub",
    version="1.1.0"
)

# CORS - Security (aus config.py)
from config import ALLOW_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MCP Hub Endpoint einbinden
app.include_router(mcp_router)

# Maintenance Endpoint einbinden
app.include_router(maintenance_router, prefix="/api/maintenance")


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
                """Generiert NDJSON-Chunks für LobeChat mit Live Thinking + Container."""
                try:
                    async for chunk, is_done, metadata in bridge.process_stream(core_request):
                        created_at = datetime.utcnow().isoformat() + "Z"
                        chunk_type = metadata.get("type", "content")
                        
                        # Live Thinking Stream
                        if chunk_type == "thinking_stream":
                            response_data = {
                                "model": model,
                                "created_at": created_at,
                                "message": {"role": "assistant", "content": ""},  # Required for LobeChat
                                "thinking_stream": metadata.get("thinking_chunk", ""),
                                "done": False,
                            }
                        
                        # Thinking Done (mit Plan)
                        elif chunk_type == "thinking_done":
                            response_data = {
                                "model": model,
                                "created_at": created_at,
                                "message": {"role": "assistant", "content": ""},  # Required for LobeChat
                                "thinking": metadata.get("thinking", {}),
                                "done": False,
                            }
                        
                        # Container Start
                        elif chunk_type == "container_start":
                            response_data = {
                                "model": model,
                                "created_at": created_at,
                                "message": {"role": "assistant", "content": ""},  # Required for LobeChat
                                "container_start": {
                                    "container": metadata.get("container", ""),
                                    "task": metadata.get("task", "execute")
                                },
                                "done": False,
                            }
                        
                        # Container Done
                        elif chunk_type == "container_done":
                            response_data = {
                                "model": model,
                                "created_at": created_at,
                                "message": {"role": "assistant", "content": ""},  # Required for LobeChat
                                "container_done": {
                                    "result": metadata.get("result", {})
                                },
                                "done": False,
                            }
                        
                        # Final Done
                        elif is_done:
                            response_data = {
                                "model": metadata.get("model", model),
                                "created_at": created_at,
                                "message": {"role": "assistant", "content": ""},
                                "done": True,
                                "done_reason": metadata.get("done_reason", "stop"),
                                "memory_used": metadata.get("memory_used", False),
                                "code_model_used": metadata.get("code_model_used", False),
                                "container_used": metadata.get("container_used", False),
                            }
                        
                        # Content Chunk
                        else:
                            response_data = {
                                "model": metadata.get("model", model),
                                "created_at": created_at,
                                "message": {"role": "assistant", "content": chunk},
                                "done": False,
                                "code_model_used": metadata.get("code_model_used", False),
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
    import httpx
    from config import OLLAMA_BASE
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{OLLAMA_BASE}/api/tags")
            resp.raise_for_status()
            return JSONResponse(resp.json())
    except Exception as e:
        log_error(f"[LobeChat-Adapter] Tags error: {e}")
        # Fallback: Leere Liste
        return JSONResponse({"models": []})


# ============================================================
# API TOOLS ENDPOINTS (für WebUI)
# ============================================================

@app.get("/api/tools")
async def list_tools():
    """Listet alle verfügbaren MCP-Tools."""
    from mcp.hub import get_hub
    
    try:
        hub = get_hub()
        tools = hub.list_tools()
        mcps = hub.list_mcps()
        
        return JSONResponse({
            "mcps": mcps,
            "tools": tools,
            "total_tools": len(tools),
            "total_mcps": len([m for m in mcps if m.get("online")])
        })
    except Exception as e:
        log_error(f"[LobeChat-Adapter] Tools error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/mcps")
async def list_mcps():
    """Listet alle MCPs mit Status."""
    from mcp.hub import get_hub
    
    try:
        hub = get_hub()
        mcps = hub.list_mcps()
        return JSONResponse({"mcps": mcps})
    except Exception as e:
        log_error(f"[LobeChat-Adapter] MCPs error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/debug/memory/{conversation_id}")
async def debug_memory(conversation_id: str, request: Request):
    """Debug-Endpoint: Zeigt Memory für eine Conversation (NUR LOCALHOST!)."""
    from mcp.client import call_tool
    from fastapi import HTTPException
    
    # Security: Nur von localhost erlaubt!
    client_host = request.client.host
    if client_host not in ["127.0.0.1", "localhost", "::1"]:
        raise HTTPException(
            status_code=403,
            detail=f"Debug-Endpoints nur von localhost erlaubt (requested from: {client_host})"
        )
    
    resp = call_tool(
        "memory_recent",
        {"conversation_id": conversation_id, "limit": 20},
        timeout=5,
    )

    if not resp:
        return JSONResponse(
            {"error": "Keine Antwort vom MCP-Server"},
            status_code=500
        )

    return JSONResponse(resp)


@app.post("/api/reload-prompt")
async def reload_prompt():
    """Hot-Reload: Lädt den System-Prompt neu ohne Neustart."""
    from core.persona import reload_persona
    
    try:
        persona = reload_persona()
        prompt = persona.build_system_prompt()
        
        return JSONResponse({
            "status": "ok",
            "message": "System-Prompt neu geladen",
            "prompt_length": len(prompt),
            "prompt_preview": prompt[:500] + "..." if len(prompt) > 500 else prompt
        })
    except Exception as e:
        log_error(f"[LobeChat-Adapter] Reload error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/system-prompt")
async def get_system_prompt():
    """Zeigt den aktuellen System-Prompt an."""
    from core.persona import get_persona
    
    try:
        persona = get_persona()
        prompt = persona.build_system_prompt()
        
        return JSONResponse({
            "name": persona.name,
            "prompt_length": len(prompt),
            "prompt": prompt
        })
    except Exception as e:
        log_error(f"[LobeChat-Adapter] Get prompt error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ============================================================
# DIRECT CODE EXECUTION (für WebUI Run-Button)
# ============================================================
@app.post("/api/execute")
async def execute_code(request: Request):
    """
    Führt Code direkt in einem Sandbox-Container aus.
    
    Verwendet für den "Run"-Button in interaktiven Code-Blöcken.
    Kein Chat-Context, nur Code-Ausführung.
    
    Request Body:
    {
        "code": "print('Hello')",
        "language": "python",
        "container": "code-sandbox"
    }
    """
    import httpx
    from config import CONTAINER_MANAGER_URL, ENABLE_CONTAINER_MANAGER
    
    if not ENABLE_CONTAINER_MANAGER:
        return JSONResponse({
            "error": "Container-Manager ist deaktiviert"
        }, status_code=503)
    
    try:
        data = await request.json()
        code = data.get("code", "")
        language = data.get("language", "python")
        container = data.get("container", "code-sandbox")
        
        if not code:
            return JSONResponse({
                "error": "Kein Code angegeben"
            }, status_code=400)
        
        log_info(f"[LobeChat-Adapter] /api/execute → {language} in {container}")
        
        # ════════════════════════════════════════════════════════════
        # CODE FORMATIERUNG: Stellt sicher dass Code korrekt formatiert ist
        # ════════════════════════════════════════════════════════════
        # Dies ist nötig weil die WebUI manchmal einzeiligen Code schickt
        # (z.B. wenn die KI den Code einzeilig in ihrer Antwort ausgibt)
        if language == "python":
            original_len = len(code)
            code = await ensure_formatted(code)
            if len(code) != original_len:
                log_info(f"[LobeChat-Adapter] Code formatted: {original_len} → {len(code)} chars")
        
        # Container-Manager aufrufen
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{CONTAINER_MANAGER_URL}/containers/start",
                json={
                    "container_name": container,
                    "code": code,
                    "timeout": 60
                }
            )
            
            if response.status_code == 403:
                return JSONResponse({
                    "error": f"Container '{container}' nicht erlaubt"
                }, status_code=403)
            
            response.raise_for_status()
            result = response.json()
            
            # Container stoppen
            container_id = result.get("container_id")
            if container_id:
                try:
                    await client.post(
                        f"{CONTAINER_MANAGER_URL}/containers/stop",
                        json={"container_id": container_id}
                    )
                except Exception as e:
                    log_error(f"[LobeChat-Adapter] Container stop failed: {e}")
            
            execution_result = result.get("execution_result", {})
            
            return JSONResponse({
                "exit_code": execution_result.get("exit_code"),
                "stdout": execution_result.get("stdout", ""),
                "stderr": execution_result.get("stderr", ""),
                "container": container,
                "language": language
            })
            
    except httpx.TimeoutException:
        return JSONResponse({
            "error": "Container-Ausführung Timeout (120s)"
        }, status_code=504)
    except httpx.HTTPStatusError as e:
        return JSONResponse({
            "error": f"Container-Manager Fehler: {e.response.status_code}"
        }, status_code=502)
    except Exception as e:
        log_error(f"[LobeChat-Adapter] Execute error: {e}")
        return JSONResponse({
            "error": str(e)
        }, status_code=500)


# ============================================================
# USER-SANDBOX ENDPOINTS (Proxy zum Container-Manager)
# ============================================================
# Diese Endpoints erlauben der WebUI direkte Kontrolle über
# die User-Sandbox. Die KI nutzt diese nicht direkt.
# ============================================================

@app.post("/api/sandbox/start")
async def sandbox_start(request: Request):
    """
    Startet die User-Sandbox.
    
    Request Body (optional):
    {
        "container_name": "code-sandbox",  // default
        "preferred_model": "qwen2.5-coder:3b"  // optional
    }
    """
    from config import CONTAINER_MANAGER_URL
    
    try:
        data = await request.json()
    except:
        data = {}
    
    log_info(f"[LobeChat-Adapter] /api/sandbox/start")
    
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:  # 2 Minuten für Build
            response = await client.post(
                f"{CONTAINER_MANAGER_URL}/sandbox/user/start",
                json={
                    "container_name": data.get("container_name", "code-sandbox"),
                    "preferred_model": data.get("preferred_model")
                }
            )
            
            result = response.json()
            
            # Wenn erfolgreich, ttyd_url für WebUI anpassen
            # (WebUI läuft evtl. auf anderem Host)
            if response.status_code == 200 and result.get("ttyd_port"):
                # ttyd_url wird im Frontend zusammengebaut
                pass
            
            return JSONResponse(result, status_code=response.status_code)
            
    except httpx.TimeoutException:
        log_error(f"[LobeChat-Adapter] Sandbox start timeout (60s)")
        return JSONResponse({"error": "Timeout - Container-Build dauert zu lange. Versuche es nochmal."}, status_code=504)
    except Exception as e:
        log_error(f"[LobeChat-Adapter] Sandbox start error: {type(e).__name__}: {e}")
        return JSONResponse({"error": str(e) or type(e).__name__}, status_code=500)

@app.post("/api/sandbox/stop")
async def sandbox_stop(request: Request):
    """Stoppt die User-Sandbox."""
    from config import CONTAINER_MANAGER_URL
    
    try:
        data = await request.json()
    except:
        data = {}
    
    log_info(f"[LobeChat-Adapter] /api/sandbox/stop")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{CONTAINER_MANAGER_URL}/sandbox/user/stop",
                json={"force": data.get("force", False)}
            )
            
            return JSONResponse(response.json(), status_code=response.status_code)
    
    except httpx.TimeoutException:
        log_error(f"[LobeChat-Adapter] Sandbox stop timeout")
        return JSONResponse({"error": "Timeout"}, status_code=504)
    except Exception as e:
        log_error(f"[LobeChat-Adapter] Sandbox stop error: {type(e).__name__}: {e}")
        return JSONResponse({"error": str(e) or type(e).__name__}, status_code=500)

@app.get("/api/sandbox/status")
async def sandbox_status():
    """Status der User-Sandbox."""
    from config import CONTAINER_MANAGER_URL
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{CONTAINER_MANAGER_URL}/sandbox/user/status"
            )
            
            return JSONResponse(response.json(), status_code=response.status_code)
    
    except httpx.TimeoutException:
        return JSONResponse({"error": "Timeout", "active": False}, status_code=504)
    except Exception as e:
        log_error(f"[LobeChat-Adapter] Sandbox status error: {type(e).__name__}: {e}")
        return JSONResponse({"error": str(e) or type(e).__name__, "active": False}, status_code=500)


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
            "api": [
                "/api/tools",          # Tool-Liste (für WebUI)
                "/api/mcps",           # MCP-Status (für WebUI)
                "/api/system-prompt",  # System-Prompt anzeigen
                "/api/reload-prompt",  # System-Prompt hot-reload (POST)
                "/api/execute",        # Direct code execution (POST)
                "/api/sandbox/start",  # User-Sandbox starten (POST)
                "/api/sandbox/stop",   # User-Sandbox stoppen (POST)
                "/api/sandbox/status", # User-Sandbox Status (GET)
            ],
            "mcp": [
                "/mcp",           # Hauptendpoint für WebUIs
                "/mcp/status",    # Status aller MCPs
                "/mcp/tools",     # Tool-Liste
                "/mcp/refresh",   # Tools neu laden
            ],
            "maintenance": [
                "/api/maintenance/status",   # Memory-Status
                "/api/maintenance/start",    # Maintenance starten
                "/api/maintenance/cancel",   # Abbrechen
                "/api/maintenance/history",  # Historie
            ],
            "debug": [
                "/debug/memory/{id}",  # Memory für Conversation
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
