from core.orchestrator_skill_task_utils import sanitize_intent_thinking_plan_for_skill_task


def _safe(value, max_len):
    text = str(value or "").strip()
    return text[:max_len]


def _extract(plan):
    out = []
    raw = (plan or {}).get("suggested_tools", []) or []
    for item in raw:
        if isinstance(item, dict):
            name = str(item.get("tool") or item.get("name") or "").strip()
        else:
            name = str(item).strip()
        if name:
            out.append(name)
    return out


def test_sanitize_intent_thinking_plan_for_skill_task_compacts_expected_fields():
    out = sanitize_intent_thinking_plan_for_skill_task(
        {
            "intent": "build something",
            "reasoning": "x" * 3000,
            "needs_memory": 1,
            "is_fact_query": 0,
            "sequential_complexity": "99",
            "memory_keys": ["k1", "", "k2"],
            "suggested_tools": [{"name": "autonomous_skill_task"}, {"tool": "run_skill"}, {"x": "y"}],
            "_sequential_result": {"noisy": True},
        },
        safe_str_fn=_safe,
        extract_suggested_tool_names_fn=_extract,
    )
    assert out["intent"] == "build something"
    assert len(out["reasoning"]) == 2000
    assert out["needs_memory"] is True
    assert out["is_fact_query"] is False
    assert out["sequential_complexity"] == 10
    assert out["memory_keys"] == ["k1", "k2"]
    assert out["suggested_tools"] == ["autonomous_skill_task", "run_skill"]
    assert "_sequential_result" not in out


def test_sanitize_intent_thinking_plan_for_skill_task_handles_non_dict():
    assert sanitize_intent_thinking_plan_for_skill_task(
        None,
        safe_str_fn=_safe,
        extract_suggested_tool_names_fn=_extract,
    ) == {}
