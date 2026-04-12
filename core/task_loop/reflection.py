from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from core.task_loop.contracts import RiskLevel, StopReason, TaskLoopSnapshot
from core.task_loop.guards import detect_loop


class ReflectionAction(str, Enum):
    CONTINUE = "continue"
    WAITING_FOR_USER = "waiting_for_user"
    BLOCKED = "blocked"
    COMPLETED = "completed"


@dataclass(frozen=True)
class ReflectionDecision:
    action: ReflectionAction
    reason: Optional[StopReason] = None
    detail: str = ""
    progress_made: bool = True


def reflect_after_chat_step(
    snapshot: TaskLoopSnapshot,
    *,
    max_steps: int = 4,
    max_errors: int = 4,
    max_no_progress: int = 2,
    repeated_action_threshold: int = 2,
) -> ReflectionDecision:
    if snapshot.error_count >= max_errors:
        return ReflectionDecision(
            ReflectionAction.BLOCKED,
            StopReason.MAX_ERRORS_REACHED,
            f"error_count={snapshot.error_count} max_errors={max_errors}",
            progress_made=False,
        )

    if snapshot.no_progress_count >= max_no_progress:
        return ReflectionDecision(
            ReflectionAction.BLOCKED,
            StopReason.NO_PROGRESS,
            f"no_progress_count={snapshot.no_progress_count} max_no_progress={max_no_progress}",
            progress_made=False,
        )

    if snapshot.tool_trace and detect_loop(
        snapshot.tool_trace,
        repeated_threshold=repeated_action_threshold,
    ):
        return ReflectionDecision(
            ReflectionAction.BLOCKED,
            StopReason.LOOP_DETECTED,
            f"repeated_action_threshold={repeated_action_threshold}",
            progress_made=False,
        )

    if snapshot.risk_level in {RiskLevel.NEEDS_CONFIRMATION, RiskLevel.RISKY}:
        return ReflectionDecision(
            ReflectionAction.WAITING_FOR_USER,
            StopReason.RISK_GATE_REQUIRED,
            snapshot.risk_level.value,
        )

    if snapshot.risk_level == RiskLevel.BLOCKED:
        return ReflectionDecision(
            ReflectionAction.BLOCKED,
            StopReason.NO_CONCRETE_NEXT_STEP,
            snapshot.risk_level.value,
            progress_made=False,
        )

    if not snapshot.pending_step.strip():
        return ReflectionDecision(ReflectionAction.COMPLETED, None, "plan_complete")

    if snapshot.step_index >= max_steps:
        return ReflectionDecision(
            ReflectionAction.WAITING_FOR_USER,
            StopReason.MAX_STEPS_REACHED,
            f"step_index={snapshot.step_index} max_steps={max_steps}",
        )

    return ReflectionDecision(
        ReflectionAction.CONTINUE,
        None,
        f"next_step={snapshot.pending_step[:120]}",
    )
