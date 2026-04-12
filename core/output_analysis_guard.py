from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


def _normalize(text: str) -> str:
    raw = str(text or "").lower()
    return (
        raw.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )


def _collapse(text: str) -> str:
    return " ".join(str(text or "").split())


def _clip(text: str, limit: int = 220) -> str:
    compact = _collapse(text)
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


def _matches_any(text: str, patterns: List[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _build_guard_config(output_cfg: Dict[str, Any]) -> Dict[str, bool]:
    cfg = dict((output_cfg or {}).get("analysis_turn_guard") or {})
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "forbid_memory": bool(cfg.get("forbid_unsupported_memory_claims", True)),
        "forbid_runtime": bool(cfg.get("forbid_unsupported_runtime_claims", True)),
        "forbid_completion": bool(cfg.get("forbid_fabricated_completion_claims", True)),
    }


_MEMORY_PATTERNS = [
    r"\bgedaechtnis\b",
    r"\bgespeichert(?:en|es|er|e)?\b",
    r"\bmemory\b",
]

_RUNTIME_PATTERNS: List[Tuple[str, List[str]]] = [
    (
        "runtime_resources",
        [
            r"\bvram\b",
            r"\bram\b",
            r"\bgpu\b",
            r"\bcpu\b",
            r"\bhardware\b",
        ],
    ),
    (
        "runtime_inventory",
        [
            r"\bcontainer(?:-id|s)?\b",
            r"\bblueprint(?:s)?\b",
        ],
    ),
    (
        "runtime_health",
        [
            r"\bsystemcheck\b",
            r"\bauslastung\b",
            r"\bueberlastung\b",
            r"\bim gruenen bereich\b",
            r"\bgruenen bereich\b",
        ],
    ),
]

_COMPLETION_PATTERNS = [
    r"\bschritt\s*\d+.{0,40}\b(?:erledigt|abgeschlossen)\b",
    r"✅",
]


def _analysis_turn_guard_trigger_source(verified_plan: Dict[str, Any]) -> str:
    if not isinstance(verified_plan, dict):
        return ""
    if verified_plan.get("needs_sequential_thinking") or verified_plan.get("sequential_thinking_required"):
        return "sequential_thinking"
    if verified_plan.get("_sequential_result"):
        return "sequential_result"
    if str(verified_plan.get("_loop_trace_mode") or "").strip().lower() == "internal_loop_analysis":
        return "loop_trace_mode"
    trace = verified_plan.get("_loop_trace_normalization")
    if (
        isinstance(trace, dict)
        and str(trace.get("mode") or "").strip().lower() == "internal_loop_analysis"
    ):
        return "loop_trace_normalization"
    return ""


def inspect_analysis_turn_guard_applicability(
    verified_plan: Dict[str, Any],
    *,
    output_cfg: Dict[str, Any] | None = None,
    has_tool_usage: bool = False,
    is_fact_query: bool = False,
) -> Dict[str, Any]:
    base = {
        "applicable": False,
        "trigger_source": "",
        "skipped_reason": "",
    }
    if not isinstance(verified_plan, dict):
        base["skipped_reason"] = "invalid_plan"
        return base
    cfg = _build_guard_config(output_cfg or {})
    if not cfg["enabled"]:
        base["skipped_reason"] = "disabled"
        return base
    if is_fact_query:
        base["skipped_reason"] = "fact_query"
        return base
    if has_tool_usage:
        base["skipped_reason"] = "tool_usage"
        return base
    if verified_plan.get("_container_query_policy") or verified_plan.get("_skill_catalog_context"):
        base["skipped_reason"] = "runtime_contract_context"
        return base
    trigger_source = _analysis_turn_guard_trigger_source(verified_plan)
    if trigger_source:
        base["applicable"] = True
        base["trigger_source"] = trigger_source
        return base
    base["skipped_reason"] = "no_analysis_loop_marker"
    return base


def is_analysis_turn_guard_applicable(
    verified_plan: Dict[str, Any],
    *,
    output_cfg: Dict[str, Any] | None = None,
    has_tool_usage: bool = False,
    is_fact_query: bool = False,
) -> bool:
    return bool(
        inspect_analysis_turn_guard_applicability(
            verified_plan,
            output_cfg=output_cfg,
            has_tool_usage=has_tool_usage,
            is_fact_query=is_fact_query,
        ).get("applicable")
    )


def evaluate_analysis_turn_answer(
    answer: str,
    *,
    verified_plan: Dict[str, Any],
    output_cfg: Dict[str, Any] | None = None,
    user_text: str = "",
    memory_data_present: bool = False,
    evidence_text: str = "",
    has_tool_usage: bool = False,
    is_fact_query: bool = False,
) -> Dict[str, Any]:
    applicability = inspect_analysis_turn_guard_applicability(
        verified_plan,
        output_cfg=output_cfg,
        has_tool_usage=has_tool_usage,
        is_fact_query=is_fact_query,
    )
    if not applicability.get("applicable"):
        return {
            "applicable": False,
            "trigger_source": "",
            "skipped_reason": str(applicability.get("skipped_reason") or ""),
            "violated": False,
            "reasons": [],
            "matches": [],
            "checked_chars": len(str(answer or "")),
            "checked_text_excerpt": _clip(answer, limit=140),
        }

    cfg = _build_guard_config(output_cfg or {})
    answer_norm = _normalize(answer)
    support_norm = _normalize(" ".join(part for part in (user_text, evidence_text) if str(part or "").strip()))

    reasons: List[str] = []
    matches: List[str] = []

    if cfg["forbid_memory"] and not memory_data_present and _matches_any(answer_norm, _MEMORY_PATTERNS):
        reasons.append("unsupported_memory_claim")
        matches.append("gedaechtnis/memory")

    if cfg["forbid_runtime"]:
        for label, patterns in _RUNTIME_PATTERNS:
            if _matches_any(answer_norm, patterns) and not _matches_any(support_norm, patterns):
                reasons.append(label)
                matches.append(label)

    if cfg["forbid_completion"] and not has_tool_usage and _matches_any(answer_norm, _COMPLETION_PATTERNS):
        reasons.append("fabricated_completion_claim")
        matches.append("completion_status")

    unique_reasons = list(dict.fromkeys(reasons))
    unique_matches = list(dict.fromkeys(matches))
    return {
        "applicable": True,
        "trigger_source": str(applicability.get("trigger_source") or ""),
        "skipped_reason": "",
        "violated": bool(unique_reasons),
        "reasons": unique_reasons,
        "matches": unique_matches,
        "checked_chars": len(str(answer or "")),
        "checked_text_excerpt": _clip(answer, limit=140),
    }


def build_analysis_turn_safe_fallback(
    verified_plan: Dict[str, Any],
    *,
    user_text: str = "",
    reasons: List[str] | None = None,
) -> str:
    focus = _clip(
        user_text
        or str(verified_plan.get("intent") or "").strip()
        or "konzeptionelle Analyse",
        limit=180,
    )
    reason_list = list(reasons or [])

    blocked_topics: List[str] = []
    if any(reason == "unsupported_memory_claim" for reason in reason_list):
        blocked_topics.append("Gedaechtnis-/Memory-Aussagen")
    if any(reason.startswith("runtime_") for reason in reason_list):
        blocked_topics.append("Runtime-/Systemaussagen")
    if "fabricated_completion_claim" in reason_list:
        blocked_topics.append("erfundene Abschluss-/Statusmeldungen")

    lines = [
        "Sicherer Zwischenstand:",
        f"- Fokus: {focus}",
        "- Gesichert: Das ist aktuell eine konzeptionelle Analyse-/Planungsantwort ohne ausgefuehrte Tools oder Runtime-Checks.",
    ]
    if blocked_topics:
        lines.append(
            "- Nicht verifiziert: "
            + ", ".join(blocked_topics)
            + "."
        )
    else:
        lines.append("- Nicht verifiziert: Keine zusaetzlichen Runtime- oder Memory-Fakten.")
    lines.append(
        "- Naechster sinnvoller Schritt: Entweder rein konzeptionell weiterplanen oder fuer echte Befunde gezielt Tools/Checks ausfuehren."
    )
    return "\n".join(lines)
