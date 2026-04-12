from core.task_loop.chat_runtime import (
    build_initial_chat_plan,
    continue_chat_task_loop,
    is_task_loop_candidate,
    maybe_handle_chat_task_loop_turn,
    should_restart_task_loop,
    start_chat_task_loop,
)
from core.task_loop.store import TaskLoopStore


def test_task_loop_candidate_is_explicit_only():
    assert is_task_loop_candidate("Task-Loop: Bitte mach das schrittweise")
    assert is_task_loop_candidate("Bitte im Multistep Modus einen Plan machen")
    assert is_task_loop_candidate("kurze frage", {"task_loop": True})
    assert not is_task_loop_candidate(
        "Bitte schrittweise einen Plan machen: Pruefe den neuen Multistep Loop"
    )
    assert not is_task_loop_candidate("Bitte mach das schrittweise")
    assert not is_task_loop_candidate("was ist 2+2?")


def test_build_initial_chat_plan_strips_task_loop_marker_from_objective():
    plan = build_initial_chat_plan(
        "Bitte schrittweise einen Plan machen: Pruefe kurz den neuen Loop"
    )

    assert plan[0] == "Pruefziel festlegen: Pruefe kurz den neuen Loop"


def test_should_restart_task_loop_requires_explicit_new_loop_prompt():
    assert should_restart_task_loop("Task-Loop: Bitte neu starten")
    assert not should_restart_task_loop("weiter")
    assert not should_restart_task_loop("stoppen")


def test_start_chat_task_loop_auto_continues_safe_steps_and_completes():
    store = TaskLoopStore()
    calls = []

    def save_workspace_entry(**kwargs):
        calls.append(kwargs)
        return {"entry_id": f"evt-{len(calls)}"}

    result = start_chat_task_loop(
        "Bitte im Multistep Modus einen Plan machen",
        "conv-loop",
        store=store,
        save_workspace_entry_fn=save_workspace_entry,
    )

    assert result.done_reason == "task_loop_completed"
    assert result.snapshot.state.value == "completed"
    assert result.snapshot.step_index == 4
    assert len(result.snapshot.workspace_event_ids) == len(calls)
    entry_types = [call["entry_type"] for call in calls]
    assert entry_types[:2] == ["task_loop_started", "task_loop_plan_updated"]
    assert entry_types.count("task_loop_step_started") == 4
    assert entry_types.count("task_loop_step_answered") == 4
    assert entry_types.count("task_loop_step_completed") == 4
    assert entry_types.count("task_loop_reflection") == 4
    assert entry_types[-1] == "task_loop_completed"
    assert all(call["source_layer"] == "task_loop" for call in calls)


def test_continue_chat_task_loop_completes_second_safe_step():
    store = TaskLoopStore()
    first = start_chat_task_loop(
        "Bitte schrittweise arbeiten",
        "conv-loop",
        store=store,
        auto_continue=False,
    )

    second = continue_chat_task_loop(first.snapshot, "weiter", store=store)
    third = continue_chat_task_loop(second.snapshot, "weiter", store=store)
    result = continue_chat_task_loop(third.snapshot, "weiter", store=store)

    assert result.done_reason == "task_loop_completed"
    assert result.snapshot.state.value == "completed"
    assert result.snapshot.step_index == 4
    assert len(result.snapshot.completed_steps) == 4
    assert "Task-Loop abgeschlossen" in result.content


def test_continue_chat_task_loop_can_cancel_waiting_loop():
    store = TaskLoopStore()
    first = start_chat_task_loop(
        "Bitte step by step arbeiten",
        "conv-loop",
        store=store,
        auto_continue=False,
    )

    result = continue_chat_task_loop(first.snapshot, "stoppen", store=store)

    assert result.done_reason == "task_loop_cancelled"
    assert result.snapshot.state.value == "cancelled"


def test_explicit_task_loop_prompt_restarts_waiting_loop_instead_of_repeating_wait_state():
    store = TaskLoopStore()
    waiting = start_chat_task_loop(
        "Task-Loop: Bitte schrittweise arbeiten",
        "conv-loop",
        store=store,
        auto_continue=False,
    )

    result = maybe_handle_chat_task_loop_turn(
        "Task-Loop: Pruefe kurz den neuen Multistep Loop und zeige mir sichere Zwischenstaende",
        "conv-loop",
        store=store,
        thinking_plan={
            "intent": "Multistep Loop pruefen",
            "hallucination_risk": "low",
            "suggested_tools": [],
        },
    )

    assert waiting.done_reason == "task_loop_waiting_for_user"
    assert result is not None
    assert result.done_reason == "task_loop_completed"
    assert result.snapshot.state.value == "completed"
    assert "Der Task-Loop wartet weiter." not in result.content


def test_maybe_handle_chat_task_loop_turn_ignores_normal_question():
    store = TaskLoopStore()

    assert (
        maybe_handle_chat_task_loop_turn(
            "was ist 2+2?",
            "conv-loop",
            store=store,
        )
        is None
    )
