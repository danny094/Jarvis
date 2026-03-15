from typing import Any, Callable, Dict, List, Tuple


def resolve_precontrol_policy_conflicts(
    user_text: str,
    thinking_plan: Dict[str, Any],
    *,
    resolver_enabled: bool,
    rollout_enabled: bool,
    has_memory_recall_signal_fn: Callable[[str], bool],
    contains_explicit_tool_intent_fn: Callable[[str], bool],
    looks_like_host_runtime_lookup_fn: Callable[[str], bool],
    has_non_memory_tool_runtime_signal_fn: Callable[[str], bool],
    extract_tool_name_fn: Callable[[Any], str],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Resolve deterministic conflicts after QueryBudget+DomainRouter mutation.

    Returns (plan, meta):
      meta = {"resolved": bool, "domain_tag": str, "reason": str}
    """
    plan = thinking_plan if isinstance(thinking_plan, dict) else {}
    meta: Dict[str, Any] = {"resolved": False, "domain_tag": "", "reason": ""}

    if not resolver_enabled or not rollout_enabled:
        return plan, meta

    route = plan.get("_domain_route")
    if not isinstance(route, dict):
        return plan, meta
    if not bool(route.get("domain_locked")):
        return plan, meta

    domain_tag = str(route.get("domain_tag") or "").strip().upper()
    if domain_tag not in {"CONTAINER", "SKILL", "CRONJOB"}:
        return plan, meta
    meta["domain_tag"] = domain_tag

    conflict_log = plan.get("_policy_conflict_resolution")
    if not isinstance(conflict_log, list):
        conflict_log = []
    resolved_reasons: List[str] = []

    recall_signal = has_memory_recall_signal_fn(user_text)
    explicit_tool_intent = contains_explicit_tool_intent_fn(user_text)
    lower_user = str(user_text or "").lower()

    if domain_tag == "CONTAINER" and not recall_signal:
        operation = str(route.get("operation") or "").strip().lower()
        host_runtime_lookup = looks_like_host_runtime_lookup_fn(user_text)
        runtime_action = host_runtime_lookup or (
            operation in {"exec", "status", "logs", "inspect", "list", "ports", "unknown"}
            and has_non_memory_tool_runtime_signal_fn(lower_user)
        )
        if runtime_action:
            if bool(plan.get("needs_sequential_thinking")) or bool(plan.get("sequential_thinking_required")):
                plan["needs_sequential_thinking"] = False
                plan["sequential_thinking_required"] = False
                plan["_sequential_deferred"] = True
                plan["_sequential_deferred_reason"] = "container_runtime_fast_path"
                rule = "container_runtime_fast_path_over_sequential_thinking"
                conflict_log.append(
                    {
                        "rule": rule,
                        "domain_tag": domain_tag,
                        "action": "disable_sequential_thinking",
                    }
                )
                resolved_reasons.append(rule)

            if host_runtime_lookup and isinstance(plan.get("suggested_tools"), list):
                tools = list(plan.get("suggested_tools") or [])
                has_exec = any(
                    extract_tool_name_fn(tool).strip().lower() == "exec_in_container"
                    for tool in tools
                )
                if has_exec:
                    filtered = [
                        tool
                        for tool in tools
                        if extract_tool_name_fn(tool).strip().lower() != "request_container"
                    ]
                    if len(filtered) != len(tools):
                        plan["suggested_tools"] = filtered
                        rule = "container_runtime_existing_container_over_request_container"
                        conflict_log.append(
                            {
                                "rule": rule,
                                "domain_tag": domain_tag,
                                "action": "drop_request_container_for_host_runtime_lookup",
                            }
                        )
                        resolved_reasons.append(rule)

    if not bool(plan.get("_query_budget_factual_memory_forced")):
        if resolved_reasons:
            plan["_policy_conflict_resolution"] = conflict_log[-6:]
            plan["_policy_conflict_resolved"] = True
            plan["_policy_conflict_reason"] = resolved_reasons[-1]
            meta["resolved"] = True
            meta["reason"] = resolved_reasons[-1]
        return plan, meta

    if recall_signal:
        return plan, meta

    raw_keys = plan.get("memory_keys", [])
    has_explicit_keys = isinstance(raw_keys, list) and any(str(k or "").strip() for k in raw_keys)
    if has_explicit_keys and not explicit_tool_intent:
        return plan, meta

    memory_changed = False
    if bool(plan.get("needs_memory")):
        plan["needs_memory"] = False
        memory_changed = True
    if bool(plan.get("is_fact_query")):
        plan["is_fact_query"] = False
        memory_changed = True

    if memory_changed:
        rule_reason = (
            "domain_locked_over_explicit_tool_intent_over_query_budget_memory_force"
            if explicit_tool_intent
            else "domain_locked_over_query_budget_memory_force"
        )
        conflict_log.append(
            {
                "rule": rule_reason,
                "domain_tag": domain_tag,
                "action": "clear_needs_memory_and_is_fact_query",
            }
        )
        resolved_reasons.append(rule_reason)

    if not resolved_reasons:
        return plan, meta

    plan["_policy_conflict_resolution"] = conflict_log[-6:]
    plan["_policy_conflict_resolved"] = True
    plan["_policy_conflict_reason"] = resolved_reasons[-1]
    meta["resolved"] = True
    meta["reason"] = resolved_reasons[-1]
    return plan, meta
