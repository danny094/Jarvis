import pytest

from core.task_loop.contracts import (
    RiskLevel,
    StopReason,
    TaskLoopSnapshot,
    TaskLoopState,
    TaskLoopTransitionError,
    transition_task_loop,
)


def test_task_loop_snapshot_serializes_stable_contract():
    snapshot = TaskLoopSnapshot(
        objective_id="obj-1",
        conversation_id="conv-1",
        plan_id="plan-1",
        current_plan=["Plan", "Execute"],
        pending_step="Plan",
    )

    out = snapshot.to_dict()

    assert out["objective_id"] == "obj-1"
    assert out["state"] == "planning"
    assert out["risk_level"] == "safe"
    assert out["stop_reason"] is None
    assert out["current_plan"] == ["Plan", "Execute"]


def test_stop_reason_includes_max_errors_contract():
    assert StopReason.MAX_ERRORS_REACHED.value == "max_errors_reached"


def test_transition_requires_stop_reason_for_blocked_state():
    snapshot = TaskLoopSnapshot(
        objective_id="obj-1",
        conversation_id="conv-1",
        plan_id="plan-1",
        pending_step="Plan",
    )

    with pytest.raises(TaskLoopTransitionError):
        transition_task_loop(snapshot, TaskLoopState.BLOCKED)


def test_transition_to_waiting_for_user_carries_stop_reason_and_risk():
    snapshot = TaskLoopSnapshot(
        objective_id="obj-1",
        conversation_id="conv-1",
        plan_id="plan-1",
        pending_step="Check risk",
    )

    next_snapshot = transition_task_loop(
        snapshot,
        TaskLoopState.WAITING_FOR_USER,
        stop_reason=StopReason.RISK_GATE_REQUIRED,
        risk_level=RiskLevel.NEEDS_CONFIRMATION,
    )

    assert next_snapshot.state is TaskLoopState.WAITING_FOR_USER
    assert next_snapshot.stop_reason is StopReason.RISK_GATE_REQUIRED
    assert next_snapshot.risk_level is RiskLevel.NEEDS_CONFIRMATION


def test_terminal_state_cannot_transition():
    snapshot = TaskLoopSnapshot(
        objective_id="obj-1",
        conversation_id="conv-1",
        plan_id="plan-1",
        state=TaskLoopState.COMPLETED,
    )

    with pytest.raises(TaskLoopTransitionError):
        transition_task_loop(snapshot, TaskLoopState.PLANNING)


def test_completed_state_must_not_carry_stop_reason():
    snapshot = TaskLoopSnapshot(
        objective_id="obj-1",
        conversation_id="conv-1",
        plan_id="plan-1",
        state=TaskLoopState.EXECUTING,
    )

    with pytest.raises(TaskLoopTransitionError):
        transition_task_loop(
            snapshot,
            TaskLoopState.COMPLETED,
            stop_reason=StopReason.MAX_STEPS_REACHED,
        )
