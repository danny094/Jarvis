from core.orchestrator_runtime_utils import (
    build_followup_tool_reuse_specs,
    parse_container_list_result_for_selection,
    should_attempt_followup_tool_reuse,
    stringify_reuse_tool_names,
)


def test_parse_container_list_result_returns_error_text():
    selected, err = parse_container_list_result_for_selection(
        {"error": "boom"},
        expected_home_blueprint_id="trion-home",
        preferred_ids=[],
    )
    assert selected == ""
    assert err == "boom"


def test_parse_container_list_result_selects_home_running():
    selected, err = parse_container_list_result_for_selection(
        {
            "containers": [
                {"container_id": "1", "status": "running", "blueprint_id": "other"},
                {"container_id": "2", "status": "running", "blueprint_id": "trion-home"},
            ]
        },
        expected_home_blueprint_id="trion-home",
        preferred_ids=[],
    )
    assert err == ""
    assert selected == "2"


def test_should_attempt_followup_tool_reuse_gate():
    assert should_attempt_followup_tool_reuse(
        followup_enabled=True,
        verified_plan={"is_fact_query": True},
        explicit_tool_intent=False,
        short_fact_followup=True,
    )
    assert not should_attempt_followup_tool_reuse(
        followup_enabled=False,
        verified_plan={"is_fact_query": True},
        explicit_tool_intent=False,
        short_fact_followup=True,
    )


def test_should_attempt_followup_tool_reuse_allows_short_confirmation_even_without_fact_flag():
    assert should_attempt_followup_tool_reuse(
        followup_enabled=True,
        verified_plan={"is_fact_query": False},
        explicit_tool_intent=False,
        short_fact_followup=False,
        short_confirmation_followup=True,
    )


def test_build_followup_tool_reuse_specs_dedups_and_limits():
    state = {
        "tool_runs": [
            {"tool_name": "a", "args": {"x": 1}},
            {"tool_name": "a", "args": {"x": 2}},
            {"tool_name": "b", "args": {}},
            {"tool_name": "c", "args": {}},
        ]
    }
    out = build_followup_tool_reuse_specs(
        state,
        sanitize_tool_args=lambda v: v if isinstance(v, dict) else {},
        max_tools=2,
    )
    assert out == [{"tool": "a", "args": {"x": 1}}, "b"]
    assert stringify_reuse_tool_names(out) == ["a", "b"]
