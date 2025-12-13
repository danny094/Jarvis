# maintenance/routes.py
"""
API Routes für Memory Maintenance.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
import json
import asyncio

from .worker import get_worker
from utils.logger import log_info

router = APIRouter(tags=["maintenance"])


@router.get("/status")
async def get_status():
    """
    Aktueller Memory-Status.
    
    Returns:
        - state: idle/running/completed/error
        - memory counts
        - last maintenance stats
    """
    worker = get_worker()
    
    # Hole auch aktuellen Memory-Status
    memory_status = await worker.get_memory_status()
    
    return JSONResponse({
        "worker": worker.get_status(),
        "memory": memory_status
    })


@router.post("/start")
async def start_maintenance(request: Request):
    """
    Startet Memory Maintenance.
    
    Streamt Progress-Updates als Server-Sent Events.
    
    Body (optional):
        tasks: ["duplicates", "promote", "summarize", "graph"]
    """
    worker = get_worker()
    
    # Tasks aus Request Body
    try:
        body = await request.json()
        tasks = body.get("tasks", None)
    except:
        tasks = None
    
    log_info(f"[Maintenance API] Starting maintenance with tasks={tasks}")
    
    async def event_stream():
        async for update in worker.run_maintenance(tasks):
            # SSE Format
            data = json.dumps(update, ensure_ascii=False)
            yield f"data: {data}\n\n"
            
            # Kleine Pause für UI-Updates
            await asyncio.sleep(0.1)
        
        yield "data: {\"type\": \"stream_end\"}\n\n"
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/cancel")
async def cancel_maintenance():
    """Bricht laufende Maintenance ab."""
    worker = get_worker()
    worker.cancel()
    
    return JSONResponse({
        "success": True,
        "message": "Cancel requested"
    })


@router.get("/history")
async def get_maintenance_history():
    """
    Letzte Maintenance-Durchläufe.
    
    TODO: Aus DB laden
    """
    worker = get_worker()
    
    return JSONResponse({
        "last_run": worker.stats.to_dict() if worker.stats.started_at else None
    })
