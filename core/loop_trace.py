from __future__ import annotations

from typing import Any, Dict, List, Optional


LOOP_TRACE_EVENT_TYPES = {
    "loop_trace_started",
    "loop_trace_plan_normalized",
    "loop_trace_step_started",
    "loop_trace_correction",
    "loop_trace_completed",
}


def _contains_any(text: str, markers: List[str]) -> bool:
    return any(marker in text for marker in markers)


def _normalize_text(text: str) -> str:
    return (
        str(text or "").strip().lower()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )


def is_internal_loop_analysis_prompt(user_text: str) -> bool:
    text = _normalize_text(user_text)
    if not text:
        return False
    direct_markers = [
        "multistep loop",
        "task loop",
        "planungsmodus",
        "implementationsplan",
    ]
    if _contains_any(text, direct_markers):
        return True
    has_loop_term = "loop" in text
    has_analysis_term = _contains_any(
        text,
        [
            "zwischenstand",
            "zwischenstaende",
            "sichere zwischenstaende",
            "sichere zwischenstaende",
            "pruefe kurz",
            "pruefe",
            "pruefung",
        ],
    )
    return has_loop_term and has_analysis_term


def _has_explicit_memory_anchor(text: str) -> bool:
    return _contains_any(
        text,
        [
            "wie besprochen",
            "gestern",
            "vorgestern",
            "letzte woche",
            "vorhin",
            "obsidian",
            "docs/",
            "dokument",
            "commit ",
            "commit:",
            "conversation",
            "konversation",
            "chatverlauf",
        ],
    )


def _tool_name_list(raw_tools: Any) -> List[str]:
    out: List[str] = []
    for item in list(raw_tools or []):
        if isinstance(item, dict):
            name = str(item.get("tool") or item.get("name") or "").strip().lower()
        else:
            name = str(item or "").strip().lower()
        if name:
            out.append(name)
    return out


def normalize_internal_loop_analysis_plan(
    thinking_plan: Dict[str, Any],
    *,
    user_text: str = "",
    contains_explicit_tool_intent: bool = False,
    has_memory_recall_signal: bool = False,
) -> Dict[str, Any]:
    plan = thinking_plan if isinstance(thinking_plan, dict) else {}
    if not plan:
        return plan
    if not is_internal_loop_analysis_prompt(user_text):
        return plan

    corrections: List[Dict[str, Any]] = []
    normalized_user_text = _normalize_text(user_text)
    explicit_memory_anchor = _has_explicit_memory_anchor(normalized_user_text)

    def _record(field: str, old: Any, new: Any, reason: str) -> None:
        if old == new:
            return
        corrections.append(
            {
                "field": field,
                "from": old,
                "to": new,
                "reason": reason,
            }
        )

    raw_strategy = plan.get("resolution_strategy")
    if raw_strategy in {
        "active_container_capability",
        "container_inventory",
        "container_blueprint_catalog",
        "container_state_binding",
        "container_request",
        "home_container_info",
        "skill_catalog_context",
    }:
        _record(
            "resolution_strategy",
            raw_strategy,
            None,
            "internal_loop_analysis_is_not_runtime_or_catalog_query",
        )
        plan["resolution_strategy"] = None

    raw_tools = list(plan.get("suggested_tools") or [])
    if raw_tools and not contains_explicit_tool_intent:
        _record(
            "suggested_tools",
            raw_tools,
            [],
            "drop_runtime_and_memory_tool_drift_for_internal_loop_analysis",
        )
        plan["suggested_tools"] = []

    raw_hints = list(plan.get("strategy_hints") or [])
    if raw_hints:
        filtered_hints = [
            hint for hint in raw_hints
            if hint not in {
                "runtime_skills",
                "checkpoint_status",
                "loop_validation",
            }
        ]
        if filtered_hints != raw_hints:
            _record(
                "strategy_hints",
                raw_hints,
                filtered_hints,
                "drop_runtime_specific_hints_for_internal_loop_analysis",
            )
            plan["strategy_hints"] = filtered_hints

    raw_needs_memory = bool(plan.get("needs_memory"))
    if raw_needs_memory and not (has_memory_recall_signal or explicit_memory_anchor):
        _record(
            "needs_memory",
            raw_needs_memory,
            False,
            "no_explicit_memory_anchor_for_internal_loop_analysis",
        )
        plan["needs_memory"] = False
        raw_memory_keys = list(plan.get("memory_keys") or [])
        if raw_memory_keys:
            _record(
                "memory_keys",
                raw_memory_keys,
                [],
                "clear_memory_keys_without_explicit_memory_anchor",
            )
            plan["memory_keys"] = []

    if not plan.get("needs_memory") and plan.get("memory_keys"):
        raw_memory_keys = list(plan.get("memory_keys") or [])
        _record(
            "memory_keys",
            raw_memory_keys,
            [],
            "memory_keys_require_needs_memory_true",
        )
        plan["memory_keys"] = []

    plan["_loop_trace_mode"] = "internal_loop_analysis"
    if corrections:
        plan["_loop_trace_normalization"] = {
            "mode": "internal_loop_analysis",
            "reason": "prompt_matches_internal_loop_analysis",
            "corrections": corrections,
        }
    else:
        plan["_loop_trace_normalization"] = {
            "mode": "internal_loop_analysis",
            "reason": "prompt_matches_internal_loop_analysis",
            "corrections": [],
        }
    schema_coercion = list(plan.get("_schema_coercion") or [])
    schema_coercion.append("normalize:internal_loop_analysis")
    plan["_schema_coercion"] = schema_coercion[-12:]
    return plan


def build_loop_trace_started_event(user_text: str, thinking_plan: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    plan = thinking_plan if isinstance(thinking_plan, dict) else {}
    return {
        "type": "loop_trace_started",
        "objective": str(user_text or "").strip(),
        "intent": str(plan.get("intent") or "").strip(),
        "resolution_strategy": plan.get("resolution_strategy"),
        "suggested_tools": _tool_name_list(plan.get("suggested_tools")),
        "needs_memory": bool(plan.get("needs_memory", False)),
        "needs_sequential_thinking": bool(
            plan.get("needs_sequential_thinking") or plan.get("sequential_thinking_required")
        ),
    }


def build_loop_trace_plan_normalized_event(thinking_plan: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    plan = thinking_plan if isinstance(thinking_plan, dict) else {}
    trace = plan.get("_loop_trace_normalization")
    if not isinstance(trace, dict):
        return None
    return {
        "type": "loop_trace_plan_normalized",
        "mode": trace.get("mode"),
        "reason": trace.get("reason"),
        "corrections": list(trace.get("corrections") or []),
        "resolution_strategy": plan.get("resolution_strategy"),
        "suggested_tools": _tool_name_list(plan.get("suggested_tools")),
        "needs_memory": bool(plan.get("needs_memory", False)),
    }


def build_loop_trace_step_started_event(
    *,
    phase: str,
    summary: str,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = {
        "type": "loop_trace_step_started",
        "phase": str(phase or "").strip(),
        "summary": str(summary or "").strip(),
    }
    if isinstance(details, dict) and details:
        payload["details"] = details
    return payload


def build_loop_trace_correction_event(
    *,
    stage: str,
    summary: str,
    reasons: Optional[List[str]] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = {
        "type": "loop_trace_correction",
        "stage": str(stage or "").strip(),
        "summary": str(summary or "").strip(),
        "reasons": list(reasons or []),
    }
    if isinstance(details, dict) and details:
        payload["details"] = details
    return payload


def build_loop_trace_completed_event(
    *,
    response_mode: str,
    model: str,
    correction_count: int = 0,
    summary: str = "",
) -> Dict[str, Any]:
    return {
        "type": "loop_trace_completed",
        "response_mode": str(response_mode or "").strip(),
        "model": str(model or "").strip(),
        "correction_count": max(0, int(correction_count or 0)),
        "summary": str(summary or "").strip(),
    }
