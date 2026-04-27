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


class TaskLoopStepType(str, Enum):
    ANALYSIS = "analysis_step"
    RESPONSE = "response_step"
    TOOL_REQUEST = "tool_request_step"
    TOOL_EXECUTION = "tool_execution_step"


class TaskLoopStepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    WAITING_FOR_USER = "waiting_for_user"
    BLOCKED = "blocked"
    FAILED = "failed"


class TaskLoopStepExecutionSource(str, Enum):
    LOOP = "loop"
    ORCHESTRATOR = "orchestrator"
    APPROVAL = "approval_wait"
    BLOCKED = "blocked"
    FALLBACK = "fallback"


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

ALLOWED_STEP_TYPE_TRANSITIONS = {
    TaskLoopStepType.ANALYSIS: {
        TaskLoopStepType.RESPONSE,
        TaskLoopStepType.TOOL_REQUEST,
        TaskLoopStepType.TOOL_EXECUTION,
    },
    TaskLoopStepType.RESPONSE: {
        TaskLoopStepType.ANALYSIS,
        TaskLoopStepType.TOOL_REQUEST,
    },
    TaskLoopStepType.TOOL_REQUEST: {
        TaskLoopStepType.TOOL_EXECUTION,
    },
    TaskLoopStepType.TOOL_EXECUTION: {
        TaskLoopStepType.ANALYSIS,
        TaskLoopStepType.RESPONSE,
    },
}

ALLOWED_STEP_STATUS_TRANSITIONS = {
    TaskLoopStepStatus.PENDING: {
        TaskLoopStepStatus.RUNNING,
    },
    TaskLoopStepStatus.RUNNING: {
        TaskLoopStepStatus.COMPLETED,
        TaskLoopStepStatus.WAITING_FOR_APPROVAL,
        TaskLoopStepStatus.WAITING_FOR_USER,
        TaskLoopStepStatus.BLOCKED,
        TaskLoopStepStatus.FAILED,
    },
    TaskLoopStepStatus.WAITING_FOR_APPROVAL: {
        TaskLoopStepStatus.RUNNING,
        TaskLoopStepStatus.BLOCKED,
        TaskLoopStepStatus.COMPLETED,
    },
    TaskLoopStepStatus.WAITING_FOR_USER: {
        TaskLoopStepStatus.RUNNING,
        TaskLoopStepStatus.BLOCKED,
        TaskLoopStepStatus.COMPLETED,
    },
    TaskLoopStepStatus.FAILED: {
        TaskLoopStepStatus.BLOCKED,
    },
    TaskLoopStepStatus.COMPLETED: set(),
    TaskLoopStepStatus.BLOCKED: set(),
}


@dataclass(frozen=True)
class TaskLoopStepRequest:
    turn_id: str
    loop_id: str
    step_id: str
    step_index: int
    step_type: TaskLoopStepType
    objective: str
    step_goal: str
    step_title: str
    artifacts_so_far: List[Dict[str, Any]] = field(default_factory=list)
    requested_capability: Dict[str, Any] = field(default_factory=dict)
    capability_context: Dict[str, Any] = field(default_factory=dict)
    suggested_tools: List[str] = field(default_factory=list)
    requires_control: bool = True
    requires_approval: bool = False
    risk_context: Dict[str, Any] = field(default_factory=dict)
    reasoning_context: Dict[str, Any] = field(default_factory=dict)
    user_visible_context: str = ""
    allowed_tool_scope: List[str] = field(default_factory=list)
    timeout_hint_s: Optional[float] = None
    origin: str = "task_loop"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "loop_id": self.loop_id,
            "step_id": self.step_id,
            "step_index": int(self.step_index),
            "step_type": self.step_type.value,
            "objective": self.objective,
            "step_goal": self.step_goal,
            "step_title": self.step_title,
            "artifacts_so_far": list(self.artifacts_so_far),
            "requested_capability": dict(self.requested_capability),
            "capability_context": dict(self.capability_context),
            "suggested_tools": list(self.suggested_tools),
            "requires_control": bool(self.requires_control),
            "requires_approval": bool(self.requires_approval),
            "risk_context": dict(self.risk_context),
            "reasoning_context": dict(self.reasoning_context),
            "user_visible_context": self.user_visible_context,
            "allowed_tool_scope": list(self.allowed_tool_scope),
            "timeout_hint_s": self.timeout_hint_s,
            "origin": self.origin,
        }


@dataclass(frozen=True)
class TaskLoopStepResult:
    turn_id: str
    loop_id: str
    step_id: str
    step_type: TaskLoopStepType
    status: TaskLoopStepStatus
    control_decision: Dict[str, Any] = field(default_factory=dict)
    execution_result: Dict[str, Any] = field(default_factory=dict)
    verified_artifacts: List[Dict[str, Any]] = field(default_factory=list)
    user_visible_summary: str = ""
    next_action: str = ""
    warnings: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    approval_request: Dict[str, Any] = field(default_factory=dict)
    trace_reason: str = ""
    step_execution_source: TaskLoopStepExecutionSource = TaskLoopStepExecutionSource.LOOP

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "loop_id": self.loop_id,
            "step_id": self.step_id,
            "step_type": self.step_type.value,
            "status": self.status.value,
            "control_decision": dict(self.control_decision),
            "execution_result": dict(self.execution_result),
            "verified_artifacts": list(self.verified_artifacts),
            "user_visible_summary": self.user_visible_summary,
            "next_action": self.next_action,
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "approval_request": dict(self.approval_request),
            "trace_reason": self.trace_reason,
            "step_execution_source": self.step_execution_source.value,
        }


@dataclass(frozen=True)
class TaskLoopSnapshot:
    objective_id: str
    conversation_id: str
    plan_id: str
    state: TaskLoopState = TaskLoopState.PLANNING
    step_index: int = 0
    current_step_id: str = ""
    current_step_type: TaskLoopStepType = TaskLoopStepType.ANALYSIS
    current_step_status: TaskLoopStepStatus = TaskLoopStepStatus.PENDING
    step_execution_source: TaskLoopStepExecutionSource = TaskLoopStepExecutionSource.LOOP
    current_plan: List[str] = field(default_factory=list)
    plan_steps: List[Dict[str, Any]] = field(default_factory=list)
    completed_steps: List[str] = field(default_factory=list)
    pending_step: str = ""
    last_user_visible_answer: str = ""
    stop_reason: Optional[StopReason] = None
    risk_level: RiskLevel = RiskLevel.SAFE
    tool_trace: List[Dict[str, Any]] = field(default_factory=list)
    verified_artifacts: List[Dict[str, Any]] = field(default_factory=list)
    last_step_result: Dict[str, Any] = field(default_factory=dict)
    workspace_event_ids: List[str] = field(default_factory=list)
    error_count: int = 0
    no_progress_count: int = 0
    objective_summary: str = ""
    system_state: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "conversation_id": self.conversation_id,
            "plan_id": self.plan_id,
            "step_index": self.step_index,
            "state": self.state.value,
            "current_step_id": self.current_step_id,
            "current_step_type": self.current_step_type.value,
            "current_step_status": self.current_step_status.value,
            "step_execution_source": self.step_execution_source.value,
            "current_plan": list(self.current_plan),
            "plan_steps": list(self.plan_steps),
            "completed_steps": list(self.completed_steps),
            "pending_step": self.pending_step,
            "last_user_visible_answer": self.last_user_visible_answer,
            "stop_reason": self.stop_reason.value if self.stop_reason else None,
            "risk_level": self.risk_level.value,
            "tool_trace": list(self.tool_trace),
            "verified_artifacts": list(self.verified_artifacts),
            "last_step_result": dict(self.last_step_result),
            "workspace_event_ids": list(self.workspace_event_ids),
            "error_count": int(self.error_count),
            "no_progress_count": int(self.no_progress_count),
            "objective_summary": self.objective_summary,
            "system_state": dict(self.system_state),
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


def transition_task_loop_step(
    snapshot: TaskLoopSnapshot,
    *,
    next_step_id: Optional[str] = None,
    next_step_type: Optional[TaskLoopStepType] = None,
    next_step_status: Optional[TaskLoopStepStatus] = None,
    step_execution_source: Optional[TaskLoopStepExecutionSource] = None,
    verified_artifacts: Optional[List[Dict[str, Any]]] = None,
    last_step_result: Optional[Dict[str, Any]] = None,
    reset_for_new_step: bool = False,
) -> TaskLoopSnapshot:
    current_step_id = str(snapshot.current_step_id or "")
    target_step_id = current_step_id if next_step_id is None else str(next_step_id or "")
    current_type = snapshot.current_step_type
    target_type = snapshot.current_step_type if next_step_type is None else next_step_type
    current_status = snapshot.current_step_status
    target_status = snapshot.current_step_status if next_step_status is None else next_step_status

    if reset_for_new_step:
        if not target_step_id:
            raise TaskLoopTransitionError("new step requires step_id")
        if target_status not in {TaskLoopStepStatus.PENDING, TaskLoopStepStatus.RUNNING}:
            raise TaskLoopTransitionError("new step must start as pending or running")
        return replace(
            snapshot,
            current_step_id=target_step_id,
            current_step_type=target_type,
            current_step_status=target_status,
            step_execution_source=(
                snapshot.step_execution_source
                if step_execution_source is None
                else step_execution_source
            ),
            verified_artifacts=(
                list(snapshot.verified_artifacts)
                if verified_artifacts is None
                else list(verified_artifacts)
            ),
            last_step_result=(
                dict(snapshot.last_step_result)
                if last_step_result is None
                else dict(last_step_result)
            ),
        )

    if target_type != current_type:
        allowed_types = ALLOWED_STEP_TYPE_TRANSITIONS.get(current_type, set())
        if target_type not in allowed_types:
            raise TaskLoopTransitionError(
                f"invalid task loop step type transition: {current_type.value}->{target_type.value}"
            )

    if target_status != current_status:
        allowed_statuses = ALLOWED_STEP_STATUS_TRANSITIONS.get(current_status, set())
        if target_status not in allowed_statuses:
            raise TaskLoopTransitionError(
                f"invalid task loop step status transition: {current_status.value}->{target_status.value}"
            )

    return replace(
        snapshot,
        current_step_id=target_step_id,
        current_step_type=target_type,
        current_step_status=target_status,
        step_execution_source=(
            snapshot.step_execution_source
            if step_execution_source is None
            else step_execution_source
        ),
        verified_artifacts=(
            list(snapshot.verified_artifacts)
            if verified_artifacts is None
            else list(verified_artifacts)
        ),
        last_step_result=(
            dict(snapshot.last_step_result)
            if last_step_result is None
            else dict(last_step_result)
        ),
    )
