import threading
import time
from typing import Any, Dict, List

import pytest

from core.autonomous.loop_engine import LoopEngine
from core.tools.tool_result import ToolResult
from mcp.hub import MCPHub


def test_mcp_hub_refresh_re_registers_fast_lane_tools():
    hub = MCPHub()
    hub._transports = {"sql-memory": object(), "skill-server": object()}

    calls: List[str] = []

    def _discover(name: str):
        calls.append(f"discover:{name}")

    def _fast_lane():
        calls.append("fast_lane")

    def _auto_register():
        calls.append("auto_register")

    hub._discover_tools = _discover  # type: ignore[assignment]
    hub._register_fast_lane_tools = _fast_lane  # type: ignore[assignment]
    hub._auto_register_tools = _auto_register  # type: ignore[assignment]

    hub.refresh()

    assert "fast_lane" in calls
    assert "auto_register" in calls
    assert calls.index("fast_lane") < calls.index("auto_register")


class _FakeResponse:
    def __init__(self, payload: Dict[str, Any]):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _fake_async_client_factory(payloads: List[Dict[str, Any]]):
    state = {"idx": 0}

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json):
            idx = state["idx"]
            state["idx"] += 1
            payload = payloads[idx] if idx < len(payloads) else payloads[-1]
            return _FakeResponse(payload)

    return _FakeAsyncClient


class _FakeHub:
    def __init__(self, result: Any):
        self._result = result

    def call_tool(self, tool_name, tool_args):
        return self._result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_result",
    [
        {"error": "boom-dict"},
        '{"error":"boom-string"}',
        ToolResult.from_error(error="boom-toolresult", tool_name="memory_search"),
    ],
)
async def test_loop_engine_treats_error_payload_as_tool_failure(monkeypatch, tool_result):
    payloads = [
        {
            "message": {
                "tool_calls": [
                    {"function": {"name": "memory_search", "arguments": {"query": "x"}}}
                ],
                "content": "",
            }
        },
        {"message": {"tool_calls": [], "content": "done"}},
    ]
    fake_client = _fake_async_client_factory(payloads)
    monkeypatch.setattr("core.autonomous.loop_engine.httpx.AsyncClient", fake_client)

    engine = LoopEngine(ollama_base="http://fake", model="fake-model")
    engine._hub = _FakeHub(tool_result)
    engine._get_ollama_tools = lambda: []  # type: ignore[assignment]

    events = []
    async for chunk, done, meta in engine.run_stream(
        user_text="run",
        system_prompt="sys",
        max_iterations=2,
    ):
        events.append((chunk, done, meta))
        if done:
            break

    tool_results = [meta for _, _, meta in events if meta.get("type") == "loop_tool_result"]
    assert tool_results, "Expected at least one loop_tool_result event"
    assert tool_results[0].get("success") is False
    assert "boom" in str(tool_results[0].get("error", "")).lower()


@pytest.mark.asyncio
async def test_loop_engine_stream_path_yields_content_without_sync_fallback(monkeypatch):
    engine = LoopEngine(ollama_base="http://fake", model="fake-model")
    engine._hub = _FakeHub({"ok": True})
    engine._get_ollama_tools = lambda: []  # type: ignore[assignment]

    async def _fake_iter_chat_stream(*_args, **_kwargs):
        yield {"message": {"content": "abc"}}
        yield {"message": {"content": "def"}, "done": True}

    async def _fail_sync(*_args, **_kwargs):
        raise AssertionError("sync fallback should not be used")

    monkeypatch.setattr(engine, "_iter_chat_stream", _fake_iter_chat_stream)
    monkeypatch.setattr(engine, "_chat_once_sync", _fail_sync)

    chunks: List[str] = []
    done_meta: Dict[str, Any] = {}
    async for chunk, done, meta in engine.run_stream(
        user_text="run",
        system_prompt="sys",
        max_iterations=1,
    ):
        if chunk:
            chunks.append(chunk)
        if done:
            done_meta = meta
            break

    assert "".join(chunks) == "abcdef"
    assert done_meta.get("type") == "done"
    assert done_meta.get("iterations") == 1


@pytest.mark.asyncio
async def test_loop_engine_output_char_cap_truncates_and_stops(monkeypatch):
    engine = LoopEngine(ollama_base="http://fake", model="fake-model")
    engine._hub = _FakeHub({"ok": True})
    engine._get_ollama_tools = lambda: []  # type: ignore[assignment]

    async def _fake_iter_chat_stream(*_args, **_kwargs):
        yield {"message": {"content": "abcdef"}, "done": True}

    monkeypatch.setattr(engine, "_iter_chat_stream", _fake_iter_chat_stream)

    chunks: List[str] = []
    done_meta: Dict[str, Any] = {}
    async for chunk, done, meta in engine.run_stream(
        user_text="run",
        system_prompt="sys",
        max_iterations=1,
        output_char_cap=4,
    ):
        if chunk:
            chunks.append(chunk)
        if done:
            done_meta = meta
            break

    assert chunks[0] == "abcd"
    assert any("Output-Budget" in c for c in chunks[1:])
    assert done_meta.get("truncated") is True


def test_mcp_hub_refresh_blocks_call_tool_until_registry_is_consistent():
    class _FakeTransport:
        def call_tool(self, tool_name, arguments):
            return {"ok": True, "tool": tool_name, "arguments": arguments}

    hub = MCPHub()
    hub._initialized = True
    hub._transports = {"demo-mcp": _FakeTransport()}
    hub._tools_cache = {"demo_tool": "demo-mcp"}
    hub._tool_definitions = {"demo_tool": {"name": "demo_tool"}}

    refresh_has_cleared = threading.Event()
    allow_refresh_to_finish = threading.Event()

    def _discover(name: str):
        refresh_has_cleared.set()
        allow_refresh_to_finish.wait(timeout=1.0)
        hub._tools_cache["demo_tool"] = "demo-mcp"
        hub._tool_definitions["demo_tool"] = {"name": "demo_tool"}

    hub._discover_tools = _discover  # type: ignore[assignment]
    hub._register_fast_lane_tools = lambda: None  # type: ignore[assignment]
    hub._auto_register_tools = lambda: None  # type: ignore[assignment]

    refresh_thread = threading.Thread(target=hub.refresh)
    refresh_thread.start()
    assert refresh_has_cleared.wait(timeout=1.0)

    call_result: Dict[str, Any] = {}

    def _call_tool():
        call_result["value"] = hub.call_tool("demo_tool", {"x": 1})

    call_thread = threading.Thread(target=_call_tool)
    call_thread.start()
    time.sleep(0.05)
    assert call_thread.is_alive(), "call_tool should wait while refresh holds registry lock"

    allow_refresh_to_finish.set()
    refresh_thread.join(timeout=1.0)
    call_thread.join(timeout=1.0)

    assert call_result["value"]["ok"] is True
    assert call_result["value"]["tool"] == "demo_tool"
