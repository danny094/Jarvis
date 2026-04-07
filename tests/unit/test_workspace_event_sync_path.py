"""
Unit-Tests: Sync-Pfad schreibt Workspace-Entries (Phase 2).

Prüft:
  - Nach ThinkingLayer: mindestens 1 "observation"/"thinking"-Entry wenn obs_text vorhanden
  - Nach ControlLayer: mindestens 1 "control_decision"/"control"-Entry
  - Am Ende (Done): mindestens 1 "chat_done"/"orchestrator"-Entry

Strategie:
  - process_request aus orchestrator_sync_flow_utils wird direkt aufgerufen
  - Alle externen Dependencies (hub, ThinkingLayer, ControlLayer, OutputLayer, etc.) werden gemockt
  - _save_workspace_entry wird überwacht um Entry-Calls zu zählen
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

# Sicherstellen dass ws_stream nicht importfehler verursacht
_mock_ws_stream = MagicMock()
sys.modules.setdefault("container_commander.ws_stream", _mock_ws_stream)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_thinking_plan(with_obs: bool = True) -> dict:
    plan = {
        "intent": "test_intent" if with_obs else "unknown",
        "memory_keys": ["key1"] if with_obs else [],
        "hallucination_risk": "low",
        "needs_sequential_thinking": False,
        "suggested_tools": [],
        "response_mode": "interactive",
    }
    return plan


def _make_verification() -> dict:
    return {
        "approved": True,
        "corrections": {},
        "warnings": [],
        "reason": "",
    }


def _make_request(conversation_id: str = "conv-sync-test") -> MagicMock:
    req = MagicMock()
    req.conversation_id = conversation_id
    req.source_adapter = "test"
    req.model = "test-model"
    req.messages = []
    req.get_last_user_message.return_value = "was ist 2+2?"
    return req


def _make_orch(thinking_plan: dict, verification: dict) -> MagicMock:
    """Baut einen Orchestrator-Mock der den kritischen Pfad durchläuft."""
    orch = MagicMock()

    # Lifecycle
    orch.lifecycle = MagicMock()

    # Thinking
    orch.thinking = MagicMock()
    orch.thinking.analyze = AsyncMock(return_value=thinking_plan)
    orch.thinking._default_plan = MagicMock(return_value=thinking_plan)

    # Control
    orch._execute_control_layer = AsyncMock(return_value=(verification, {"_control_decision": verification}))
    orch._collect_control_tool_decisions = AsyncMock(return_value={})
    orch._is_control_hard_block_decision = MagicMock(return_value=False)

    # Output
    orch.output = MagicMock()
    orch.output.generate = AsyncMock(return_value="4")

    # Context
    orch.build_effective_context = MagicMock(return_value=(
        "context text",
        {
            "memory_used": False,
            "small_model_mode": False,
            "context_chars": 100,
            "retrieval_count": 0,
            "context_sources": [],
            "context_chars_final": 100,
        },
        MagicMock(required_missing=False),
    ))

    # Workspace helpers
    orch._extract_workspace_observations = MagicMock(
        return_value="**Intent:** test_intent\n**Memory keys:** key1"
        if thinking_plan.get("intent") != "unknown" else None
    )
    orch._build_control_workspace_summary = MagicMock(
        return_value="approved=True | corrections={} | warnings=[]"
    )
    orch._build_done_workspace_summary = MagicMock(
        return_value="done_reason=stop | response_mode=interactive"
    )
    orch._save_workspace_entry = MagicMock(return_value=None)

    # Misc
    orch._requested_response_mode = MagicMock(return_value=None)
    orch._classify_tone_signal = AsyncMock(return_value=None)
    orch._check_pending_confirmation = AsyncMock(return_value=None)
    orch._should_skip_thinking_from_query_budget = MagicMock(return_value=False)
    orch._ensure_dialogue_controls = MagicMock(side_effect=lambda plan, *a, **kw: plan)
    orch._maybe_prefetch_skills = MagicMock(return_value=(None, "off"))
    orch._is_explicit_deep_request = MagicMock(return_value=False)
    orch._resolve_execution_suggested_tools = MagicMock(return_value=[])
    orch._execute_tools_sync = MagicMock(return_value="")
    orch._clip_tool_context = MagicMock(return_value="")
    orch._tool_context_has_failures_or_skips = MagicMock(return_value=False)
    orch._tool_context_has_success = MagicMock(return_value=False)
    orch._inject_carryover_grounding_evidence = MagicMock()
    orch._maybe_auto_recover_grounding_once = AsyncMock(return_value=None)
    orch._remember_conversation_grounding_state = MagicMock()
    orch._apply_final_cap = MagicMock(side_effect=lambda ctx, *a, **kw: ctx)
    orch._apply_effective_context_guardrail = MagicMock(side_effect=lambda ctx, *a, **kw: ctx)
    orch._compute_ctx_mode = MagicMock(return_value="full")
    orch._apply_conversation_consistency_guard = AsyncMock(side_effect=lambda **kw: kw["answer"])
    orch._save_memory = MagicMock()
    orch._post_task_processing = MagicMock()
    orch._append_context_block = MagicMock(side_effect=lambda ctx, block, *a, **kw: ctx + block)
    orch._build_failure_compact_block = MagicMock(return_value=None)
    orch._compute_retrieval_policy = MagicMock(return_value={"max_retrievals": 3})
    orch._tool_context_has_failures_or_skips = MagicMock(return_value=False)
    orch._maybe_build_active_container_capability_context = AsyncMock(return_value=None)
    orch._maybe_build_skill_semantic_context = AsyncMock(return_value=None)

    # Plan data
    orch._conversation_container_state = {}

    return orch


async def _run_sync(orch, request):
    """Ruft process_request direkt auf."""
    from core.orchestrator_sync_flow_utils import process_request

    class _CoreChatResponse:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    # Pipeline-Stages mocken
    with patch("core.orchestrator_pipeline_stages.run_tool_selection_stage",
               new=AsyncMock(return_value=([], None, None, None))), \
         patch("core.orchestrator_pipeline_stages.run_plan_finalization",
               return_value=(request._mock_children.get("_thinking_plan", orch.thinking._default_plan()), "interactive")), \
         patch("core.orchestrator_pipeline_stages.run_pre_control_gates", return_value=(None, None)), \
         patch("core.orchestrator_pipeline_stages.prepare_output_invocation",
               return_value=("test-model", False)), \
         patch("core.control_contract.control_decision_from_plan",
               return_value=MagicMock(
                   with_tools_allowed=MagicMock(return_value=MagicMock()),
               )), \
         patch("core.control_contract.persist_control_decision"), \
         patch("config.get_small_model_mode", return_value=False), \
         patch("config.get_output_timeout_interactive_s", return_value=30), \
         patch("config.get_output_timeout_deep_s", return_value=120):
        return await process_request(
            orch,
            request,
            core_chat_response_cls=_CoreChatResponse,
            intent_system_available=False,
            get_master_settings_fn=lambda: {},
            thinking_plan_cache=MagicMock(get=MagicMock(return_value=None), set=MagicMock()),
            soften_control_deny_fn=MagicMock(),
            log_info_fn=lambda *a: None,
            log_warn_fn=lambda *a: None,
            log_warning_fn=lambda *a: None,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_path_saves_thinking_observation_when_present():
    """Sync-Pfad speichert Thinking-Observation wenn obs_text vorhanden."""
    thinking_plan = _make_thinking_plan(with_obs=True)
    verification = _make_verification()
    orch = _make_orch(thinking_plan, verification)
    request = _make_request()

    await _run_sync(orch, request)

    # _save_workspace_entry muss mit "observation"/"thinking" aufgerufen worden sein
    calls = orch._save_workspace_entry.call_args_list
    obs_calls = [c for c in calls if len(c[0]) >= 3 and c[0][2] == "observation" and c[0][3] == "thinking"]
    assert len(obs_calls) >= 1, (
        f"Kein observation/thinking Entry gefunden. Alle Calls: {calls}"
    )


@pytest.mark.asyncio
async def test_sync_path_skips_thinking_observation_when_none():
    """Sync-Pfad speichert KEINE Thinking-Observation wenn _extract_workspace_observations None zurückgibt."""
    thinking_plan = _make_thinking_plan(with_obs=False)
    verification = _make_verification()
    orch = _make_orch(thinking_plan, verification)
    orch._extract_workspace_observations = MagicMock(return_value=None)
    request = _make_request()

    await _run_sync(orch, request)

    calls = orch._save_workspace_entry.call_args_list
    obs_calls = [c for c in calls if len(c[0]) >= 3 and c[0][2] == "observation" and c[0][3] == "thinking"]
    assert len(obs_calls) == 0, f"Unerwarteter observation/thinking Entry: {obs_calls}"


@pytest.mark.asyncio
async def test_sync_path_saves_control_decision():
    """Sync-Pfad speichert control_decision Entry nach ControlLayer."""
    thinking_plan = _make_thinking_plan()
    verification = _make_verification()
    orch = _make_orch(thinking_plan, verification)
    request = _make_request()

    await _run_sync(orch, request)

    calls = orch._save_workspace_entry.call_args_list
    ctrl_calls = [c for c in calls if len(c[0]) >= 3 and c[0][2] == "control_decision"]
    assert len(ctrl_calls) >= 1, (
        f"Kein control_decision Entry gefunden. Alle Calls: {calls}"
    )
    # Sicherstellen dass _build_control_workspace_summary aufgerufen wurde
    orch._build_control_workspace_summary.assert_called_once()


@pytest.mark.asyncio
async def test_sync_path_saves_chat_done():
    """Sync-Pfad speichert chat_done Entry am Ende."""
    thinking_plan = _make_thinking_plan()
    verification = _make_verification()
    orch = _make_orch(thinking_plan, verification)
    request = _make_request()

    await _run_sync(orch, request)

    calls = orch._save_workspace_entry.call_args_list
    done_calls = [c for c in calls if len(c[0]) >= 3 and c[0][2] == "chat_done"]
    assert len(done_calls) >= 1, (
        f"Kein chat_done Entry gefunden. Alle Calls: {calls}"
    )
    orch._build_done_workspace_summary.assert_called_once()


@pytest.mark.asyncio
async def test_sync_path_total_workspace_entries():
    """Sync-Pfad schreibt mindestens 3 Workspace-Entries (obs + ctrl + done)."""
    thinking_plan = _make_thinking_plan(with_obs=True)
    verification = _make_verification()
    orch = _make_orch(thinking_plan, verification)
    request = _make_request()

    await _run_sync(orch, request)

    total = len(orch._save_workspace_entry.call_args_list)
    assert total >= 3, (
        f"Sync-Pfad sollte ≥3 Workspace-Entries schreiben, hat {total}. "
        f"Calls: {orch._save_workspace_entry.call_args_list}"
    )
