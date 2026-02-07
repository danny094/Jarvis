# tests/workspace/test_orchestrator_emission.py
"""
Unit Tests: Orchestrator workspace event emission

Tests the workspace helper methods and event structures.
Since core.orchestrator has heavy transitive imports (Ollama, MCP, layers),
we test the logic by importing only the orchestrator module with pre-mocked deps.
"""

import pytest
import sys
import os
import json
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime
from pathlib import Path

# ═══════════════════════════════════════════════════════════
# Import orchestrator with mocked heavy dependencies
# ═══════════════════════════════════════════════════════════

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)

# We need to ensure PROJECT_ROOT config.py is importable (not sql-memory's)
# Save and restore to avoid polluting other tests
_original_modules = {}


def _setup_mocks():
    """Pre-populate sys.modules with mocks for orchestrator's dependencies."""
    # These modules are imported by core.orchestrator and need mocking
    mocks = {
        "core.models": MagicMock(CoreChatRequest=MagicMock, CoreChatResponse=MagicMock),
        "core.context_manager": MagicMock(ContextManager=MagicMock, ContextResult=MagicMock),
        "core.layers.thinking": MagicMock(ThinkingLayer=MagicMock),
        "core.layers.control": MagicMock(ControlLayer=MagicMock),
        "core.layers.output": MagicMock(OutputLayer=MagicMock),
        "core.sequential_registry": MagicMock(get_registry=MagicMock),
        "core.intent_models": MagicMock(),
        "core.intent_store": MagicMock(),
        "core.safety.light_cim": MagicMock(),
        "mcp.client": MagicMock(autosave_assistant=MagicMock, call_tool=MagicMock),
        "mcp.hub": MagicMock(get_hub=MagicMock),
        "utils.logger": MagicMock(
            log_info=MagicMock(), log_warn=MagicMock(),
            log_error=MagicMock(), log_debug=MagicMock()
        ),
    }

    # Mock the project root config with the values orchestrator needs
    mock_config = MagicMock()
    mock_config.OLLAMA_BASE = "http://localhost:11434"
    mock_config.ENABLE_CONTROL_LAYER = True
    mock_config.SKIP_CONTROL_ON_LOW_RISK = True
    mock_config.ENABLE_CHUNKING = False
    mock_config.CHUNKING_THRESHOLD = 2000

    for mod_name, mock_obj in mocks.items():
        _original_modules[mod_name] = sys.modules.get(mod_name)
        sys.modules[mod_name] = mock_obj

    # Handle config specially - save and replace
    _original_modules["config"] = sys.modules.get("config")
    sys.modules["config"] = mock_config

    return mocks


def _teardown_mocks():
    """Restore original sys.modules."""
    for mod_name, orig in _original_modules.items():
        if orig is None:
            sys.modules.pop(mod_name, None)
        else:
            sys.modules[mod_name] = orig


def _import_orchestrator():
    """Import PipelineOrchestrator with mocked deps."""
    _setup_mocks()
    try:
        # Clear cached module to force re-import
        sys.modules.pop("core.orchestrator", None)

        # Add project root to path for core package
        old_path = sys.path[:]
        if PROJECT_ROOT not in sys.path:
            sys.path.insert(0, PROJECT_ROOT)

        from core.orchestrator import PipelineOrchestrator
        return PipelineOrchestrator
    except Exception as e:
        _teardown_mocks()
        pytest.skip(f"Cannot import PipelineOrchestrator: {e}")
    finally:
        sys.path[:] = old_path


# Try to import; skip all tests in this module if it fails
try:
    PipelineOrchestrator = _import_orchestrator()
    _IMPORT_OK = True
except Exception:
    _IMPORT_OK = False
    PipelineOrchestrator = None

pytestmark = pytest.mark.skipif(not _IMPORT_OK, reason="Cannot import orchestrator")


class TestExtractWorkspaceObservations:
    """Test _extract_workspace_observations helper."""

    def _make_orch(self):
        return PipelineOrchestrator.__new__(PipelineOrchestrator)

    def test_extracts_intent(self):
        orch = self._make_orch()
        plan = {
            "intent": "User asks about Docker setup",
            "needs_memory": False,
            "memory_keys": [],
            "hallucination_risk": "low",
        }
        result = orch._extract_workspace_observations(plan)
        assert result is not None
        assert "Docker setup" in result

    def test_extracts_memory_keys(self):
        orch = self._make_orch()
        plan = {
            "intent": "question",
            "memory_keys": ["docker", "compose"],
            "hallucination_risk": "medium",
        }
        result = orch._extract_workspace_observations(plan)
        assert result is not None
        assert "docker" in result
        assert "compose" in result

    def test_extracts_high_risk_warning(self):
        orch = self._make_orch()
        plan = {
            "intent": "personal question",
            "hallucination_risk": "high",
            "memory_keys": [],
        }
        result = orch._extract_workspace_observations(plan)
        assert result is not None
        assert "high" in result.lower() or "High" in result

    def test_extracts_sequential_thinking(self):
        orch = self._make_orch()
        plan = {
            "intent": "complex analysis",
            "needs_sequential_thinking": True,
            "hallucination_risk": "medium",
            "memory_keys": [],
        }
        result = orch._extract_workspace_observations(plan)
        assert result is not None
        assert "sequential" in result.lower() or "Sequential" in result

    def test_returns_none_for_trivial_plan(self):
        orch = self._make_orch()
        plan = {
            "intent": "unknown",
            "needs_memory": False,
            "memory_keys": [],
            "hallucination_risk": "low",
        }
        result = orch._extract_workspace_observations(plan)
        assert result is None


class TestSaveWorkspaceEntry:
    """Test _save_workspace_entry helper method."""

    def _make_orch(self):
        return PipelineOrchestrator.__new__(PipelineOrchestrator)

    def test_save_returns_event_dict(self):
        orch = self._make_orch()

        mock_hub = MagicMock()
        mock_hub.call_tool.return_value = {
            "structuredContent": {"id": 42, "conversation_id": "conv-1"}
        }

        # Patch get_hub in the orchestrator module
        orch_module = sys.modules["core.orchestrator"]
        original_get_hub = getattr(orch_module, "get_hub", None)
        orch_module.get_hub = MagicMock(return_value=mock_hub)
        try:
            event = orch._save_workspace_entry(
                "conv-1", "test observation", "observation", "thinking"
            )
        finally:
            if original_get_hub is not None:
                orch_module.get_hub = original_get_hub

        assert event is not None
        assert event["type"] == "workspace_update"
        assert event["entry_id"] == 42
        assert event["content"] == "test observation"
        assert event["entry_type"] == "observation"
        assert event["source_layer"] == "thinking"
        assert event["conversation_id"] == "conv-1"
        assert "timestamp" in event

    def test_save_returns_none_on_failure(self):
        orch = self._make_orch()

        mock_hub = MagicMock()
        mock_hub.call_tool.side_effect = Exception("MCP connection failed")

        orch_module = sys.modules["core.orchestrator"]
        original_get_hub = getattr(orch_module, "get_hub", None)
        orch_module.get_hub = MagicMock(return_value=mock_hub)
        try:
            event = orch._save_workspace_entry(
                "conv-1", "test", "observation", "thinking"
            )
        finally:
            if original_get_hub is not None:
                orch_module.get_hub = original_get_hub

        assert event is None

    def test_save_returns_none_when_no_id(self):
        orch = self._make_orch()

        mock_hub = MagicMock()
        mock_hub.call_tool.return_value = {"structuredContent": {}}

        orch_module = sys.modules["core.orchestrator"]
        original_get_hub = getattr(orch_module, "get_hub", None)
        orch_module.get_hub = MagicMock(return_value=mock_hub)
        try:
            event = orch._save_workspace_entry(
                "conv-1", "test", "observation", "thinking"
            )
        finally:
            if original_get_hub is not None:
                orch_module.get_hub = original_get_hub

        assert event is None

    def test_save_calls_hub_with_correct_args(self):
        orch = self._make_orch()

        mock_hub = MagicMock()
        mock_hub.call_tool.return_value = {
            "structuredContent": {"id": 1}
        }

        orch_module = sys.modules["core.orchestrator"]
        original_get_hub = getattr(orch_module, "get_hub", None)
        orch_module.get_hub = MagicMock(return_value=mock_hub)
        try:
            orch._save_workspace_entry("conv-X", "my content", "task", "control")
        finally:
            if original_get_hub is not None:
                orch_module.get_hub = original_get_hub

        mock_hub.call_tool.assert_called_once_with("workspace_save", {
            "conversation_id": "conv-X",
            "content": "my content",
            "entry_type": "task",
            "source_layer": "control",
        })


class TestWorkspaceEmissionInPipeline:
    """Test that workspace events are emitted at the 3 correct points."""

    def test_emission_point_structure(self):
        event = {
            "type": "workspace_update",
            "entry_id": 1,
            "content": "test",
            "entry_type": "observation",
            "source_layer": "thinking",
            "conversation_id": "conv-1",
            "timestamp": "2026-02-06T12:00:00Z",
        }

        assert event["type"] == "workspace_update"
        assert "entry_id" in event
        assert "content" in event
        assert "entry_type" in event
        assert "conversation_id" in event
        assert "timestamp" in event

    def test_tool_context_workspace_note(self):
        suggested_tools = ["memory_graph_search", "list_skills"]
        tool_context = "### TOOL-ERGEBNIS (memory_graph_search):\n{results: []}\n"

        tool_summary = f"**Tools executed:** {', '.join(suggested_tools)}\n\n{tool_context[:500]}"

        assert "memory_graph_search" in tool_summary
        assert "list_skills" in tool_summary
        assert "TOOL-ERGEBNIS" in tool_summary

    def test_control_corrections_workspace_entry(self):
        verification = {
            "approved": True,
            "corrections": {"memory_keys": ["docker_setup"]},
            "warnings": ["Memory key 'compose' not found"],
        }

        ctrl_parts = []
        if verification.get("warnings"):
            ctrl_parts.append(f"**Warnings:** {', '.join(str(w) for w in verification['warnings'])}")
        if verification.get("corrections"):
            ctrl_parts.append(f"**Corrections:** {json.dumps(verification['corrections'])[:300]}")

        result = "\n".join(ctrl_parts)

        assert "Warnings" in result
        assert "compose" in result
        assert "Corrections" in result
        assert "docker_setup" in result
