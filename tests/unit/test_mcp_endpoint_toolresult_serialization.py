"""
Regression tests for MCP endpoint ToolResult serialization.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import types
from unittest.mock import MagicMock, patch

from fastapi import APIRouter
from core.tools.tool_result import ToolResult


def _load_mcp_endpoint_module():
    """
    Load mcp/endpoint.py with a stubbed installer router.
    This avoids optional runtime dependency on python-multipart in tests.
    """
    root = "/DATA/AppData/MCP/Jarvis/Jarvis"
    installer_stub = types.ModuleType("mcp.installer")
    installer_stub.router = APIRouter()
    with patch.dict(sys.modules, {"mcp.installer": installer_stub}):
        spec = importlib.util.spec_from_file_location(
            "mcp_endpoint_toolresult_test",
            os.path.join(root, "mcp", "endpoint.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


mcp_endpoint = _load_mcp_endpoint_module()


class _DummyRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


def _tools_call_payload(name: str, arguments: dict):
    return {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


def test_tools_call_serializes_fast_lane_toolresult_success():
    hub = MagicMock()
    hub.call_tool.return_value = ToolResult.from_fast_lane(
        content={"written": True},
        tool_name="home_write",
        latency_ms=1.2,
    )
    request = _DummyRequest(_tools_call_payload("home_write", {"path": "notes/a.txt", "content": "x"}))

    with patch.object(mcp_endpoint, "get_hub", return_value=hub):
        response = asyncio.run(mcp_endpoint.mcp_handler(request))

    body = json.loads(response.body.decode("utf-8"))
    assert "error" not in body
    assert body["id"] == 7
    assert body["result"]["tool_name"] == "home_write"
    assert body["result"]["success"] is True
    assert body["result"]["content"] == {"written": True}


def test_tools_call_maps_fast_lane_toolresult_error_to_jsonrpc_error():
    hub = MagicMock()
    hub.call_tool.return_value = ToolResult.from_error(
        error="read failed",
        tool_name="home_read",
        execution_mode="fast_lane",
    )
    request = _DummyRequest(_tools_call_payload("home_read", {"path": "notes/missing.txt"}))

    with patch.object(mcp_endpoint, "get_hub", return_value=hub):
        response = asyncio.run(mcp_endpoint.mcp_handler(request))

    body = json.loads(response.body.decode("utf-8"))
    assert "error" in body
    assert body["error"]["code"] == -32000
    assert "read failed" in body["error"]["message"]


def test_tools_call_keeps_dict_error_behavior():
    hub = MagicMock()
    hub.call_tool.return_value = {"error": "Tool not available"}
    request = _DummyRequest(_tools_call_payload("unknown_tool", {}))

    with patch.object(mcp_endpoint, "get_hub", return_value=hub):
        response = asyncio.run(mcp_endpoint.mcp_handler(request))

    body = json.loads(response.body.decode("utf-8"))
    assert body["error"]["code"] == -32000
    assert "Tool not available" in body["error"]["message"]
