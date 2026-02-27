"""
tests/unit/test_token_efficiency_pipeline.py

Token-efficiency guards for the current context pipeline:
1) C5/C6 TypedState skill-context budget behavior.
2) Small-model orchestrator hard-cap behavior in token terms.
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.typedstate_skills import build_skills_context
from utils.chunker import count_tokens


def _make_many_skills(n: int = 60):
    skills = []
    for i in range(1, n + 1):
        skills.append(
            {
                "name": f"skill_{i:02d}_super_long_name_for_budget_probe",
                "channel": "active" if i % 3 else "draft",
                "status": "installed" if i % 3 else "draft",
                "validation_score": 1.0 if i % 5 else 0.4,
                "triggers": [
                    "docker",
                    "deploy",
                    "logs",
                    "metrics",
                    "alerts",
                    "healthcheck",
                ],
                "gap_question": "Please provide API token if needed",
                "required_packages": ["requests", "pydantic", "httpx", "pyyaml"],
                "signature_status": "signed" if i % 7 else "unsigned",
                "description": "Synthetic skill for token-budget measurement only",
            }
        )
    return skills


class TestTypedstateSkillTokenBudget:
    def test_tokens_drop_when_char_cap_drops(self):
        skills = _make_many_skills()
        c2000 = build_skills_context(skills, mode="active", top_k_count=10, char_cap=2000)
        c1200 = build_skills_context(skills, mode="active", top_k_count=10, char_cap=1200)

        t2000 = count_tokens(c2000)
        t1200 = count_tokens(c1200)

        assert c2000.startswith("SKILLS:")
        assert c1200.startswith("SKILLS:")
        assert len(c1200) <= len(c2000)
        assert t1200 <= t2000

    def test_c6_default_budget_stays_reasonable(self):
        skills = _make_many_skills()
        # C6 call-site currently uses top_k=10, char_cap=2000.
        ctx = build_skills_context(skills, mode="active", top_k_count=10, char_cap=2000)
        tokens = count_tokens(ctx)

        assert len(ctx) > 0
        assert tokens > 0
        assert len(ctx) <= 2200
        assert tokens <= 900


def _make_orchestrator_for_budget_probe():
    from core.orchestrator import PipelineOrchestrator

    thinking = MagicMock()
    thinking.analyze = AsyncMock(
        return_value={
            "intent": "question",
            "needs_memory": True,
            "memory_keys": ["k1"],
            "hallucination_risk": "low",
            "needs_sequential_thinking": False,
        }
    )
    control = MagicMock()
    control.verify = AsyncMock(return_value={"approved": True, "corrections": {}, "warnings": []})
    control.apply_corrections = MagicMock(side_effect=lambda p, v: {**p, "_verified": True})
    control._check_sequential_thinking = AsyncMock(return_value=None)
    control.set_mcp_hub = MagicMock()
    output = MagicMock()
    output.generate = AsyncMock(return_value="ok")

    ctx_result = MagicMock()
    ctx_result.memory_data = "MEMORY_LINE " * 800
    ctx_result.memory_used = True
    ctx_result.system_tools = "TOOL_RULE " * 400
    ctx_result.sources = ["memory", "tools"]

    ctx_mgr = MagicMock()
    ctx_mgr.get_context.return_value = ctx_result
    ctx_mgr.build_small_model_context.return_value = ("NOW:\n  - state a\n  - state b\n" * 80)

    with (
        patch("core.orchestrator.ThinkingLayer", return_value=thinking),
        patch("core.orchestrator.ControlLayer", return_value=control),
        patch("core.orchestrator.OutputLayer", return_value=output),
        patch("core.orchestrator.ContextManager", return_value=ctx_mgr),
        patch("core.orchestrator.get_hub", return_value=MagicMock()),
        patch("core.orchestrator.get_registry", return_value=MagicMock()),
        patch("config.get_context_trace_dryrun", return_value=False),
    ):
        orch = PipelineOrchestrator()
        orch.context = ctx_mgr
        return orch


def _build_small_mode_context(orch, cap: int):
    with (
        patch("config.get_small_model_mode", return_value=True),
        patch("config.get_small_model_now_max", return_value=5),
        patch("config.get_small_model_rules_max", return_value=3),
        patch("config.get_small_model_next_max", return_value=2),
        patch("config.get_small_model_char_cap", return_value=cap),
        patch("config.get_jit_retrieval_max", return_value=1),
        patch("config.get_jit_retrieval_max_on_failure", return_value=2),
    ):
        text, trace = orch.build_effective_context(
            user_text="token probe",
            conv_id="conv-token-probe",
            small_model_mode=True,
            cleanup_payload={"needs_memory": True, "memory_keys": ["k1"]},
        )
    return text, trace


class TestOrchestratorTokenBudget:
    def test_small_mode_cap_bounds_tokens(self):
        orch = _make_orchestrator_for_budget_probe()
        ctx_1800, trace_1800 = _build_small_mode_context(orch, 1800)
        ctx_2200, trace_2200 = _build_small_mode_context(orch, 2200)

        tok_1800 = count_tokens(ctx_1800)
        tok_2200 = count_tokens(ctx_2200)

        assert len(ctx_1800) <= 1800
        assert len(ctx_2200) <= 2200
        assert tok_1800 <= tok_2200
        assert tok_2200 <= 900
        assert "compact" in trace_1800.get("context_sources", [])
        assert "compact" in trace_2200.get("context_sources", [])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
