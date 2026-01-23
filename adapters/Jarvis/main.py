# adapters/Jarvis/main.py
"""
Jarvis Adapter - Standalone FastAPI Server
"""

import sys
sys.path.insert(0, "/DATA/AppData/MCP/Jarvis/Jarvis")

import json
import uvicorn
import requests
from datetime import datetime
from mcp.hub import MCPHub
from shared_schemas import SequentialResponse, StepSchema
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from typing import Optional

import sys
import os

# Path-Setup
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters.Jarvis.adapter import get_adapter
from core.bridge import get_bridge
from mcp.endpoint import router as mcp_router
from utils.logger import log_info, log_error, log_debug

# FastAPI App
app = FastAPI(
    title="Jarvis Adapter + MCP Hub + Sequential Thinking",
    description="Native Jarvis API → Core-Bridge + MCP Hub + Sequential Mode",
    version="2.1.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(mcp_router)

from adapters.Jarvis.maintenance_endpoints import router as maintenance_router
app.include_router(maintenance_router)

from adapters.Jarvis.persona_endpoints import router as persona_router
app.include_router(persona_router)

# ═══════════════════════════════════════════════════════════════
# MCP HUB INITIALIZATION
# ═══════════════════════════════════════════════════════════════
mcp_hub = MCPHub()

@app.on_event("startup")
async def startup_event():
    """Initialize MCP Hub on startup"""
    log_info("[Startup] Initializing MCP Hub...")
    mcp_hub.initialize()
    log_info("[Startup] MCP Hub ready!")



@app.get("/health")
async def health():
    """Health Check"""
    return {"status": "ok", "adapter": "jarvis", "version": "2.1.0"}


@app.post("/chat")
async def chat(request: Request):
    """Regular Chat Endpoint"""
    data = await request.json()
    
    adapter = get_adapter()
    bridge = get_bridge()
    
    core_request = adapter.transform_request(data)
    
    if core_request.stream:
        async def stream():
            async for chunk in bridge.stream_chat(core_request):
                response = adapter.transform_response(chunk)
                yield f"data: {json.dumps(response)}\n\n"
        return StreamingResponse(stream(), media_type="text/event-stream")
    else:
        response = await bridge.chat(core_request)
        return adapter.transform_response(response)


# ═══════════════════════════════════════════════════════════
# SEQUENTIAL THINKING ENDPOINTS (Task 2 - Phase 3)
# ═══════════════════════════════════════════════════════════

sequential_tasks = {}

# [DISABLED OLD SEQUENTIAL] @app.post("/chat/sequential")
# [DISABLED OLD SEQUENTIAL] async def chat_sequential(request: Request):
# [DISABLED OLD SEQUENTIAL]     """Sequential Thinking Mode Endpoint"""
# [DISABLED OLD SEQUENTIAL]     try:
# [DISABLED OLD SEQUENTIAL]         data = await request.json()
# [DISABLED OLD SEQUENTIAL]         message = data.get("message", "")
# [DISABLED OLD SEQUENTIAL]         
# [DISABLED OLD SEQUENTIAL]         if not message:
# [DISABLED OLD SEQUENTIAL]             raise HTTPException(status_code=400, detail="Message required")
# [DISABLED OLD SEQUENTIAL]         
# [DISABLED OLD SEQUENTIAL]         log_info(f"[Sequential] Starting: {message[:50]}...")
# [DISABLED OLD SEQUENTIAL]         
        # Call via MCP Hub (centralized routing!)
# [DISABLED OLD SEQUENTIAL]         try:
# [DISABLED OLD SEQUENTIAL]             mcp_data = mcp_hub.call_tool(
# [DISABLED OLD SEQUENTIAL]                 tool_name="think",
# [DISABLED OLD SEQUENTIAL]                 arguments={"message": message, "steps": 5}
# [DISABLED OLD SEQUENTIAL]             )
# [DISABLED OLD SEQUENTIAL]             
            # Check for errors
# [DISABLED OLD SEQUENTIAL]             if "error" in mcp_data:
# [DISABLED OLD SEQUENTIAL]                 raise HTTPException(status_code=500, detail=mcp_data["error"])
# [DISABLED OLD SEQUENTIAL]             
            # Hub returns JSON-RPC format, extract result
# [DISABLED OLD SEQUENTIAL]             if "result" in mcp_data:
# [DISABLED OLD SEQUENTIAL]                 mcp_data = mcp_data["result"]
# [DISABLED OLD SEQUENTIAL]                 
# [DISABLED OLD SEQUENTIAL]         except Exception as e:
# [DISABLED OLD SEQUENTIAL]             log_error(f"[Sequential] Hub call failed: {e}")
# [DISABLED OLD SEQUENTIAL]             raise HTTPException(status_code=502, detail=str(e))
        # MCP Server now returns SequentialResponse with proper task_id and steps
# [DISABLED OLD SEQUENTIAL]         task_id = mcp_data.get("task_id", f"task_{int(datetime.now().timestamp() * 1000)}")
# [DISABLED OLD SEQUENTIAL]         
# [DISABLED OLD SEQUENTIAL]         sequential_tasks[task_id] = {
# [DISABLED OLD SEQUENTIAL]             "task_id": task_id,
# [DISABLED OLD SEQUENTIAL]             "message": message,
# [DISABLED OLD SEQUENTIAL]             "status": "running",
# [DISABLED OLD SEQUENTIAL]             "progress": mcp_data.get("progress", 0.0),
# [DISABLED OLD SEQUENTIAL]             "steps": mcp_data.get("steps", []),  # Properly populated from SequentialResponse!
# [DISABLED OLD SEQUENTIAL]             "started_at": mcp_data.get("started_at", datetime.now().isoformat())
# [DISABLED OLD SEQUENTIAL]         }
# [DISABLED OLD SEQUENTIAL]         
# [DISABLED OLD SEQUENTIAL]         log_info(f"[Sequential] Task {task_id} started with {len(mcp_data.get('steps', []))} steps")
# [DISABLED OLD SEQUENTIAL]         
# [DISABLED OLD SEQUENTIAL]         return {
# [DISABLED OLD SEQUENTIAL]             "success": True,
# [DISABLED OLD SEQUENTIAL]             "task_id": task_id,
# [DISABLED OLD SEQUENTIAL]             "message": "Task started via MCP Hub",
# [DISABLED OLD SEQUENTIAL]             "data": sequential_tasks[task_id]
# [DISABLED OLD SEQUENTIAL]         }
# [DISABLED OLD SEQUENTIAL]         
# [DISABLED OLD SEQUENTIAL]     except Exception as e:
# [DISABLED OLD SEQUENTIAL]         log_error(f"[Sequential] Error: {e}")
# [DISABLED OLD SEQUENTIAL]         raise HTTPException(status_code=500, detail=str(e))
# [DISABLED OLD SEQUENTIAL] 
# [DISABLED OLD SEQUENTIAL] 
# [DISABLED OLD SEQUENTIAL] @app.get("/sequential/status/{task_id}")
# [DISABLED OLD SEQUENTIAL] async def get_sequential_status(task_id: str):
# [DISABLED OLD SEQUENTIAL]     """Get Sequential Task Status"""
# [DISABLED OLD SEQUENTIAL]     if task_id not in sequential_tasks:
# [DISABLED OLD SEQUENTIAL]         raise HTTPException(status_code=404, detail="Task not found")
# [DISABLED OLD SEQUENTIAL]     
# [DISABLED OLD SEQUENTIAL]     task = sequential_tasks[task_id]
# [DISABLED OLD SEQUENTIAL]     steps = task.get("steps", [])
# [DISABLED OLD SEQUENTIAL]     
# [DISABLED OLD SEQUENTIAL]     if steps:
# [DISABLED OLD SEQUENTIAL]         verified = sum(1 for s in steps if s.get("status") == "verified")
# [DISABLED OLD SEQUENTIAL]         progress = verified / len(steps)
# [DISABLED OLD SEQUENTIAL]     else:
# [DISABLED OLD SEQUENTIAL]         progress = 0.0
# [DISABLED OLD SEQUENTIAL]     
# [DISABLED OLD SEQUENTIAL]     task["progress"] = progress
# [DISABLED OLD SEQUENTIAL]     if progress >= 1.0:
# [DISABLED OLD SEQUENTIAL]         task["status"] = "complete"
# [DISABLED OLD SEQUENTIAL]     
# [DISABLED OLD SEQUENTIAL]     return {
# [DISABLED OLD SEQUENTIAL]         "task_id": task_id,
# [DISABLED OLD SEQUENTIAL]         "status": task["status"],
# [DISABLED OLD SEQUENTIAL]         "progress": progress,
# [DISABLED OLD SEQUENTIAL]         "steps": steps
# [DISABLED OLD SEQUENTIAL]     }
# [DISABLED OLD SEQUENTIAL] 
# [DISABLED OLD SEQUENTIAL] 
# [DISABLED OLD SEQUENTIAL] @app.post("/sequential/stop/{task_id}")
# [DISABLED OLD SEQUENTIAL] async def stop_sequential_task(task_id: str):
# [DISABLED OLD SEQUENTIAL]     """Stop Sequential Task"""
# [DISABLED OLD SEQUENTIAL]     if task_id not in sequential_tasks:
# [DISABLED OLD SEQUENTIAL]         raise HTTPException(status_code=404, detail="Task not found")
# [DISABLED OLD SEQUENTIAL]     
# [DISABLED OLD SEQUENTIAL]     sequential_tasks[task_id]["status"] = "stopped"
# [DISABLED OLD SEQUENTIAL]     log_info(f"[Sequential] Task {task_id} stopped")
# [DISABLED OLD SEQUENTIAL]     
# [DISABLED OLD SEQUENTIAL]     return {"success": True, "task_id": task_id}
# [DISABLED OLD SEQUENTIAL] 
# [DISABLED OLD SEQUENTIAL] 
# [DISABLED OLD SEQUENTIAL] if __name__ == "__main__":
# [DISABLED OLD SEQUENTIAL]     uvicorn.run(app, host="0.0.0.0", port=8000)
