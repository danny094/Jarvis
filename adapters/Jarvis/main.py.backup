# adapters/jarvis/main.py
"""
Standalone FastAPI Server für den Jarvis-Adapter.

Native Jarvis API - Einfaches JSON-Format ohne Protokoll-Overhead.

Endpoints:
- POST /chat          → Chat-Completion (Jarvis-Format)
- POST /query         → Alias für /chat
- GET  /health        → Health-Check
- GET  /conversation  → Conversation-History abrufen
"""

import json
import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from typing import Optional

import sys
import os

# Path-Setup für Imports aus dem Hauptprojekt
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from adapters.jarvis.adapter import get_adapter
from core.bridge import get_bridge
from mcp.endpoint import router as mcp_router
from utils.logger import log_info, log_error, log_debug


# FastAPI App
app = FastAPI(
    title="Jarvis Adapter + MCP Hub",
    description="Native Jarvis API → Core-Bridge + MCP Hub",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MCP Hub Endpoint einbinden
app.include_router(mcp_router)

# Maintenance Endpoints
from adapters.jarvis.maintenance_endpoints import router as maintenance_router
app.include_router(maintenance_router)


@app.get("/health")
async def health():
    """Health-Check Endpoint."""
    return {"status": "ok", "adapter": "jarvis"}


@app.post("/chat")
@app.post("/query")
async def chat(request: Request):
    """
    Jarvis Chat Endpoint.
    
    Request:
    {
        "query": "Was ist mein Name?",
        "conversation_id": "user_123",
        "model": "llama3.1:8b",
        "stream": true
    }
    
    Response (Non-Streaming):
    {
        "response": "Dein Name ist Danny.",
        "done": true,
