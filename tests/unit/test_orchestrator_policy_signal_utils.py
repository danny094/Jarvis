from core.orchestrator_policy_signal_utils import (
    apply_query_budget_to_plan,
    ensure_dialogue_controls,
    has_memory_recall_signal,
    has_non_memory_tool_runtime_signal,
    sanitize_tone_signal,
    should_force_query_budget_factual_memory,
    should_skip_thinking_from_query_budget,
)


def test_sanitize_tone_signal_defaults_and_clamps_confidence():
    assert sanitize_tone_signal(None)["dialogue_act"] == "request"
    out = sanitize_tone_signal(
        {"dialogue_act": "question", "response_tone": "warm", "response_length_hint": "short", "tone_confidence": 3}
    )
    assert out["dialogue_act"] == "question"
    assert out["tone_confidence"] == 1.0


def test_memory_and_runtime_signal_helpers():
    assert has_memory_recall_signal("weißt du noch was ich sagte")
    assert has_non_memory_tool_runtime_signal("nutze exec_in_container auf host server")


def test_should_skip_thinking_from_query_budget():
    assert should_skip_thinking_from_query_budget(
        {"skip_thinking_candidate": True, "confidence": 0.9},
        user_text="kurze frage",
        forced_mode="",
        skip_enabled=True,
        min_confidence=0.7,
        is_explicit_deep_request=lambda text: False,
        contains_explicit_tool_intent=lambda text: False,
    )
    assert not should_skip_thinking_from_query_budget(
        {"skip_thinking_candidate": True, "confidence": 0.4},
        user_text="kurze frage",
        forced_mode="",
        skip_enabled=True,
        min_confidence=0.7,
        is_explicit_deep_request=lambda text: False,
        contains_explicit_tool_intent=lambda text: False,
    )


def test_should_force_query_budget_factual_memory():
    assert not should_force_query_budget_factual_memory(
        user_text="nutze container tool",
        thinking_plan={},
        signal={"intent_hint": "analysis"},
        tool_domain_tag="CONTAINER",
        has_non_memory_tool_runtime_signal_fn=has_non_memory_tool_runtime_signal,
        has_memory_recall_signal_fn=has_memory_recall_signal,
    )
    assert should_force_query_budget_factual_memory(
        user_text="was ist die hauptstadt von deutschland",
        thinking_plan={},
        signal={"intent_hint": "analysis"},
        tool_domain_tag="NONE",
        has_non_memory_tool_runtime_signal_fn=has_non_memory_tool_runtime_signal,
        has_memory_recall_signal_fn=has_memory_recall_signal,
    )


def test_apply_query_budget_to_plan_sets_expected_fields():
    plan = {}
    out = apply_query_budget_to_plan(
        plan,
        {"query_type": "factual", "intent_hint": "analysis", "response_budget": "short", "confidence": 0.9, "tool_hint": "search"},
        user_text="frage",
        query_budget_enabled=True,
        should_force_factual_memory=lambda text, p, s: True,
    )
    assert out.get("is_fact_query") is True
    assert out.get("needs_memory") is True
    assert out.get("response_length_hint") == "short"
    assert out.get("suggested_tools") == ["search"]


def test_ensure_dialogue_controls_backfills_and_overrides_with_high_confidence_signal():
    out = ensure_dialogue_controls(
        {"dialogue_act": "request", "response_tone": "neutral", "response_length_hint": "medium"},
        {
            "dialogue_act": "feedback",
            "response_tone": "warm",
            "response_length_hint": "short",
            "tone_confidence": 0.93,
        },
        override_threshold=0.82,
    )
    assert out["dialogue_act"] == "feedback"
    assert out["response_tone"] == "warm"
    assert out["response_length_hint"] == "short"
    assert out["tone_confidence"] == 0.93
