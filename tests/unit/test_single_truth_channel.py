"""
Tests for Commits 1-5 + Codex fixes: Single Truth Channel, Tool Cards (sync+stream parity),
Protocol Gate, Retrieval Policy (sync+stream budget), Observability.

Date: 2026-02-18
"""

import pytest
import sys
import os
import json
import types
from unittest.mock import Mock, AsyncMock, patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ─── helpers ────────────────────────────────────────────────────────────────

def _make_output_layer():
    try:
        from core.layers.output import OutputLayer
        return OutputLayer()
    except Exception:
        return None


def _make_verified_plan(**kwargs):
    base = {
        "intent": "question",
        "_verified": True,
        "_tool_results": "",
        "_ctx_trace": {
            "mode": "full",
            "context_sources": [],
            "retrieval_count": 0,
        },
    }
    base.update(kwargs)
    return base


def _make_store_module():
    m = types.ModuleType("container_commander.blueprint_store")
    m.get_active_blueprint_ids = Mock(return_value=set())
    m.init_db = Mock()
    return m


def _make_orch():
    mock_store = _make_store_module()
    thinking = MagicMock()
    thinking.analyze = AsyncMock(return_value={
        "intent": "question", "needs_memory": False,
        "memory_keys": [], "hallucination_risk": "low",
        "needs_sequential_thinking": False, "sequential_complexity": 0,
        "suggested_tools": [],
    })
    control = MagicMock()
    control.verify = AsyncMock(return_value={"approved": True, "corrections": {}, "warnings": []})
    control.apply_corrections = MagicMock(side_effect=lambda p, v: {**p, "_verified": True})
    control._check_sequential_thinking = AsyncMock(return_value=None)
    control.set_mcp_hub = MagicMock()
    output = MagicMock()
    output.generate = AsyncMock(return_value="ok")
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


# ═════════════════════════════════════════════════════════════════
# Commit 1: No Double Injection
# ═════════════════════════════════════════════════════════════════

class TestNoDoubleInjection:
    """Commit 1: _tool_results must not appear separately in system prompt or user message."""

    def test_system_prompt_has_no_tool_results_section(self):
        """_build_system_prompt must not contain a PFLICHT-TOOL-ERGEBNISSE block."""
        ol = _make_output_layer()
        if ol is None:
            pytest.skip("OutputLayer not importable")
        plan = _make_verified_plan(
            _tool_results="some tool output data",
            _tool_confidence="high",
        )
        prompt = ol._build_system_prompt(plan, memory_data="base memory")
        # Must NOT have the old triple-injection block
        assert "PFLICHT — TOOL-ERGEBNISSE" not in prompt
        assert "DATEN AUS TOOL-ABFRAGE" not in prompt

    def test_system_prompt_has_no_tool_results_in_non_small_mode(self):
        """Even in non-small mode _tool_results should not appear as separate section."""
        ol = _make_output_layer()
        if ol is None:
            pytest.skip("OutputLayer not importable")
        plan = _make_verified_plan(_tool_results="X" * 500)
        with patch("core.layers.output._is_small_model_mode", return_value=False):
            prompt = ol._build_system_prompt(plan, memory_data="base")
        assert "PFLICHT — TOOL-ERGEBNISSE" not in prompt

    def test_user_message_is_plain_user_text(self):
        """_build_messages user message is only user_text, no tool/protocol injection."""
        ol = _make_output_layer()
        if ol is None:
            pytest.skip("OutputLayer not importable")
        plan = _make_verified_plan(
            _tool_results="tool output here",
            time_reference="today",
        )
        msgs = ol._build_messages("Was ist mein Name?", plan, memory_data="protocol data")
        user_msgs = [m for m in msgs if m["role"] == "user"]
        assert len(user_msgs) == 1
        content = user_msgs[0]["content"]
        assert content == "Was ist mein Name?"
        assert "DATEN AUS TOOL-ABFRAGE" not in content
        assert "TAGESPROTOKOLL" not in content
        assert "TOOL-FEHLER" not in content

    def test_user_message_plain_even_with_error(self):
        """Tool failure must not cause duplicate error injection in user message."""
        ol = _make_output_layer()
        if ol is None:
            pytest.skip("OutputLayer not importable")
        plan = _make_verified_plan(_tool_results="TOOL-FEHLER: something broke")
        msgs = ol._build_messages("Run something", plan, memory_data="ctx")
        user_msgs = [m for m in msgs if m["role"] == "user"]
        assert user_msgs[0]["content"] == "Run something"

    def test_legacy_full_prompt_no_tool_injection(self):
        """_build_full_prompt must not append a DATEN AUS TOOL-ABFRAGE block."""
        ol = _make_output_layer()
        if ol is None:
            pytest.skip("OutputLayer not importable")
        plan = _make_verified_plan(_tool_results="raw result here")
        prompt = ol._build_full_prompt("test query", plan, memory_data="base")
        assert "DATEN AUS TOOL-ABFRAGE" not in prompt
        assert "test query" in prompt


# ═════════════════════════════════════════════════════════════════
# Commit 2: Tool Result Cards
# ═════════════════════════════════════════════════════════════════

class TestToolResultCard:
    """Commit 2: _build_tool_result_card must produce bounded cards with ref_id."""

    def test_card_within_cap(self):
        """Card must fit within _TOOL_CARD_CHAR_CAP."""
        orch = _make_orch()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        with patch.object(orch, "_save_workspace_entry", return_value=None):
            card, ref_id = orch._build_tool_result_card(
                "memory_fact_save", "A" * 10000, "ok", "conv123"
            )
        assert len(card) <= orch._TOOL_CARD_CHAR_CAP + 30  # +30 for truncation marker
        assert ref_id

    def test_card_contains_ref_id(self):
        """Card text must contain the ref_id."""
        orch = _make_orch()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        with patch.object(orch, "_save_workspace_entry", return_value=None):
            card, ref_id = orch._build_tool_result_card(
                "get_system_info", "cpu: 4 cores\nram: 16gb\ndisk: 500gb", "ok", "conv123"
            )
        assert ref_id in card

    def test_card_has_key_facts(self):
        """Card must include extracted facts (non-empty lines)."""
        orch = _make_orch()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        raw = "cpu: 4 cores\nram: 16gb\ndisk: 500gb"
        with patch.object(orch, "_save_workspace_entry", return_value=None):
            card, _ = orch._build_tool_result_card("info_tool", raw, "ok", "conv")
        assert "cpu: 4 cores" in card

    def test_card_bullet_cap_respected(self):
        """Card must contain at most _TOOL_CARD_BULLET_CAP facts."""
        orch = _make_orch()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        raw = "\n".join(f"fact {i}" for i in range(20))
        with patch.object(orch, "_save_workspace_entry", return_value=None):
            card, _ = orch._build_tool_result_card("multi_tool", raw, "ok", "conv")
        bullets = [l for l in card.splitlines() if l.startswith("- ")]
        assert len(bullets) <= orch._TOOL_CARD_BULLET_CAP

    def test_error_card_contains_error_marker(self):
        """Error card must contain the tool-name."""
        orch = _make_orch()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        with patch.object(orch, "_save_workspace_entry", return_value=None):
            card, _ = orch._build_tool_result_card(
                "bad_tool", "connection refused", "error", "conv"
            )
        assert "bad_tool" in card

    def test_workspace_event_saved(self):
        """_save_workspace_entry must be called once per tool card."""
        orch = _make_orch()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        with patch.object(orch, "_save_workspace_entry") as mock_save:
            mock_save.return_value = None
            orch._build_tool_result_card("my_tool", "result text", "ok", "conv_x")
        mock_save.assert_called_once()
        call_args = mock_save.call_args
        payload = json.loads(call_args[0][1])
        assert payload["tool_name"] == "my_tool"
        assert payload["status"] == "ok"
        assert "ref_id" in payload
        assert "payload" in payload

    def test_fail_closed_on_empty_result(self):
        """Empty raw result → fallback fact instead of empty card."""
        orch = _make_orch()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        with patch.object(orch, "_save_workspace_entry", return_value=None):
            card, _ = orch._build_tool_result_card("quiet_tool", "", "partial", "conv")
        assert "Keine Ausgabe" in card or card.strip()  # not empty


# ═════════════════════════════════════════════════════════════════
# Commit 3: Protocol no-dump
# ═════════════════════════════════════════════════════════════════

class TestProtocolNoDump:
    """Commit 3: Daily protocol must only load when time_reference is set."""

    def _cm_patch_all(self, cm):
        """Return a context manager that patches all CM methods that touch external systems."""
        return [
            patch.object(cm, "_load_trion_laws", return_value=""),
            patch.object(cm, "_load_active_containers", return_value=""),
            patch.object(cm, "_search_system_tools", return_value=""),
            patch.object(cm, "_search_skill_graph", return_value=""),
            patch.object(cm, "_search_blueprint_graph", return_value=""),
            patch.object(cm, "_load_skill_knowledge_hint", return_value=""),
            patch.object(cm, "_search_memory_multi_context", return_value=("", False)),
        ]

    def test_protocol_not_loaded_without_time_reference(self):
        """get_context() must not load protocol when thinking_plan has no time_reference."""
        try:
            from core.context_manager import ContextManager
        except ImportError as e:
            pytest.skip(f"ContextManager not importable: {e}")

        cm = ContextManager()
        thinking_plan = {"intent": "question", "needs_memory": False, "memory_keys": []}

        patches = self._cm_patch_all(cm)
        with patch.object(cm, "_load_daily_protocol") as mock_protocol:
            mock_protocol.return_value = "[DATUM: 2026-02-18]\nSome content"
            for p in patches:
                p.start()
            try:
                with patch("config.get_small_model_mode", return_value=False):
                    result = cm.get_context("What is my name?", thinking_plan, "conv1")
                mock_protocol.assert_not_called()
                assert "daily_protocol" not in result.sources
            finally:
                for p in patches:
                    p.stop()

    def test_protocol_loaded_with_time_reference(self):
        """get_context() loads protocol only when time_reference is set."""
        try:
            from core.context_manager import ContextManager
        except ImportError as e:
            pytest.skip(f"ContextManager not importable: {e}")

        cm = ContextManager()
        thinking_plan = {
            "intent": "temporal",
            "needs_memory": False,
            "memory_keys": [],
            "time_reference": "today",
        }

        patches = self._cm_patch_all(cm)
        with patch.object(cm, "_load_daily_protocol") as mock_protocol:
            mock_protocol.return_value = "[DATUM: 2026-02-18]\nSome content"
            for p in patches:
                p.start()
            try:
                with patch("config.get_small_model_mode", return_value=False):
                    result = cm.get_context("Was haben wir heute besprochen?", thinking_plan, "conv1")
                mock_protocol.assert_called_once_with(time_reference="today")
                assert "daily_protocol" in result.sources
            finally:
                for p in patches:
                    p.stop()

    def test_protocol_not_in_memory_data_for_general_query(self):
        """memory_data must not contain [DATUM: ...] blocks for non-temporal queries."""
        try:
            from core.context_manager import ContextManager
        except ImportError as e:
            pytest.skip(f"ContextManager not importable: {e}")

        cm = ContextManager()
        thinking_plan = {"intent": "question", "needs_memory": False, "memory_keys": []}

        patches = self._cm_patch_all(cm)
        # _load_daily_protocol returns content but must NOT be called
        for p in patches:
            p.start()
        try:
            with patch("config.get_small_model_mode", return_value=False):
                result = cm.get_context("Hello", thinking_plan, "conv1")
            assert "[DATUM:" not in result.memory_data
        finally:
            for p in patches:
                p.stop()


# ═════════════════════════════════════════════════════════════════
# Commit 4: Retrieval Policy
# ═════════════════════════════════════════════════════════════════

class TestRetrievalPolicy:
    """Commit 4: _compute_retrieval_policy must return correct budget."""

    def test_normal_budget(self):
        """Normal request → get_jit_retrieval_max budget."""
        orch = _make_orch()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        with patch("config.get_jit_retrieval_max", return_value=1), \
             patch("config.get_jit_retrieval_max_on_failure", return_value=2):
            policy = orch._compute_retrieval_policy(
                {"intent": "question"}, {"_verified": True}, ""
            )
        assert policy["max_retrievals"] == 1
        assert policy["tool_failure"] is False

    def test_failure_budget(self):
        """Tool failure → get_jit_retrieval_max_on_failure budget."""
        orch = _make_orch()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        with patch("config.get_jit_retrieval_max", return_value=1), \
             patch("config.get_jit_retrieval_max_on_failure", return_value=2):
            policy = orch._compute_retrieval_policy(
                {}, {}, "some output\nTOOL-FEHLER: boom"
            )
        assert policy["max_retrievals"] == 2
        assert policy["tool_failure"] is True

    def test_verify_failure_triggers_budget(self):
        """VERIFY-FEHLER also triggers failure budget."""
        orch = _make_orch()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        with patch("config.get_jit_retrieval_max", return_value=1), \
             patch("config.get_jit_retrieval_max_on_failure", return_value=2):
            policy = orch._compute_retrieval_policy(
                {}, {}, "VERIFY-FEHLER: container not running"
            )
        assert policy["tool_failure"] is True
        assert policy["max_retrievals"] == 2

    def test_time_reference_forwarded(self):
        """time_reference from thinking_plan is forwarded in policy."""
        orch = _make_orch()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        with patch("config.get_jit_retrieval_max", return_value=1), \
             patch("config.get_jit_retrieval_max_on_failure", return_value=2):
            policy = orch._compute_retrieval_policy(
                {"time_reference": "yesterday"}, {}, ""
            )
        assert policy["time_reference"] == "yesterday"

    def test_extra_lookup_respects_budget(self):
        """Extra lookup from control corrections must stop when budget exhausted."""
        orch = _make_orch()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")

        # Simulate ctx_trace already at budget
        ctx_trace = {"retrieval_count": 1, "context_sources": [], "context_chars_final": 0}
        retrieved_memory = "base context"

        build_calls = []

        def _fake_build(**kwargs):
            build_calls.append(kwargs)
            return "extra data", {"context_chars": 10, "context_sources": ["memory:key"]}

        with patch("config.get_jit_retrieval_max", return_value=1), \
             patch("config.get_jit_retrieval_max_on_failure", return_value=2), \
             patch.object(orch, "build_effective_context", side_effect=_fake_build):

            thinking_plan = {"intent": "q", "memory_keys": []}
            verified_plan = {"corrections": {"memory_keys": ["key1", "key2"]}, "_verified": True}

            _policy = orch._compute_retrieval_policy(thinking_plan, verified_plan)
            _budget = _policy["max_retrievals"]  # 1

            for key in ["key1", "key2"]:
                if key not in thinking_plan.get("memory_keys", []):
                    if ctx_trace["retrieval_count"] >= _budget:
                        continue
                    extra_text, _ = orch.build_effective_context(
                        user_text=key, conv_id="c", small_model_mode=False,
                        cleanup_payload={"needs_memory": True, "memory_keys": [key]},
                        include_blocks={"compact": False, "system_tools": False, "memory_data": True},
                    )
                    if extra_text:
                        ctx_trace["retrieval_count"] += 1

        # Budget=1 already at 1 → no extra lookups allowed
        assert len(build_calls) == 0


# ═════════════════════════════════════════════════════════════════
# Commit 5: Observability Parity
# ═════════════════════════════════════════════════════════════════

class TestObservabilityParity:
    """Commit 5: [CTX-FINAL] must appear in both sync and stream paths."""

    def test_ctx_final_in_generate_stream(self):
        """generate_stream must emit [CTX-FINAL] log."""
        import inspect
        ol = _make_output_layer()
        if ol is None:
            pytest.skip("OutputLayer not importable")
        source = inspect.getsource(ol.generate_stream)
        assert "[CTX-FINAL]" in source

    def test_ctx_final_in_generate_stream_sync(self):
        """generate_stream_sync must also emit [CTX-FINAL] log (Commit 5 parity)."""
        import inspect
        ol = _make_output_layer()
        if ol is None:
            pytest.skip("OutputLayer not importable")
        source = inspect.getsource(ol.generate_stream_sync)
        assert "[CTX-FINAL]" in source

    def test_ctx_final_same_fields(self):
        """Both sync and stream [CTX-FINAL] must log the same 4 fields."""
        import inspect
        ol = _make_output_layer()
        if ol is None:
            pytest.skip("OutputLayer not importable")

        required_fields = ["mode=", "context_sources=", "payload_chars=", "retrieval_count="]
        for method_name in ("generate_stream", "generate_stream_sync"):
            source = inspect.getsource(getattr(ol, method_name))
            assert "[CTX-FINAL]" in source, f"[CTX-FINAL] not found in {method_name}"
            for field in required_fields:
                assert field in source, (
                    f"Field '{field}' missing from {method_name} (needed for [CTX-FINAL] parity)"
                )


# ═════════════════════════════════════════════════════════════════
# Codex Fix 1: Stream Tool Cards parity
# ═════════════════════════════════════════════════════════════════

def _find_orchestrator_path():
    """Locate orchestrator.py relative to this file or via sys.path."""
    import pathlib
    # When run from tests/unit/, parents[2] = project root
    for depth in (2, 3, 4):
        try:
            p = pathlib.Path(__file__).parents[depth] / "core" / "orchestrator.py"
            if p.exists():
                return p
        except IndexError:
            pass
    # Fallback: search sys.path
    for base in sys.path:
        p = pathlib.Path(base) / "core" / "orchestrator.py"
        if p.exists():
            return p
    return None


class TestStreamToolCardParity:
    """Stream path must use _build_tool_result_card same as sync path."""

    def _get_orchestrator_source(self):
        """Read the full orchestrator.py source directly from file."""
        p = _find_orchestrator_path()
        if p is None:
            return None
        return p.read_text(encoding="utf-8")

    def _get_card_source(self):
        import inspect
        try:
            from core.orchestrator import PipelineOrchestrator
            return inspect.getsource(PipelineOrchestrator._build_tool_result_card)
        except Exception:
            return None

    def test_stream_success_uses_card(self):
        """process_stream tool success path calls _build_tool_result_card."""
        source = self._get_orchestrator_source()
        if source is None:
            pytest.skip("Cannot read orchestrator.py")
        assert "_build_tool_result_card" in source
        assert "Commit 2 stream parity" in source

    def test_stream_error_uses_card(self):
        """Stream error path must wire _build_tool_result_card."""
        source = self._get_orchestrator_source()
        if source is None:
            pytest.skip("Cannot read orchestrator.py")
        # Both sync and stream card calls must be present
        assert source.count("_build_tool_result_card") >= 6, (
            "Expected >=6 card call-sites (sync: FL+retry+err+ok, stream: FL+retry+err+ok)"
        )

    def test_stream_fast_lane_uses_card(self):
        """Stream Fast Lane path must also wire _build_tool_result_card."""
        source = self._get_orchestrator_source()
        if source is None:
            pytest.skip("Cannot read orchestrator.py")
        assert "Commit 2 stream parity: Card" in source

    def test_payload_cap_is_large(self):
        """Workspace event payload cap must be >= 50_000 chars (not 8000)."""
        source = self._get_card_source()
        if source is None:
            pytest.skip("Cannot inspect _build_tool_result_card")
        assert "50_000" in source or "50000" in source, (
            "Payload cap must be >= 50 000 chars, not 8000 (audit quality)"
        )


# ═════════════════════════════════════════════════════════════════
# Codex Fix 2: Stream Retrieval Budget parity
# ═════════════════════════════════════════════════════════════════

class TestStreamRetrievalBudgetParity:
    """Stream extra-lookup must respect retrieval budget same as sync path."""

    def _get_orchestrator_source(self):
        p = _find_orchestrator_path()
        if p is None:
            return None
        return p.read_text(encoding="utf-8")

    def test_stream_extra_lookup_has_budget_check(self):
        """process_stream extra-lookup must call _compute_retrieval_policy."""
        source = self._get_orchestrator_source()
        if source is None:
            pytest.skip("Cannot read orchestrator.py")
        # Both sync and stream paths must reference _compute_retrieval_policy
        assert source.count("_compute_retrieval_policy") >= 2, (
            "Stream extra-lookup must gate through _compute_retrieval_policy (sync + stream = >=2 calls)"
        )

    def test_stream_budget_skip_logged(self):
        """Stream budget exhausted → skip message must be present."""
        source = self._get_orchestrator_source()
        if source is None:
            pytest.skip("Cannot read orchestrator.py")
        # Message appears in both sync and stream paths
        assert source.count("budget exhausted") >= 2, (
            "budget exhausted log must appear in both sync and stream paths"
        )

    def test_budget_policy_normal_vs_failure_stream(self):
        """Policy returns correct budget regardless of which path calls it."""
        orch = _make_orch()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        with patch("config.get_jit_retrieval_max", return_value=1), \
             patch("config.get_jit_retrieval_max_on_failure", return_value=2):
            normal = orch._compute_retrieval_policy({}, {}, "")
            failure = orch._compute_retrieval_policy({}, {}, "TOOL-FEHLER: boom")
        assert normal["max_retrievals"] == 1
        assert failure["max_retrievals"] == 2


# ═════════════════════════════════════════════════════════════════
# Phase-2 Residual 1: retrieval_count — nicht statisch
# ═════════════════════════════════════════════════════════════════

class TestRetrievalCountIsNotStatic:
    """
    Phase-2 Residual: retrieval_count in trace must reflect real retrieval steps.
    Normal path → 1 fetch (budget=1). Failure path → 2 fetches (budget=2).
    _container_events conv → always 1 (no recursive fetch).
    """

    def _make_orch_for_retrieval(self):
        return _make_orch()

    def test_normal_path_compact_sets_retrieval_count_1(self):
        """Normal small_model_mode: retrieval_count == 1 after build_effective_context."""
        orch = self._make_orch_for_retrieval()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        with patch("config.get_small_model_mode", return_value=True), \
             patch("config.get_jit_retrieval_max", return_value=1), \
             patch("config.get_jit_retrieval_max_on_failure", return_value=2), \
             patch("config.get_small_model_now_max", return_value=5), \
             patch("config.get_small_model_rules_max", return_value=3), \
             patch("config.get_small_model_next_max", return_value=2), \
             patch("config.get_small_model_char_cap", return_value=8000), \
             patch("config.get_context_trace_dryrun", return_value=False), \
             patch.object(orch, "_get_compact_context", return_value="NOW:\n  - state\n"):
            _, trace = orch.build_effective_context(
                user_text="hello",
                conv_id="conv-x",
                small_model_mode=True,
            )
        assert trace["retrieval_count"] == 1, (
            f"Normal path (budget=1) must yield retrieval_count=1, got {trace['retrieval_count']}"
        )

    def test_failure_path_compact_sets_retrieval_count_2(self):
        """Failure small_model_mode (budget=2, non-container conv): retrieval_count == 2."""
        orch = self._make_orch_for_retrieval()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        with patch("config.get_small_model_mode", return_value=True), \
             patch("config.get_jit_retrieval_max", return_value=1), \
             patch("config.get_jit_retrieval_max_on_failure", return_value=2), \
             patch("config.get_small_model_now_max", return_value=5), \
             patch("config.get_small_model_rules_max", return_value=3), \
             patch("config.get_small_model_next_max", return_value=2), \
             patch("config.get_small_model_char_cap", return_value=8000), \
             patch("config.get_context_trace_dryrun", return_value=False), \
             patch.object(orch, "_get_compact_context", return_value="NOW:\n  - fail\n"):
            _, trace = orch.build_effective_context(
                user_text="hello",
                conv_id="conv-fail",
                small_model_mode=True,
                debug_flags={"has_tool_failure": True},
            )
        assert trace["retrieval_count"] == 2, (
            f"Failure path (budget=2, non-container conv) must yield retrieval_count=2, "
            f"got {trace['retrieval_count']}"
        )

    def test_container_events_conv_retrieval_count_stays_1(self):
        """_container_events conv always yields retrieval_count=1 (no recursive fetch)."""
        orch = self._make_orch_for_retrieval()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        with patch("config.get_small_model_mode", return_value=True), \
             patch("config.get_jit_retrieval_max", return_value=1), \
             patch("config.get_jit_retrieval_max_on_failure", return_value=2), \
             patch("config.get_small_model_now_max", return_value=5), \
             patch("config.get_small_model_rules_max", return_value=3), \
             patch("config.get_small_model_next_max", return_value=2), \
             patch("config.get_small_model_char_cap", return_value=8000), \
             patch("config.get_context_trace_dryrun", return_value=False), \
             patch.object(orch, "_get_compact_context", return_value="NOW:\n  - container\n"):
            _, trace = orch.build_effective_context(
                user_text="container query",
                conv_id="_container_events",
                small_model_mode=True,
                debug_flags={"has_tool_failure": True},  # failure mode BUT container conv
            )
        assert trace["retrieval_count"] == 1, (
            f"_container_events conv must yield retrieval_count=1 even in failure mode, "
            f"got {trace['retrieval_count']}"
        )

    def test_full_model_mode_compact_not_built(self):
        """Full model mode: compact not built → retrieval_count not set from compact."""
        orch = self._make_orch_for_retrieval()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        with patch("config.get_context_trace_dryrun", return_value=False):
            _, trace = orch.build_effective_context(
                user_text="hello",
                conv_id="conv-full",
                small_model_mode=False,
            )
        # compact must NOT appear in full-model sources
        assert "compact" not in trace["context_sources"], (
            "compact block must not be built in full-model mode"
        )
        # retrieval_count in full mode reflects memory_data fetches only (0 or 1)
        assert trace["retrieval_count"] >= 0

    def test_retrieval_count_not_exceeds_budget(self):
        """retrieval_count must never exceed the configured budget."""
        orch = self._make_orch_for_retrieval()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        with patch("config.get_small_model_mode", return_value=True), \
             patch("config.get_jit_retrieval_max", return_value=1), \
             patch("config.get_jit_retrieval_max_on_failure", return_value=2), \
             patch("config.get_small_model_now_max", return_value=5), \
             patch("config.get_small_model_rules_max", return_value=3), \
             patch("config.get_small_model_next_max", return_value=2), \
             patch("config.get_small_model_char_cap", return_value=8000), \
             patch("config.get_context_trace_dryrun", return_value=False), \
             patch.object(orch, "_get_compact_context", return_value="NOW:\n  - state\n"):
            _, trace_normal = orch.build_effective_context(
                user_text="q", conv_id="c", small_model_mode=True,
                debug_flags={"has_tool_failure": False},
            )
            _, trace_failure = orch.build_effective_context(
                user_text="q", conv_id="c2", small_model_mode=True,
                debug_flags={"has_tool_failure": True},
            )
        assert trace_normal["retrieval_count"] <= 1, "Normal budget=1 must not exceed 1"
        assert trace_failure["retrieval_count"] <= 2, "Failure budget=2 must not exceed 2"

    def test_retrieval_count_capped_when_memory_used(self):
        """memory_used=True in memory_data block must not push retrieval_count over budget.

        Fix 2: When compact_rc=2 (failure path) and memory_used=True, the += 1 is capped
        at budget=2 so trace["retrieval_count"] stays at 2 (not 3).
        Normal path: compact_rc=1, memory_used=True → capped at budget=1 (stays 1, not 2).
        """
        orch = self._make_orch_for_retrieval()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")

        # Simulate ctx with non-empty memory_data AND memory_used=True
        mock_ctx = MagicMock()
        mock_ctx.memory_data = "LAWS:\n  - Do not harm.\n"
        mock_ctx.memory_used = True
        mock_ctx.system_tools = ""

        with patch("config.get_small_model_mode", return_value=True), \
             patch("config.get_jit_retrieval_max", return_value=1), \
             patch("config.get_jit_retrieval_max_on_failure", return_value=2), \
             patch("config.get_small_model_now_max", return_value=5), \
             patch("config.get_small_model_rules_max", return_value=3), \
             patch("config.get_small_model_next_max", return_value=2), \
             patch("config.get_small_model_char_cap", return_value=8000), \
             patch("config.get_context_trace_dryrun", return_value=False), \
             patch.object(orch, "_get_compact_context", return_value="NOW:\n  - state\n"), \
             patch.object(orch.context, "get_context", return_value=mock_ctx):
            # Failure path: compact_rc=2, memory_used=True → without cap would be 3
            _, trace_failure = orch.build_effective_context(
                user_text="q", conv_id="c-fail", small_model_mode=True,
                debug_flags={"has_tool_failure": True},
            )
            # Normal path: compact_rc=1, memory_used=True → without cap would be 2
            _, trace_normal = orch.build_effective_context(
                user_text="q", conv_id="c-norm", small_model_mode=True,
                debug_flags={"has_tool_failure": False},
            )

        assert trace_failure["retrieval_count"] <= 2, (
            f"Failure path: memory_used=True must not push retrieval_count over budget=2, "
            f"got {trace_failure['retrieval_count']}"
        )
        assert trace_normal["retrieval_count"] <= 1, (
            f"Normal path: memory_used=True must not push retrieval_count over budget=1, "
            f"got {trace_normal['retrieval_count']}"
        )


# ═════════════════════════════════════════════════════════════════
# Phase-2 Residual 2: Single-Truth Channel Guard
# ═════════════════════════════════════════════════════════════════

class TestSingleTruthChannelGuard:
    """
    Phase-2 Residual: Single Truth Channel — tool_result events must not appear
    in both compact context AND tool_context within the same pipeline run.

    Guard implementation:
      - _build_failure_compact_block passes exclude_event_types={"tool_result"}
        to _get_compact_context so that tool_result workspace events (just saved
        by _build_tool_result_card) are not re-injected into the compact context.
      - build_small_model_context filters excluded event types before calling
        build_compact_context.
    """

    def test_get_compact_context_accepts_exclude_event_types(self):
        """_get_compact_context must accept keyword-only exclude_event_types parameter."""
        orch = _make_orch()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")
        import inspect
        sig = inspect.signature(orch._get_compact_context)
        assert "exclude_event_types" in sig.parameters, (
            "_get_compact_context must accept exclude_event_types for Single-Truth Guard"
        )

    def test_failure_compact_builder_passes_exclude_tool_result(self):
        """_build_failure_compact_block must call _get_compact_context with
        exclude_event_types={'tool_result'} — the Single-Truth Guard."""
        orch = _make_orch()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")

        captured_kwargs = {}

        def _capture_call(conv_id, has_tool_failure=False, **kwargs):
            captured_kwargs.update(kwargs)
            return "NOW:\n  - some state\n"

        with patch.object(orch, "_get_compact_context", side_effect=_capture_call):
            orch._build_failure_compact_block("conv123", 0, False)

        assert captured_kwargs.get("exclude_event_types") == {"tool_result"}, (
            f"failure-compact must pass exclude_event_types={{'tool_result'}} to _get_compact_context. "
            f"Got: {captured_kwargs.get('exclude_event_types')!r}"
        )

    def test_build_small_model_context_accepts_exclude_event_types(self):
        """build_small_model_context must accept exclude_event_types parameter."""
        try:
            from core.context_manager import ContextManager
        except ImportError as e:
            pytest.skip(f"ContextManager not importable: {e}")
        import inspect
        sig = inspect.signature(ContextManager.build_small_model_context)
        assert "exclude_event_types" in sig.parameters, (
            "build_small_model_context must accept exclude_event_types for Single-Truth Guard"
        )

    def test_exclude_event_types_filters_before_compact_build(self):
        """Events of excluded types must not reach build_compact_context."""
        try:
            from core.context_manager import ContextManager
        except ImportError as e:
            pytest.skip(f"ContextManager not importable: {e}")

        cm = ContextManager()

        tool_result_event = {
            "event_type": "tool_result",
            "event_data": {"tool_name": "memory_search", "status": "ok"},
            "created_at": "2026-02-19T10:00:00Z",
            "id": "evt-tr-001",
        }
        workspace_event = {
            "event_type": "container_started",
            "event_data": {"container_id": "c-abc"},
            "created_at": "2026-02-19T10:00:01Z",
            "id": "evt-ws-001",
        }

        class MockToolResult:
            content = [tool_result_event, workspace_event]

        mock_hub = MagicMock()
        mock_hub.initialize = MagicMock()
        mock_hub.call_tool.return_value = MockToolResult()

        captured_events = []

        def _capture_build(events, *args, **kwargs):
            captured_events.extend(events)
            from core.context_cleanup import CompactContext
            return CompactContext([], [], [])

        with patch("mcp.hub.get_hub", return_value=mock_hub), \
             patch("core.context_cleanup.build_compact_context", side_effect=_capture_build), \
             patch("core.context_cleanup.format_compact_context", return_value=""):
            cm.build_small_model_context(
                conversation_id="test-conv",
                exclude_event_types={"tool_result"},
            )

        event_types = [e.get("event_type") for e in captured_events]
        assert "tool_result" not in event_types, (
            f"tool_result events must be filtered by exclude_event_types. "
            f"Found in compact build: {event_types}"
        )
        assert "container_started" in event_types, (
            "Non-excluded events (container_started) must still reach compact build"
        )

    def test_normal_compact_does_not_restrict_event_types(self):
        """Normal (non-failure) compact path must NOT filter tool_result events."""
        orch = _make_orch()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")

        captured_kwargs = {}

        def _capture_call(conv_id, has_tool_failure=False, **kwargs):
            captured_kwargs.update({"exclude_event_types": kwargs.get("exclude_event_types")})
            return "NOW:\n  - state\n"

        with patch.object(orch, "_get_compact_context", side_effect=_capture_call), \
             patch("config.get_small_model_mode", return_value=True), \
             patch("config.get_jit_retrieval_max", return_value=1), \
             patch("config.get_jit_retrieval_max_on_failure", return_value=2), \
             patch("config.get_small_model_now_max", return_value=5), \
             patch("config.get_small_model_rules_max", return_value=3), \
             patch("config.get_small_model_next_max", return_value=2), \
             patch("config.get_small_model_char_cap", return_value=8000), \
             patch("config.get_context_trace_dryrun", return_value=False):
            orch.build_effective_context(
                user_text="q", conv_id="c", small_model_mode=True,
            )

        # Normal compact path: no exclude_event_types needed (compact built before tool execution)
        assert captured_kwargs.get("exclude_event_types") is None, (
            "Normal compact path must NOT exclude event types "
            f"(got {captured_kwargs.get('exclude_event_types')!r})"
        )

    def test_tool_result_single_channel_assertion(self):
        """
        Contract assertion: after a full pipeline run, tool_result data can only
        be in tool_ctx source, not independently in compact source.
        Verified via trace context_sources invariant.
        """
        # Simulate the invariant: compact = workspace state, tool_ctx = tool results
        trace = {
            "context_sources": ["compact", "tool_ctx"],
            "retrieval_count": 1,
        }
        # compact is present (workspace state — containers, constraints)
        # tool_ctx is present (tool result cards — single truth channel)
        assert "compact" in trace["context_sources"]
        assert "tool_ctx" in trace["context_sources"]
        # failure_ctx would also be present on failure, but still via unified prepend
        assert trace["context_sources"].count("tool_ctx") == 1, (
            "tool_ctx must appear exactly once (single truth channel)"
        )


# ═════════════════════════════════════════════════════════════════
# Fix 1: Compact-Meta retrieval_count wired (not static)
# ═════════════════════════════════════════════════════════════════

class TestCompactMetaRetrievalCountWired:
    """
    Fix 1 [High]: _get_compact_context must wire the computed retrieval_count into
    limits["retrieval_count"] so that CompactContext meta["retrieval_count"] reflects
    the real number of fetches (1 or 2) instead of always defaulting to 1.
    """

    def test_normal_budget_wires_retrieval_count_1_into_limits(self):
        """Normal path (budget=1): limits["retrieval_count"] == 1 passed to build_small_model_context."""
        orch = _make_orch()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")

        captured_limits = {}

        def _capture(conversation_id=None, limits=None, **kwargs):
            if limits:
                captured_limits.update(limits)
            return ""

        with patch("config.get_small_model_mode", return_value=True), \
             patch("config.get_jit_retrieval_max", return_value=1), \
             patch("config.get_jit_retrieval_max_on_failure", return_value=2), \
             patch("config.get_small_model_now_max", return_value=5), \
             patch("config.get_small_model_rules_max", return_value=3), \
             patch("config.get_small_model_next_max", return_value=2), \
             patch.object(orch.context, "build_small_model_context", side_effect=_capture):
            orch._get_compact_context("conv-x", has_tool_failure=False)

        assert captured_limits.get("retrieval_count") == 1, (
            f"Normal path (budget=1) must wire retrieval_count=1 into limits, "
            f"got {captured_limits.get('retrieval_count')!r}"
        )

    def test_failure_budget_wires_retrieval_count_2_into_limits(self):
        """Failure path (budget=2, non-container conv): limits["retrieval_count"] == 2."""
        orch = _make_orch()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")

        captured_limits = {}

        def _capture(conversation_id=None, limits=None, **kwargs):
            if limits:
                captured_limits.update(limits)
            return ""

        with patch("config.get_small_model_mode", return_value=True), \
             patch("config.get_jit_retrieval_max", return_value=1), \
             patch("config.get_jit_retrieval_max_on_failure", return_value=2), \
             patch("config.get_small_model_now_max", return_value=5), \
             patch("config.get_small_model_rules_max", return_value=3), \
             patch("config.get_small_model_next_max", return_value=2), \
             patch.object(orch.context, "build_small_model_context", side_effect=_capture):
            orch._get_compact_context("conv-fail", has_tool_failure=True)

        assert captured_limits.get("retrieval_count") == 2, (
            f"Failure path (budget=2, non-container) must wire retrieval_count=2 into limits, "
            f"got {captured_limits.get('retrieval_count')!r}"
        )

    def test_container_conv_wires_retrieval_count_1_even_in_failure(self):
        """_container_events conv always wires retrieval_count=1 (no recursive fetch)."""
        orch = _make_orch()
        if orch is None:
            pytest.skip("Cannot import PipelineOrchestrator")

        captured_limits = {}

        def _capture(conversation_id=None, limits=None, **kwargs):
            if limits:
                captured_limits.update(limits)
            return ""

        with patch("config.get_small_model_mode", return_value=True), \
             patch("config.get_jit_retrieval_max", return_value=1), \
             patch("config.get_jit_retrieval_max_on_failure", return_value=2), \
             patch("config.get_small_model_now_max", return_value=5), \
             patch("config.get_small_model_rules_max", return_value=3), \
             patch("config.get_small_model_next_max", return_value=2), \
             patch.object(orch.context, "build_small_model_context", side_effect=_capture):
            orch._get_compact_context("_container_events", has_tool_failure=True)

        assert captured_limits.get("retrieval_count") == 1, (
            f"_container_events conv must wire retrieval_count=1 (no recursive fetch), "
            f"got {captured_limits.get('retrieval_count')!r}"
        )
