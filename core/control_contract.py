"""Typed control/runtime contracts for single-authority policy flow."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional, Sequence, Tuple


def _normalize_tool_names(names: Iterable[Any]) -> Tuple[str, ...]:
    out = []
    seen = set()
    for raw in names or []:
        name = str(raw or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return tuple(out)


def _sanitize_corrections(raw: Any) -> Mapping[str, Any]:
    if not isinstance(raw, dict):
        return MappingProxyType({})
    cleaned: Dict[str, Any] = {}
    for key, value in raw.items():
        k = str(key or "").strip()
        if not k:
            continue
        cleaned[k] = value
    return MappingProxyType(cleaned)


@dataclass(frozen=True)
class ControlDecision:
    """Immutable policy decision produced by the Control layer."""

    approved: bool = False
    hard_block: bool = False
    decision_class: str = "hard_block"
    block_reason_code: str = "missing_control_decision"
    reason: str = "missing_control_decision"
    final_instruction: str = ""
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    corrections: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    tools_allowed: Tuple[str, ...] = field(default_factory=tuple)
    source: str = "control"
    policy_version: str = "2.0"

    def with_tools_allowed(self, tool_names: Iterable[Any]) -> "ControlDecision":
        return replace(self, tools_allowed=_normalize_tool_names(tool_names))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approved": bool(self.approved),
            "hard_block": bool(self.hard_block),
            "decision_class": str(self.decision_class or "").strip(),
            "block_reason_code": str(self.block_reason_code or "").strip(),
            "reason": str(self.reason or "").strip(),
            "final_instruction": str(self.final_instruction or "").strip(),
            "warnings": [str(w) for w in self.warnings],
            "corrections": dict(self.corrections),
            "tools_allowed": [str(t) for t in self.tools_allowed],
            "source": str(self.source or "control"),
            "policy_version": str(self.policy_version or "2.0"),
        }

    @classmethod
    def from_verification(
        cls,
        verification: Any,
        *,
        default_approved: bool = False,
        source: str = "control",
    ) -> "ControlDecision":
        if not isinstance(verification, dict):
            if default_approved:
                return cls(
                    approved=True,
                    hard_block=False,
                    decision_class="allow",
                    block_reason_code="",
                    reason="control_default_allow",
                    source=source,
                )
            return cls(source=source)

        # A5 Fix: respect default_approved when "approved" key is absent from verification.
        # Previously: None is not False == True, so empty dict always returned approved=True.
        if "approved" in verification:
            approved = verification["approved"] is not False
        else:
            approved = default_approved
        decision_class = str(verification.get("decision_class") or "").strip().lower()
        hard_block = bool(verification.get("hard_block"))
        block_reason_code = str(verification.get("block_reason_code") or "").strip().lower()
        reason = str(verification.get("reason") or "").strip()
        final_instruction = str(verification.get("final_instruction") or "").strip()

        warnings_raw = verification.get("warnings")
        if isinstance(warnings_raw, list):
            warnings = tuple(str(w) for w in warnings_raw if str(w).strip())
        elif warnings_raw:
            warnings = (str(warnings_raw),)
        else:
            warnings = tuple()

        corrections = _sanitize_corrections(verification.get("corrections"))

        tools_allowed_raw = verification.get("tools_allowed")
        tools_allowed = _normalize_tool_names(tools_allowed_raw if isinstance(tools_allowed_raw, list) else [])

        if approved:
            if not decision_class or decision_class == "hard_block":
                decision_class = "warn" if warnings else "allow"
            hard_block = False
            block_reason_code = ""
            if not reason:
                reason = "approved"
        else:
            if not decision_class:
                decision_class = "hard_block"
            if not block_reason_code:
                block_reason_code = "control_denied"
            if not reason:
                reason = block_reason_code
            hard_block = bool(hard_block or decision_class == "hard_block")

        return cls(
            approved=approved,
            hard_block=hard_block,
            decision_class=decision_class or ("allow" if approved else "hard_block"),
            block_reason_code=block_reason_code,
            reason=reason,
            final_instruction=final_instruction,
            warnings=warnings,
            corrections=corrections,
            tools_allowed=tools_allowed,
            source=source,
        )


class DoneReason(str, Enum):
    SUCCESS = "success"
    UNAVAILABLE = "unavailable"
    TECH_FAIL = "tech_fail"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"
    STOP = "stop"


@dataclass
class ExecutionResult:
    """Mutable runtime result that must not contain policy authority."""

    done_reason: DoneReason = DoneReason.STOP
    tool_statuses: list = field(default_factory=list)
    grounding: Dict[str, Any] = field(default_factory=dict)
    direct_response: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def append_tool_status(self, *, tool_name: str, status: str, reason: str = "") -> None:
        self.tool_statuses.append(
            {
                "tool_name": str(tool_name or "").strip(),
                "status": str(status or "").strip().lower(),
                "reason": str(reason or "").strip(),
            }
        )

    def finalize_done_reason(self) -> None:
        statuses = {
            str((row or {}).get("status") or "").strip().lower()
            for row in self.tool_statuses
            if isinstance(row, dict)
        }
        if "ok" in statuses:
            self.done_reason = DoneReason.SUCCESS
        elif "error" in statuses:
            self.done_reason = DoneReason.TECH_FAIL
        elif "unavailable" in statuses:
            self.done_reason = DoneReason.UNAVAILABLE
        elif "timeout" in statuses:
            self.done_reason = DoneReason.TIMEOUT
        elif statuses:
            self.done_reason = DoneReason.SKIPPED
        else:
            self.done_reason = DoneReason.STOP

    def to_dict(self) -> Dict[str, Any]:
        return {
            "done_reason": self.done_reason.value,
            "tool_statuses": list(self.tool_statuses),
            "grounding": dict(self.grounding),
            "direct_response": str(self.direct_response or ""),
            "metadata": dict(self.metadata),
        }


def execution_result_from_plan(plan: Optional[MutableMapping[str, Any]]) -> ExecutionResult:
    if not isinstance(plan, dict):
        return ExecutionResult()
    raw = plan.get("_execution_result")
    if not isinstance(raw, dict):
        return ExecutionResult()
    done_reason_raw = str(raw.get("done_reason") or DoneReason.STOP.value).strip().lower()
    try:
        done_reason = DoneReason(done_reason_raw)
    except Exception:
        done_reason = DoneReason.STOP
    tool_statuses = list(raw.get("tool_statuses") or []) if isinstance(raw.get("tool_statuses"), list) else []
    grounding = dict(raw.get("grounding") or {}) if isinstance(raw.get("grounding"), dict) else {}
    metadata = dict(raw.get("metadata") or {}) if isinstance(raw.get("metadata"), dict) else {}
    direct_response = str(raw.get("direct_response") or "")
    return ExecutionResult(
        done_reason=done_reason,
        tool_statuses=tool_statuses,
        grounding=grounding,
        direct_response=direct_response,
        metadata=metadata,
    )


def persist_execution_result(plan: Optional[MutableMapping[str, Any]], result: ExecutionResult) -> None:
    if not isinstance(plan, dict):
        return
    plan["_execution_result"] = result.to_dict()


def control_decision_from_plan(
    plan: Optional[Mapping[str, Any]],
    *,
    default_approved: bool = False,
) -> ControlDecision:
    if not isinstance(plan, dict):
        return ControlDecision.from_verification({}, default_approved=default_approved)
    value = plan.get("_control_decision")
    if isinstance(value, dict):
        cd = ControlDecision.from_verification(value, default_approved=default_approved)
    else:
        obj = plan.get("_control_decision_obj")
        if isinstance(obj, ControlDecision):
            cd = obj
        else:
            cd = ControlDecision.from_verification({}, default_approved=default_approved)

    # A1 Fix: enforce INV-01 — gate_blocked=True + approved=True is illegal.
    # Blueprint Gate runs pre-Control and signals that request_container cannot proceed
    # (no blueprint_id available). Control must not silently override this routing constraint.
    # We reconcile here at read-time so the illegal state never propagates downstream.
    if cd.approved and plan.get("_blueprint_gate_blocked"):
        suggested = list(plan.get("suggested_tools") or [])
        current_allowed = list(cd.tools_allowed) or suggested
        # Exclude request_container — gate block makes it unexecutable regardless.
        effective = [t for t in current_allowed if t != "request_container"]
        gate_reason = str(plan.get("_blueprint_gate_reason") or "blueprint_routing_required")
        if effective:
            # Other tools remain approved; only request_container is excluded.
            cd = cd.with_tools_allowed(effective)
        else:
            # request_container was the only tool (or no tools known) — downgrade to routing_block.
            cd = ControlDecision(
                approved=False,
                hard_block=False,
                decision_class="routing_block",
                block_reason_code="blueprint_routing_required",
                reason=f"Blueprint gate blocked request_container: {gate_reason}",
                source="control_gate_reconcile",
                policy_version=cd.policy_version,
            )

    return cd


def persist_control_decision(plan: Optional[MutableMapping[str, Any]], decision: ControlDecision) -> None:
    if not isinstance(plan, dict):
        return
    plan["_control_decision_obj"] = decision
    plan["_control_decision"] = decision.to_dict()


def tool_allowed_by_control_decision(
    decision: Optional[ControlDecision],
    tool_name: str,
) -> bool:
    if not isinstance(decision, ControlDecision):
        return True
    if not decision.approved:
        return False
    allowed = set(decision.tools_allowed or ())
    if not allowed:
        return True
    return str(tool_name or "").strip() in allowed
