from core.orchestrator_plan_schema_utils import coerce_thinking_plan_schema


def test_coerce_thinking_plan_schema_normalizes_bool_enums_and_lists():
    raw = {
        "needs_memory": "true",
        "is_fact_query": "false",
        "needs_chat_history": "1",
        "hallucination_risk": "unknown",
        "dialogue_act": "REQUEST",
        "response_tone": "LOUD",
        "response_length_hint": "verbose",
        "memory_keys": "",
        "suggested_tools": "exec_in_container",
    }
    out = coerce_thinking_plan_schema(
        raw,
        user_text="Nutze bitte Tools.",
        max_memory_keys_per_request=5,
        contains_explicit_tool_intent_fn=lambda text: True,
        has_memory_recall_signal_fn=lambda text: False,
    )
    assert out["needs_memory"] is False
    assert out["is_fact_query"] is False
    assert out["needs_chat_history"] is True
    assert out["hallucination_risk"] == "medium"
    assert out["dialogue_act"] == "request"
    assert out["response_tone"] == "neutral"
    assert out["response_length_hint"] == "medium"
    assert out["memory_keys"] == []
    assert out["suggested_tools"] == ["exec_in_container"]
    assert isinstance(out.get("_schema_coercion"), list)


def test_coerce_thinking_plan_schema_preserves_memory_for_recall_signal():
    raw = {
        "needs_memory": True,
        "is_fact_query": True,
        "memory_keys": [],
        "_domain_route": {"domain_tag": "CONTAINER", "domain_locked": True},
    }
    out = coerce_thinking_plan_schema(
        raw,
        user_text="Was hast du dir über meine Präferenz gemerkt?",
        max_memory_keys_per_request=5,
        contains_explicit_tool_intent_fn=lambda text: True,
        has_memory_recall_signal_fn=lambda text: True,
    )
    assert out["needs_memory"] is True
    assert out["is_fact_query"] is True
