from core.orchestrator_query_budget_tool_policy_utils import apply_query_budget_tool_policy


def test_query_budget_tool_policy_conversational_clears_tools():
    filtered, policy = apply_query_budget_tool_policy(
        "hey",
        {"_query_budget": {"query_type": "conversational", "confidence": 0.9}},
        ["analyze"],
        query_budget_enabled=True,
        max_tools_factual_low=1,
        heavy_tools=("analyze",),
        contains_explicit_tool_intent_fn=lambda text: False,
        is_explicit_deep_request_fn=lambda text: False,
        is_explicit_think_request_fn=lambda text: False,
        extract_tool_name_fn=lambda tool: str(tool),
    )
    assert filtered == []
    assert isinstance(policy, dict)
    assert "conversational_no_tool_intent" in policy.get("reasons", [])


def test_query_budget_tool_policy_factual_low_drops_heavy_and_seeds_hint():
    filtered, policy = apply_query_budget_tool_policy(
        "frage",
        {
            "_query_budget": {
                "query_type": "factual",
                "complexity_signal": "low",
                "confidence": 0.95,
                "tool_hint": "memory_search",
            }
        },
        ["analyze"],
        query_budget_enabled=True,
        max_tools_factual_low=1,
        heavy_tools=("analyze",),
        contains_explicit_tool_intent_fn=lambda text: False,
        is_explicit_deep_request_fn=lambda text: False,
        is_explicit_think_request_fn=lambda text: False,
        extract_tool_name_fn=lambda tool: str(tool),
    )
    assert filtered == ["memory_search"]
    assert isinstance(policy, dict)
    assert any(str(r).startswith("seed_hint=") for r in policy.get("reasons", []))


def test_query_budget_tool_policy_noop_when_disabled():
    suggested = ["analyze", "memory_search"]
    filtered, policy = apply_query_budget_tool_policy(
        "frage",
        {"_query_budget": {"query_type": "factual", "confidence": 0.95}},
        suggested,
        query_budget_enabled=False,
        max_tools_factual_low=1,
        heavy_tools=("analyze",),
        contains_explicit_tool_intent_fn=lambda text: False,
        is_explicit_deep_request_fn=lambda text: False,
        is_explicit_think_request_fn=lambda text: False,
        extract_tool_name_fn=lambda tool: str(tool),
    )
    assert filtered == suggested
    assert policy is None
