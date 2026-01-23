# MCP Servers

Model Context Protocol (MCP) servers that extend TRION's capabilities with specialized tools.

## Overview

MCP servers provide modular, extensible functionality that can be called by the Core pipeline. Each server is a standalone FastAPI application that communicates via HTTP.

## Available Servers

### Sequential Thinking

- **Path**: `sequential-thinking/`
- **Port**: 8011
- **Purpose**: Step-by-step reasoning for complex queries
- **Tools**:
  - `think`: Perform sequential thinking with configurable steps
  - `get_status`: Check thinking progress

### CIM Server

- **Path**: `cim-server/`
- **Port**: 8012
- **Purpose**: Causal Inference Module for hallucination detection
- **Tools**:
  - `analyze`: Analyze query for potential hallucination risks
  - `validate`: Validate response against source data

### Network Telemetry

- **Path**: `network-telemetry/`
- **Purpose**: Network monitoring and diagnostics
- **Status**: Experimental

## Architecture

```
┌─────────────────────────────────────────────┐
│              MCP Registry                    │
│         (mcp_registry.py)                    │
└──────────────────┬──────────────────────────┘
                   │
       ┌───────────┼───────────┐
       │           │           │
       ▼           ▼           ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│Sequential│ │   CIM    │ │  Other   │
│ Thinking │ │  Server  │ │  MCPs    │
│  :8011   │ │  :8012   │ │   ...    │
└──────────┘ └──────────┘ └──────────┘
```

## Creating a New MCP Server

1. Create a new directory under `mcp-servers/`
2. Create `main.py` with FastMCP:

```python
from fastmcp import FastMCP

mcp = FastMCP("my-server")

@mcp.tool()
def my_tool(param: str) -> str:
    """Tool description"""
    return f"Result: {param}"

if __name__ == "__main__":
    mcp.run()
```

1. Add Dockerfile
2. Register in `docker-compose.yml`
3. Add to `mcp_registry.py`

## Configuration

MCP servers are configured in `docker-compose.yml`:

```yaml
mcp-sequential:
  build: ./mcp-servers/sequential-thinking
  ports:
    - "8011:8011"
  environment:
    - OLLAMA_BASE=http://ollama:11434
```
