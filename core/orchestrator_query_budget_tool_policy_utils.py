from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


def apply_query_budget_tool_policy(
    user_text: str,
    verified_plan: Dict[str, Any],
    suggested_tools: List[Any],
    *,
    query_budget_enabled: bool,
    max_tools_factual_low: int,
    heavy_tools: Sequence[str],
    contains_explicit_tool_intent_fn: Callable[[str], bool],
    is_explicit_deep_request_fn: Callable[[str], bool],
    is_explicit_think_request_fn: Callable[[str], bool],
    extract_tool_name_fn: Callable[[Any], str],
) -> Tuple[List[Any], Optional[Dict[str, Any]]]:
    if not query_budget_enabled:
        return suggested_tools, None
    if not isinstance(verified_plan, dict):
        return suggested_tools, None
    if not suggested_tools:
        return suggested_tools, None

    signal = verified_plan.get("_query_budget")
    if not isinstance(signal, dict) or not signal:
        return suggested_tools, None
    try:
        confidence = float(signal.get("confidence", 0.0) or 0.0)
    except Exception:
        confidence = 0.0
    if confidence < 0.60:
        return suggested_tools, None

    query_type = str(signal.get("query_type") or "").strip().lower()
    complexity = str(signal.get("complexity_signal") or "").strip().lower()
    tool_hint = str(signal.get("tool_hint") or "").strip()
    response_mode = str(verified_plan.get("_response_mode", "interactive")).strip().lower()
    explicit_tool_intent = contains_explicit_tool_intent_fn(user_text)
    explicit_deep_or_think = (
        is_explicit_deep_request_fn(user_text) or is_explicit_think_request_fn(user_text)
    )
    heavy = {str(x).strip().lower() for x in heavy_tools if str(x).strip()}

    filtered = list(suggested_tools)
    dropped = 0
    reasons: List[str] = []

    if query_type == "conversational" and not explicit_tool_intent:
        dropped = len(filtered)
        filtered = []
        reasons.append("conversational_no_tool_intent")
    elif (
        query_type == "analytical"
        and response_mode != "deep"
        and not explicit_tool_intent
        and not explicit_deep_or_think
    ):
        before = len(filtered)
        filtered = [
            tool
            for tool in filtered
            if extract_tool_name_fn(tool).strip().lower() not in heavy
        ]
        dropped += max(0, before - len(filtered))
        reasons.append("analytical_interactive_drop_heavy")
    elif query_type == "factual" and complexity == "low" and not explicit_tool_intent:
        before = len(filtered)
        filtered = [
            tool
            for tool in filtered
            if extract_tool_name_fn(tool).strip().lower() not in heavy
        ]
        dropped += max(0, before - len(filtered))
        reasons.append("factual_low_drop_heavy")

        cap = int(max_tools_factual_low)
        if cap >= 0 and len(filtered) > cap:
            dropped += max(0, len(filtered) - cap)
            filtered = filtered[:cap]
            reasons.append(f"cap={cap}")

    if (not filtered) and query_type == "factual" and tool_hint and not explicit_tool_intent:
        tool_hint_l = tool_hint.lower()
        if tool_hint_l not in heavy:
            filtered = [tool_hint]
            reasons.append(f"seed_hint={tool_hint}")

    if not reasons:
        return filtered, None
    policy = {
        "query_type": query_type,
        "complexity_signal": complexity,
        "confidence": round(confidence, 3),
        "reasons": reasons,
        "dropped": dropped,
    }
    return filtered, policy
