"""
MCP Tool Definitions for Sequential Thinking
"""

from typing import Dict, Any

# Tool 1: Sequential Thinking
SEQUENTIAL_THINKING_TOOL = {
    "name": "sequential_thinking",
    "description": "Execute complex tasks step-by-step with Frank's CIM validation",
    "inputSchema": {
        "type": "object",
        "properties": {
            "task_description": {
                "type": "string",
                "description": "Description of the task to execute"
            },
            "steps": {
                "type": "array",
                "description": "Optional: Predefined steps",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "description": {"type": "string"},
                        "dependencies": {
                            "type": "array",
                            "items": {"type": "string"}
                        }
                    },
                    "required": ["id", "description"]
                }
            },
            "max_steps": {
                "type": "integer",
                "description": "Maximum number of steps to execute (default: 100)"
            },
            "max_duration": {
                "type": "integer",
                "description": "Maximum execution time in seconds (default: 3600)"
            }
        },
        "required": ["task_description"]
    }
}

# Tool 2: Sequential Workflow (placeholder for Task 3)
SEQUENTIAL_WORKFLOW_TOOL = {
    "name": "sequential_workflow",
    "description": "Get a predefined workflow template",
    "inputSchema": {
        "type": "object",
        "properties": {
            "template_id": {
                "type": "string",
                "description": "Template ID (data_analysis, research, code_review, decision_making)"
            },
            "variables": {
                "type": "object",
                "description": "Template variables"
            }
        },
        "required": ["template_id"]
    }
}

# All tools
TOOLS = [
    SEQUENTIAL_THINKING_TOOL,
    SEQUENTIAL_WORKFLOW_TOOL
]
