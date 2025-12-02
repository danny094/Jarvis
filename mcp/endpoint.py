# mcp/endpoint.py
"""
MCP Endpoint - Der einzige Endpoint den WebUIs eintragen müssen.

Stellt das MCP-Protokoll (Streamable HTTP) bereit.
Übersetzt intern zu allen Backend-MCPs (HTTP/SSE/STDIO).

WebUI trägt ein: http://bridge:8100/mcp
Und sieht alle Tools von allen MCPs als eine Liste.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
import json
from typing import Dict, Any

from mcp.hub import get_hub
from utils.logger import log_info, log_error, log_debug

router = APIRouter()


@router.post("/mcp")
async def mcp_handler(request: Request):
    """
    Universeller MCP Endpoint (JSON-RPC über HTTP).
    
    Unterstützte Methoden:
    - initialize: Client-Initialisierung
    - tools/list: Liste aller verfügbaren Tools
    - tools/call: Tool ausführen
    """
    try:
        data = await request.json()
        method = data.get("method", "")
        params = data.get("params", {})
        request_id = data.get("id", 1)
        
        log_debug(f"[MCP-Endpoint] Method: {method}")
        
        hub = get_hub()
        
        # ─────────────────────────────────────────────────────────────
        # INITIALIZE
        # ─────────────────────────────────────────────────────────────
        if method == "initialize":
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {
                        "name": "jarvis-mcp-hub",
                        "version": "1.0.0"
                    },
                    "capabilities": {
                        "tools": {"listChanged": True}
                    }
                }
            })
        
        # ─────────────────────────────────────────────────────────────
        # TOOLS/LIST - Aggregierte Liste aller MCPs
        # ─────────────────────────────────────────────────────────────
        elif method == "tools/list":
            tools = hub.list_tools()
            
            log_info(f"[MCP-Endpoint] tools/list → {len(tools)} tools")
            
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": tools
                }
            })
        
        # ─────────────────────────────────────────────────────────────
        # TOOLS/CALL - Routet zum richtigen MCP
        # ─────────────────────────────────────────────────────────────
        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            
            if not tool_name:
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32602,
                        "message": "Missing tool name"
                    }
                })
            
            log_info(f"[MCP-Endpoint] tools/call → {tool_name}")
            
            result = hub.call_tool(tool_name, arguments)
            
            # Check for error
            if isinstance(result, dict) and "error" in result:
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": result["error"]
                    }
                })
            
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            })
        
        # ─────────────────────────────────────────────────────────────
        # UNKNOWN METHOD
        # ─────────────────────────────────────────────────────────────
        else:
            log_error(f"[MCP-Endpoint] Unknown method: {method}")
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            })
            
    except Exception as e:
        log_error(f"[MCP-Endpoint] Error: {e}")
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": 1,
            "error": {
                "code": -32603,
                "message": str(e)
            }
        }, status_code=500)


# ═══════════════════════════════════════════════════════════════
# MANAGEMENT ENDPOINTS (für WebUI / Debugging)
# ═══════════════════════════════════════════════════════════════

@router.get("/mcp/status")
async def mcp_status():
    """Status aller MCPs."""
    hub = get_hub()
    return JSONResponse({
        "mcps": hub.list_mcps(),
        "total_tools": len(hub.list_tools())
    })


@router.post("/mcp/refresh")
async def mcp_refresh():
    """Aktualisiert Tool-Liste von allen MCPs."""
    hub = get_hub()
    hub.refresh()
    return JSONResponse({
        "status": "ok",
        "total_tools": len(hub.list_tools())
    })


@router.get("/mcp/tools")
async def mcp_tools():
    """Liste aller verfügbaren Tools."""
    hub = get_hub()
    tools = hub.list_tools()
    
    # Gruppiere nach MCP
    by_mcp = {}
    for tool in tools:
        tool_name = tool.get("name", "")
        mcp_name = hub.get_mcp_for_tool(tool_name) or "unknown"
        
        if mcp_name not in by_mcp:
            by_mcp[mcp_name] = []
        by_mcp[mcp_name].append(tool)
    
    return JSONResponse({
        "total": len(tools),
        "by_mcp": by_mcp
    })
