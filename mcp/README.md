# MCP Module

The Model Context Protocol (MCP) implementation for the assistant proxy. It acts as both a client (consuming other MCP servers) and a coordinator (the Hub).

## Purpose

To manage connections to various MCP servers (like `sql-memory`, `sequential-thinking`) and expose their tools to the Core assistant. It abstracts away the transport details (HTTP vs. SSE vs. STDIO) and provides a unified interface for tool execution.

## Components

### `hub.py` (The MCP Hub)
The central singleton that manages all MCP connections.
- **Discovery**: Connects to configured MCP servers and lists their available tools.
- **Routing**: Automatically routes a tool call (e.g., `memory_save`) to the correct MCP server.
- **System Knowledge**: Automatically saves available tool definitions into the memory graph so the assistant "knows what it can do".

### `client.py`
A high-level client library used by the Core Bridge.
- **Tool Execution**: Wraps `hub.call_tool`.
- **Memory Helpers**: specialized functions for interacting with the `sql-memory` MCP (e.g., `autosave_assistant`, `get_fact_for_query`).

### `transports/`
Contains implementations for different MCP communication protocols:
- `http.py`: For stateless HTTP connections.
- `sse.py`: For Server-Sent Events (streaming).
- `stdio.py`: For local process communication.

## Configuration

The Hub loads its configuration from `mcp_registry.py` (in the parent directory), which defines the available MCP servers and their endpoints.

## Usage

```python
from mcp.hub import get_hub

hub = get_hub()
hub.initialize()

# List tools from all connected servers
tools = hub.list_tools()

# Call a tool (router finds the right server)
result = hub.call_tool("memory_save", {
    "conversation_id": "123",
    "role": "user",
    "content": "Hello"
})
```
