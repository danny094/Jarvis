import pytest
import asyncio
from mcp.hub import get_hub
from utils.logger import log_info

@pytest.mark.asyncio
async def test_safe_tool_execution():
    """Executes safe, read-only tools to verify end-to-end pipeline."""
    hub = get_hub()
    hub.initialize()
    
    # 1. Graph Stats
    log_info("Testing memory_graph_stats...")
    stats = hub.call_tool("memory_graph_stats", {})
    assert "error" not in stats
    # Expect some keys like 'total_facts', 'total_edges'
    assert isinstance(stats, dict)
    
    # 2. Time (if available)
    mcps = hub.list_mcps()
    time_mcp = next((m for m in mcps if m["name"] == "time-mcp"), None)
    
    if time_mcp and time_mcp["online"] and time_mcp["tools_count"] > 0:
        log_info("Testing get_current_time...")
        time_res = hub.call_tool("get_current_time", {})
        assert "error" not in time_res
        # Result is likely a list of TextContent or a dict
        log_info(f"Time result: {time_res}")
    else:
        log_info("Skipping get_current_time (MCP offline)")

@pytest.mark.asyncio
async def test_sequential_thinking_execution():
    """Executes a simple sequential thinking task."""
    hub = get_hub()
    hub.initialize()
    
    # This calls the sequential-thinking MCP directly
    # Note: sequential-thinking usually requires a complex structure.
    # We will try a simple 'validate' or 'analyze' if available, 
    # or just check if we can list its tools (already covered in health).
    # Actually, the sequential-thinking MCP exposes 'sequential_thinking' tool.
    
    # Let's try calling it with a dummy thought data
    log_info("Testing sequential_thinking tool...")
    
    # Based on MCP definition, it takes (thought, thoughtNumber, totalThoughts, nextThoughtNeeded)
    result = hub.call_tool("sequential_thinking", {
        "thought": "Test thought for reliability check",
        "thoughtNumber": 1,
        "totalThoughts": 2,
        "nextThoughtNeeded": True
    })
    
    assert "error" not in result
    # It should return some confirmation
    log_info(f"Sequential result: {result}")
