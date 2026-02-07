"""
Skill Memory Client: Records skill execution metrics to mcp-sql-memory.

Calls the MCP service via HTTP JSON-RPC to track success/failure,
execution time, and error details for each skill run.
"""

import json
import os
import time
import httpx
from typing import Optional, Dict

MEMORY_URL = os.getenv("MEMORY_URL", "http://mcp-sql-memory:8081")

# FastMCP requires both Accept types
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _parse_sse_response(text: str) -> Optional[Dict]:
    """Parse SSE response from FastMCP to extract JSON-RPC result."""
    for line in text.strip().split("\n"):
        if line.startswith("data: "):
            try:
                return json.loads(line[6:])
            except json.JSONDecodeError:
                pass
    return None


async def _mcp_call(tool_name: str, arguments: dict) -> Optional[Dict]:
    """Make a JSON-RPC call to mcp-sql-memory."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{MEMORY_URL}/mcp",
                headers=_HEADERS,
                json={
                    "jsonrpc": "2.0",
                    "id": int(time.time() * 1000),
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": arguments,
                    }
                }
            )
            if response.status_code == 200:
                parsed = _parse_sse_response(response.text)
                if parsed:
                    return parsed.get("result", {}).get("structuredContent", {})
    except Exception as e:
        print(f"[SkillMemory] MCP call '{tool_name}' failed: {e}")
    return None


async def record_execution(
    skill_id: str,
    success: bool,
    exec_time_ms: float,
    error: Optional[str] = None,
    version: str = "1.0"
) -> Optional[Dict]:
    """Record a skill execution result in the central database."""
    return await _mcp_call("skill_metric_record", {
        "skill_id": skill_id,
        "success": success,
        "exec_time_ms": exec_time_ms,
        "error": error,
        "version": version,
    })


async def get_metrics(skill_id: str) -> Optional[Dict]:
    """Get metrics for a specific skill."""
    return await _mcp_call("skill_metric_get", {"skill_id": skill_id})


async def list_all_metrics(status: Optional[str] = None) -> list:
    """List all skill metrics."""
    args = {"limit": 100}
    if status:
        args["status"] = status
    result = await _mcp_call("skill_metrics_list", args)
    if result:
        return result.get("structuredContent", {}).get("metrics", [])
    return []
