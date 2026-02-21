"""
Container Commander — MCP Hub Bridge
═══════════════════════════════════════
Registers Commander tools in the MCPHub so the KI can use them.
Uses a LocalTransport that calls Commander functions directly.

Usage in hub.py initialize():
    from container_commander.mcp_bridge import register_commander_tools
    register_commander_tools(hub)
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

MCP_NAME = "container-commander"

# These tools are handled by Fast-Lane (direct execution, faster).
# Do NOT register them here — Fast-Lane registers last and would overwrite anyway,
# but filtering here makes the intent explicit and prevents ghost registrations.
_FAST_LANE_NAMES = {"home_read", "home_write", "home_list"}


class CommanderTransport:
    """
    Local transport that routes tool calls directly to
    container_commander.mcp_tools without any HTTP overhead.
    """

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        from container_commander.mcp_tools import call_tool
        return call_tool(tool_name, arguments)

    def list_tools(self) -> list:
        from container_commander.mcp_tools import get_tool_definitions
        return get_tool_definitions()


def register_commander_tools(hub):
    """
    Register all Container Commander tools in the MCPHub.
    Call this during hub.initialize().
    """
    try:
        from container_commander.mcp_tools import get_tool_definitions

        transport = CommanderTransport()
        hub._transports[MCP_NAME] = transport

        tools = get_tool_definitions()
        registered = 0
        for tool in tools:
            tool_name = tool["name"]
            if tool_name in _FAST_LANE_NAMES:
                continue  # Fast-Lane handles these — skip to avoid ghost registration
            tool["mcp"] = MCP_NAME  # So persona.py can detect Commander tools
            hub._tools_cache[tool_name] = MCP_NAME
            hub._tool_definitions[tool_name] = tool
            registered += 1

        logger.info(f"[MCP-Commander] Registered {registered} tools in MCPHub (skipped {len(tools) - registered} Fast-Lane duplicates)")

    except Exception as e:
        logger.error(f"[MCP-Commander] Registration failed: {e}")
