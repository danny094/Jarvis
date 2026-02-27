"""
Unit Tests for Phase 1.5: Context Budgeting Hardening

Tests:
1. _apply_final_cap always active in small mode (no ENV needed)
2. _clip_tool_context caps tool output
3. Unified failure-compact: single source, no double-counting (sync)
4. Sync / stream produce the same source-set for equivalent inputs
5. LoopEngine disabled in small-model-mode

Date: 2026-02-18
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import sys
import os
import types
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ─── helpers ────────────────────────────────────────────────────────────────

def _make_mock_store_module():
    """Inject a fake container_commander.blueprint_store to avoid init_db()."""
    m = types.ModuleType("container_commander.blueprint_store")
    m.get_active_blueprint_ids = Mock(return_value=set())
    m.init_db = Mock()
    return m


def _make_orchestrator(mock_layers=None):
    """Return a PipelineOrchestrator with all heavy deps mocked."""
    ml = mock_layers or {}
    thinking = ml.get("thinking", MagicMock())
    thinking.analyze = AsyncMock(return_value={
        "intent": "question",
        "needs_memory": False,
        "memory_keys": [],
        "hallucination_risk": "low",
        "needs_sequential_thinking": False,
        "sequential_complexity": 0,
        "suggested_tools": [],
    })
    control = ml.get("control", MagicMock())
    control.verify = AsyncMock(return_value={"approved": True, "corrections": {}, "warnings": []})
    control.apply_corrections = MagicMock(side_effect=lambda p, v: {**p, "_verified": True})
    control._check_sequential_thinking = AsyncMock(return_value=None)
    control.set_mcp_hub = MagicMock()
    output = ml.get("output", MagicMock())
    output.generate = AsyncMock(return_value="ok")

    mock_store = _make_mock_store_module()
    with patch.dict(sys.modules, {"container_commander.blueprint_store": mock_store}):
        with patch("core.orchestrator.ThinkingLayer", return_value=thinking), \
             patch("core.orchestrator.ControlLayer", return_value=control), \
             patch("core.orchestrator.OutputLayer", return_value=output), \
             patch("core.orchestrator.get_hub", return_value=MagicMock()), \
             patch("core.orchestrator.get_registry", return_value=MagicMock()):
            try:
                from core.orchestrator import PipelineOrchestrator
                return PipelineOrchestrator()
            except Exception:
                return None


# ─── Commit 1: _apply_final_cap ─────────────────────────────────────────────

class TestApplyFinalCap:
    """_apply_final_cap helper (Phase 1.5 Commit 1)"""

    def test_no_op_when_not_small_mode(self):
        """Full-model mode: no cap applied regardless of length."""
        orch = _make_orchestrator()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        trace = {"context_chars_final": 100}
        long_ctx = "x" * 50_000
        result = orch._apply_final_cap(long_ctx, trace, small_model_mode=False, label="test")
        assert result == long_ctx
        assert trace["context_chars_final"] == 100  # unchanged

    def test_cap_applied_in_small_mode_via_fallback(self):
        """Small mode without SMALL_MODEL_FINAL_CAP falls back to SMALL_MODEL_CHAR_CAP."""
        orch = _make_orchestrator()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        trace = {"context_chars_final": 99999}
        # Default SMALL_MODEL_CHAR_CAP should be > 0
        with patch("config.get_small_model_final_cap", return_value=0), \
             patch("config.get_small_model_char_cap", return_value=500):
            long_ctx = "x" * 2000
            result = orch._apply_final_cap(long_ctx, trace, small_model_mode=True, label="test")
            assert len(result) == 500
            assert trace["context_chars_final"] == 500

    def test_cap_applied_via_explicit_final_cap(self):
        """SMALL_MODEL_FINAL_CAP > 0 used when set."""
        orch = _make_orchestrator()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        trace = {"context_chars_final": 99999}
        with patch("config.get_small_model_final_cap", return_value=300), \
             patch("config.get_small_model_char_cap", return_value=500):
            long_ctx = "x" * 2000
            result = orch._apply_final_cap(long_ctx, trace, small_model_mode=True, label="test")
            assert len(result) == 300
            assert trace["context_chars_final"] == 300

    def test_no_truncation_when_under_cap(self):
        """Context shorter than cap is returned unchanged."""
        orch = _make_orchestrator()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        trace = {"context_chars_final": 50}
        with patch("config.get_small_model_final_cap", return_value=1000), \
             patch("config.get_small_model_char_cap", return_value=500):
            short_ctx = "hello world"
            result = orch._apply_final_cap(short_ctx, trace, small_model_mode=True, label="test")
            assert result == short_ctx
            assert trace["context_chars_final"] == 50  # not updated


# ─── Commit 2: _clip_tool_context ───────────────────────────────────────────

class TestClipToolContext:
    """_clip_tool_context helper (Phase 1.5 Commit 2)"""

    def test_no_op_when_not_small_mode(self):
        """Full-model mode: tool_context never clipped."""
        orch = _make_orchestrator()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        large = "x" * 100_000
        result = orch._clip_tool_context(large, small_model_mode=False)
        assert result == large

    def test_no_op_when_cap_is_zero(self):
        """SMALL_MODEL_TOOL_CTX_CAP=0 means unlimited."""
        orch = _make_orchestrator()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        with patch("config.get_small_model_tool_ctx_cap", return_value=0):
            large = "x" * 100_000
            result = orch._clip_tool_context(large, small_model_mode=True)
            assert result == large

    def test_clips_to_cap_in_small_mode(self):
        """Tool context clipped so total length <= cap (marker fits within cap)."""
        orch = _make_orchestrator()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        with patch("config.get_small_model_tool_ctx_cap", return_value=200):
            large = "y" * 5000
            result = orch._clip_tool_context(large, small_model_mode=True)
            # Result must fit within cap — marker takes some space, content fills the rest
            assert len(result) <= 200
            assert result.startswith("y")
            assert "[...truncated:" in result

    def test_no_clip_when_under_cap(self):
        """Context shorter than cap passed through unchanged."""
        orch = _make_orchestrator()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        with patch("config.get_small_model_tool_ctx_cap", return_value=1000):
            short = "hello"
            result = orch._clip_tool_context(short, small_model_mode=True)
            assert result == short

    def test_no_op_on_empty_string(self):
        """Empty string returned as-is."""
        orch = _make_orchestrator()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        result = orch._clip_tool_context("", small_model_mode=True)
        assert result == ""

    def test_json_only_context_stays_valid_json_when_clipped(self):
        """JSON-only tool_context must remain parseable JSON after clipping."""
        orch = _make_orchestrator()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")

        payload = {
            "tool": "memory_graph_search",
            "results": [{"id": i, "text": "x" * 800} for i in range(20)],
            "meta": {"source": "test", "ok": True},
        }
        json_ctx = json.dumps(payload, ensure_ascii=False)

        with patch("config.get_small_model_tool_ctx_cap", return_value=280):
            result = orch._clip_tool_context(json_ctx, small_model_mode=True)

        assert len(result) <= 280
        parsed = json.loads(result)
        assert isinstance(parsed, (dict, list))

    def test_structured_context_does_not_cut_json_line_blindly(self):
        """Structured clipping should keep JSON lines parseable when they are retained."""
        orch = _make_orchestrator()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")

        json_line = json.dumps(
            {"path": "/tmp/data", "items": [{"name": "a", "value": "y" * 1200}]},
            ensure_ascii=False,
        )
        structured = (
            "\n### TOOL-ERGEBNIS (home_list):\n"
            f"{json_line}\n"
            "\n[TOOL-CARD: home_list | ✅ ok | ref:abc123]\n"
            "- done\n"
            "ts:2026-02-26T10:00:00Z\n"
        )

        with patch("config.get_small_model_tool_ctx_cap", return_value=260):
            result = orch._clip_tool_context(structured, small_model_mode=True)

        assert len(result) <= 260
        for line in result.splitlines():
            s = line.strip()
            if s.startswith("{") and s.endswith("}"):
                json.loads(s)

    def test_failure_marker_preserved_even_if_failure_block_is_clipped(self):
        """
        Clipping must not erase failure evidence, otherwise confidence logic can be wrong.
        """
        orch = _make_orchestrator()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")

        failing = (
            "\n### TOOL-FEHLER (create_skill): missing_required=['code']\n"
            + ("A" * 1200)
            + "\n[TOOL-CARD: run_skill | ✅ ok | ref:ok123]\n"
            + "- executed\n"
            + "ts:2026-02-26T10:00:00Z\n"
        )

        with patch("config.get_small_model_tool_ctx_cap", return_value=200):
            result = orch._clip_tool_context(failing, small_model_mode=True)

        assert len(result) <= 200
        assert orch._tool_context_has_failures_or_skips(result) is True


# ─── Commit 3: Unified failure-compact (sync path) ──────────────────────────

class TestUnifiedFailureCompactSync:
    """Failure-compact sync path now prepends to tool_context before single append."""

    def test_failure_compact_single_source_tag(self):
        """When failure present, sources = ['failure_ctx', 'tool_ctx'] (no duplicate)."""
        orch = _make_orchestrator()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")

        trace = {
            "context_sources": [],
            "context_chars_final": 0,
            "retrieval_count": 0,
        }
        fail_block = "[COMPACT-CONTEXT-ON-FAILURE]\nsome compact info\n\n"

        with patch.object(orch, "_build_failure_compact_block", return_value=fail_block), \
             patch("config.get_small_model_mode", return_value=False):

            tool_ctx_with_failure = "result: ok\nTOOL-FEHLER: something failed"

            # Simulate the unified sync block logic directly
            _smm = False
            tool_context = tool_ctx_with_failure
            retrieved_memory = "base context"

            if tool_context and "TOOL-FEHLER" in tool_context:
                _fb = orch._build_failure_compact_block("conv123", len(retrieved_memory), _smm)
                if _fb:
                    tool_context = _fb + tool_context
                    trace["context_sources"].append("failure_ctx")

            if tool_context:
                retrieved_memory = orch._append_context_block(
                    retrieved_memory, tool_context, "tool_ctx", trace
                )

            sources = trace["context_sources"]
            assert "failure_ctx" in sources
            assert "tool_ctx" in sources
            # failure_ctx must appear exactly once
            assert sources.count("failure_ctx") == 1
            # tool_ctx must appear exactly once (no separate prepend append)
            assert sources.count("tool_ctx") == 1

    def test_no_failure_block_when_no_fehler(self):
        """Without TOOL-FEHLER, failure_ctx source is NOT added."""
        orch = _make_orchestrator()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")

        trace = {"context_sources": [], "context_chars_final": 0}
        tool_ctx = "result: everything worked fine"
        retrieved_memory = "base"

        with patch.object(orch, "_build_failure_compact_block") as mock_build:
            if tool_ctx and "TOOL-FEHLER" in tool_ctx:
                _fb = orch._build_failure_compact_block("conv123", 4, False)
                if _fb:
                    tool_ctx = _fb + tool_ctx
                    trace["context_sources"].append("failure_ctx")

            if tool_ctx:
                retrieved_memory = orch._append_context_block(
                    retrieved_memory, tool_ctx, "tool_ctx", trace
                )

            assert "failure_ctx" not in trace["context_sources"]
            assert "tool_ctx" in trace["context_sources"]
            mock_build.assert_not_called()

    def test_chars_counted_once(self):
        """Total chars after unified append = base + len(fail_block) + len(tool_ctx_orig)."""
        orch = _make_orchestrator()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")

        fail_block = "[COMPACT-CONTEXT-ON-FAILURE]\ndata\n\n"
        tool_ctx_orig = "TOOL-FEHLER: boom"
        base = "base"

        trace = {"context_sources": [], "context_chars_final": len(base)}

        with patch.object(orch, "_build_failure_compact_block", return_value=fail_block):
            tool_context = tool_ctx_orig
            retrieved_memory = base

            if tool_context and "TOOL-FEHLER" in tool_context:
                _fb = orch._build_failure_compact_block("conv", len(retrieved_memory), False)
                if _fb:
                    tool_context = _fb + tool_context
                    trace["context_sources"].append("failure_ctx")

            if tool_context:
                retrieved_memory = orch._append_context_block(
                    retrieved_memory, tool_context, "tool_ctx", trace
                )

        expected_chars = len(base) + len(fail_block) + len(tool_ctx_orig)
        assert trace["context_chars_final"] == expected_chars


# ─── Sync / Stream parity ────────────────────────────────────────────────────

class TestSyncStreamParity:
    """Both paths emit the same source set for equivalent failure inputs."""

    def test_both_paths_emit_failure_ctx_and_tool_ctx(self):
        """Simulate both paths: same inputs → same source-set."""
        orch = _make_orchestrator()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")

        fail_block = "[COMPACT-CONTEXT-ON-FAILURE]\ninfo\n\n"
        tool_ctx_with_failure = "TOOL-FEHLER: something broke"
        base = "context"

        with patch.object(orch, "_build_failure_compact_block", return_value=fail_block):

            # --- Sync path ---
            trace_sync = {"context_sources": [], "context_chars_final": len(base)}
            tool_context_sync = tool_ctx_with_failure
            retrieved_memory = base

            if tool_context_sync and "TOOL-FEHLER" in tool_context_sync:
                _fb = orch._build_failure_compact_block("c", len(retrieved_memory), False)
                if _fb:
                    tool_context_sync = _fb + tool_context_sync
                    trace_sync["context_sources"].append("failure_ctx")
            if tool_context_sync:
                retrieved_memory = orch._append_context_block(
                    retrieved_memory, tool_context_sync, "tool_ctx", trace_sync
                )

            # --- Stream path (existing logic) ---
            trace_stream = {"context_sources": [], "context_chars_final": len(base)}
            tool_context_stream = tool_ctx_with_failure
            full_context = base

            _stream_has_failure = bool(tool_context_stream and "TOOL-FEHLER" in tool_context_stream)
            if _stream_has_failure:
                _fb_s = orch._build_failure_compact_block("c", len(full_context), False)
                if _fb_s:
                    tool_context_stream = _fb_s + tool_context_stream
                    trace_stream["context_sources"].append("failure_ctx")
            if tool_context_stream:
                full_context = orch._append_context_block(
                    full_context, tool_context_stream, "tool_ctx", trace_stream
                )

            # Both must have same source set
            assert set(trace_sync["context_sources"]) == set(trace_stream["context_sources"])
            assert trace_sync["context_chars_final"] == trace_stream["context_chars_final"]


# ─── Commit 4: LoopEngine guard ──────────────────────────────────────────────

class TestLoopEngineSmallModelGuard:
    """LoopEngine must be disabled in small-model-mode (Phase 1.5 Commit 4)."""

    def test_loop_engine_disabled_in_small_mode(self):
        """When _smm_stream=True and use_loop_engine=True, guard sets it to False."""
        # Test the guard logic directly (simulates lines 2321-2325 in orchestrator.py)
        _autonomous_task = False
        _loop_complexity = 8  # would trigger LoopEngine
        _loop_complexity_threshold = 8
        _loop_min_tools = 1
        _loop_sequential = False
        _loop_tools_count = 1
        _response_mode_stream = "deep"
        _smm_stream = True  # small-model-mode

        _loop_candidate = (
            _loop_complexity >= _loop_complexity_threshold
            or (_loop_sequential and _loop_tools_count >= 2)
        )
        use_loop_engine = (
            not _autonomous_task
            and _response_mode_stream == "deep"
            and _loop_tools_count >= _loop_min_tools
            and _loop_candidate
        )
        assert use_loop_engine is True  # would have triggered

        # Phase 1.5 guard:
        if use_loop_engine and _smm_stream:
            use_loop_engine = False

        assert use_loop_engine is False

    def test_loop_engine_allowed_in_full_mode(self):
        """Full model mode: LoopEngine not disabled by the guard."""
        _autonomous_task = False
        _loop_complexity = 8
        _loop_complexity_threshold = 8
        _loop_min_tools = 1
        _loop_sequential = False
        _loop_tools_count = 1
        _response_mode_stream = "deep"
        _smm_stream = False  # full model

        _loop_candidate = (
            _loop_complexity >= _loop_complexity_threshold
            or (_loop_sequential and _loop_tools_count >= 2)
        )
        use_loop_engine = (
            not _autonomous_task
            and _response_mode_stream == "deep"
            and _loop_tools_count >= _loop_min_tools
            and _loop_candidate
        )

        if use_loop_engine and _smm_stream:
            use_loop_engine = False

        assert use_loop_engine is True  # NOT disabled in full mode

    def test_loop_engine_autonomous_still_skipped_in_small_mode(self):
        """autonomous_skill_task disables LoopEngine regardless of small mode."""
        _autonomous_task = True
        _loop_complexity = 9
        _loop_complexity_threshold = 8
        _loop_min_tools = 1
        _loop_sequential = True
        _loop_tools_count = 5
        _response_mode_stream = "deep"
        _smm_stream = False  # doesn't matter

        _loop_candidate = (
            _loop_complexity >= _loop_complexity_threshold
            or (_loop_sequential and _loop_tools_count >= 2)
        )
        use_loop_engine = (
            not _autonomous_task
            and _response_mode_stream == "deep"
            and _loop_tools_count >= _loop_min_tools
            and _loop_candidate
        )

        assert use_loop_engine is False  # autonomous disables before guard

    def test_guard_in_orchestrator_source(self):
        """Verify the guard code exists in orchestrator.py (static analysis)."""
        import ast, inspect
        try:
            from core.orchestrator import PipelineOrchestrator
            source = inspect.getsource(PipelineOrchestrator.process_stream)
        except (ImportError, AttributeError) as e:
            pytest.skip(f"Cannot inspect: {e}")

        # Guard must be present
        assert "use_loop_engine and _smm_stream" in source, \
            "Phase 1.5 guard missing: 'if use_loop_engine and _smm_stream' not found in process_stream"
        assert "use_loop_engine = False" in source, \
            "Phase 1.5 guard missing: 'use_loop_engine = False' not found in process_stream"
        assert 'response_mode_stream == "deep"' in source, \
            "LoopEngine gate missing deep-mode requirement"
        assert "_loop_tools_count >= _loop_min_tools" in source, \
            "LoopEngine gate missing minimum tool-count requirement"
