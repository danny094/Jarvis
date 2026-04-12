from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Dict, List, Optional


class TaskLoopState(str, Enum):
    PLANNING = "planning"
    ANSWERING = "answering"
    EXECUTING = "executing"
    REFLECTING = "reflecting"
    WAITING_FOR_USER = "waiting_for_user"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class StopReason(str, Enum):
    MAX_STEPS_REACHED = "max_steps_reached"
    MAX_ERRORS_REACHED = "max_errors_reached"
    MAX_RUNTIME_REACHED = "max_runtime_reached"
    LOOP_DETECTED = "loop_detected"
    REPEATED_IDENTICAL_STEP = "repeated_identical_step"
    NO_PROGRESS = "no_progress"
    RISK_GATE_REQUIRED = "risk_gate_required"
    UNCLEAR_USER_INTENT = "unclear_user_intent"
    TOOL_ERROR_NO_RECOVERY = "tool_error_no_recovery"
    INTERACTIVE_PROMPT = "interactive_prompt"
    OPEN_GUI_OR_SHELL_STATE = "open_gui_or_shell_state"
    NO_CONCRETE_NEXT_STEP = "no_concrete_next_step"
    USER_DECISION_REQUIRED = "user_decision_required"
    USER_CANCELLED = "user_cancelled"


class RiskLevel(str, Enum):
    SAFE = "safe"
    NEEDS_CONFIRMATION = "needs_confirmation"
    RISKY = "risky"
    BLOCKED = "blocked"


class TaskLoopTransitionError(ValueError):
    """Raised when a task loop state transition violates the contract."""


TERMINAL_STATES = {TaskLoopState.COMPLETED, TaskLoopState.CANCELLED}

ALLOWED_TRANSITIONS = {
    TaskLoopState.PLANNING: {
        TaskLoopState.ANSWERING,
        TaskLoopState.EXECUTING,
        TaskLoopState.WAITING_FOR_USER,
        TaskLoopState.BLOCKED,
        TaskLoopState.CANCELLED,
    },
    TaskLoopState.ANSWERING: {
        TaskLoopState.REFLECTING,
        TaskLoopState.WAITING_FOR_USER,
        TaskLoopState.BLOCKED,
        TaskLoopState.COMPLETED,
        TaskLoopState.CANCELLED,
    },
    TaskLoopState.EXECUTING: {
        TaskLoopState.REFLECTING,
        TaskLoopState.WAITING_FOR_USER,
        TaskLoopState.BLOCKED,
        TaskLoopState.COMPLETED,
        TaskLoopState.CANCELLED,
    },
    TaskLoopState.REFLECTING: {
        TaskLoopState.PLANNING,
        TaskLoopState.ANSWERING,
        TaskLoopState.EXECUTING,
        TaskLoopState.WAITING_FOR_USER,
        TaskLoopState.BLOCKED,
        TaskLoopState.COMPLETED,
        TaskLoopState.CANCELLED,
    },
    TaskLoopState.WAITING_FOR_USER: {
        TaskLoopState.PLANNING,
        TaskLoopState.ANSWERING,
        TaskLoopState.EXECUTING,
        TaskLoopState.CANCELLED,
    },
    TaskLoopState.BLOCKED: {
        TaskLoopState.PLANNING,
        TaskLoopState.WAITING_FOR_USER,
        TaskLoopState.CANCELLED,
    },
    TaskLoopState.COMPLETED: set(),
    TaskLoopState.CANCELLED: set(),
}

STOPPED_STATES = {
    TaskLoopState.WAITING_FOR_USER,
    TaskLoopState.BLOCKED,
    TaskLoopState.COMPLETED,
    TaskLoopState.CANCELLED,
}


@dataclass(frozen=True)
class TaskLoopSnapshot:
    objective_id: str
    conversation_id: str
    plan_id: str
    state: TaskLoopState = TaskLoopState.PLANNING
    step_index: int = 0
    current_plan: List[str] = field(default_factory=list)
    plan_steps: List[Dict[str, Any]] = field(default_factory=list)
    completed_steps: List[str] = field(default_factory=list)
    pending_step: str = ""
    last_user_visible_answer: str = ""
    stop_reason: Optional[StopReason] = None
    risk_level: RiskLevel = RiskLevel.SAFE
    tool_trace: List[Dict[str, Any]] = field(default_factory=list)
    workspace_event_ids: List[str] = field(default_factory=list)
    error_count: int = 0
    no_progress_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "conversation_id": self.conversation_id,
            "plan_id": self.plan_id,
            "step_index": self.step_index,
            "state": self.state.value,
            "current_plan": list(self.current_plan),
            "plan_steps": list(self.plan_steps),
            "completed_steps": list(self.completed_steps),
            "pending_step": self.pending_step,
            "last_user_visible_answer": self.last_user_visible_answer,
            "stop_reason": self.stop_reason.value if self.stop_reason else None,
            "risk_level": self.risk_level.value,
            "tool_trace": list(self.tool_trace),
            "workspace_event_ids": list(self.workspace_event_ids),
            "error_count": int(self.error_count),
            "no_progress_count": int(self.no_progress_count),
        }


def transition_task_loop(
    snapshot: TaskLoopSnapshot,
    next_state: TaskLoopState,
    *,
    stop_reason: Optional[StopReason] = None,
    step_index: Optional[int] = None,
    pending_step: Optional[str] = None,
    last_user_visible_answer: Optional[str] = None,
    risk_level: Optional[RiskLevel] = None,
) -> TaskLoopSnapshot:
    if snapshot.state in TERMINAL_STATES:
        raise TaskLoopTransitionError(f"terminal state cannot transition: {snapshot.state.value}")

    allowed = ALLOWED_TRANSITIONS.get(snapshot.state, set())
    if next_state not in allowed:
        raise TaskLoopTransitionError(
            f"invalid task loop transition: {snapshot.state.value}->{next_state.value}"
        )

    if next_state in STOPPED_STATES and next_state != TaskLoopState.COMPLETED and stop_reason is None:
        raise TaskLoopTransitionError(f"{next_state.value} requires stop_reason")

    if next_state == TaskLoopState.CANCELLED and stop_reason is None:
        stop_reason = StopReason.USER_CANCELLED

    if next_state == TaskLoopState.COMPLETED and stop_reason is not None:
        raise TaskLoopTransitionError("completed state must not carry stop_reason")

    return replace(
        snapshot,
        state=next_state,
        stop_reason=stop_reason,
        step_index=snapshot.step_index if step_index is None else int(step_index),
        pending_step=snapshot.pending_step if pending_step is None else str(pending_step),
        last_user_visible_answer=(
            snapshot.last_user_visible_answer
            if last_user_visible_answer is None
            else str(last_user_visible_answer)
        ),
        risk_level=snapshot.risk_level if risk_level is None else risk_level,
    )
