from typing import Any, Callable, Dict, List


def coerce_thinking_plan_schema(
    thinking_plan: Dict[str, Any],
    *,
    user_text: str = "",
    max_memory_keys_per_request: int,
    contains_explicit_tool_intent_fn: Callable[[str], bool],
    has_memory_recall_signal_fn: Callable[[str], bool],
) -> Dict[str, Any]:
    plan = thinking_plan if isinstance(thinking_plan, dict) else {}
    if not plan:
        return plan

    fixes: List[str] = []

    def _coerce_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return bool(value)
        low = str(value).strip().lower()
        if low in {"true", "1", "yes", "ja", "on"}:
            return True
        if low in {"false", "0", "no", "nein", "off", ""}:
            return False
        return default

    bool_keys = (
        "needs_memory",
        "is_fact_query",
        "needs_chat_history",
        "is_new_fact",
        "needs_sequential_thinking",
        "sequential_thinking_required",
    )
    for key in bool_keys:
        if key in plan:
            old = plan.get(key)
            new = _coerce_bool(old, default=False)
            if old != new:
                fixes.append(f"coerce_bool:{key}")
            plan[key] = new

    risk = str(plan.get("hallucination_risk") or "").strip().lower()
    if risk not in {"low", "medium", "high"}:
        plan["hallucination_risk"] = "medium"
        fixes.append("enum:hallucination_risk")

    act = str(plan.get("dialogue_act") or "").strip().lower()
    if act and act not in {"ack", "feedback", "question", "request", "analysis", "smalltalk"}:
        plan["dialogue_act"] = "request"
        fixes.append("enum:dialogue_act")
    elif act:
        if str(plan.get("dialogue_act")) != act:
            fixes.append("normalize:dialogue_act")
        plan["dialogue_act"] = act

    tone = str(plan.get("response_tone") or "").strip().lower()
    if tone and tone not in {"mirror_user", "warm", "neutral", "formal"}:
        plan["response_tone"] = "neutral"
        fixes.append("enum:response_tone")
    elif tone:
        if str(plan.get("response_tone")) != tone:
            fixes.append("normalize:response_tone")
        plan["response_tone"] = tone

    length = str(plan.get("response_length_hint") or "").strip().lower()
    if length and length not in {"short", "medium", "long"}:
        plan["response_length_hint"] = "medium"
        fixes.append("enum:response_length_hint")
    elif length:
        if str(plan.get("response_length_hint")) != length:
            fixes.append("normalize:response_length_hint")
        plan["response_length_hint"] = length

    raw_keys = plan.get("memory_keys", [])
    normalized_keys: List[str] = []
    if isinstance(raw_keys, list):
        seen = set()
        for item in raw_keys:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized_keys.append(text)
            if len(normalized_keys) >= int(max(1, max_memory_keys_per_request)):
                break
    elif raw_keys:
        normalized_keys = [str(raw_keys).strip()]
        fixes.append("coerce_list:memory_keys")
    plan["memory_keys"] = normalized_keys

    raw_tools = plan.get("suggested_tools", [])
    if isinstance(raw_tools, list):
        plan["suggested_tools"] = raw_tools
    elif raw_tools:
        plan["suggested_tools"] = [raw_tools]
        fixes.append("coerce_list:suggested_tools")
    else:
        plan["suggested_tools"] = []

    route = plan.get("_domain_route") or {}
    route = route if isinstance(route, dict) else {}
    domain_tag = str(route.get("domain_tag") or "").strip().upper()
    domain_locked = bool(route.get("domain_locked"))
    explicit_tool_intent = contains_explicit_tool_intent_fn(user_text)
    recall_signal = has_memory_recall_signal_fn(user_text)
    if plan.get("needs_memory") and not plan.get("memory_keys"):
        if (domain_locked and domain_tag in {"CONTAINER", "SKILL", "CRONJOB"}) or explicit_tool_intent:
            if not recall_signal:
                plan["needs_memory"] = False
                plan["is_fact_query"] = False
                fixes.append("guard:drop_empty_memory_for_domain_or_tool_intent")

    if fixes:
        plan["_schema_coercion"] = fixes[-12:]
    return plan
