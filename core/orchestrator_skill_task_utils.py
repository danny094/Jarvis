from typing import Any, Callable, Dict, List


def sanitize_intent_thinking_plan_for_skill_task(
    thinking_plan: Any,
    *,
    safe_str_fn: Callable[[Any, int], str],
    extract_suggested_tool_names_fn: Callable[[Dict[str, Any]], List[str]],
) -> Dict[str, Any]:
    """
    Build a compact, schema-safe subset for autonomous_skill_task.
    Prevents noisy / incompatible structures from crossing service boundaries.
    """
    if not isinstance(thinking_plan, dict):
        return {}

    safe: Dict[str, Any] = {}

    text_keys = (
        "intent",
        "reasoning",
        "reasoning_type",
        "hallucination_risk",
        "time_reference",
    )
    for key in text_keys:
        if key in thinking_plan:
            value = safe_str_fn(thinking_plan.get(key), 2000)
            if value:
                safe[key] = value

    for key in ("needs_memory", "is_fact_query", "needs_sequential_thinking", "sequential_thinking_required"):
        if key in thinking_plan:
            safe[key] = bool(thinking_plan.get(key))

    if "sequential_complexity" in thinking_plan:
        try:
            complexity = int(thinking_plan.get("sequential_complexity", 0))
        except Exception:
            complexity = 0
        safe["sequential_complexity"] = max(0, min(10, complexity))

    raw_memory_keys = thinking_plan.get("memory_keys", [])
    memory_keys: List[str] = []
    if isinstance(raw_memory_keys, list):
        for item in raw_memory_keys:
            text = safe_str_fn(item, 80)
            if text:
                memory_keys.append(text)
    if memory_keys:
        safe["memory_keys"] = memory_keys[:20]

    suggested_tools = extract_suggested_tool_names_fn(
        {"suggested_tools": thinking_plan.get("suggested_tools", [])}
    )
    if suggested_tools:
        safe["suggested_tools"] = suggested_tools[:20]

    return safe
