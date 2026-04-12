from core.task_loop.contracts import StopReason, TaskLoopSnapshot, TaskLoopState
from core.task_loop.events import (
    TASK_LOOP_EVENT_TYPES,
    TaskLoopEventType,
    build_task_loop_workspace_summary,
    make_task_loop_event,
    persist_task_loop_workspace_event,
)


def test_task_loop_event_names_match_contract():
    assert {
        "task_loop_started",
        "task_loop_plan_updated",
        "task_loop_step_started",
        "task_loop_step_answered",
        "task_loop_step_completed",
        "task_loop_reflection",
        "task_loop_waiting_for_user",
        "task_loop_blocked",
        "task_loop_completed",
        "task_loop_cancelled",
    } == TASK_LOOP_EVENT_TYPES


def test_make_task_loop_event_includes_task_loop_source_layer():
    snapshot = TaskLoopSnapshot(
        objective_id="obj-1",
        conversation_id="conv-1",
        plan_id="plan-1",
        state=TaskLoopState.EXECUTING,
        step_index=1,
        pending_step="Do first safe chat step",
    )

    event = make_task_loop_event(TaskLoopEventType.STEP_STARTED, snapshot)

    assert event["type"] == "task_loop_step_started"
    assert event["source_layer"] == "task_loop"
    assert event["objective_id"] == "obj-1"
    assert event["event_data"]["pending_step"] == "Do first safe chat step"


def test_build_task_loop_workspace_summary_includes_stop_reason():
    snapshot = TaskLoopSnapshot(
        objective_id="obj-1",
        conversation_id="conv-1",
        plan_id="plan-1",
        state=TaskLoopState.BLOCKED,
        step_index=2,
        pending_step="Write file",
        stop_reason=StopReason.RISK_GATE_REQUIRED,
    )
    event = make_task_loop_event(TaskLoopEventType.BLOCKED, snapshot)

    entry_type, content = build_task_loop_workspace_summary(event)

    assert entry_type == "task_loop_blocked"
    assert "objective_id=obj-1" in content
    assert "state=blocked" in content
    assert "stop_reason=risk_gate_required" in content


def test_persist_task_loop_workspace_event_delegates_with_task_loop_layer():
    calls = []

    def save_workspace_entry(**kwargs):
        calls.append(kwargs)
        return {"type": "workspace_update", "entry_id": "evt-1"}

    snapshot = TaskLoopSnapshot(
        objective_id="obj-1",
        conversation_id="conv-1",
        plan_id="plan-1",
        pending_step="Plan",
    )
    event = make_task_loop_event(TaskLoopEventType.STARTED, snapshot)

    out = persist_task_loop_workspace_event(save_workspace_entry, "conv-1", event)

    assert out == {"type": "workspace_update", "entry_id": "evt-1"}
    assert calls == [
        {
            "conversation_id": "conv-1",
            "content": (
                "objective_id=obj-1 | plan_id=plan-1 | state=planning | "
                "step=0 | pending=Plan"
            ),
            "entry_type": "task_loop_started",
            "source_layer": "task_loop",
        }
    ]


def test_persist_task_loop_workspace_event_ignores_unknown_events():
    out = persist_task_loop_workspace_event(lambda **_kwargs: {"bad": True}, "conv-1", {"type": "x"})

    assert out is None
