# Maintenance Endpoints für Memory Management
import httpx
import json
import asyncio
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])

MEMORY_SERVICE_URL = "http://mcp-sql-memory:8081"

def parse_sse(text: str):
    """Parse SSE response to get JSON data."""
    for line in text.strip().split('\n'):
        if line.startswith('data: '):
            return json.loads(line[6:])
    return None

@router.get("/status")
async def get_maintenance_status():
    """Get memory stats - CORRECT KEYS for WebUI."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{MEMORY_SERVICE_URL}/mcp",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream"
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "memory_graph_stats",
                        "arguments": {}
                    }
                },
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = parse_sse(response.text)
                if data and 'result' in data and 'structuredContent' in data['result']:
                    stats = data['result']['structuredContent']
                    node_types = stats.get('node_types', {})
                    
                    return {
                        "memory": {
                            "stm_entries": node_types.get('stm', 0),
                            "mtm_entries": node_types.get('mtm', 0),
                            "ltm_entries": node_types.get('ltm', 0),
                            "graph_nodes": stats.get('nodes', 0),
                            "graph_edges": stats.get('edges', 0)
                        }
                    }
    except Exception:
        pass
    
    # Fallback
    return {
        "memory": {
            "stm_entries": 0,
            "mtm_entries": 0,
            "ltm_entries": 0,
            "graph_nodes": 0,
            "graph_edges": 0
        }
    }

async def maintenance_stream(model: str, validator_model: str = None):
    """Stream maintenance progress in WebUI format."""
    try:
        # Send started event
        yield 'data: ' + json.dumps({
            "type": "started", 
            "tasks": ["dedupe", "promote", "summarize", "graph"],
            "model": model,
            "validator": validator_model
        }) + '\n\n'
        
        # Send initial progress
        yield 'data: ' + json.dumps({"type": "task_start", "message": f"Starte AI Maintenance (Model: {model})..."}) + '\n\n'
        yield 'data: ' + json.dumps({"type": "task_progress", "message": "Analysiere mit AI...", "progress": 10}) + '\n\n'
        
        # Call maintenance with AI params
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{MEMORY_SERVICE_URL}/mcp",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream"
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "maintenance_run",
                        "arguments": {
                            "model": model,
                            "validator_model": validator_model or "",
                            "ollama_url": "http://ollama:11434"
                        }
                    }
                }
            )
            
            yield 'data: ' + json.dumps({"type": "task_progress", "message": "AI verarbeitet Memories...", "progress": 50}) + '\n\n'
            
            if response.status_code == 200:
                data = parse_sse(response.text)
                
                if data and 'result' in data:
                    result = data['result']
                    
                    # Check for errors
                    if result.get('isError'):
                        error_msg = result['content'][0]['text']
                        yield 'data: ' + json.dumps({"type": "error", "message": error_msg}) + '\n\n'
                        return
                    
                    # Parse result
                    if 'structuredContent' in result:
                        maint_result = result['structuredContent']
                        actions = maint_result.get('actions', {})
                        stats = maint_result.get('stats', {})
                        
                        # Send completion with stats
                        yield 'data: ' + json.dumps({"type": "completed", "stats": {"actions": actions}}) + '\n\n'
                        
                        # Build summary message
                        dups = actions.get('duplicates_merged', 0)
                        promoted = actions.get('promoted_to_ltm', 0)
                        ai_decisions = actions.get('ai_decisions', 0)
                        conflicts = actions.get('conflicts_count', 0)
                        
                        summary = f"Fertig: {ai_decisions} AI Decisions, {dups} Duplikate, {promoted} zu LTM"
                        if conflicts > 0:
                            summary += f", {conflicts} Conflicts (siehe Log)"
                        
                        yield 'data: ' + json.dumps({"type": "status", "message": summary}) + '\n\n'
                        
                        # Show conflict log if any
                        conflict_log = maint_result.get('conflict_log')
                        if conflict_log:
                            yield 'data: ' + json.dumps({
                                "type": "warning", 
                                "message": f"Conflict Log: {conflict_log}"
                            }) + '\n\n'
                    else:
                        yield 'data: ' + json.dumps({"type": "completed", "stats": {"actions": {}}}) + '\n\n'
            else:
                yield 'data: ' + json.dumps({"type": "error", "message": "Backend error"}) + '\n\n'
        
        # Send stream end
        yield 'data: ' + json.dumps({"type": "stream_end"}) + '\n\n'
        
    except Exception as e:
        yield 'data: ' + json.dumps({"type": "error", "message": str(e)}) + '\n\n'

@router.post("/start")
async def start_maintenance(request: Request):
    """Start maintenance - STREAMING response for WebUI with AI params."""
    try:
        body = await request.json()
    except:
        body = {}
    
    # Extract AI parameters from request
    model = body.get('model', 'qwen3:4b')
    validator_model = body.get('validator_model')
    
    return StreamingResponse(
        maintenance_stream(model=model, validator_model=validator_model),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
