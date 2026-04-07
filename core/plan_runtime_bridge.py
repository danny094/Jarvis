"""Bridge helpers for contract-based runtime state (ExecutionResult)."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping, Optional

from core.control_contract import control_decision_from_plan


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


def get_runtime_tool_results(plan: Optional[Mapping[str, Any]]) -> str:
    raw = _execution_result(plan)
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    value = metadata.get("tool_results")
    if isinstance(value, str) and value.strip():
        return value
    return ""


def set_runtime_tool_results(
    plan: Optional[MutableMapping[str, Any]],
    value: Any,
) -> None:
    if not isinstance(plan, dict):
        return
    result = _ensure_execution_result(plan)
    result["metadata"]["tool_results"] = str(value or "")


def append_runtime_tool_results(
    plan: Optional[MutableMapping[str, Any]],
    extra: Any,
) -> None:
    base = get_runtime_tool_results(plan)
    merged = f"{base}{str(extra or '')}"
    set_runtime_tool_results(plan, merged)


def get_runtime_grounding_evidence(plan: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    raw = _execution_result(plan)
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    value = metadata.get("grounding_evidence")
    if isinstance(value, list):
        return list(value)
    return []


def get_runtime_carryover_grounding_evidence(plan: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    raw = _execution_result(plan)
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    value = metadata.get("carryover_grounding_evidence")
    if isinstance(value, list):
        return list(value)
    return []


def set_runtime_carryover_grounding_evidence(
    plan: Optional[MutableMapping[str, Any]],
    evidence: Any,
) -> None:
    if not isinstance(plan, dict):
        return
    normalized = list(evidence) if isinstance(evidence, list) else []
    result = _ensure_execution_result(plan)
    result["metadata"]["carryover_grounding_evidence"] = normalized


def set_runtime_grounding_evidence(
    plan: Optional[MutableMapping[str, Any]],
    evidence: Any,
) -> None:
    if not isinstance(plan, dict):
        return
    normalized = list(evidence) if isinstance(evidence, list) else []
    result = _ensure_execution_result(plan)
    result["metadata"]["grounding_evidence"] = normalized


def get_runtime_successful_tool_runs(plan: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    raw = _execution_result(plan)
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    value = metadata.get("successful_tool_runs")
    if isinstance(value, list):
        return list(value)
    return []


def set_runtime_successful_tool_runs(
    plan: Optional[MutableMapping[str, Any]],
    runs: Any,
) -> None:
    if not isinstance(plan, dict):
        return
    normalized = list(runs) if isinstance(runs, list) else []
    result = _ensure_execution_result(plan)
    result["metadata"]["successful_tool_runs"] = normalized


def get_runtime_direct_response(plan: Optional[Mapping[str, Any]]) -> str:
    raw = _execution_result(plan)
    return str(raw.get("direct_response") or "").strip()


def set_runtime_direct_response(
    plan: Optional[MutableMapping[str, Any]],
    value: Any,
) -> None:
    if not isinstance(plan, dict):
        return
    text = str(value or "").strip()
    result = _ensure_execution_result(plan)
    result["direct_response"] = text


def get_runtime_tool_failure(plan: Optional[Mapping[str, Any]]) -> bool:
    raw = _execution_result(plan)
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    return bool(metadata.get("tool_failure"))


def set_runtime_tool_failure(
    plan: Optional[MutableMapping[str, Any]],
    value: Any,
) -> None:
    if not isinstance(plan, dict):
        return
    result = _ensure_execution_result(plan)
    result["metadata"]["tool_failure"] = bool(value)


def get_runtime_tool_confidence(plan: Optional[Mapping[str, Any]]) -> str:
    raw = _execution_result(plan)
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    return str(metadata.get("tool_confidence") or "").strip()


def set_runtime_tool_confidence(
    plan: Optional[MutableMapping[str, Any]],
    value: Any,
) -> None:
    if not isinstance(plan, dict):
        return
    text = str(value or "").strip()
    result = _ensure_execution_result(plan)
    result["metadata"]["tool_confidence"] = text


def get_runtime_grounding_value(
    plan: Optional[Mapping[str, Any]],
    *,
    key: str,
    default: Any,
) -> Any:
    raw = _execution_result(plan)
    grounding = raw.get("grounding") if isinstance(raw.get("grounding"), dict) else {}
    return grounding.get(key, default)


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
