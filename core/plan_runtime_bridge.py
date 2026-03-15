"""Bridge helpers for migrating legacy verified_plan fields to contract-based runtime state."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping, MutableMapping, Optional

from core.control_contract import control_decision_from_plan

LEGACY_POLICY_KEYS = {
    "_final_instruction",
    "_warnings",
    "_verified",
    "_skipped",
}

LEGACY_RUNTIME_KEYS = {
    "_tool_results",
    "_grounding_evidence",
    "_carryover_grounding_evidence",
    "_successful_tool_runs",
    "_direct_response",
    "_tool_failure",
    "_tool_confidence",
    "_grounding_missing_evidence",
    "_grounding_violation_detected",
    "_grounded_fallback_used",
    "_grounding_repair_attempted",
    "_grounding_repair_used",
    "_grounding_successful_evidence",
    "_grounding_successful_evidence_status_only",
    "_grounding_evidence_total",
    "_grounding_hybrid_mode",
    "_grounding_block_reason",
    "_tool_execution_failed",
    "_grounding_qualitative_violation",
}


_LEGACY_GROUNDING_KEY_MAP = {
    "_grounding_missing_evidence": "missing_evidence",
    "_grounding_violation_detected": "violation_detected",
    "_grounded_fallback_used": "fallback_used",
    "_grounding_repair_attempted": "repair_attempted",
    "_grounding_repair_used": "repair_used",
    "_grounding_successful_evidence": "successful_evidence",
    "_grounding_successful_evidence_status_only": "successful_evidence_status_only",
    "_grounding_evidence_total": "evidence_total",
    "_grounding_hybrid_mode": "hybrid_mode",
    "_grounding_block_reason": "block_reason",
    "_tool_execution_failed": "tool_execution_failed",
    "_grounding_qualitative_violation": "qualitative_violation",
}


def legacy_runtime_compat_enabled() -> bool:
    raw = str(os.getenv("TRION_LEGACY_RUNTIME_COMPAT", "") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _use_dual_write(dual_write: Optional[bool]) -> bool:
    if dual_write is None:
        return legacy_runtime_compat_enabled()
    return bool(dual_write)


def _allow_legacy_read_fallback() -> bool:
    return legacy_runtime_compat_enabled()


def adopt_legacy_runtime_fields(
    plan: Optional[MutableMapping[str, Any]],
    *,
    remove_legacy: bool = True,
) -> None:
    """
    One-shot migration of legacy runtime keys into `_execution_result`.
    This is used to absorb old callers while keeping core flow logic contract-only.
    """
    if not isinstance(plan, dict):
        return
    result = _ensure_execution_result(plan)
    metadata = result.get("metadata", {})
    grounding = result.get("grounding", {})

    if "tool_results" not in metadata and "_tool_results" in plan:
        metadata["tool_results"] = str(plan.get("_tool_results") or "")
    if "grounding_evidence" not in metadata and isinstance(plan.get("_grounding_evidence"), list):
        metadata["grounding_evidence"] = list(plan.get("_grounding_evidence") or [])
    if "carryover_grounding_evidence" not in metadata and isinstance(plan.get("_carryover_grounding_evidence"), list):
        metadata["carryover_grounding_evidence"] = list(plan.get("_carryover_grounding_evidence") or [])
    if "successful_tool_runs" not in metadata and isinstance(plan.get("_successful_tool_runs"), list):
        metadata["successful_tool_runs"] = list(plan.get("_successful_tool_runs") or [])
    if "tool_failure" not in metadata and "_tool_failure" in plan:
        metadata["tool_failure"] = bool(plan.get("_tool_failure"))
    if "tool_confidence" not in metadata and "_tool_confidence" in plan:
        metadata["tool_confidence"] = str(plan.get("_tool_confidence") or "").strip()

    if not str(result.get("direct_response") or "").strip() and "_direct_response" in plan:
        result["direct_response"] = str(plan.get("_direct_response") or "").strip()

    for legacy_key, runtime_key in _LEGACY_GROUNDING_KEY_MAP.items():
        if runtime_key not in grounding and legacy_key in plan:
            grounding[runtime_key] = plan.get(legacy_key)

    result["metadata"] = metadata
    result["grounding"] = grounding

    if remove_legacy:
        for key in LEGACY_RUNTIME_KEYS:
            plan.pop(key, None)


def _ensure_execution_result(plan: Optional[MutableMapping[str, Any]]) -> Dict[str, Any]:
    if not isinstance(plan, dict):
        return {}
    raw = plan.get("_execution_result")
    if not isinstance(raw, dict):
        raw = {
            "done_reason": "stop",
            "tool_statuses": [],
            "grounding": {},
            "direct_response": "",
            "metadata": {},
        }
        plan["_execution_result"] = raw
    if not isinstance(raw.get("grounding"), dict):
        raw["grounding"] = {}
    if not isinstance(raw.get("metadata"), dict):
        raw["metadata"] = {}
    if not isinstance(raw.get("tool_statuses"), list):
        raw["tool_statuses"] = []
    return raw


def _execution_result(plan: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not isinstance(plan, dict):
        return {}
    raw = plan.get("_execution_result")
    return raw if isinstance(raw, dict) else {}


def _adopt_runtime_if_needed(plan: Optional[Mapping[str, Any]]) -> None:
    if isinstance(plan, dict):
        adopt_legacy_runtime_fields(plan, remove_legacy=False)


def get_runtime_tool_results(plan: Optional[Mapping[str, Any]]) -> str:
    _adopt_runtime_if_needed(plan)
    raw = _execution_result(plan)
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    value = metadata.get("tool_results")
    if isinstance(value, str) and value.strip():
        return value
    return str((plan or {}).get("_tool_results") or "")


def set_runtime_tool_results(
    plan: Optional[MutableMapping[str, Any]],
    value: Any,
    *,
    dual_write: Optional[bool] = None,
) -> None:
    if not isinstance(plan, dict):
        return
    result = _ensure_execution_result(plan)
    result["metadata"]["tool_results"] = str(value or "")
    if _use_dual_write(dual_write):
        plan["_tool_results"] = str(value or "")


def append_runtime_tool_results(
    plan: Optional[MutableMapping[str, Any]],
    extra: Any,
    *,
    dual_write: Optional[bool] = None,
) -> None:
    base = get_runtime_tool_results(plan)
    merged = f"{base}{str(extra or '')}"
    set_runtime_tool_results(plan, merged, dual_write=dual_write)


def get_runtime_grounding_evidence(plan: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    _adopt_runtime_if_needed(plan)
    raw = _execution_result(plan)
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    value = metadata.get("grounding_evidence")
    if isinstance(value, list):
        return list(value)
    if _allow_legacy_read_fallback():
        legacy = (plan or {}).get("_grounding_evidence")
        return list(legacy) if isinstance(legacy, list) else []
    return []


def get_runtime_carryover_grounding_evidence(plan: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    _adopt_runtime_if_needed(plan)
    raw = _execution_result(plan)
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    value = metadata.get("carryover_grounding_evidence")
    if isinstance(value, list):
        return list(value)
    if _allow_legacy_read_fallback():
        legacy = (plan or {}).get("_carryover_grounding_evidence")
        return list(legacy) if isinstance(legacy, list) else []
    return []


def set_runtime_carryover_grounding_evidence(
    plan: Optional[MutableMapping[str, Any]],
    evidence: Any,
    *,
    dual_write: Optional[bool] = None,
) -> None:
    if not isinstance(plan, dict):
        return
    normalized = list(evidence) if isinstance(evidence, list) else []
    result = _ensure_execution_result(plan)
    result["metadata"]["carryover_grounding_evidence"] = normalized
    if _use_dual_write(dual_write):
        plan["_carryover_grounding_evidence"] = normalized


def set_runtime_grounding_evidence(
    plan: Optional[MutableMapping[str, Any]],
    evidence: Any,
    *,
    dual_write: Optional[bool] = None,
) -> None:
    if not isinstance(plan, dict):
        return
    normalized = list(evidence) if isinstance(evidence, list) else []
    result = _ensure_execution_result(plan)
    result["metadata"]["grounding_evidence"] = normalized
    if _use_dual_write(dual_write):
        plan["_grounding_evidence"] = normalized


def get_runtime_successful_tool_runs(plan: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    _adopt_runtime_if_needed(plan)
    raw = _execution_result(plan)
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    value = metadata.get("successful_tool_runs")
    if isinstance(value, list):
        return list(value)
    if _allow_legacy_read_fallback():
        legacy = (plan or {}).get("_successful_tool_runs")
        return list(legacy) if isinstance(legacy, list) else []
    return []


def set_runtime_successful_tool_runs(
    plan: Optional[MutableMapping[str, Any]],
    runs: Any,
    *,
    dual_write: Optional[bool] = None,
) -> None:
    if not isinstance(plan, dict):
        return
    normalized = list(runs) if isinstance(runs, list) else []
    result = _ensure_execution_result(plan)
    result["metadata"]["successful_tool_runs"] = normalized
    if _use_dual_write(dual_write):
        plan["_successful_tool_runs"] = normalized


def get_runtime_direct_response(plan: Optional[Mapping[str, Any]]) -> str:
    _adopt_runtime_if_needed(plan)
    raw = _execution_result(plan)
    direct = str(raw.get("direct_response") or "").strip()
    if direct:
        return direct
    if _allow_legacy_read_fallback():
        return str((plan or {}).get("_direct_response") or "").strip()
    return ""


def set_runtime_direct_response(
    plan: Optional[MutableMapping[str, Any]],
    value: Any,
    *,
    dual_write: Optional[bool] = None,
) -> None:
    if not isinstance(plan, dict):
        return
    text = str(value or "").strip()
    result = _ensure_execution_result(plan)
    result["direct_response"] = text
    if _use_dual_write(dual_write):
        if text:
            plan["_direct_response"] = text
        else:
            plan.pop("_direct_response", None)


def get_runtime_tool_failure(plan: Optional[Mapping[str, Any]]) -> bool:
    _adopt_runtime_if_needed(plan)
    raw = _execution_result(plan)
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    if "tool_failure" in metadata:
        return bool(metadata.get("tool_failure"))
    if _allow_legacy_read_fallback():
        return bool((plan or {}).get("_tool_failure"))
    return False


def set_runtime_tool_failure(
    plan: Optional[MutableMapping[str, Any]],
    value: Any,
    *,
    dual_write: Optional[bool] = None,
) -> None:
    if not isinstance(plan, dict):
        return
    result = _ensure_execution_result(plan)
    result["metadata"]["tool_failure"] = bool(value)
    if _use_dual_write(dual_write):
        plan["_tool_failure"] = bool(value)


def get_runtime_tool_confidence(plan: Optional[Mapping[str, Any]]) -> str:
    _adopt_runtime_if_needed(plan)
    raw = _execution_result(plan)
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    value = str(metadata.get("tool_confidence") or "").strip()
    if value:
        return value
    if _allow_legacy_read_fallback():
        return str((plan or {}).get("_tool_confidence") or "").strip()
    return ""


def set_runtime_tool_confidence(
    plan: Optional[MutableMapping[str, Any]],
    value: Any,
    *,
    dual_write: Optional[bool] = None,
) -> None:
    if not isinstance(plan, dict):
        return
    text = str(value or "").strip()
    result = _ensure_execution_result(plan)
    result["metadata"]["tool_confidence"] = text
    if _use_dual_write(dual_write):
        if text:
            plan["_tool_confidence"] = text
        else:
            plan.pop("_tool_confidence", None)


def get_runtime_grounding_value(
    plan: Optional[Mapping[str, Any]],
    *,
    key: str,
    legacy_key: str,
    default: Any,
) -> Any:
    raw = _execution_result(plan)
    grounding = raw.get("grounding") if isinstance(raw.get("grounding"), dict) else {}
    if key in grounding:
        return grounding.get(key)
    if _allow_legacy_read_fallback():
        return (plan or {}).get(legacy_key, default)
    return default


def get_policy_final_instruction(plan: Optional[Mapping[str, Any]]) -> str:
    decision = control_decision_from_plan(plan, default_approved=False)
    text = str(decision.final_instruction or "").strip()
    if text:
        return text
    return str((plan or {}).get("_final_instruction") or "").strip()


def get_policy_warnings(plan: Optional[Mapping[str, Any]]) -> List[str]:
    decision = control_decision_from_plan(plan, default_approved=False)
    if decision.warnings:
        return [str(w) for w in decision.warnings if str(w).strip()]
    raw = (plan or {}).get("_warnings")
    if isinstance(raw, list):
        return [str(w) for w in raw if str(w).strip()]
    if raw:
        return [str(raw)]
    return []


def get_runtime_metadata(plan: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    raw = _execution_result(plan)
    metadata = raw.get("metadata")
    return dict(metadata) if isinstance(metadata, dict) else {}
