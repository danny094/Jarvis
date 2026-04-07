"""
Unit-Tests für WorkspaceEventEmitter.

Phase 1 — kein Behavior-Change:
  - persist() baut korrektes SSE-dict und parst entry_id robust
  - persist_container() normalisiert container_evt korrekt
  - persist_and_broadcast() ruft emit_activity auf, gibt sse_dict=None zurück
  - graceful None wenn Fast-Lane fehlt oder entry_id nicht parsbar

Alle Tests mocken die Fast-Lane (hub.call_tool) — kein DB-Aufruf.
"""

from __future__ import annotations

import json
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# container_commander.ws_stream wird in Tests nicht gebraucht — in sys.modules mocken
# damit die lokalen Imports im Emitter nicht fehlschlagen.
_mock_ws_stream = MagicMock()
sys.modules.setdefault("container_commander.ws_stream", _mock_ws_stream)

from core.workspace_event_emitter import (  # noqa: E402
    WorkspaceEventEmitter,
    WorkspaceEventResult,
    _parse_entry_id,
    get_workspace_emitter,
)


# ---------------------------------------------------------------------------
# _parse_entry_id
# ---------------------------------------------------------------------------

class TestParseEntryId:
    def test_toolresult_content_json_string(self):
        result = MagicMock()
        result.content = json.dumps({"id": 42, "status": "saved"})
        assert _parse_entry_id(result) == 42

    def test_dict_structuredcontent(self):
        result = {"structuredContent": {"id": 7}}
        assert _parse_entry_id(result) == 7

    def test_dict_direct_id(self):
        result = {"id": 99}
        assert _parse_entry_id(result) == 99

    def test_plain_json_string(self):
        assert _parse_entry_id('{"id": 5}') == 5

    def test_toolresult_broken_json(self):
        result = MagicMock()
        result.content = "not-json"
        assert _parse_entry_id(result) is None

    def test_none_input(self):
        assert _parse_entry_id(None) is None

    def test_empty_dict(self):
        assert _parse_entry_id({}) is None

    def test_toolresult_missing_id_key(self):
        result = MagicMock()
        result.content = json.dumps({"status": "saved"})
        assert _parse_entry_id(result) is None


# ---------------------------------------------------------------------------
# WorkspaceEventEmitter.persist()
# ---------------------------------------------------------------------------

class TestEmitterPersist:
    def _make_hub(self, entry_id: Any):
        hub = MagicMock()
        hub.call_tool.return_value = {"id": entry_id}
        return hub

    def test_returns_sse_dict_on_success(self):
        emitter = WorkspaceEventEmitter()
        hub = self._make_hub(42)
        with patch("mcp.hub.get_hub", return_value=hub):
            result = emitter.persist(
                conversation_id="conv-1",
                content="test content",
                entry_type="thinking_plan",
                source_layer="thinking",
            )
        assert isinstance(result, WorkspaceEventResult)
        assert result.entry_id == 42
        assert result.sse_dict is not None
        assert result.sse_dict["type"] == "workspace_update"
        assert result.sse_dict["entry_id"] == 42
        assert result.sse_dict["content"] == "test content"
        assert result.sse_dict["entry_type"] == "thinking_plan"
        assert result.sse_dict["source_layer"] == "thinking"
        assert result.sse_dict["conversation_id"] == "conv-1"
        assert result.sse_dict["source"] == "event"

    def test_returns_none_on_missing_entry_id(self):
        emitter = WorkspaceEventEmitter()
        hub = MagicMock()
        hub.call_tool.return_value = {"status": "saved"}  # no id
        with patch("mcp.hub.get_hub", return_value=hub):
            result = emitter.persist("conv-1", "content", "type", "layer")
        assert result.entry_id is None
        assert result.sse_dict is None

    def test_returns_none_on_hub_exception(self):
        emitter = WorkspaceEventEmitter()
        hub = MagicMock()
        hub.call_tool.side_effect = RuntimeError("hub down")
        with patch("mcp.hub.get_hub", return_value=hub):
            result = emitter.persist("conv-1", "content", "type", "layer")
        assert result.entry_id is None
        assert result.sse_dict is None

    def test_calls_hub_with_correct_payload(self):
        emitter = WorkspaceEventEmitter()
        hub = self._make_hub(1)
        with patch("mcp.hub.get_hub", return_value=hub):
            emitter.persist("cid", "my content", "tool_call", "tools")
        hub.call_tool.assert_called_once_with("workspace_event_save", {
            "conversation_id": "cid",
            "event_type": "tool_call",
            "event_data": {
                "content": "my content",
                "source_layer": "tools",
            },
        })

    def test_toolresult_content_json_shape(self):
        """Fast-Lane gibt ToolResult mit .content als JSON-String zurück."""
        emitter = WorkspaceEventEmitter()
        hub = MagicMock()
        fake_result = MagicMock()
        fake_result.content = json.dumps({"id": 77, "status": "saved"})
        hub.call_tool.return_value = fake_result
        with patch("mcp.hub.get_hub", return_value=hub):
            result = emitter.persist("conv-2", "text", "output", "output")
        assert result.entry_id == 77
        assert result.sse_dict["entry_id"] == 77


# ---------------------------------------------------------------------------
# WorkspaceEventEmitter.persist_container()
# ---------------------------------------------------------------------------

class TestEmitterPersistContainer:
    def _make_hub(self, entry_id: Any):
        hub = MagicMock()
        hub.call_tool.return_value = {"id": entry_id}
        return hub

    def test_returns_sse_dict_with_container_format(self):
        emitter = WorkspaceEventEmitter()
        hub = self._make_hub(10)
        container_evt = {
            "event_type": "container_start",
            "event_data": {
                "container_id": "abc123def456",
                "blueprint_id": "python-sandbox",
                "purpose": "run tests",
            },
        }
        with patch("mcp.hub.get_hub", return_value=hub):
            result = emitter.persist_container("conv-3", container_evt)
        assert result.entry_id == 10
        assert result.sse_dict is not None
        assert result.sse_dict["entry_type"] == "container_start"
        assert "python-sandbox/abc123def4" in result.sse_dict["content"]
        assert "run tests" in result.sse_dict["content"]
        assert result.sse_dict["event_data"] == container_evt["event_data"]

    def test_content_fallback_when_no_container_id(self):
        emitter = WorkspaceEventEmitter()
        hub = self._make_hub(11)
        container_evt = {
            "event_type": "container_stop",
            "event_data": {},
        }
        with patch("mcp.hub.get_hub", return_value=hub):
            result = emitter.persist_container("conv-4", container_evt)
        assert result.sse_dict["content"] == "container_stop"

    def test_returns_none_on_hub_exception(self):
        emitter = WorkspaceEventEmitter()
        hub = MagicMock()
        hub.call_tool.side_effect = Exception("down")
        with patch("mcp.hub.get_hub", return_value=hub):
            result = emitter.persist_container("conv-5", {"event_type": "x", "event_data": {}})
        assert result.entry_id is None
        assert result.sse_dict is None

    def test_defaults_event_type_when_missing(self):
        emitter = WorkspaceEventEmitter()
        hub = self._make_hub(12)
        with patch("mcp.hub.get_hub", return_value=hub):
            emitter.persist_container("conv-6", {"event_data": {}})
        call_args = hub.call_tool.call_args[0][1]
        assert call_args["event_type"] == "container_event"


# ---------------------------------------------------------------------------
# WorkspaceEventEmitter.persist_and_broadcast()
# ---------------------------------------------------------------------------

class TestEmitterPersistAndBroadcast:
    def setup_method(self):
        # Sicherstellen dass emit_activity ein frischer Mock ist
        _mock_ws_stream.emit_activity = MagicMock()

    def _make_hub(self, entry_id: Any):
        hub = MagicMock()
        hub.call_tool.return_value = {"id": entry_id}
        return hub

    def test_sse_dict_is_none_in_shell_path(self):
        emitter = WorkspaceEventEmitter()
        hub = self._make_hub(20)
        with patch("mcp.hub.get_hub", return_value=hub):
            result = emitter.persist_and_broadcast(
                conversation_id="conv-7",
                event_type="shell_checkpoint",
                event_data={"content": "step 5"},
                content="step 5",
            )
        assert result.entry_id == 20
        assert result.sse_dict is None  # Shell-Pfad: kein SSE-Stream

    def test_calls_emit_activity(self):
        emitter = WorkspaceEventEmitter()
        hub = self._make_hub(21)
        with patch("mcp.hub.get_hub", return_value=hub):
            emitter.persist_and_broadcast(
                conversation_id="conv-8",
                event_type="shell_session_summary",
                event_data={"goal": "test"},
                content="summary text",
                source_layer="shell",
            )
        _mock_ws_stream.emit_activity.assert_called_once()
        call_args, call_kwargs = _mock_ws_stream.emit_activity.call_args
        assert call_args[0] == "workspace_update"
        assert call_kwargs["entry_id"] == 21
        assert call_kwargs["entry_type"] == "shell_session_summary"
        assert call_kwargs["conversation_id"] == "conv-8"
        assert call_kwargs["source_layer"] == "shell"
        assert call_kwargs["content"] == "summary text"

    def test_emit_activity_failure_is_non_fatal(self):
        """emit_activity-Fehler darf persist_and_broadcast nicht zum Absturz bringen."""
        emitter = WorkspaceEventEmitter()
        hub = self._make_hub(22)
        _mock_ws_stream.emit_activity.side_effect = Exception("ws down")
        with patch("mcp.hub.get_hub", return_value=hub):
            result = emitter.persist_and_broadcast(
                conversation_id="conv-9",
                event_type="shell_checkpoint",
                event_data={},
                content="step",
            )
        # entry_id wurde gespeichert, nur emit_activity schlug fehl
        assert result.entry_id == 22

    def test_returns_none_when_hub_fails(self):
        emitter = WorkspaceEventEmitter()
        hub = MagicMock()
        hub.call_tool.side_effect = RuntimeError("hub down")
        with patch("mcp.hub.get_hub", return_value=hub):
            result = emitter.persist_and_broadcast("conv-10", "type", {}, "content")
        assert result.entry_id is None
        assert result.sse_dict is None

    def test_no_emit_when_entry_id_none(self):
        """Wenn Fast-Lane keinen entry_id zurückgibt, darf emit_activity nicht aufgerufen werden."""
        emitter = WorkspaceEventEmitter()
        hub = MagicMock()
        hub.call_tool.return_value = {"status": "saved"}  # no id
        with patch("mcp.hub.get_hub", return_value=hub):
            emitter.persist_and_broadcast("conv-11", "type", {}, "content")
        _mock_ws_stream.emit_activity.assert_not_called()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_get_workspace_emitter_returns_same_instance(self):
        a = get_workspace_emitter()
        b = get_workspace_emitter()
        assert a is b

    def test_get_workspace_emitter_is_workspace_event_emitter(self):
        assert isinstance(get_workspace_emitter(), WorkspaceEventEmitter)
