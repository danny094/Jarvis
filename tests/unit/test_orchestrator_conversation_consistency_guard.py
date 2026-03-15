import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_orchestrator():
    from core.orchestrator import PipelineOrchestrator

    with patch("core.orchestrator.ThinkingLayer", return_value=MagicMock()), \
         patch("core.orchestrator.ControlLayer", return_value=MagicMock()), \
         patch("core.orchestrator.OutputLayer", return_value=MagicMock()), \
         patch("core.orchestrator.ToolSelector", return_value=MagicMock()), \
         patch("core.orchestrator.ContextManager", return_value=MagicMock()), \
         patch("core.orchestrator.get_hub", return_value=MagicMock()), \
         patch("core.orchestrator.get_registry", return_value=MagicMock()), \
         patch("core.orchestrator.get_master_orchestrator", return_value=MagicMock()):
        return PipelineOrchestrator()


def _policy(**overrides):
    base = {
        "enabled": True,
        "history_ttl_s": 3600,
        "max_entries_per_conversation": 24,
        "require_evidence_on_stance_change": True,
        "min_successful_evidence_on_stance_change": 1,
        "embedding_enable": True,
        "embedding_similarity_threshold": 0.78,
        "fallback_mode": "explicit_uncertainty",
    }
    base.update(overrides)
    return base


def _runtime_plan(successful_evidence: int, evidence: list):
    return {
        "_execution_result": {
            "done_reason": "stop",
            "tool_statuses": [],
            "direct_response": "",
            "grounding": {"successful_evidence": successful_evidence},
            "metadata": {"grounding_evidence": list(evidence or [])},
        }
    }


@pytest.mark.asyncio
async def test_consistency_guard_conflict_without_evidence_triggers_fallback():
    orch = _make_orchestrator()
    conv_id = "conv-consistency-fallback"
    now = time.time()
    orch._conversation_consistency_state[conv_id] = [
        {
            "topic": "host_runtime_ip_disclosure",
            "stance": "deny",
            "snippet": "Ich kann nicht die Host-IP preisgeben.",
            "ts": now,
            "embedding": [1.0, 0.0],
        }
    ]
    orch.output._build_grounding_fallback = MagicMock(
        return_value="Ich kann nicht sicher bestätigen, welche Host-IP außerhalb Docker gilt."
    )

    def _signals_for_text(text: str):
        lower = str(text or "").lower()
        if "nicht sicher bestätigen" in lower:
            return [{
                "topic": "host_runtime_ip_disclosure",
                "stance": "deny",
                "snippet": "Ich kann nicht sicher bestätigen, welche Host-IP außerhalb Docker gilt.",
            }]
        return [{
            "topic": "host_runtime_ip_disclosure",
            "stance": "allow",
            "snippet": "Ich kann die Host-IP direkt nennen.",
        }]

    verified_plan = _runtime_plan(0, [{"tool_name": "get_system_info", "status": "ok"}])
    with patch("core.orchestrator.load_conversation_consistency_policy", return_value=_policy()), \
         patch("core.orchestrator.util_extract_stance_signals", side_effect=_signals_for_text), \
         patch("core.orchestrator.embed_text_runtime", AsyncMock(return_value=[1.0, 0.0])):
        out = await orch._apply_conversation_consistency_guard(
            conversation_id=conv_id,
            verified_plan=verified_plan,
            answer="Ich kann die Host-IP direkt nennen.",
        )

    assert "nicht sicher bestätigen" in out.lower()
    assert verified_plan.get("_consistency_conflict_detected") is True
    assert verified_plan.get("_grounded_fallback_used") is True
    assert isinstance(verified_plan.get("_consistency_conflicts"), list)


@pytest.mark.asyncio
async def test_consistency_guard_conflict_with_evidence_keeps_answer():
    orch = _make_orchestrator()
    conv_id = "conv-consistency-evidence"
    now = time.time()
    orch._conversation_consistency_state[conv_id] = [
        {
            "topic": "host_runtime_ip_disclosure",
            "stance": "deny",
            "snippet": "Ich kann nicht die Host-IP preisgeben.",
            "ts": now,
            "embedding": [1.0, 0.0],
        }
    ]
    orch.output._build_grounding_fallback = MagicMock(return_value="fallback-should-not-be-used")

    with patch("core.orchestrator.load_conversation_consistency_policy", return_value=_policy()), \
         patch("core.orchestrator.util_extract_stance_signals", return_value=[{
             "topic": "host_runtime_ip_disclosure",
             "stance": "allow",
             "snippet": "Ich kann die Host-IP direkt nennen.",
         }]), \
         patch("core.orchestrator.embed_text_runtime", AsyncMock(return_value=[1.0, 0.0])):
        out = await orch._apply_conversation_consistency_guard(
            conversation_id=conv_id,
            verified_plan=_runtime_plan(2, []),
            answer="Ich kann die Host-IP direkt nennen.",
        )

    assert out == "Ich kann die Host-IP direkt nennen."
    orch.output._build_grounding_fallback.assert_not_called()


@pytest.mark.asyncio
async def test_consistency_guard_embedding_threshold_avoids_false_conflict():
    orch = _make_orchestrator()
    conv_id = "conv-consistency-threshold"
    now = time.time()
    orch._conversation_consistency_state[conv_id] = [
        {
            "topic": "host_runtime_ip_disclosure",
            "stance": "deny",
            "snippet": "Ich kann nicht die Host-IP preisgeben.",
            "ts": now,
            "embedding": [1.0, 0.0],
        }
    ]
    orch.output._build_grounding_fallback = MagicMock(return_value="fallback-should-not-be-used")

    with patch(
        "core.orchestrator.load_conversation_consistency_policy",
        return_value=_policy(embedding_similarity_threshold=0.85),
    ), patch(
        "core.orchestrator.util_extract_stance_signals",
        return_value=[{
            "topic": "host_runtime_ip_disclosure",
            "stance": "allow",
            "snippet": "Ich kann die Host-IP direkt nennen.",
        }],
    ), patch(
        "core.orchestrator.embed_text_runtime",
        AsyncMock(return_value=[0.0, 1.0]),  # cosine=0 against prior entry
    ):
        out = await orch._apply_conversation_consistency_guard(
            conversation_id=conv_id,
            verified_plan=_runtime_plan(0, []),
            answer="Ich kann die Host-IP direkt nennen.",
        )

    assert out == "Ich kann die Host-IP direkt nennen."
    orch.output._build_grounding_fallback.assert_not_called()


@pytest.mark.asyncio
async def test_consistency_guard_disabled_is_noop():
    orch = _make_orchestrator()
    with patch(
        "core.orchestrator.load_conversation_consistency_policy",
        return_value=_policy(enabled=False),
    ):
        out = await orch._apply_conversation_consistency_guard(
            conversation_id="conv-disabled",
            verified_plan={},
            answer="Antwort ohne Änderung.",
        )
    assert out == "Antwort ohne Änderung."
