from core.orchestrator_precontrol_policy_utils import resolve_precontrol_policy_conflicts


def test_precontrol_policy_conflicts_disables_sequential_for_container_runtime_action():
    plan = {
        "needs_sequential_thinking": True,
        "sequential_thinking_required": True,
        "_domain_route": {"domain_tag": "CONTAINER", "domain_locked": True, "operation": "status"},
    }
    out, meta = resolve_precontrol_policy_conflicts(
        "finde host ip",
        plan,
        resolver_enabled=True,
        rollout_enabled=True,
        has_memory_recall_signal_fn=lambda text: False,
        contains_explicit_tool_intent_fn=lambda text: False,
        looks_like_host_runtime_lookup_fn=lambda text: False,
        has_non_memory_tool_runtime_signal_fn=lambda text: True,
        extract_tool_name_fn=lambda tool: str(tool),
    )
    assert out["needs_sequential_thinking"] is False
    assert out["sequential_thinking_required"] is False
    assert out.get("_sequential_deferred") is True
    assert meta["resolved"] is True


def test_precontrol_policy_conflicts_drops_request_container_if_exec_present_on_host_lookup():
    plan = {
        "_domain_route": {"domain_tag": "CONTAINER", "domain_locked": True, "operation": "unknown"},
        "suggested_tools": ["request_container", "exec_in_container"],
    }
    out, meta = resolve_precontrol_policy_conflicts(
        "host lookup",
        plan,
        resolver_enabled=True,
        rollout_enabled=True,
        has_memory_recall_signal_fn=lambda text: False,
        contains_explicit_tool_intent_fn=lambda text: False,
        looks_like_host_runtime_lookup_fn=lambda text: True,
        has_non_memory_tool_runtime_signal_fn=lambda text: True,
        extract_tool_name_fn=lambda tool: str(tool),
    )
    assert out["suggested_tools"] == ["exec_in_container"]
    assert meta["resolved"] is True
    assert "existing_container_over_request_container" in str(meta["reason"])


def test_precontrol_policy_conflicts_clears_memory_force_on_locked_domain():
    plan = {
        "_domain_route": {"domain_tag": "SKILL", "domain_locked": True},
        "_query_budget_factual_memory_forced": True,
        "needs_memory": True,
        "is_fact_query": True,
    }
    out, meta = resolve_precontrol_policy_conflicts(
        "nutze tools",
        plan,
        resolver_enabled=True,
        rollout_enabled=True,
        has_memory_recall_signal_fn=lambda text: False,
        contains_explicit_tool_intent_fn=lambda text: False,
        looks_like_host_runtime_lookup_fn=lambda text: False,
        has_non_memory_tool_runtime_signal_fn=lambda text: True,
        extract_tool_name_fn=lambda tool: str(tool),
    )
    assert out["needs_memory"] is False
    assert out["is_fact_query"] is False
    assert meta["resolved"] is True
