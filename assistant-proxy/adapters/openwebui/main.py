# adapters/openwebui/main.py
"""
Standalone FastAPI Server für den Open WebUI Adapter.

Sehr ähnlich zum LobeChat-Adapter, aber als separater Service.
Port: 8200 (default)
"""

import json
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from adapters.openwebui.adapter import get_adapter
from core.bridge import get_bridge
from utils.logger import log_info, log_error, log_debug


app = FastAPI(
    title="Open WebUI Adapter",
    description="Ollama-kompatible API für Open WebUI → Core-Bridge",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "adapter": "openwebui"}


@app.post("/api/chat")
async def chat(request: Request):
    adapter = get_adapter()
    bridge = get_bridge()
    
    try:
        raw_data = await request.json()
        log_info(f"[OpenWebUI-Adapter] /api/chat → model={raw_data.get('model')}")
        
        core_request = adapter.transform_request(raw_data)
        core_response = await bridge.process(core_request)
        response_data = adapter.transform_response(core_response)
        
        def iter_response():
            yield (json.dumps(response_data) + "\n").encode("utf-8")
        
        return StreamingResponse(iter_response(), media_type="application/x-ndjson")
        
    except Exception as e:
        log_error(f"[OpenWebUI-Adapter] Error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/generate")
async def generate(request: Request):
    adapter = get_adapter()
    bridge = get_bridge()
    
    try:
        raw_data = await request.json()
        prompt = raw_data.get("prompt", "")
        
        chat_data = {
            "model": raw_data.get("model"),
            "messages": [{"role": "user", "content": prompt}],
            "options": raw_data.get("options", {}),
            "stream": raw_data.get("stream", False),
        }
        
        core_request = adapter.transform_request(chat_data)
        core_response = await bridge.process(core_request)
        
        response_data = {
            "model": core_response.model,
            "response": core_response.content,
            "done": core_response.done,
        }
        
        return JSONResponse(response_data)
            
    except Exception as e:
        log_error(f"[OpenWebUI-Adapter] Generate error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/tags")
async def tags():
    import requests
    from config import OLLAMA_BASE
    
    try:
        resp = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=10)
        return JSONResponse(resp.json())
    except Exception as e:
        return JSONResponse({"models": []})


@app.get("/")
async def root():
    return {
        "service": "Open WebUI Adapter",
        "status": "running",
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8200, reload=False)
