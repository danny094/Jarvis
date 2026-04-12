from datetime import datetime, timedelta, timezone

import pytest

from core.task_loop.contracts import RiskLevel, TaskLoopSnapshot, TaskLoopState
from core.task_loop.guards import detect_loop, evaluate_stop_conditions, fingerprint_action


def test_fingerprint_action_is_stable_for_dict_key_order():
    assert fingerprint_action({"tool": "a", "args": {"b": 1, "a": 2}}) == fingerprint_action(
        {"args": {"a": 2, "b": 1}, "tool": "a"}
    )


def test_detect_loop_requires_repeated_tail():
    assert detect_loop(
        [
            {"tool": "read", "args": {"path": "a"}},
            {"tool": "read", "args": {"path": "a"}},
        ]
    )
    assert not detect_loop(
        [
            {"tool": "read", "args": {"path": "a"}},
            {"tool": "read", "args": {"path": "b"}},
        ]
    )


def test_detect_loop_rejects_invalid_threshold():
    with pytest.raises(ValueError):
        detect_loop([], repeated_threshold=1)


def test_evaluate_stop_conditions_stops_at_max_steps():
    snapshot = TaskLoopSnapshot(
        objective_id="obj-1",
        conversation_id="conv-1",
        plan_id="plan-1",
        state=TaskLoopState.EXECUTING,
        step_index=2,
        pending_step="Run next safe step",
    )

    decision = evaluate_stop_conditions(snapshot, max_steps=2)

    assert decision.should_stop is True
    assert decision.reason.value == "max_steps_reached"


def test_evaluate_stop_conditions_stops_on_runtime_limit():
    now = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
    snapshot = TaskLoopSnapshot(
        objective_id="obj-1",
        conversation_id="conv-1",
        plan_id="plan-1",
        state=TaskLoopState.EXECUTING,
        pending_step="Run next safe step",
    )

    decision = evaluate_stop_conditions(
        snapshot,
        max_steps=3,
        max_runtime_s=10,
        started_at=now - timedelta(seconds=10),
        now=now,
    )

    assert decision.should_stop is True
    assert decision.reason.value == "max_runtime_reached"


def test_evaluate_stop_conditions_stops_on_risk_gate():
    snapshot = TaskLoopSnapshot(
        objective_id="obj-1",
        conversation_id="conv-1",
        plan_id="plan-1",
        risk_level=RiskLevel.NEEDS_CONFIRMATION,
        pending_step="Change files",
    )

    decision = evaluate_stop_conditions(snapshot, max_steps=3)

    assert decision.should_stop is True
    assert decision.reason.value == "risk_gate_required"


def test_evaluate_stop_conditions_stops_on_loop_trace():
    snapshot = TaskLoopSnapshot(
        objective_id="obj-1",
        conversation_id="conv-1",
        plan_id="plan-1",
        state=TaskLoopState.EXECUTING,
        pending_step="Read",
        tool_trace=[
            {"tool": "read", "args": {"path": "a"}},
            {"tool": "read", "args": {"path": "a"}},
        ],
    )

    decision = evaluate_stop_conditions(snapshot, max_steps=3)

    assert decision.should_stop is True
    assert decision.reason.value == "loop_detected"


def test_evaluate_stop_conditions_requires_concrete_next_step_while_planning():
    snapshot = TaskLoopSnapshot(
        objective_id="obj-1",
        conversation_id="conv-1",
        plan_id="plan-1",
        state=TaskLoopState.PLANNING,
    )

    decision = evaluate_stop_conditions(snapshot, max_steps=3)

    assert decision.should_stop is True
    assert decision.reason.value == "no_concrete_next_step"


def test_evaluate_stop_conditions_allows_safe_progress():
    snapshot = TaskLoopSnapshot(
        objective_id="obj-1",
        conversation_id="conv-1",
        plan_id="plan-1",
        state=TaskLoopState.EXECUTING,
        step_index=1,
        pending_step="Answer intermediate result",
    )

    decision = evaluate_stop_conditions(snapshot, max_steps=3)

    assert decision.should_stop is False
    assert decision.reason is None
