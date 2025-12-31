from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse

from config import ALLOW_ORIGINS
from utils.logger import log_info

# Router Imports
from ollama.generate import router as generate_router
from ollama.chat import router as chat_router
from mcp.client import router as mcp_router, call_tool
from modules.meta_decision.decision_router import router as decision_router
from ollama.tags import router as tags_router


# ---------------------------------------------------------
# FastAPI App erstellen
# ---------------------------------------------------------
app = FastAPI(title="Assistant Proxy", version="1.0.0")


# ---------------------------------------------------------
# CORS Setup
# ---------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS if ALLOW_ORIGINS else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------
# Router registrieren
# ---------------------------------------------------------
app.include_router(generate_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(mcp_router, prefix="/api/mcp")
app.include_router(decision_router, prefix="/api/meta")
app.include_router(tags_router, prefix="/api")
# ---------------------------------------------------------
# Debug Endpoint
# ---------------------------------------------------------
@app.get("/debug/memory/{conversation_id}")
async def debug_memory(conversation_id: str):
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