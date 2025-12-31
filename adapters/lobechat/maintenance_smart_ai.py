# Smart AI Proxy - Streaming mit Progress Simulation
import httpx
import json
import asyncio
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/maintenance", tags=["maintenance-smart"])

MEMORY_SERVICE_URL = "http://mcp-sql-memory:8081"

def parse_sse(text: str):
    """Parse SSE response."""
    for line in text.strip().split('\n'):
        if line.startswith('data: '):
            return json.loads(line[6:])
    return None

async def smart_ai_stream(
    model: str,
    validator_model: str = None,
    tasks: list = None
):
    """
    Smart Streaming Proxy:
    - Zeigt sofort Progress
    - Ruft Memory Service im Background
    - Simuliert AI Thinking mit echten Model-Namen
    - Zeigt finale Results
    """
    
    slow_mode = validator_model and validator_model != ""
    
    # Start Event
    yield 'data: ' + json.dumps({
        "type": "started",
        "tasks": tasks or ["dedupe", "promote", "summarize", "graph"],
        "model": model,
        "validator": validator_model,
        "mode": "Slow (Dual Validation)" if slow_mode else "Normal (Fast)"
    }) + '\n\n'
    
    yield 'data: ' + json.dumps({
        "type": "info",
        "message": f"🤖 Primary Model: {model}"
    }) + '\n\n'
    
    if slow_mode:
        yield 'data: ' + json.dumps({
            "type": "info",
            "message": f"🔍 Validator Model: {validator_model}"
        }) + '\n\n'
    
    # Phase 1: Vorbereitung
    yield 'data: ' + json.dumps({
        "type": "task_start",
        "message": "🚀 Starte AI-gestütztes Memory Maintenance..."
    }) + '\n\n'
    
    await asyncio.sleep(0.3)
    
    yield 'data: ' + json.dumps({
        "type": "task_progress",
        "message": "📊 Lade Memory Datenbank...",
        "progress": 5
    }) + '\n\n'
    
    # Background: Call Memory Service
    maintenance_task = None
    result_holder = {"result": None, "error": None}
    
    async def call_memory_service():
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
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
                
                if response.status_code == 200:
                    data = parse_sse(response.text)
                    result_holder["result"] = data
                else:
                    result_holder["error"] = f"HTTP {response.status_code}"
                    
        except Exception as e:
            result_holder["error"] = str(e)
    
    maintenance_task = asyncio.create_task(call_memory_service())
    
    await asyncio.sleep(0.5)
    
    # Phase 2: AI Analysis
    yield 'data: ' + json.dumps({
        "type": "task_progress",
        "message": f"🧠 {model} analysiert Memory Entries...",
        "progress": 15
    }) + '\n\n'
    
    await asyncio.sleep(1)
    
    yield 'data: ' + json.dumps({
        "type": "thinking",
        "message": f"🤔 Evaluiere STM → LTM Kandidaten..."
    }) + '\n\n'
    
    await asyncio.sleep(0.8)
    
    yield 'data: ' + json.dumps({
        "type": "thinking",
        "message": "💭 Analysiere semantische Eigenschaften..."
    }) + '\n\n'
    
    await asyncio.sleep(0.7)
    
    yield 'data: ' + json.dumps({
        "type": "task_progress",
        "message": "🔍 Prüfe auf Duplikate...",
        "progress": 30
    }) + '\n\n'
    
    await asyncio.sleep(0.6)
    
    if slow_mode:
        yield 'data: ' + json.dumps({
            "type": "thinking",
            "message": f"🔍 {validator_model} validiert Primary Decisions..."
        }) + '\n\n'
        
        await asyncio.sleep(1.2)
    
    yield 'data: ' + json.dumps({
        "type": "task_progress",
        "message": "⚙️ AI trifft Entscheidungen...",
        "progress": 50
    }) + '\n\n'
    
    # Wait for maintenance to complete
    max_wait = 30  # Max 30 additional progress updates
    for i in range(max_wait):
        if maintenance_task.done():
            break
        
        progress = 50 + (i * 2)  # 50 → 110
        if progress > 95:
            progress = 95
        
        messages = [
            "💡 Reasoning über Memory Importance...",
            "🎯 Klassifiziere Entry Typen...",
            "📈 Evaluiere Confidence Scores...",
            "🔗 Analysiere semantische Verbindungen...",
            "✨ Optimiere Knowledge Graph...",
        ]
        
        msg = messages[i % len(messages)]
        
        yield 'data: ' + json.dumps({
            "type": "task_progress",
            "message": msg,
            "progress": progress
        }) + '\n\n'
        
        await asyncio.sleep(0.8)
    
    # Ensure task is done
    if not maintenance_task.done():
        yield 'data: ' + json.dumps({
            "type": "warning",
            "message": "⏱️ AI arbeitet länger als erwartet..."
        }) + '\n\n'
        
        await maintenance_task
    
    # Process Results
    if result_holder["error"]:
        yield 'data: ' + json.dumps({
            "type": "error",
            "message": f"❌ Error: {result_holder['error']}"
        }) + '\n\n'
    
    elif result_holder["result"]:
        data = result_holder["result"]
        
        if data.get('result', {}).get('isError'):
            error_text = data['result']['content'][0]['text']
            yield 'data: ' + json.dumps({
                "type": "error",
                "message": f"❌ {error_text}"
            }) + '\n\n'
        
        elif 'structuredContent' in data.get('result', {}):
            maint_result = data['result']['structuredContent']
            actions = maint_result.get('actions', {})
            
            # Completion
            yield 'data: ' + json.dumps({
                "type": "completed",
                "stats": {"actions": actions}
            }) + '\n\n'
            
            # Summary
            ai_dec = actions.get('ai_decisions', 0)
            promoted = actions.get('promoted_to_ltm', 0)
            dups = actions.get('duplicates_merged', 0)
            conflicts = actions.get('conflicts_count', 0)
            
            summary = f"✅ Fertig: {ai_dec} AI Decisions, {promoted} → LTM, {dups} Duplikate"
            if conflicts > 0:
                summary += f", ⚠️ {conflicts} Conflicts (siehe Log)"
            
            yield 'data: ' + json.dumps({
                "type": "status",
                "message": summary
            }) + '\n\n'
            
            # Conflict log
            if maint_result.get('conflict_log'):
                yield 'data: ' + json.dumps({
                    "type": "warning",
                    "message": f"📝 Conflict Log: {maint_result['conflict_log']}"
                }) + '\n\n'
    
    # Stream end
    yield 'data: ' + json.dumps({"type": "stream_end"}) + '\n\n'

@router.post("/start-ai")
async def start_smart_ai_maintenance(request: Request):
    """
    Smart AI Maintenance mit simuliertem Thinking Stream.
    """
    try:
        body = await request.json()
    except:
        body = {}
    
    model = body.get('model', 'qwen3:4b')
    validator_model = body.get('validator_model')
    tasks = body.get('tasks', [])
    
    return StreamingResponse(
        smart_ai_stream(model=model, validator_model=validator_model, tasks=tasks),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
