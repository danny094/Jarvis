from core.control_contract import ControlDecision, persist_control_decision
from core.plan_runtime_bridge import (
    LEGACY_RUNTIME_KEYS,
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


def test_runtime_tool_results_no_legacy_mirror_by_default():
    plan = {}
    set_runtime_tool_results(plan, "abc")
    assert "_tool_results" not in plan
    assert plan["_execution_result"]["metadata"]["tool_results"] == "abc"


def test_runtime_tool_results_dual_write_and_read_prefer_contract():
    plan = {}
    set_runtime_tool_results(plan, "abc", dual_write=True)
    assert plan["_tool_results"] == "abc"
    assert plan["_execution_result"]["metadata"]["tool_results"] == "abc"

    plan["_tool_results"] = "legacy-only"
    plan["_execution_result"]["metadata"]["tool_results"] = "contract"
    assert get_runtime_tool_results(plan) == "contract"


def test_runtime_evidence_and_direct_response_bridge():
    plan = {}
    set_runtime_grounding_evidence(plan, [{"tool_name": "x", "status": "ok"}], dual_write=True)
    set_runtime_direct_response(plan, "done", dual_write=True)

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


def test_runtime_grounding_value_no_legacy_fallback_by_default():
    plan = {"_grounding_hybrid_mode": True}
    assert (
        get_runtime_grounding_value(
            plan,
            key="hybrid_mode",
            legacy_key="_grounding_hybrid_mode",
            default=False,
        )
        is False
    )


def test_runtime_grounding_value_fallback_can_be_enabled_via_env(monkeypatch):
    monkeypatch.setenv("TRION_LEGACY_RUNTIME_COMPAT", "1")
    plan = {"_grounding_hybrid_mode": True}
    assert (
        get_runtime_grounding_value(
            plan,
            key="hybrid_mode",
            legacy_key="_grounding_hybrid_mode",
            default=False,
        )
        is True
    )


def test_runtime_key_set_contains_critical_keys():
    for key in ["_tool_results", "_grounding_evidence", "_direct_response", "_tool_failure"]:
        assert key in LEGACY_RUNTIME_KEYS
