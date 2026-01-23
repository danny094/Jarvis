# PHASE 2 - TASK 1: MCP SERVER FOR SEQUENTIAL THINKING
**Duration:** 3 hours  
**Location:** mcp-servers/sequential-thinking/

---

## STEP 1.1: MCP Server Setup (30 min)

### **Create Directory Structure:**

```bash
mcp-servers/sequential-thinking/
├─ __init__.py
├─ server.py              # Main MCP server
├─ tools.py               # Tool definitions
├─ requirements.txt
└─ README.md
```

---

### **File: server.py**

```python
"""
Sequential Thinking MCP Server

Provides "sequential_thinking" tool to MCP Hub
"""

import sys
import os
from pathlib import Path

# Add Jarvis root to path
JARVIS_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(JARVIS_ROOT))

from modules.sequential_thinking.engine import SequentialThinkingEngine
from modules.sequential_thinking.types import create_task, create_step
from mcp.server import MCPServer
from typing import Dict, Any, List
import json
import traceback
from uuid import uuid4

class SequentialThinkingServer:
    """MCP Server for Sequential Thinking"""
    
    def __init__(self):
        self.engine = SequentialThinkingEngine()
        self.server = MCPServer(name="sequential-thinking")
        self._register_tools()
    
    def _register_tools(self):
        """Register all tools"""
        
        # Tool 1: Execute Sequential Task
        self.server.register_tool(
            name="sequential_thinking",
            description="Execute complex tasks step-by-step with Frank's CIM validation",
            parameters={
                "task_description": {
                    "type": "string",
                    "required": True,
                    "description": "Description of the task to execute"
                },
                "steps": {
                    "type": "array",
                    "required": False,
                    "description": "Optional: Predefined steps",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "description": {"type": "string"},
                            "dependencies": {"type": "array", "items": {"type": "string"}}
                        }
                    }
                },
                "max_steps": {
                    "type": "integer",
                    "required": False,
                    "default": 100,
                    "description": "Maximum number of steps to execute"
                },
                "max_duration": {
                    "type": "integer",
                    "required": False,
                    "default": 3600,
                    "description": "Maximum execution time in seconds"
                }
            },
            handler=self.handle_sequential_thinking
        )
        
        # Tool 2: Get Workflow Template
        self.server.register_tool(
            name="sequential_workflow",
            description="Get a predefined workflow template",
            parameters={
                "template_id": {
                    "type": "string",
                    "required": True,
                    "description": "Template ID (data_analysis, research, code_review, decision_making)"
                },
                "variables": {
                    "type": "object",
                    "required": False,
                    "description": "Template variables"
                }
            },
            handler=self.handle_workflow_template
        )
    
    async def handle_sequential_thinking(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle sequential_thinking tool call
        """
        try:
            # Parse parameters
            description = params["task_description"]
            steps_data = params.get("steps", [])
            max_steps = params.get("max_steps", 100)
            max_duration = params.get("max_duration", 3600)
            
            # Create task
            if steps_data:
                # User provided steps
                steps = [
                    create_step(
                        id=s.get("id", f"step_{i+1}"),
                        description=s["description"],
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
                # Auto-generate steps (TODO: use LLM)
                # For now, create simple single-step task
                task = create_task(
                    task_id=f"seq_{uuid4()}",
                    description=description,
                    steps=[create_step("step_1", description)]
                )
            
            # Execute
            result = self.engine.execute_task(
                task,
                max_steps=max_steps,
                max_duration_seconds=max_duration
            )
            
            # Format response
            return {
                "success": True,
                "task_id": task.id,
                "progress": result.progress(),
                "completed_steps": len(result.completed_steps()),
                "failed_steps": len(result.failed_steps()),
                "total_steps": len(result.steps),
                "state_file": str(result.state_file) if result.state_file else None,
                "memory_used_mb": self.engine.memory.get_size_mb(),
                "steps": [
                    {
                        "id": step.id,
                        "description": step.description,
                        "status": step.status.value,
                        "result": step.result,
                        "error": step.error
                    }
                    for step in result.steps
                ]
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc()
            }
    
    async def handle_workflow_template(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle workflow template request
        """
        try:
            template_id = params["template_id"]
            variables = params.get("variables", {})
            
            # Get workflow (will be implemented in Task 3)
            # For now, return template info
            
            return {
                "success": True,
                "template_id": template_id,
                "message": "Workflow templates coming in Task 3!"
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def run(self, host="0.0.0.0", port=8001):
        """Start the MCP server"""
        self.server.run(host=host, port=port)


if __name__ == "__main__":
    server = SequentialThinkingServer()
    server.run()
```

---

### **File: requirements.txt**

```
fastapi>=0.104.0
uvicorn>=0.24.0
pydantic>=2.4.0
```

---

### **File: README.md**

```markdown
# Sequential Thinking MCP Server

MCP Server providing Sequential Thinking capabilities.

## Tools

### 1. sequential_thinking
Execute complex tasks step-by-step with validation.

**Parameters:**
- task_description: Description of task
- steps: Optional predefined steps
- max_steps: Maximum steps (default: 100)
- max_duration: Maximum duration in seconds (default: 3600)

**Returns:**
- success: True/False
- progress: 0.0 to 1.0
- steps: List of steps with status
- state_file: Path to state file

### 2. sequential_workflow
Get predefined workflow template.

**Parameters:**
- template_id: Template identifier
- variables: Template variables

## Running

```bash
cd mcp-servers/sequential-thinking
python server.py
```

Server runs on port 8001.
```

---

## STEP 1.2: MCP Hub Integration (1h)

### **Modify: mcp/hub.py**

Add Sequential Thinking server to hub:

```python
# mcp/hub.py (add to servers list)

SERVERS = {
    # ... existing servers ...
    
    "sequential-thinking": {
        "url": "http://localhost:8001",
        "enabled": True,
        "description": "Sequential Thinking with Frank's CIM"
    }
}
```

---

### **Modify: mcp/endpoint.py**

Add route for Sequential Thinking:

```python
# mcp/endpoint.py (add route)

@router.post("/mcp/sequential")
async def sequential_thinking(request: Request):
    """
    Call Sequential Thinking tool
    """
    data = await request.json()
    
    result = await mcp_client.call_tool(
        server="sequential-thinking",
        tool="sequential_thinking",
        params=data
    )
    
    return result
```

---

## STEP 1.3: Testing (1h)

### **File: test_mcp_sequential.py**

```python
"""
Integration tests for Sequential Thinking MCP Server
"""

import pytest
import requests

MCP_BASE = "http://localhost:8000"  # Jarvis main server
SEQ_BASE = "http://localhost:8001"  # Sequential server

def test_sequential_server_health():
    """Test if Sequential server is running"""
    response = requests.get(f"{SEQ_BASE}/health")
    assert response.status_code == 200

def test_simple_task():
    """Test simple 3-step task"""
    data = {
        "task_description": "Analyze sales data",
        "steps": [
            {"id": "load", "description": "Load data"},
            {"id": "analyze", "description": "Analyze trends", "dependencies": ["load"]},
            {"id": "report", "description": "Generate report", "dependencies": ["analyze"]}
        ]
    }
    
    response = requests.post(f"{MCP_BASE}/mcp/sequential", json=data)
    result = response.json()
    
    assert result["success"] == True
    assert result["progress"] == 1.0
    assert len(result["steps"]) == 3

def test_auto_generation():
    """Test with auto step generation"""
    data = {
        "task_description": "Research AI trends"
    }
    
    response = requests.post(f"{MCP_BASE}/mcp/sequential", json=data)
    result = response.json()
    
    assert result["success"] == True
    assert len(result["steps"]) > 0

def test_error_handling():
    """Test error handling"""
    data = {
        "task_description": ""  # Invalid
    }
    
    response = requests.post(f"{MCP_BASE}/mcp/sequential", json=data)
    result = response.json()
    
    # Should handle gracefully
    assert "error" in result or result["success"] == False
```

---

## DELIVERABLES

```
✅ MCP Server created (mcp-servers/sequential-thinking/)
✅ Tool "sequential_thinking" registered
✅ Tool "sequential_workflow" registered
✅ MCP Hub integration
✅ Endpoint in mcp/endpoint.py
✅ Tests passing

Result: Sequential Thinking available via MCP!
```

---

**Time:** 3 hours  
**Next:** Task 2 - JarvisWebUI Integration
