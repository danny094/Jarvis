from core.grounding_state_utils import (
    build_grounding_state_payload,
    count_successful_grounding_evidence,
    extract_recent_grounding_state,
    grounding_evidence_has_content,
    has_usable_grounding_evidence,
    inject_carryover_grounding_evidence,
    select_first_whitelisted_tool_run,
)
from core.plan_runtime_bridge import get_runtime_carryover_grounding_evidence


def test_grounding_evidence_has_content_detects_key_facts_or_output():
    assert grounding_evidence_has_content({"key_facts": ["x"]})
    assert grounding_evidence_has_content({"structured": {"output": "ok"}})
    assert not grounding_evidence_has_content({"key_facts": [""]})


def test_extract_recent_grounding_state_marks_expired_or_stale():
    snap, drop = extract_recent_grounding_state(
        {"updated_at": 10.0, "history_len": 2, "tool_runs": [], "evidence": []},
        now_ts=25.0,
        ttl_s=5,
        ttl_turns=3,
        history_len=2,
    )
    assert snap is None
    assert drop

    snap2, drop2 = extract_recent_grounding_state(
        {"updated_at": 10.0, "history_len": 2, "tool_runs": [{"tool_name": "a"}], "evidence": []},
        now_ts=12.0,
        ttl_s=60,
        ttl_turns=1,
        history_len=8,
    )
    assert snap2 is None
    assert drop2


def test_build_grounding_state_payload_uses_successful_tool_runs_then_fallback():
    payload = build_grounding_state_payload(
        {
            "_grounding_evidence": [{"status": "ok", "key_facts": ["fact"], "tool_name": "search"}],
            "_successful_tool_runs": [{"tool_name": "tool_a", "args": {"x": 1}}],
        },
        sanitize_tool_args=lambda v: v if isinstance(v, dict) else {},
        evidence_has_content=grounding_evidence_has_content,
    )
    assert payload is not None
    assert payload["tool_runs"][0]["tool_name"] == "tool_a"

    payload2 = build_grounding_state_payload(
        {"_grounding_evidence": [{"status": "ok", "key_facts": ["fact"], "tool_name": "search"}]},
        sanitize_tool_args=lambda v: v if isinstance(v, dict) else {},
        evidence_has_content=grounding_evidence_has_content,
    )
    assert payload2 is not None
    assert payload2["tool_runs"][0]["tool_name"] == "search"


def test_inject_carryover_grounding_evidence_adds_evidence_and_tool_names():
    plan = {"is_fact_query": True}
    injected = inject_carryover_grounding_evidence(
        plan,
        {"evidence": [{"status": "ok", "key_facts": ["x"]}], "tool_runs": [{"tool_name": "search"}]},
        evidence_has_content=grounding_evidence_has_content,
    )
    assert injected
    assert get_runtime_carryover_grounding_evidence(plan)
    assert plan.get("_selected_tools_for_prompt") == ["search"]


def test_has_usable_grounding_evidence_and_whitelist_selection():
    assert has_usable_grounding_evidence(
        {"_carryover_grounding_evidence": [{"status": "ok", "key_facts": ["x"]}]},
        evidence_has_content=grounding_evidence_has_content,
    )
    candidate = select_first_whitelisted_tool_run(
        {"tool_runs": [{"tool_name": "a"}, {"tool_name": "b"}]},
        {"b"},
    )
    assert candidate is not None
    assert candidate.get("tool_name") == "b"


def test_count_successful_grounding_evidence_respects_allowed_statuses():
    plan = {
        "_grounding_evidence": [
            {"status": "ok"},
            {"status": "warning"},
            {"status": "fail"},
            {"status": "OK"},
        ]
    }
    assert count_successful_grounding_evidence(plan, ["ok"]) == 2
    assert count_successful_grounding_evidence(plan, ["ok", "warning"]) == 3
