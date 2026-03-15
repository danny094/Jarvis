from typing import Any, Callable, Dict


def should_suppress_conversational_tools(
    user_text: str,
    verified_plan: Dict[str, Any],
    *,
    tool_execution_policy: Dict[str, Any],
    contains_explicit_tool_intent_fn: Callable[[str], bool],
) -> bool:
    if bool((verified_plan or {}).get("_followup_tool_reuse_active")):
        return False
    policy = tool_execution_policy or {}
    conv_cfg = policy.get("conversational_guard", {}) if isinstance(policy, dict) else {}
    if contains_explicit_tool_intent_fn(user_text):
        return False
    act = str((verified_plan or {}).get("dialogue_act") or "").strip().lower()
    suppress_acts = {
        str(a).strip().lower()
        for a in conv_cfg.get("suppress_dialogue_acts", ["ack", "feedback", "smalltalk"])
        if str(a).strip()
    } or {"ack", "feedback", "smalltalk"}
    if act not in suppress_acts:
        return False
    if bool(conv_cfg.get("allow_question_suffix_bypass", False)) and str(user_text or "").strip().endswith("?"):
        return False
    return True
