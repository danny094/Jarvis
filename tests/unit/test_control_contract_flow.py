from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.control_contract import ControlDecision
from core.layers.output import OutputLayer


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


def test_control_decision_is_immutable():
    decision = ControlDecision.from_verification(
        {
            "approved": True,
            "decision_class": "allow",
            "warnings": ["ok"],
        }
    )
    with pytest.raises(FrozenInstanceError):
        decision.approved = False


@pytest.mark.asyncio
async def test_execute_control_layer_persists_typed_contracts():
    orch = _make_orchestrator()
    orch.control.verify = AsyncMock(
        return_value={
            "approved": True,
            "hard_block": False,
            "decision_class": "allow",
            "block_reason_code": "",
            "reason": "ok",
            "corrections": {},
            "warnings": [],
            "final_instruction": "",
        }
    )
    orch.control.apply_corrections = MagicMock(side_effect=lambda tp, _: dict(tp))

    verification, verified_plan = await orch._execute_control_layer(
        user_text="Bitte nutze tools",
        thinking_plan={"intent": "tool", "hallucination_risk": "medium", "suggested_tools": ["list_skills"]},
        memory_data="",
        conversation_id="conv-1",
    )

    assert verification["approved"] is True
    assert isinstance(verified_plan.get("_control_decision"), dict)
    assert verified_plan["_control_decision"]["approved"] is True
    assert isinstance(verified_plan.get("_execution_result"), dict)
    assert verified_plan["_execution_result"]["done_reason"] == "stop"


def test_execute_tools_sync_respects_control_tools_allowed():
    orch = _make_orchestrator()

    class _FakeHub:
        def initialize(self):
            return None

        def call_tool(self, *_args, **_kwargs):
            raise AssertionError("tool must not be called when blocked by control_decision")

    with patch("core.orchestrator.get_hub", return_value=_FakeHub()):
        plan = {}
        control_decision = ControlDecision.from_verification(
            {
                "approved": True,
                "decision_class": "allow",
                "tools_allowed": ["list_skills"],
            }
        )
        tool_context = orch._execute_tools_sync(
            ["exec_in_container"],
            "Bitte exec",
            control_tool_decisions={"exec_in_container": {"container_id": "x", "command": "hostname -I"}},
            control_decision=control_decision,
            verified_plan=plan,
            session_id="conv-2",
        )

    assert tool_context == ""
    execution_result = plan.get("_execution_result", {})
    assert execution_result.get("done_reason") == "unavailable"
    statuses = execution_result.get("tool_statuses", [])
    assert statuses and statuses[0].get("reason") == "control_tool_not_allowed"


def test_output_precheck_writes_runtime_grounding_state():
    output = OutputLayer()
    plan = {
        "is_fact_query": True,
        "_tool_results": "TOOL used",
        "_selected_tools_for_prompt": ["container_inspect"],
        "_grounding_evidence": [],
    }
    execution_result = {}

    precheck = output._grounding_precheck(plan, memory_data="", execution_result=execution_result)

    assert precheck["mode"] in {"missing_evidence_fallback", "tool_execution_failed_fallback", "pass", "evidence_summary_fallback"}
    grounding = execution_result.get("grounding", {})
    assert "missing_evidence" in grounding
    assert "successful_evidence" in grounding


def test_control_default_verification_is_fail_closed():
    from core.layers.control import ControlLayer

    layer = ControlLayer()
    verification = layer._default_verification({"intent": "x"})
    assert verification["approved"] is False
    assert verification["hard_block"] is True
    assert verification["decision_class"] == "hard_block"
