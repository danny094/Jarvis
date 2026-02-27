"""
Sequential Thinking MCP Server

Provides sequential_thinking and sequential_workflow tools via MCP protocol.
"""

import sys
import os
from pathlib import Path

# Add Jarvis root to path
JARVIS_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(JARVIS_ROOT))

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import sys
import re
# FIX 1: Dynamic path resolution (portable)
import os
from pathlib import Path

# Calculate PROJECT_ROOT dynamically
# Priority: 1) ENV VAR, 2) Relative to this file
PROJECT_ROOT = os.getenv(
    "JARVIS_PROJECT_ROOT",
    str(Path(__file__).parent.parent.parent.parent.resolve())
)
sys.path.insert(0, PROJECT_ROOT)
from shared_schemas import SequentialResponse, StepSchema
from datetime import datetime
import uvicorn
import traceback
from uuid import uuid4

# Import Sequential Engine from Phase 1
from modules.sequential_thinking.engine import SequentialThinkingEngine
from modules.sequential_thinking.types import create_task, create_step

# Import from this module (absolute imports)
from sequential_mcp.tools import TOOLS
from sequential_mcp.config import HOST, PORT, MAX_STEPS_DEFAULT, MAX_DURATION_DEFAULT

# Create FastAPI app
app = FastAPI(title="Sequential Thinking MCP Server")

# Initialize Sequential Engine
engine = SequentialThinkingEngine()

# MCP Protocol Models
class ToolCallRequest(BaseModel):
    """MCP tool call request"""
    name: str
    arguments: Dict[str, Any]

class ToolCallResponse(BaseModel):
    """MCP tool call response"""
    content: List[Dict[str, Any]]
    isError: Optional[bool] = False


WORKFLOW_TEMPLATES: Dict[str, List[str]] = {
    "data_analysis": [
        "Define objective and expected output for {dataset}.",
        "Validate data quality and identify missing or inconsistent fields.",
        "Run exploratory analysis and summarize high-impact findings.",
        "Build and validate a baseline model or statistical comparison.",
        "Produce final report with recommendations and risks.",
    ],
    "research": [
        "Define research question and scope for {topic}.",
        "Collect and classify primary and secondary sources.",
        "Extract evidence and group by claims and counter-claims.",
        "Synthesize findings into a consistent argument structure.",
        "Deliver concise conclusion with open questions.",
    ],
    "code_review": [
        "Identify scope and critical paths in {repository}.",
        "Review correctness risks, edge cases, and failure handling.",
        "Check security, input validation, and dependency exposure.",
        "Assess test coverage and missing regression scenarios.",
        "Propose prioritized fixes with implementation notes.",
    ],
    "decision_making": [
        "Define decision objective and non-negotiable constraints.",
        "List options with assumptions, cost, and feasibility.",
        "Evaluate risk, reversibility, and expected impact per option.",
        "Select preferred option and define fallback trigger.",
        "Create execution and monitoring checklist.",
    ],
}


class _SafeTemplateVars(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _generate_steps_from_description(description: str, max_steps: int) -> List[Dict[str, Any]]:
    """Generate a deterministic step plan from free-form task text."""
    clean = " ".join((description or "").strip().split())
    if not clean:
        clean = "Execute the requested task."

    parts = re.split(r"(?:[.;\n]+|\s+(?:and then|then|dann|anschließend|anschliessend)\s+)", clean, flags=re.IGNORECASE)
    normalized = [p.strip(" -") for p in parts if isinstance(p, str) and p.strip()]
    if not normalized:
        normalized = [clean]

    limited = normalized[: max(1, int(max_steps))]
    steps: List[Dict[str, Any]] = []
    for idx, text in enumerate(limited):
        step_id = f"step_{idx + 1}"
        deps = [f"step_{idx}"] if idx > 0 else []
        steps.append({"id": step_id, "description": text, "dependencies": deps})
    return steps


def _render_workflow_steps(template_id: str, variables: Dict[str, Any]) -> List[Dict[str, Any]]:
    template = WORKFLOW_TEMPLATES.get(template_id)
    if not template:
        available = ", ".join(sorted(WORKFLOW_TEMPLATES.keys()))
        raise ValueError(f"Unknown workflow template '{template_id}'. Available: {available}")

    safe_vars = _SafeTemplateVars(**(variables or {}))
    steps: List[Dict[str, Any]] = []
    for idx, step_text in enumerate(template):
        step_id = f"wf_step_{idx + 1}"
        deps = [f"wf_step_{idx}"] if idx > 0 else []
        steps.append(
            {
                "id": step_id,
                "description": step_text.format_map(safe_vars),
                "dependencies": deps,
            }
        )
    return steps

# === MCP PROTOCOL ENDPOINTS ===

@app.get("/")
async def root():
    """Health check"""
    return {
        "name": "sequential-thinking",
        "version": "1.0.0",
        "status": "healthy"
    }

@app.post("/")
async def handle_jsonrpc(request: Request):
    body = await request.json()
    method = body.get("method")
    params = body.get("params", {})
    
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "result": {"tools": TOOLS}
        }
    
    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        
        try:
            if tool_name == "sequential_thinking":
                result = await handle_sequential_thinking(arguments)
            elif tool_name == "sequential_workflow":
                result = await handle_sequential_workflow(arguments)
            else:
                raise HTTPException(status_code=404, detail=f"Tool not found: {tool_name}")
            
            return {
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "result": result
            }
        
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }
    
    else:
        raise HTTPException(status_code=400, detail=f"Unknown method: {method}")

@app.get("/tools")
async def list_tools():
    """List available tools (MCP protocol)"""
    return {"tools": TOOLS}

@app.post("/tools/call")
async def call_tool(request: ToolCallRequest):
    """Execute a tool (MCP protocol)"""
    
    try:
        if request.name == "sequential_thinking":
            result = await handle_sequential_thinking(request.arguments)
        elif request.name == "sequential_workflow":
            result = await handle_sequential_workflow(request.arguments)
        else:
            raise HTTPException(status_code=404, detail=f"Tool not found: {request.name}")
        
        return ToolCallResponse(
            content=[{
                "type": "text",
                "text": str(result)
            }],
            isError=False
        )
    
    except Exception as e:
        return ToolCallResponse(
            content=[{
                "type": "text", 
                "text": f"Error: {str(e)}\n{traceback.format_exc()}"
            }],
            isError=True
        )


# === TOOL HANDLERS ===

async def handle_sequential_thinking(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle sequential_thinking tool call
    
    Connects to Sequential Engine from Phase 1
    """
    # Parse arguments
    description = args["task_description"]
    steps_data = args.get("steps", [])
    max_steps = args.get("max_steps", MAX_STEPS_DEFAULT)
    max_duration = args.get("max_duration", MAX_DURATION_DEFAULT)
    
    # Create task
    if steps_data:
        # User provided steps
        steps = [
            create_step(
                step_id=s.get("id", f"step_{i+1}"),
                query=s["description"],
                dependencies=s.get("dependencies", [])
            )
            for i, s in enumerate(steps_data)
        ]
        task = create_task(
            task_id=f"seq_{uuid4()}",
            description=description,
            steps=steps
        )
    else:
        # Auto-generate deterministic steps from free-form description.
        generated = _generate_steps_from_description(description, max_steps)
        task = create_task(
            task_id=f"seq_{uuid4()}",
            description=description,
            steps=[
                create_step(
                    step_id=item["id"],
                    query=item["description"],
                    dependencies=item.get("dependencies", []),
                )
                for item in generated
            ],
        )
    
    # Execute via Sequential Engine
    result = engine.execute_task(task)
    
    # Format response using SequentialResponse schema
    steps_formatted = [
        StepSchema(
            id=step.id,
            description=step.query,
            status=step.status.value,
            result=str(step.result) if step.result else None,
            error=str(step.error) if step.error else None,
            timestamp=datetime.now().isoformat()
        )
        for step in result.steps
    ]
    
    return SequentialResponse(
        task_id=task.id,
        success=True,
        steps=steps_formatted,
        progress=result.progress()
    ).dict()

async def handle_sequential_workflow(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle sequential_workflow tool call
    
    Resolve a predefined workflow template into executable sequential steps.
    """
    template_id = str(args["template_id"]).strip().lower()
    variables = args.get("variables", {})
    steps = _render_workflow_steps(template_id, variables)

    return {
        "success": True,
        "template_id": template_id,
        "variables": variables,
        "steps": steps,
        "step_count": len(steps),
    }


# === STARTUP ===

if __name__ == "__main__":
    print(f"🚀 Starting Sequential Thinking MCP Server on {HOST}:{PORT}")
    print(f"   Tools available: {len(TOOLS)}")
    print(f"   - sequential_thinking")
    print(f"   - sequential_workflow")
    
    uvicorn.run(
        app, 
        host=HOST, 
        port=PORT,
        log_level="info"
    )
