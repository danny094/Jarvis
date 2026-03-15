from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from core.container_state_utils import select_preferred_container_id


def parse_container_list_result_for_selection(
    list_result: Any,
    *,
    expected_home_blueprint_id: str,
    preferred_ids: Optional[List[str]] = None,
) -> Tuple[str, str]:
    """
    Parse container_list result and select preferred container id.
    Returns: (selected_container_id, error_text)
    """
    if isinstance(list_result, dict):
        err = str(list_result.get("error", "")).strip()
        if err:
            return "", err
        rows = list_result.get("containers", [])
    else:
        rows = []

    selected = select_preferred_container_id(
        rows,
        expected_home_blueprint_id=expected_home_blueprint_id,
        preferred_ids=preferred_ids,
    )
    return selected, ""


def should_attempt_followup_tool_reuse(
    *,
    followup_enabled: bool,
    verified_plan: Dict[str, Any],
    explicit_tool_intent: bool,
    short_fact_followup: bool,
    short_confirmation_followup: bool = False,
) -> bool:
    if not followup_enabled:
        return False
    if not isinstance(verified_plan, dict):
        return False
    if explicit_tool_intent:
        return False
    if short_confirmation_followup:
        return True
    if not bool(verified_plan.get("is_fact_query", False)):
        return False
    if not short_fact_followup:
        return False
    return True


def build_followup_tool_reuse_specs(
    state: Optional[Dict[str, Any]],
    *,
    sanitize_tool_args: Callable[[Any], Dict[str, Any]],
    max_tools: int = 2,
) -> List[Any]:
    if not isinstance(state, dict):
        return []
    out: List[Any] = []
    seen = set()
    for row in state.get("tool_runs") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("tool_name", "")).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        args = sanitize_tool_args(row.get("args") or {})
        if args:
            out.append({"tool": name, "args": args})
        else:
            out.append(name)
        if len(out) >= max(1, int(max_tools or 2)):
            break
    return out


def stringify_reuse_tool_names(tools: Sequence[Any]) -> List[str]:
    return [str(t.get("tool") if isinstance(t, dict) else t) for t in tools]
