from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from core.plan_runtime_bridge import (
    get_runtime_carryover_grounding_evidence,
    get_runtime_grounding_evidence,
    get_runtime_successful_tool_runs,
    set_runtime_carryover_grounding_evidence,
)


def grounding_evidence_has_content(item: Dict[str, Any]) -> bool:
    if not isinstance(item, dict):
        return False
    facts = item.get("key_facts")
    if isinstance(facts, list):
        for fact in facts:
            if str(fact or "").strip():
                return True
    structured = item.get("structured")
    if isinstance(structured, dict):
        output_text = str(structured.get("output") or structured.get("result") or "").strip()
        if output_text:
            return True
    metrics = item.get("metrics")
    if isinstance(metrics, dict):
        return bool(metrics)
    if isinstance(metrics, list):
        return any(
            isinstance(m, dict) and str(m.get("key") or m.get("name") or "").strip()
            for m in metrics
        )
    return False


def extract_recent_grounding_state(
    state: Any,
    *,
    now_ts: float,
    ttl_s: int,
    ttl_turns: int,
    history_len: int,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    """
    Returns (snapshot, should_drop_from_store).
    """
    if not isinstance(state, dict):
        return None, False
    age_s = now_ts - float(state.get("updated_at", 0.0) or 0.0)
    if age_s > int(ttl_s):
        return None, True
    state_history_len = int(state.get("history_len", 0) or 0)
    if history_len > 0 and state_history_len > 0 and history_len >= state_history_len:
        max_delta = max(2, int(ttl_turns) * 2)
        if (history_len - state_history_len) > max_delta:
            return None, True
    return (
        {
            "tool_runs": list(state.get("tool_runs") or []),
            "evidence": list(state.get("evidence") or []),
            "history_len": state_history_len,
            "updated_at": float(state.get("updated_at", 0.0) or 0.0),
        },
        False,
    )


def build_grounding_state_payload(
    verified_plan: Dict[str, Any],
    *,
    sanitize_tool_args: Callable[[Any], Dict[str, Any]],
    evidence_has_content: Callable[[Dict[str, Any]], bool],
    max_evidence: int = 8,
    max_tool_runs: int = 6,
    max_fallback_tool_runs: int = 4,
) -> Optional[Dict[str, Any]]:
    if not isinstance(verified_plan, dict):
        return None
    evidence = get_runtime_grounding_evidence(verified_plan)
    if not isinstance(evidence, list):
        evidence = []
    usable_evidence = [
        item
        for item in evidence
        if isinstance(item, dict)
        and str(item.get("status", "")).strip().lower() == "ok"
        and evidence_has_content(item)
    ][: max(1, int(max_evidence))]

    tool_runs_raw = get_runtime_successful_tool_runs(verified_plan)
    tool_runs: List[Dict[str, Any]] = []
    if isinstance(tool_runs_raw, list):
        for row in tool_runs_raw:
            if not isinstance(row, dict):
                continue
            name = str(row.get("tool_name", "")).strip()
            if not name:
                continue
            tool_runs.append(
                {
                    "tool_name": name,
                    "args": sanitize_tool_args(row.get("args") or {}),
                }
            )
            if len(tool_runs) >= max(1, int(max_tool_runs)):
                break
    if not tool_runs:
        for item in usable_evidence:
            name = str(item.get("tool_name", "")).strip()
            if not name:
                continue
            tool_runs.append({"tool_name": name, "args": {}})
            if len(tool_runs) >= max(1, int(max_fallback_tool_runs)):
                break

    if not usable_evidence and not tool_runs:
        return None
    return {"tool_runs": tool_runs, "evidence": usable_evidence}


def inject_carryover_grounding_evidence(
    verified_plan: Dict[str, Any],
    state: Optional[Dict[str, Any]],
    *,
    evidence_has_content: Callable[[Dict[str, Any]], bool],
    max_carry_evidence: int = 8,
    max_selected_tools: int = 4,
) -> bool:
    if not isinstance(verified_plan, dict):
        return False
    if not bool(verified_plan.get("is_fact_query", False)):
        return False

    current_evidence = get_runtime_grounding_evidence(verified_plan)
    if isinstance(current_evidence, list):
        has_current_usable = any(
            isinstance(item, dict)
            and str(item.get("status", "")).strip().lower() == "ok"
            and evidence_has_content(item)
            for item in current_evidence
        )
        if has_current_usable:
            return False

    if not isinstance(state, dict):
        return False
    carry = list(state.get("evidence") or [])
    if not carry:
        return False

    set_runtime_carryover_grounding_evidence(
        verified_plan,
        carry[: max(1, int(max_carry_evidence))],
    )
    verified_plan["needs_chat_history"] = True

    if not verified_plan.get("_selected_tools_for_prompt"):
        names: List[str] = []
        seen = set()
        for row in state.get("tool_runs") or []:
            name = str((row or {}).get("tool_name", "")).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)
            if len(names) >= max(1, int(max_selected_tools)):
                break
        if names:
            verified_plan["_selected_tools_for_prompt"] = names
    return True


def has_usable_grounding_evidence(
    verified_plan: Dict[str, Any],
    *,
    evidence_has_content: Callable[[Dict[str, Any]], bool],
) -> bool:
    if not isinstance(verified_plan, dict):
        return False
    merged: List[Any] = []
    current = get_runtime_grounding_evidence(verified_plan)
    carry = get_runtime_carryover_grounding_evidence(verified_plan)
    if isinstance(current, list):
        merged.extend(current)
    if isinstance(carry, list):
        merged.extend(carry)
    for item in merged:
        if not isinstance(item, dict):
            continue
        if str(item.get("status", "")).strip().lower() != "ok":
            continue
        if evidence_has_content(item):
            return True
    return False


def count_successful_grounding_evidence(
    verified_plan: Dict[str, Any],
    allowed_statuses: Optional[List[str]] = None,
) -> int:
    allowed = {str(s).strip().lower() for s in (allowed_statuses or ["ok"]) if str(s).strip()}
    if not allowed:
        allowed = {"ok"}
    evidence = get_runtime_grounding_evidence(verified_plan)
    if not isinstance(evidence, list):
        return 0
    count = 0
    for item in evidence:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "")).strip().lower()
        if status in allowed:
            count += 1
    return count


def select_first_whitelisted_tool_run(
    state: Optional[Dict[str, Any]],
    whitelist: Iterable[str],
) -> Optional[Dict[str, Any]]:
    if not isinstance(state, dict):
        return None
    allowed: Set[str] = {str(x).strip() for x in whitelist if str(x).strip()}
    if not allowed:
        return None
    for row in state.get("tool_runs") or []:
        name = str((row or {}).get("tool_name", "")).strip()
        if name in allowed:
            return row if isinstance(row, dict) else {"tool_name": name, "args": {}}
    return None
