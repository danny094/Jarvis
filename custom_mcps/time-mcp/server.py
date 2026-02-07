#!/usr/bin/env python3
"""
Time MCP Server - Simple
Provides current time information via MCP protocol
"""
import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent


# Create server instance
app = Server("time-mcp")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available time tools."""
    return [
        Tool(
            name="get_current_time",
            description="Get the current time in various formats (UTC, local, ISO, timestamp)",
            inputSchema={
                "type": "object",
                "properties": {
                    "format": {
                        "type": "string",
                        "enum": ["utc", "local", "iso", "timestamp", "all"],
                        "description": "Time format to return",
                        "default": "all"
                    }
                }
            }
        ),
        Tool(
            name="get_timezone",
            description="Get system timezone information",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle tool calls."""
    
    if name == "get_current_time":
        format_type = arguments.get("format", "all")
        
        now_utc = datetime.now(timezone.utc)
        now_local = datetime.now()
        
        result = {}
        
        if format_type in ["utc", "all"]:
            result["utc"] = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
        
        if format_type in ["local", "all"]:
            result["local"] = now_local.strftime("%Y-%m-%d %H:%M:%S")
        
        if format_type in ["iso", "all"]:
            result["iso"] = now_utc.isoformat()
        
        if format_type in ["timestamp", "all"]:
            result["timestamp"] = int(now_utc.timestamp())
        
        return [
            TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )
        ]
    
    elif name == "get_timezone":
        now_local = datetime.now()
        tz_offset = now_local.astimezone().utcoffset()
        
        result = {
            "timezone_name": str(now_local.astimezone().tzinfo),
            "utc_offset_hours": tz_offset.total_seconds() / 3600 if tz_offset else 0,
            "is_dst": bool(now_local.astimezone().dst())
        }
        
        return [
            TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )
        ]
    
    else:
        raise ValueError(f"Unknown tool: {name}")


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
