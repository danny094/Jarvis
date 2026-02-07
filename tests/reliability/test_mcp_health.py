import pytest
import asyncio
from mcp.hub import get_hub
from utils.logger import log_info

@pytest.mark.asyncio
async def test_core_mcps_online():
    """Verifies that all Core MCPs are online and healthy."""
    hub = get_hub()
    hub.initialize()
    
    # Refresh to get latest state
    hub.refresh()
    
    mcps = hub.list_mcps()
    mcp_map = {m["name"]: m for m in mcps}
    
    log_info(f"MCP Status: {mcp_map}")
    
    # 1. SQL Memory (Critical)
    assert "sql-memory" in mcp_map, "SQL Memory MCP missing"
    mem = mcp_map["sql-memory"]
    assert mem["online"], "SQL Memory is OFFLINE"
    assert mem["tools_count"] >= 20, f"SQL Memory tools too low: {mem['tools_count']}"

    # 2. Sequential Thinking (Critical)
    assert "sequential-thinking" in mcp_map, "Sequential Thinking MCP missing"
    seq = mcp_map["sequential-thinking"]
    assert seq["online"], "Sequential Thinking is OFFLINE"
    assert seq["tools_count"] >= 3, f"Sequential Thinking tools too low: {seq['tools_count']}"

    # 3. CIM (Critical)
    assert "cim" in mcp_map, "CIM MCP missing"
    cim = mcp_map["cim"]
    assert cim["online"], "CIM is OFFLINE"
    assert cim["tools_count"] >= 5, f"CIM tools too low: {cim['tools_count']}"

@pytest.mark.asyncio
async def test_time_mcp_registration():
    """Verifies time-mcp registration (allow offline for CI env)."""
    hub = get_hub()
    # No refresh needed if run after previous test, but good practice
    
    mcps = hub.list_mcps()
    mcp_map = {m["name"]: m for m in mcps}
    
    assert "time-mcp" in mcp_map, "Time MCP missing from registry"
    
    # In strict CI, we might assert online, but here we warn
    time_mcp = mcp_map["time-mcp"]
    if not time_mcp["online"]:
        pytest.skip("Time MCP is offline (Environmental Timeout Known)")
    
    assert time_mcp["tools_count"] > 0, "Time MCP is online but has 0 tools"
