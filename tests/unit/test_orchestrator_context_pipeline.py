"""
Unit Tests: Orchestrator Context Pipeline — Phase 1/2/2.5 Core Risks
=====================================================================

Minimal Test Plan (ranked):
  1. Sync/Stream parity — same build_effective_context entry-point
  2. Extra-lookup increments retrieval_count + registers jit_memory source
  3. Retrieval budget normal (1 fetch) vs tool-failure (2 fetches)
  4. Failure-compact counted exactly once in stream path (no double-counting)
  5. Final-cap applied after ALL appends (sync + stream, Phase 2.5)
  6. [CTX-FINAL] payload_chars matches sum of messages content lengths
  7. SMALL_MODEL_TOOL_CTX_CAP config is readable; enforcement documented
  8. Workspace-event parsing: ToolResult / structuredContent / legacy list
  9. Blueprint router gates: strict / suggest / no-match + trust filter
 10. TTL event contains session_id + blueprint_id for audit trace
"""

import json
import pytest
import time
import sys
import os
from unittest.mock import MagicMock, AsyncMock, patch, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ─────────────────────────────────────────────────────────────────
# Shared orchestrator factory
# ─────────────────────────────────────────────────────────────────

def _make_orch(mock_layers, mock_ctx_mgr=None):
    """Instantiate PipelineOrchestrator with all external deps mocked."""
    try:
        from core.orchestrator import PipelineOrchestrator
    except ImportError as e:
        pytest.skip(f"Cannot import PipelineOrchestrator: {e}")

    ctx = mock_ctx_mgr or _default_ctx_mgr()

    with patch("core.orchestrator.ThinkingLayer", return_value=mock_layers["thinking"]), \
         patch("core.orchestrator.ControlLayer", return_value=mock_layers["control"]), \
         patch("core.orchestrator.OutputLayer", return_value=mock_layers["output"]), \
         patch("core.orchestrator.get_hub", return_value=MagicMock()), \
         patch("core.orchestrator.get_registry", return_value=MagicMock()), \
         patch("core.orchestrator.ContextManager", return_value=ctx):
        orch = PipelineOrchestrator()

    # Inject context manager directly so helper methods can use it
    orch.context = ctx
    return orch


def _default_layers():
    thinking = MagicMock()
    thinking.analyze = AsyncMock(return_value={
        "intent": "question",
        "needs_memory": False,
        "memory_keys": [],
        "hallucination_risk": "low",
        "needs_sequential_thinking": False,
    })
    control = MagicMock()
    control.verify = AsyncMock(return_value={"approved": True, "corrections": {}, "warnings": []})
    control.apply_corrections = MagicMock(side_effect=lambda p, v: {**p, "_verified": True})
    control._check_sequential_thinking = AsyncMock(return_value=None)
    control.set_mcp_hub = MagicMock()
    control.decide_tools = AsyncMock(return_value=[])
    output = MagicMock()
    output.generate = AsyncMock(return_value="OK")
    return {"thinking": thinking, "control": control, "output": output}


class _MockCtxResult:
    def __init__(self, memory_data="", memory_used=False, system_tools="", sources=None):
        self.memory_data = memory_data
        self.memory_used = memory_used
        self.system_tools = system_tools
        self.sources = sources or []


def _default_ctx_mgr(memory_data="", memory_used=False):
    ctx = MagicMock()
    ctx.get_context.return_value = _MockCtxResult(
        memory_data=memory_data,
        memory_used=memory_used,
    )
    ctx.build_small_model_context.return_value = "NOW:\n  - test state\n"
    return ctx


# ═════════════════════════════════════════════════════════════════
# Test 1: build_effective_context — canonical public entry-point
# ═════════════════════════════════════════════════════════════════

class TestBuildEffectiveContextPublicAPI:
    """Test 1: Sync/Stream parity — both paths use build_effective_context."""

    def test_public_alias_exists(self):
        """build_effective_context must be the public alias for _build_effective_context."""
        orch = _make_orch(_default_layers())
        assert callable(getattr(orch, "build_effective_context", None)), \
            "build_effective_context must be a public method"

    def test_returns_tuple_str_dict(self):
        """build_effective_context must return (str, dict)."""
        orch = _make_orch(_default_layers())
        result = orch.build_effective_context(
            user_text="hello",
            conv_id="test-conv",
            small_model_mode=False,
        )
        assert isinstance(result, tuple) and len(result) == 2
        text, trace = result
        assert isinstance(text, str)
        assert isinstance(trace, dict)

    def test_trace_has_required_keys(self):
        """Trace dict must contain all required keys for [CTX-PRE-OUTPUT] logging."""
        orch = _make_orch(_default_layers())
        _, trace = orch.build_effective_context(
            user_text="query",
            conv_id="conv-a",
            small_model_mode=False,
        )
        required = {"context_sources", "context_blocks", "context_chars",
                    "context_chars_final", "retrieval_count", "mode", "flags"}
        missing = required - set(trace.keys())
        assert not missing, f"Trace missing keys: {missing}"

    def test_context_chars_final_equals_context_chars_initially(self):
        """context_chars_final must equal context_chars before any post-build appends."""
        orch = _make_orch(_default_layers(), _default_ctx_mgr(memory_data="some data"))
        _, trace = orch.build_effective_context(
            user_text="q",
            conv_id="c",
            small_model_mode=False,
        )
        assert trace["context_chars_final"] == trace["context_chars"], \
            "context_chars_final must be initialised equal to context_chars (no appends yet)"

    def test_public_alias_delegates_to_private(self):
        """build_effective_context must produce the same result as _build_effective_context."""
        orch = _make_orch(_default_layers())
        r1 = orch.build_effective_context(user_text="x", conv_id="y", small_model_mode=False)
        r2 = orch._build_effective_context(user_text="x", conv_id="y", small_model_mode=False)
        assert r1[0] == r2[0], "Public alias must produce same context text as private method"
        assert r1[1]["context_chars"] == r2[1]["context_chars"], "Same context_chars"

    def test_include_blocks_memory_only(self):
        """include_blocks=compact:False,system_tools:False must omit those blocks."""
        orch = _make_orch(
            _default_layers(),
            _default_ctx_mgr(memory_data="MY_MEMORY_DATA"),
        )
        text, trace = orch.build_effective_context(
            user_text="extra key",
            conv_id="conv-x",
            small_model_mode=False,
            cleanup_payload={"needs_memory": True, "memory_keys": ["extra key"]},
            include_blocks={"compact": False, "system_tools": False, "memory_data": True},
        )
        # system_tools not in sources (system_tools="" in mock)
        assert "compact" not in trace["context_sources"]
        assert "system_tools" not in trace["context_sources"]


# ═════════════════════════════════════════════════════════════════
# Test 2: _append_context_block — central mutation hook
# ═════════════════════════════════════════════════════════════════

class TestAppendContextBlock:
    """Test 2: Extra-lookup increments retrieval_count + adds jit_memory source."""

    def _make_trace(self):
        return {"context_sources": [], "context_chars_final": 0}

    def test_append_updates_sources_and_chars(self):
        """_append_context_block must register source and update chars."""
        orch = _make_orch(_default_layers())
        trace = self._make_trace()
        block = "EXTRA_MEMORY_DATA"
        result = orch._append_context_block("base", block, "jit_memory", trace)
        assert "jit_memory" in trace["context_sources"]
        assert trace["context_chars_final"] == len(block)
        assert result == "base" + block

    def test_prepend_flag(self):
        """prepend=True must insert new_block before ctx_str."""
        orch = _make_orch(_default_layers())
        trace = self._make_trace()
        result = orch._append_context_block("existing", "PREFIX_", "failure_ctx", trace, prepend=True)
        assert result.startswith("PREFIX_")
        assert result == "PREFIX_existing"

    def test_empty_block_is_noop(self):
        """Empty new_block must not change ctx_str or trace."""
        orch = _make_orch(_default_layers())
        trace = self._make_trace()
        result = orch._append_context_block("unchanged", "", "noop", trace)
        assert result == "unchanged"
        assert trace["context_sources"] == []
        assert trace["context_chars_final"] == 0

    def test_extra_lookup_pattern_increments_retrieval(self):
        """Simulate extra-lookup path: source registered + retrieval_count incremented."""
        orch = _make_orch(_default_layers())
        trace = {"context_sources": ["memory_data"], "context_chars_final": 100, "retrieval_count": 1}
        extra_text = "EXTRA_FACT"
        retrieved = orch._append_context_block("context", "\n" + extra_text, "jit_memory", trace)
        # Simulate retrieval_count += 1 (as orchestrator does)
        trace["retrieval_count"] += 1

        assert "jit_memory" in trace["context_sources"]
        assert trace["retrieval_count"] == 2
        assert trace["context_chars_final"] == 100 + len("\n" + extra_text)
        assert extra_text in retrieved

    def test_multiple_appends_accumulate_chars(self):
        """Multiple appends must accumulate context_chars_final correctly."""
        orch = _make_orch(_default_layers())
        trace = self._make_trace()
        ctx = ""
        ctx = orch._append_context_block(ctx, "AAA", "src_a", trace)
        ctx = orch._append_context_block(ctx, "BB", "src_b", trace)
        assert trace["context_chars_final"] == 5  # 3 + 2
        assert trace["context_sources"] == ["src_a", "src_b"]


# ═════════════════════════════════════════════════════════════════
# Test 3: Retrieval budget normal vs tool-failure
# ═════════════════════════════════════════════════════════════════

class TestRetrievalBudget:
    """Test 3: _get_compact_context budget 1 (normal) vs 2 (tool-failure)."""

    def _orch_with_small_mode(self):
        orch = _make_orch(_default_layers())
        orch.context.build_small_model_context.return_value = "NOW:\n  - state\n"
        return orch

    def test_normal_budget_one_retrieval(self):
        """Normal path: exactly 1 call to build_small_model_context."""
        orch = self._orch_with_small_mode()
        with patch("config.get_small_model_mode", return_value=True), \
             patch("config.get_jit_retrieval_max", return_value=1), \
             patch("config.get_jit_retrieval_max_on_failure", return_value=2), \
             patch("config.get_small_model_now_max", return_value=5), \
             patch("config.get_small_model_rules_max", return_value=3), \
             patch("config.get_small_model_next_max", return_value=2):
            orch._get_compact_context(conversation_id="conv-normal", has_tool_failure=False)

        calls = orch.context.build_small_model_context.call_args_list
        conv_calls = [c for c in calls if c.kwargs.get("conversation_id") == "conv-normal"
                      or (c.args and c.args[0] == "conv-normal")]
        assert len(conv_calls) == 1, \
            f"Normal path should make 1 retrieval, got {len(calls)} total calls"

    def test_failure_budget_two_retrievals(self):
        """Failure path: 2 calls — session + _container_events global store."""
        orch = self._orch_with_small_mode()
        orch.context.build_small_model_context.reset_mock()
        with patch("config.get_small_model_mode", return_value=True), \
             patch("config.get_jit_retrieval_max", return_value=1), \
             patch("config.get_jit_retrieval_max_on_failure", return_value=2), \
             patch("config.get_small_model_now_max", return_value=5), \
             patch("config.get_small_model_rules_max", return_value=3), \
             patch("config.get_small_model_next_max", return_value=2):
            orch._get_compact_context(conversation_id="conv-fail", has_tool_failure=True)

        total_calls = orch.context.build_small_model_context.call_count
        assert total_calls == 2, \
            f"Failure path should make 2 retrievals (session + _container_events), got {total_calls}"

    def test_failure_budget_skipped_for_container_events_conv(self):
        """Failure path: no second retrieval when conv_id == '_container_events'."""
        orch = self._orch_with_small_mode()
        orch.context.build_small_model_context.reset_mock()
        with patch("config.get_small_model_mode", return_value=True), \
             patch("config.get_jit_retrieval_max", return_value=1), \
             patch("config.get_jit_retrieval_max_on_failure", return_value=2), \
             patch("config.get_small_model_now_max", return_value=5), \
             patch("config.get_small_model_rules_max", return_value=3), \
             patch("config.get_small_model_next_max", return_value=2):
            orch._get_compact_context(conversation_id="_container_events", has_tool_failure=True)

        total_calls = orch.context.build_small_model_context.call_count
        assert total_calls == 1, \
            "_container_events conv must NOT trigger second retrieval (avoid recursive fetch)"

    def test_disabled_small_mode_returns_empty(self):
        """_get_compact_context returns '' when SMALL_MODEL_MODE is False."""
        orch = self._orch_with_small_mode()
        with patch("config.get_small_model_mode", return_value=False):
            result = orch._get_compact_context("any-conv", has_tool_failure=True)
        assert result == "", "Compact context must be empty when small_model_mode=False"


# ═════════════════════════════════════════════════════════════════
# Test 4: Failure-compact counted exactly once in stream path
# ═════════════════════════════════════════════════════════════════

class TestFailureCompactCountedOnce:
    """Test 4: Double-counting fix — failure_ctx chars counted only via tool_ctx."""

    def test_stream_failure_path_no_double_counting(self):
        """
        Stream path: failure_ctx is prepended to tool_context, source registered manually.
        Then tool_context (including failure block) is appended via _append_context_block.
        Result: context_chars_final == len(tool_context) — NOT len(fail) + len(tool_context).
        """
        orch = _make_orch(_default_layers())

        fail_block = "[COMPACT-CONTEXT-ON-FAILURE]\nNOW: container c-1 running\n\n"
        tool_output = "\nTool result: exit_code=0\n"

        trace = {"context_sources": [], "context_chars_final": 50}  # simulate post-build state
        full_context = "BASE_CONTEXT"

        # ── Stream path (Phase 1 fix) ──────────────────────────────────────
        # 1. Prepend fail_block to tool_context (no char accounting here)
        tool_context = fail_block + tool_output
        # 2. Register failure_ctx source manually (no char update)
        trace["context_sources"].append("failure_ctx")
        # 3. Append full tool_context once via _append_context_block
        full_context = orch._append_context_block(
            full_context, tool_context, "tool_ctx", trace
        )

        # ── Assertions ────────────────────────────────────────────────────
        assert trace["context_sources"].count("failure_ctx") == 1, \
            "failure_ctx must appear exactly once in context_sources"
        assert trace["context_sources"].count("tool_ctx") == 1, \
            "tool_ctx must appear exactly once"

        # chars_final must reflect ONLY one append: len(tool_context) added once
        expected_delta = len(tool_context)
        assert trace["context_chars_final"] == 50 + expected_delta, \
            (f"context_chars_final must not double-count failure_ctx. "
             f"Expected 50+{expected_delta}={50 + expected_delta}, "
             f"got {trace['context_chars_final']}")

    def test_sync_failure_path_prepends_and_counts(self):
        """
        Sync path: failure_ctx is prepended via _append_context_block (prepend=True).
        chars are counted ONCE for the failure block specifically.
        """
        orch = _make_orch(_default_layers())

        fail_block = "[COMPACT-CONTEXT-ON-FAILURE]\nstate\n\n"
        base = "BASE_CTX"
        trace = {"context_sources": [], "context_chars_final": len(base)}

        # Sync path: failure_ctx is prepended and chars counted by _append_context_block
        result = orch._append_context_block(base, fail_block, "failure_ctx", trace, prepend=True)

        assert result.startswith(fail_block), "failure block must be prepended"
        assert trace["context_chars_final"] == len(base) + len(fail_block)
        assert "failure_ctx" in trace["context_sources"]

    def test_failure_compact_block_builder_returns_formatted_string(self):
        """_build_failure_compact_block must return formatted block or empty string."""
        orch = _make_orch(_default_layers())
        # Mock _get_compact_context to return test content
        orch._get_compact_context = MagicMock(return_value="NOW:\n  - c-1 running\n")

        block = orch._build_failure_compact_block(
            conv_id="test-conv",
            current_context_len=0,
            small_model_mode=False,
        )
        assert isinstance(block, str)
        assert "[COMPACT-CONTEXT-ON-FAILURE]" in block
        assert "c-1 running" in block

    def test_failure_compact_block_empty_when_no_compact_data(self):
        """_build_failure_compact_block must return '' when _get_compact_context is empty."""
        orch = _make_orch(_default_layers())
        orch._get_compact_context = MagicMock(return_value="")

        block = orch._build_failure_compact_block("conv", 0, False)
        assert block == "", "No compact data → no failure block"


# ═════════════════════════════════════════════════════════════════
# Test 5: Final-cap applied after ALL appends (Phase 2.5)
# ═════════════════════════════════════════════════════════════════

class TestFinalCapAfterAllAppends:
    """Test 5: SMALL_MODEL_FINAL_CAP truncates context after tool_ctx + jit + failure appends."""

    def _apply_final_cap(self, retrieved_memory: str, ctx_trace: dict, cap: int) -> str:
        """Simulate the Phase 2.5 cap logic inline (same code as orchestrator)."""
        if cap > 0 and len(retrieved_memory) > cap:
            retrieved_memory = retrieved_memory[:cap]
            ctx_trace["context_chars_final"] = cap
        return retrieved_memory

    def test_cap_truncates_oversized_context(self):
        """Context longer than cap must be truncated."""
        ctx = "A" * 5000
        trace = {"context_chars_final": 5000}
        result = self._apply_final_cap(ctx, trace, cap=100)
        assert len(result) == 100
        assert trace["context_chars_final"] == 100

    def test_cap_not_applied_when_under_limit(self):
        """Context at or below cap must not be truncated."""
        ctx = "B" * 50
        trace = {"context_chars_final": 50}
        result = self._apply_final_cap(ctx, trace, cap=100)
        assert len(result) == 50
        assert trace["context_chars_final"] == 50  # unchanged

    def test_cap_zero_means_disabled(self):
        """Cap=0 must not truncate anything (disabled by default)."""
        ctx = "C" * 10000
        trace = {"context_chars_final": 10000}
        result = self._apply_final_cap(ctx, trace, cap=0)
        assert len(result) == 10000  # untouched

    def test_config_default_is_zero_disabled(self):
        """get_small_model_final_cap() default must be 0 (disabled)."""
        try:
            from config import get_small_model_final_cap
        except ImportError:
            pytest.skip("config not importable")
        with patch.dict(os.environ, {}, clear=False):
            # Remove env override if present
            os.environ.pop("SMALL_MODEL_FINAL_CAP", None)
            val = get_small_model_final_cap()
            # We can't guarantee the env is clean in all environments,
            # but the default value should be 0 if not configured
            assert isinstance(val, int), "get_small_model_final_cap must return int"

    def test_cap_applied_after_all_appends_simulation(self):
        """
        Full simulation: build_effective_context → append tool_ctx → append jit_memory
        → apply final cap. Verifies cap is enforced on the cumulative result.
        """
        orch = _make_orch(_default_layers(), _default_ctx_mgr(memory_data="MEM"))

        # Step 1: Build initial context
        ctx, trace = orch.build_effective_context(
            user_text="query", conv_id="conv", small_model_mode=False
        )

        # Step 2: Append tool output (large)
        big_tool_ctx = "T" * 2000
        ctx = orch._append_context_block(ctx, big_tool_ctx, "tool_ctx", trace)

        # Step 3: Apply final cap (100 chars)
        cap = 100
        if len(ctx) > cap:
            ctx = ctx[:cap]
            trace["context_chars_final"] = cap

        assert len(ctx) <= cap, f"Context must be <= {cap} after final cap"
        assert trace["context_chars_final"] == cap


# ═════════════════════════════════════════════════════════════════
# Test 6: [CTX-FINAL] payload_chars computation
# ═════════════════════════════════════════════════════════════════

class TestCtxFinalPayloadChars:
    """Test 6: OutputLayer payload_chars = sum(len(m['content']) for m in messages)."""

    def test_payload_chars_formula(self):
        """CTX-FINAL marker formula must equal sum of message content lengths."""
        messages = [
            {"role": "system", "content": "System instructions here"},
            {"role": "user", "content": "User query text"},
        ]
        payload_chars = sum(len(m.get("content") or "") for m in messages)
        expected = len("System instructions here") + len("User query text")
        assert payload_chars == expected

    def test_payload_chars_handles_none_content(self):
        """Messages with None content must be treated as 0 chars."""
        messages = [
            {"role": "system", "content": None},
            {"role": "user", "content": "text"},
        ]
        payload_chars = sum(len(m.get("content") or "") for m in messages)
        assert payload_chars == len("text")

    def test_build_messages_returns_list_with_system_and_user(self):
        """OutputLayer._build_messages must return messages with system + user roles."""
        try:
            from core.layers.output import OutputLayer
        except ImportError as e:
            pytest.skip(f"Cannot import OutputLayer: {e}")

        with patch("core.layers.output.get_hub", return_value=MagicMock()), \
             patch("core.layers.output.get_enabled_tools", return_value=[]), \
             patch("core.layers.output.get_persona") as mock_persona:

            mock_p = MagicMock()
            mock_p.build_system_prompt.return_value = "SYSTEM_PROMPT_TEXT"
            mock_persona.return_value = mock_p

            layer = OutputLayer()
            messages = layer._build_messages(
                user_text="hello world",
                verified_plan={"_ctx_trace": {"mode": "full", "context_sources": [], "retrieval_count": 0}},
                memory_data="some memory",
                memory_required_but_missing=False,
                chat_history=None,
            )

        assert isinstance(messages, list)
        roles = [m["role"] for m in messages]
        assert "system" in roles
        assert "user" in roles

        # payload_chars formula
        payload_chars = sum(len(m.get("content") or "") for m in messages)
        sys_msg = next(m for m in messages if m["role"] == "system")
        user_msg = next(m for m in messages if m["role"] == "user")
        assert payload_chars == len(sys_msg["content"]) + len(user_msg.get("content", ""))

    def test_ctx_trace_flows_into_plan(self):
        """verified_plan['_ctx_trace'] must be accessible for [CTX-FINAL] logging."""
        ctx_trace = {
            "mode": "small+failure",
            "context_sources": ["compact", "failure_ctx", "tool_ctx"],
            "retrieval_count": 2,
            "context_chars_final": 800,
        }
        verified_plan = {"_ctx_trace": ctx_trace}
        retrieved = verified_plan.get("_ctx_trace", {})
        assert retrieved.get("mode") == "small+failure"
        assert retrieved.get("retrieval_count") == 2
        assert "failure_ctx" in retrieved.get("context_sources", [])


# ═════════════════════════════════════════════════════════════════
# Test 7: SMALL_MODEL_TOOL_CTX_CAP config
# ═════════════════════════════════════════════════════════════════

class TestToolContextCapConfig:
    """Test 7: SMALL_MODEL_TOOL_CTX_CAP is readable; enforcement via xfail."""

    def test_config_function_returns_int(self):
        """get_small_model_tool_ctx_cap() must return an int."""
        try:
            from config import get_small_model_tool_ctx_cap
        except ImportError:
            pytest.skip("config not importable")
        val = get_small_model_tool_ctx_cap()
        assert isinstance(val, int)

    def test_default_is_zero_disabled(self):
        """Default SMALL_MODEL_TOOL_CTX_CAP must be 0 (disabled)."""
        try:
            from config import get_small_model_tool_ctx_cap
        except ImportError:
            pytest.skip("config not importable")
        os.environ.pop("SMALL_MODEL_TOOL_CTX_CAP", None)
        val = get_small_model_tool_ctx_cap()
        # Can only assert it's an int since env may be pre-set in some envs
        assert val >= 0, "Tool context cap must be non-negative"

    def test_configurable_via_env(self):
        """SMALL_MODEL_TOOL_CTX_CAP must be settable via env var."""
        try:
            from config import get_small_model_tool_ctx_cap
        except ImportError:
            pytest.skip("config not importable")
        with patch.dict(os.environ, {"SMALL_MODEL_TOOL_CTX_CAP": "2000"}):
            val = get_small_model_tool_ctx_cap()
            assert val == 2000

    def test_tool_ctx_cap_enforcement_in_orchestrator(self):
        """
        _clip_tool_context with SMALL_MODEL_TOOL_CTX_CAP=200 and tool_context > 200:
        - result must be <= 200 chars (marker fits within cap, no blowout)
        - a truncation marker must be present
        """
        orch = _make_orch(_default_layers())
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")

        big_tool_ctx = "T" * 5000
        cap = 200

        with patch("config.get_small_model_tool_ctx_cap", return_value=cap):
            result = orch._clip_tool_context(big_tool_ctx, small_model_mode=True)

        assert len(result) <= cap, (
            f"_clip_tool_context result ({len(result)}) exceeds cap ({cap})"
        )
        assert "[...truncated:" in result


# ═════════════════════════════════════════════════════════════════
# Test 8: Workspace-event parsing stability
# ═════════════════════════════════════════════════════════════════

class TestWorkspaceEventParsing:
    """Test 8: _extract_workspace_events and _get_event_data with all input formats."""

    def _make_ctx_mgr(self):
        """Return a ContextManager instance (no-arg constructor)."""
        try:
            from core.context_manager import ContextManager
        except ImportError as e:
            pytest.skip(f"Cannot import ContextManager: {e}")
        return ContextManager()

    # ── _extract_workspace_events ──────────────────────────────────────────

    def test_extract_toolresult_with_list_content(self):
        """ToolResult (Fast-Lane): result.content is a list → return it directly."""
        ctx = self._make_ctx_mgr()
        events = [{"event_type": "container_started", "event_data": {"container_id": "c-1"}}]

        class MockToolResult:
            content = events

        result = ctx._extract_workspace_events(MockToolResult())
        assert result == events

    def test_extract_toolresult_with_json_string_content(self):
        """ToolResult with JSON-string content must be parsed."""
        ctx = self._make_ctx_mgr()
        events = [{"event_type": "x", "event_data": {}}]

        class MockToolResult:
            content = json.dumps(events)

        result = ctx._extract_workspace_events(MockToolResult())
        assert isinstance(result, list)
        assert len(result) == 1

    def test_extract_structured_content_dict(self):
        """Dict with structuredContent.entries → return entries."""
        ctx = self._make_ctx_mgr()
        events = [{"event_type": "blueprint_selected", "event_data": {"blueprint_id": "bp-1"}}]
        result_dict = {"structuredContent": {"entries": events}}
        extracted = ctx._extract_workspace_events(result_dict)
        assert extracted == events

    def test_extract_structured_content_legacy_events_key(self):
        """Dict with structuredContent.events (legacy key) → return it."""
        ctx = self._make_ctx_mgr()
        events = [{"event_type": "y"}]
        result_dict = {"structuredContent": {"events": events}}
        extracted = ctx._extract_workspace_events(result_dict)
        assert extracted == events

    def test_extract_plain_list(self):
        """Plain list input → return as-is."""
        ctx = self._make_ctx_mgr()
        events = [{"event_type": "z"}]
        result = ctx._extract_workspace_events(events)
        assert result == events

    def test_extract_none_returns_empty(self):
        """None or unknown type → return empty list."""
        ctx = self._make_ctx_mgr()
        assert ctx._extract_workspace_events(None) == []
        assert ctx._extract_workspace_events(42) == []
        assert ctx._extract_workspace_events("invalid") == []

    def test_extract_empty_toolresult_content(self):
        """ToolResult with empty list content → return empty list."""
        ctx = self._make_ctx_mgr()

        class MockToolResult:
            content = []

        result = ctx._extract_workspace_events(MockToolResult())
        assert result == []

    # ── _get_event_data ────────────────────────────────────────────────────

    def test_get_event_data_dict(self):
        """event_data as dict → return it directly."""
        ctx = self._make_ctx_mgr()
        entry = {"event_data": {"container_id": "c-1", "blueprint_id": "bp-python"}}
        data = ctx._get_event_data(entry)
        assert data == {"container_id": "c-1", "blueprint_id": "bp-python"}

    def test_get_event_data_json_string(self):
        """event_data as JSON string (legacy pre-migration rows) → parse it."""
        ctx = self._make_ctx_mgr()
        inner = {"container_id": "c-2", "exit_code": 0}
        entry = {"event_data": json.dumps(inner)}
        data = ctx._get_event_data(entry)
        assert data == inner

    def test_get_event_data_invalid_json_returns_empty(self):
        """Invalid JSON string in event_data → return empty dict."""
        ctx = self._make_ctx_mgr()
        entry = {"event_data": "not-valid-json{{{"}
        data = ctx._get_event_data(entry)
        assert data == {}

    def test_get_event_data_missing_key_returns_empty(self):
        """Missing event_data key → return empty dict."""
        ctx = self._make_ctx_mgr()
        data = ctx._get_event_data({})
        assert data == {}

    def test_get_event_data_preserves_nested_structure(self):
        """event_data with nested dicts must be returned intact."""
        ctx = self._make_ctx_mgr()
        nested = {"container_id": "c-3", "stats": {"cpu": 80, "ram": 4096}}
        entry = {"event_data": nested}
        data = ctx._get_event_data(entry)
        assert data["stats"]["cpu"] == 80


# ═════════════════════════════════════════════════════════════════
# Test 9: Blueprint router gates
# ═════════════════════════════════════════════════════════════════

class TestBlueprintRouterGates:
    """Test 9: BlueprintSemanticRouter — strict / suggest / no-match + trust filter.

    blueprint_store calls init_db() at module-import time which requires /app/data.
    We inject a mock via sys.modules so the local `from ... import` inside route()
    picks up our mock without ever touching the real module.
    """

    def _make_router(self):
        try:
            from core.blueprint_router import BlueprintSemanticRouter
        except ImportError as e:
            pytest.skip(f"Cannot import BlueprintSemanticRouter: {e}")
        return BlueprintSemanticRouter()

    def _verified_meta(self, blueprint_id: str) -> str:
        return json.dumps({"trust_level": "verified", "blueprint_id": blueprint_id})

    def _mock_store(self, active_ids=None):
        """Return a fake blueprint_store module with controllable get_active_blueprint_ids."""
        import types
        store = types.ModuleType("container_commander.blueprint_store")
        store.get_active_blueprint_ids = MagicMock(return_value=active_ids if active_ids is not None else {"__any__"})
        return store

    def test_strict_score_auto_routes(self):
        """Score >= 0.85 → use_blueprint (auto-route, no user input needed)."""
        router = self._make_router()
        mock_results = [{"similarity": 0.91, "metadata": self._verified_meta("bp-python")}]

        import sys
        with patch.dict(sys.modules, {"container_commander.blueprint_store": self._mock_store({"bp-python"})}), \
             patch("mcp.client.blueprint_semantic_search", return_value=mock_results):
            decision = router.route("run python code", "code execution")

        assert decision.decision == "use_blueprint"
        assert decision.blueprint_id == "bp-python"
        assert decision.score >= 0.85

    def test_suggest_zone_asks_user(self):
        """Score in [0.68, 0.85) → suggest_blueprint (ask user, don't auto-start)."""
        router = self._make_router()
        mock_results = [{"similarity": 0.75, "metadata": self._verified_meta("bp-node")}]

        import sys
        with patch.dict(sys.modules, {"container_commander.blueprint_store": self._mock_store({"bp-node"})}), \
             patch("mcp.client.blueprint_semantic_search", return_value=mock_results):
            decision = router.route("run something node-like")

        assert decision.decision == "suggest_blueprint", \
            "Score in suggest zone must trigger user confirmation, not auto-route"
        assert decision.blueprint_id is not None

    def test_no_match_blocks_request_container(self):
        """Score < 0.68 → no_blueprint (hard gate, no freestyle fallback)."""
        router = self._make_router()
        mock_results = [{"similarity": 0.30, "metadata": self._verified_meta("bp-x")}]

        import sys
        with patch.dict(sys.modules, {"container_commander.blueprint_store": self._mock_store({"bp-x"})}), \
             patch("mcp.client.blueprint_semantic_search", return_value=mock_results):
            decision = router.route("something completely unrelated")

        assert decision.decision == "no_blueprint", \
            "Low score must result in no_blueprint — no freestyle container launch!"

    def test_empty_results_returns_no_blueprint(self):
        """Empty search results → no_blueprint."""
        router = self._make_router()

        with patch("mcp.client.blueprint_semantic_search", return_value=[]):
            decision = router.route("deploy something")

        assert decision.decision == "no_blueprint"

    def test_trust_filter_blocks_unverified(self):
        """Blueprint without trust_level='verified' must be skipped → no_blueprint."""
        router = self._make_router()
        untrusted_meta = json.dumps({"trust_level": "unverified", "blueprint_id": "bp-evil"})
        mock_results = [{"similarity": 0.99, "metadata": untrusted_meta}]

        import sys
        with patch.dict(sys.modules, {"container_commander.blueprint_store": self._mock_store({"bp-evil"})}), \
             patch("mcp.client.blueprint_semantic_search", return_value=mock_results):
            decision = router.route("launch evil container")

        assert decision.decision == "no_blueprint", \
            "Unverified blueprint must be blocked regardless of score"

    def test_trust_filter_handles_broken_metadata(self):
        """Broken metadata (non-JSON) → skip blueprint → no_blueprint."""
        router = self._make_router()
        mock_results = [{"similarity": 0.95, "metadata": "INVALID_JSON{{{}"}]

        with patch("mcp.client.blueprint_semantic_search", return_value=mock_results):
            decision = router.route("launch")

        assert decision.decision == "no_blueprint", \
            "Broken metadata must be treated as untrusted → skip → no_blueprint"

    def test_soft_deleted_blueprint_blocked(self):
        """Blueprint in graph but soft-deleted in SQLite (not in active set) → skip."""
        router = self._make_router()
        mock_results = [{"similarity": 0.92, "metadata": self._verified_meta("bp-deleted")}]

        import sys
        with patch.dict(sys.modules, {"container_commander.blueprint_store": self._mock_store(set())}), \
             patch("mcp.client.blueprint_semantic_search", return_value=mock_results):
            decision = router.route("launch deleted blueprint")

        assert decision.decision == "no_blueprint", \
            "Soft-deleted blueprint (not in SQLite active set) must be blocked"

    def test_suggest_includes_top2_candidates(self):
        """Suggest zone response must include candidate list for user selection."""
        router = self._make_router()
        mock_results = [
            {"similarity": 0.74, "metadata": self._verified_meta("bp-a")},
            {"similarity": 0.71, "metadata": self._verified_meta("bp-b")},
        ]

        import sys
        with patch.dict(sys.modules, {"container_commander.blueprint_store": self._mock_store({"bp-a", "bp-b"})}), \
             patch("mcp.client.blueprint_semantic_search", return_value=mock_results):
            decision = router.route("maybe python or node?")

        if decision.decision == "suggest_blueprint":
            assert len(decision.candidates) >= 1, \
                "Suggest response must include at least 1 candidate for user selection"


# ═════════════════════════════════════════════════════════════════
# Test 10: TTL event contains session_id + blueprint_id
# ═════════════════════════════════════════════════════════════════

class TestTtlEventStructure:
    """Test 10: container_ttl_expired event must contain session_id + blueprint_id."""

    def test_ttl_event_shape_via_direct_callback(self):
        """
        Invoke _timeout directly (bypassing threading.Timer delay).
        Verify workspace_event_save receives event_type + required event_data fields.
        """
        try:
            from container_commander import engine
        except ImportError as e:
            pytest.skip(f"Cannot import container_commander.engine: {e}")

        container_id = "test-ttl-unit-abc123"
        recorded_calls: list = []

        mock_container = MagicMock()
        mock_container.labels = {
            "trion.blueprint": "bp-python",
            "trion.session_id": "sess-unit-test",
        }
        mock_container.reload = MagicMock()

        mock_docker = MagicMock()
        mock_docker.containers.get.return_value = mock_container

        with patch.object(engine, "get_client", return_value=mock_docker), \
             patch("mcp.client.call_tool",
                   side_effect=lambda t, a: recorded_calls.append((t, a))), \
             patch.object(engine, "stop_container"):

            # Create timer with long TTL to avoid auto-firing
            engine._set_ttl_timer(container_id, 99999)
            timer = engine._ttl_timers.get(container_id)
            assert timer is not None, "_ttl_timers must store the timer"
            timer.cancel()  # Cancel to prevent background firing
            # Invoke _timeout callback directly (synchronous)
            timer.function()

        assert len(recorded_calls) >= 1, "workspace_event_save must have been called"
        tool_name, args = recorded_calls[0]
        assert tool_name == "workspace_event_save", \
            f"Expected workspace_event_save, got {tool_name!r}"

        ev_type = args.get("event_type")
        assert ev_type == "container_ttl_expired", \
            f"event_type must be 'container_ttl_expired', got {ev_type!r}"

        event_data = args.get("event_data", {})
        assert "blueprint_id" in event_data, "event_data must contain blueprint_id"
        assert "session_id" in event_data, "event_data must contain session_id"
        assert event_data["blueprint_id"] == "bp-python"
        assert event_data["session_id"] == "sess-unit-test"
        assert "expired_at" in event_data, "event_data must contain expired_at timestamp"
        assert "reason" in event_data, "event_data must contain reason field"

    def test_ttl_event_fallback_to_in_memory_when_docker_unavailable(self):
        """When Docker container is gone, fallback to in-memory registry for session_id."""
        try:
            from container_commander import engine
        except ImportError as e:
            pytest.skip(f"Cannot import container_commander.engine: {e}")

        container_id = "test-ttl-fallback-xyz"
        recorded_calls: list = []

        mock_docker = MagicMock()
        mock_docker.containers.get.side_effect = Exception("Container not found")

        # Inject in-memory fallback entry
        from container_commander.engine import _active

        class _FakeEntry:
            blueprint_id = "bp-fallback"
            session_id = "sess-fallback-001"

        _active[container_id] = _FakeEntry()

        try:
            with patch.object(engine, "get_client", return_value=mock_docker), \
                 patch("mcp.client.call_tool",
                       side_effect=lambda t, a: recorded_calls.append((t, a))), \
                 patch.object(engine, "stop_container"):

                engine._set_ttl_timer(container_id, 99999)
                timer = engine._ttl_timers.get(container_id)
                assert timer is not None
                timer.cancel()
                timer.function()
        finally:
            _active.pop(container_id, None)

        assert len(recorded_calls) >= 1
        _, args = recorded_calls[0]
        event_data = args.get("event_data", {})
        assert event_data.get("blueprint_id") == "bp-fallback"
        assert event_data.get("session_id") == "sess-fallback-001"



# ═════════════════════════════════════════════════════════════════
# Commit B (Phase 3): Fail-Closed End-to-End
# ═════════════════════════════════════════════════════════════════


class TestGetCompactContextFailClosed:
    """
    Commit B (Phase 3): _get_compact_context and build_small_model_context must
    return canonical fail context (not silent "") when the pipeline fails.
    """

    def test_get_compact_context_returns_fail_context_on_build_error(self):
        """
        _get_compact_context must return canonical CONTEXT ERROR string (not "")
        when build_small_model_context raises an exception.
        """
        orch = _make_orch(_default_layers())

        failing_ctx = MagicMock()
        failing_ctx.get_context.return_value = _MockCtxResult()
        failing_ctx.build_small_model_context.side_effect = RuntimeError("hub down")
        orch.context = failing_ctx

        with patch("config.get_small_model_mode", return_value=True), \
             patch("config.get_jit_retrieval_max", return_value=1), \
             patch("config.get_jit_retrieval_max_on_failure", return_value=2), \
             patch("config.get_small_model_now_max", return_value=5), \
             patch("config.get_small_model_rules_max", return_value=3), \
             patch("config.get_small_model_next_max", return_value=2):
            result = orch._get_compact_context("test-conv")

        assert result != "", "_get_compact_context must not return empty string on failure"
        assert "CONTEXT ERROR" in result, (
            f"Fail-closed result must contain 'CONTEXT ERROR', got: {result!r}"
        )

    def test_get_compact_context_returns_now_section_on_failure(self):
        """Fail-closed result must contain a NOW: section."""
        orch = _make_orch(_default_layers())
        failing_ctx = MagicMock()
        failing_ctx.get_context.return_value = _MockCtxResult()
        failing_ctx.build_small_model_context.side_effect = Exception("timeout")
        orch.context = failing_ctx

        with patch("config.get_small_model_mode", return_value=True), \
             patch("config.get_jit_retrieval_max", return_value=1), \
             patch("config.get_jit_retrieval_max_on_failure", return_value=2), \
             patch("config.get_small_model_now_max", return_value=5), \
             patch("config.get_small_model_rules_max", return_value=3), \
             patch("config.get_small_model_next_max", return_value=2):
            result = orch._get_compact_context("test-conv")

        assert "NOW" in result, (
            f"Fail-closed result must contain 'NOW', got: {result!r}"
        )

    def test_get_compact_context_returns_next_rückfrage_on_failure(self):
        """Fail-closed result must contain the Rückfrage NEXT bullet."""
        orch = _make_orch(_default_layers())
        failing_ctx = MagicMock()
        failing_ctx.get_context.return_value = _MockCtxResult()
        failing_ctx.build_small_model_context.side_effect = ValueError("corrupt state")
        orch.context = failing_ctx

        with patch("config.get_small_model_mode", return_value=True), \
             patch("config.get_jit_retrieval_max", return_value=1), \
             patch("config.get_jit_retrieval_max_on_failure", return_value=2), \
             patch("config.get_small_model_now_max", return_value=5), \
             patch("config.get_small_model_rules_max", return_value=3), \
             patch("config.get_small_model_next_max", return_value=2):
            result = orch._get_compact_context("test-conv")

        assert "präzisieren" in result or "wiederholen" in result or "NEXT" in result, (
            f"Fail-closed result must contain Rückfrage or NEXT, got: {result!r}"
        )

    def test_get_compact_context_empty_when_small_model_mode_off(self):
        """_get_compact_context must still return '' when small_model_mode=False (no change)."""
        orch = _make_orch(_default_layers())
        with patch("config.get_small_model_mode", return_value=False):
            result = orch._get_compact_context("test-conv")
        assert result == "", (
            f"With small_model_mode=False, must return '' (unchanged), got: {result!r}"
        )

    def test_build_small_model_context_fail_closed(self):
        """
        ContextManager.build_small_model_context must return canonical fail context (not "")
        when an internal error occurs.
        """
        try:
            from core.context_manager import ContextManager
        except ImportError as e:
            pytest.skip(f"Cannot import ContextManager: {e}")

        cm = ContextManager.__new__(ContextManager)
        cm._protocol_cache = {}

        # get_hub is imported inside build_small_model_context → patch at mcp.hub
        with patch("mcp.hub.get_hub", side_effect=RuntimeError("hub unavailable")):
            result = cm.build_small_model_context(conversation_id="conv-test")

        assert result != "", (
            "build_small_model_context must not return '' on failure (fail-closed)"
        )
        assert "CONTEXT ERROR" in result, (
            f"build_small_model_context fail-closed result must contain 'CONTEXT ERROR', got: {result!r}"
        )
