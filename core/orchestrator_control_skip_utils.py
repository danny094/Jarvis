from typing import Dict, Iterable, Sequence, Tuple


def should_skip_control_layer(
    user_text: str,
    thinking_plan: Dict[str, object],
    *,
    enable_control_layer: bool,
    skip_control_on_low_risk: bool,
    force_verify_fact: bool,
    suggested_tool_names: Iterable[str],
    control_skip_block_tools: Sequence[str],
    control_skip_block_keywords: Sequence[str],
    control_skip_hard_safety_keywords: Sequence[str],
) -> Tuple[bool, str]:
    """
    Unified skip policy for sync + stream to avoid drift.

    Returns:
      (skip_control, reason)
    """
    if not enable_control_layer:
        return True, "control_disabled"

    if force_verify_fact and bool((thinking_plan or {}).get("is_fact_query", False)):
        return False, "fact_query_requires_control"
    if bool((thinking_plan or {}).get("_hardware_gate_triggered")):
        return False, "hardware_gate_requires_control"

    hallucination_risk = (thinking_plan or {}).get("hallucination_risk", "medium")
    if not (skip_control_on_low_risk and hallucination_risk == "low"):
        return False, "control_required"

    suggested = {str(name).strip() for name in (suggested_tool_names or []) if str(name).strip()}
    sensitive_hits = sorted(
        suggested.intersection(
            {str(name).strip() for name in (control_skip_block_tools or []) if str(name).strip()}
        )
    )
    if sensitive_hits:
        return False, f"sensitive_tools:{','.join(sensitive_hits)}"

    user_lower = (user_text or "").lower()
    if any(str(kw) in user_lower for kw in (control_skip_block_keywords or [])):
        return False, "creation_keywords"
    if any(str(kw) in user_lower for kw in (control_skip_hard_safety_keywords or [])):
        return False, "hard_safety_keywords"

    return True, "low_risk_skip"
