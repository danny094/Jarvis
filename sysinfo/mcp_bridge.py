"""
SysInfo MCP Bridge — Registriert SysInfo-Tools im MCPHub
"""
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)
MCP_NAME = "sysinfo"


class SysInfoTransport:
    """Local transport — kein HTTP, direkte Python-Calls."""

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        from sysinfo.mcp_tools import call_tool
        return call_tool(tool_name, arguments)

    def list_tools(self) -> list:
        from sysinfo.mcp_tools import get_tool_definitions
        return get_tool_definitions()


def register_sysinfo_tools(hub) -> None:
    """Registriert alle SysInfo-Tools im MCPHub."""
    try:
        from sysinfo.mcp_tools import get_tool_definitions

        transport = SysInfoTransport()
        hub._transports[MCP_NAME] = transport

        tools = get_tool_definitions()
        for tool in tools:
            tool_name = tool["name"]
            tool["mcp"] = MCP_NAME
            hub._tools_cache[tool_name] = MCP_NAME
            hub._tool_definitions[tool_name] = tool

        logger.info(f"[MCPHub] SysInfo: {len(tools)} tools registered "
                    f"({', '.join(t['name'] for t in tools)})")
    except Exception as e:
        logger.error(f"[MCPHub] SysInfo registration failed: {e}")
