"""
Storage Broker MCP Server — Entry Point
════════════════════════════════════════
FastMCP server for TRION Storage Governance.
Port: 8089
"""

import logging
import os
from fastmcp import FastMCP
from .tools import register_tools

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


def main():
    print("\n" + "=" * 50)
    print("🗄  STORAGE BROKER MCP SERVER — START")
    print("=" * 50)

    print("→ Creating MCP server…")
    mcp = FastMCP("storage_broker")
    print("✓ MCP instance active")

    print("→ Registering tools…")
    register_tools(mcp)
    print("✓ Tools loaded")

    try:
        tool_names = [t.name for t in mcp.tools]
        print(f"\n🔧 Available Tools ({len(tool_names)}):")
        for name in tool_names:
            print(f"   • {name}")
    except Exception:
        pass

    print("\n" + "=" * 50)
    print("🚀 SERVER READY — Listening on :8089 (streamable-http)")
    print("=" * 50 + "\n")

    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8089,
        path="/mcp",
        stateless_http=True,
    )


if __name__ == "__main__":
    main()
