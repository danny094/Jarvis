from core.control_contract import ControlDecision, persist_control_decision
from core.plan_runtime_bridge import (
    get_policy_final_instruction,
    get_policy_warnings,
    get_runtime_direct_response,
    get_runtime_grounding_evidence,
    get_runtime_grounding_value,
    get_runtime_tool_results,
    set_runtime_direct_response,
    set_runtime_grounding_evidence,
    set_runtime_tool_results,
)


def test_runtime_tool_results_no_legacy_mirror():
    plan = {}
    set_runtime_tool_results(plan, "abc")
    assert "_tool_results" not in plan
    assert plan["_execution_result"]["metadata"]["tool_results"] == "abc"


def test_runtime_evidence_and_direct_response():
    plan = {}
    set_runtime_grounding_evidence(plan, [{"tool_name": "x", "status": "ok"}])
    set_runtime_direct_response(plan, "done")

    assert get_runtime_grounding_evidence(plan)[0]["tool_name"] == "x"
    assert get_runtime_direct_response(plan) == "done"


def test_policy_reads_prefer_control_decision():
    plan = {"_final_instruction": "legacy", "_warnings": ["legacy-warn"]}
    decision = ControlDecision.from_verification(
        {
            "approved": True,
            "decision_class": "allow",
            "final_instruction": "control",
            "warnings": ["c1", "c2"],
        }
    )
    persist_control_decision(plan, decision)

    assert get_policy_final_instruction(plan) == "control"
    assert get_policy_warnings(plan) == ["c1", "c2"]


def test_runtime_grounding_value_returns_default_when_not_set():
    plan = {}
    assert get_runtime_grounding_value(plan, key="hybrid_mode", default=False) is False


def test_runtime_grounding_value_reads_from_execution_result():
    plan = {}
    set_runtime_grounding_evidence(plan, [])
    plan["_execution_result"]["grounding"]["hybrid_mode"] = True
    assert get_runtime_grounding_value(plan, key="hybrid_mode", default=False) is True


def test_runtime_tool_results_prefer_contract_over_stale_legacy():
    plan = {}
    set_runtime_tool_results(plan, "contract")
    plan["_tool_results"] = "stale-legacy"
    assert get_runtime_tool_results(plan) == "contract"
