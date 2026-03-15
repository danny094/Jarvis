from typing import Any, Callable, Dict, Optional


def sanitize_tone_signal(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    default = {
        "dialogue_act": "request",
        "response_tone": "neutral",
        "response_length_hint": "medium",
        "tone_confidence": 0.55,
        "classifier_mode": "fallback",
    }
    if not isinstance(raw, dict):
        return default

    out = dict(default)
    act = str(raw.get("dialogue_act") or "").strip().lower()
    tone = str(raw.get("response_tone") or "").strip().lower()
    length_hint = str(raw.get("response_length_hint") or "").strip().lower()

    if act in {"ack", "feedback", "question", "request", "analysis", "smalltalk"}:
        out["dialogue_act"] = act
    if tone in {"mirror_user", "warm", "neutral", "formal"}:
        out["response_tone"] = tone
    if length_hint in {"short", "medium", "long"}:
        out["response_length_hint"] = length_hint
    try:
        conf = float(raw.get("tone_confidence", out["tone_confidence"]))
    except Exception:
        conf = out["tone_confidence"]
    out["tone_confidence"] = max(0.0, min(1.0, conf))
    if raw.get("classifier_mode"):
        out["classifier_mode"] = str(raw["classifier_mode"])
    return out


def ensure_dialogue_controls(
    thinking_plan: Dict[str, Any],
    tone_signal: Optional[Dict[str, Any]],
    *,
    override_threshold: float = 0.82,
) -> Dict[str, Any]:
    plan = thinking_plan if isinstance(thinking_plan, dict) else {}
    signal = sanitize_tone_signal(tone_signal or {})

    act = str(plan.get("dialogue_act") or "").strip().lower()
    tone = str(plan.get("response_tone") or "").strip().lower()
    length_hint = str(plan.get("response_length_hint") or "").strip().lower()
    try:
        conf = float(plan.get("tone_confidence", signal["tone_confidence"]))
    except Exception:
        conf = float(signal["tone_confidence"])
    signal_conf = float(signal.get("tone_confidence", 0.0))

    if act not in {"ack", "feedback", "question", "request", "analysis", "smalltalk"}:
        act = signal["dialogue_act"]
    if tone not in {"mirror_user", "warm", "neutral", "formal"}:
        tone = signal["response_tone"]
    if length_hint not in {"short", "medium", "long"}:
        length_hint = signal["response_length_hint"]

    if signal_conf >= float(override_threshold):
        signal_act = str(signal.get("dialogue_act") or "").strip().lower()
        signal_tone = str(signal.get("response_tone") or "").strip().lower()
        signal_len = str(signal.get("response_length_hint") or "").strip().lower()

        if signal_act in {"ack", "feedback", "smalltalk"} and act in {"request", "analysis"}:
            act = signal_act
        if tone == "neutral" and signal_tone in {"mirror_user", "warm", "formal"}:
            tone = signal_tone
        if length_hint == "medium" and signal_len in {"short", "long"}:
            length_hint = signal_len
        conf = max(conf, signal_conf)

    plan["dialogue_act"] = act
    plan["response_tone"] = tone
    plan["response_length_hint"] = length_hint
    plan["tone_confidence"] = max(0.0, min(1.0, conf))
    plan["_tone_signal"] = signal
    return plan


def has_memory_recall_signal(text: str) -> bool:
    lower = str(text or "").lower()
    if not lower:
        return False
    recall_markers = (
        "was habe ich",
        "was weißt du",
        "was weisst du",
        "weißt du noch",
        "weisst du noch",
        "hast du dir gemerkt",
        "gemerkt",
        "erinnerst du",
        "remember",
        "recall",
        "über mich",
        "ueber mich",
        "meine präferenz",
        "meine praeferenz",
    )
    return any(marker in lower for marker in recall_markers)


def has_non_memory_tool_runtime_signal(text: str) -> bool:
    lower = str(text or "").lower()
    if not lower:
        return False
    markers = (
        "tool",
        "tools",
        "container",
        "blueprint",
        "docker",
        "cron",
        "cronjob",
        "skill",
        "run_skill",
        "list_skills",
        "exec_in_container",
        "request_container",
        "host server",
        "host-server",
        "ip adresse",
        "ip-adresse",
    )
    return any(marker in lower for marker in markers)


def should_skip_thinking_from_query_budget(
    signal: Optional[Dict[str, Any]],
    *,
    user_text: str,
    forced_mode: str = "",
    skip_enabled: bool,
    min_confidence: float,
    is_explicit_deep_request: Callable[[str], bool],
    contains_explicit_tool_intent: Callable[[str], bool],
) -> bool:
    if not skip_enabled:
        return False
    if not isinstance(signal, dict) or not signal:
        return False
    if forced_mode == "deep" or is_explicit_deep_request(user_text):
        return False
    if contains_explicit_tool_intent(user_text):
        return False
    if not bool(signal.get("skip_thinking_candidate")):
        return False
    try:
        conf = float(signal.get("confidence", 0.0) or 0.0)
    except Exception:
        conf = 0.0
    return conf >= float(min_confidence)


def should_force_query_budget_factual_memory(
    *,
    user_text: str,
    thinking_plan: Dict[str, Any],
    signal: Dict[str, Any],
    tool_domain_tag: str,
    has_non_memory_tool_runtime_signal_fn: Callable[[str], bool],
    has_memory_recall_signal_fn: Callable[[str], bool],
) -> bool:
    tag = str(tool_domain_tag or "").strip().upper()
    if tag in {"CRONJOB", "SKILL", "CONTAINER", "MCP_CALL"}:
        return False

    act = str((thinking_plan or {}).get("dialogue_act") or "").strip().lower()
    if act in {"smalltalk", "ack", "feedback"}:
        return False

    intent_hint = str((signal or {}).get("intent_hint") or "").strip().lower()
    if intent_hint in {"small_talk", "smalltalk"}:
        return False

    lower = str(user_text or "").lower()
    conversational_meta_markers = (
        "wie geht es dir",
        "wie geht's",
        "wie gehts",
        "wie fühl",
        "wie fuehl",
        "gefühl",
        "gefuehl",
        "gefühle",
        "gefuehle",
        "glaubst du",
        "meinst du",
        "ich finde",
    )
    if any(marker in lower for marker in conversational_meta_markers):
        return False

    if has_non_memory_tool_runtime_signal_fn(lower) and not has_memory_recall_signal_fn(lower):
        return False

    return True


def apply_query_budget_to_plan(
    thinking_plan: Dict[str, Any],
    signal: Optional[Dict[str, Any]],
    *,
    user_text: str = "",
    query_budget_enabled: bool,
    should_force_factual_memory: Callable[[str, Dict[str, Any], Dict[str, Any]], bool],
) -> Dict[str, Any]:
    plan = thinking_plan if isinstance(thinking_plan, dict) else {}
    if not query_budget_enabled:
        return plan
    if not isinstance(signal, dict) or not signal:
        return plan

    plan["_query_budget"] = dict(signal)
    query_type = str(signal.get("query_type") or "").strip().lower()
    intent_hint = str(signal.get("intent_hint") or "").strip().lower()
    response_budget = str(signal.get("response_budget") or "").strip().lower()
    tool_hint = str(signal.get("tool_hint") or "").strip()
    try:
        conf = float(signal.get("confidence", 0.0) or 0.0)
    except Exception:
        conf = 0.0

    if query_type == "factual":
        if should_force_factual_memory(user_text, plan, signal):
            plan["is_fact_query"] = True
            if not plan.get("needs_memory"):
                plan["needs_memory"] = True
            plan["_query_budget_factual_memory_forced"] = True
        else:
            plan["_query_budget_factual_memory_forced"] = False
            plan["_query_budget_factual_memory_force_skipped"] = True

    if response_budget in {"short", "medium", "long"}:
        current_len = str(plan.get("response_length_hint") or "").strip().lower()
        if (
            current_len not in {"short", "medium", "long"}
            or current_len == "medium"
            or (response_budget == "short" and conf >= 0.85 and current_len == "long")
        ):
            plan["response_length_hint"] = response_budget
            plan["_response_budget_reason"] = (
                f"query_budget:{query_type}:{response_budget}:conf_{conf:.2f}"
            )

    if intent_hint in {"small_talk", "smalltalk"} and conf >= 0.78:
        current_act = str(plan.get("dialogue_act") or "").strip().lower()
        if current_act in {"", "request", "analysis"}:
            plan["dialogue_act"] = "smalltalk"

    if tool_hint and conf >= 0.72:
        existing = plan.get("suggested_tools", [])
        if not isinstance(existing, list):
            existing = []
        if not existing:
            plan["suggested_tools"] = [tool_hint]
            plan["_query_budget_tool_seeded"] = True

    return plan
