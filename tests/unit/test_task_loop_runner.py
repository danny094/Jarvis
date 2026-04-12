import pytest

from core.task_loop.contracts import TaskLoopSnapshot
from core.task_loop.events import TaskLoopEventType, make_task_loop_event
from core.task_loop.planner import create_task_loop_snapshot_from_plan
from core.task_loop.runner import run_chat_auto_loop, stream_chat_auto_loop


def test_run_chat_auto_loop_completes_four_safe_steps():
    snapshot = TaskLoopSnapshot(
        objective_id="obj-1",
        conversation_id="conv-1",
        plan_id="plan-1",
        current_plan=["one", "two", "three", "four"],
        pending_step="one",
    )
    events = [make_task_loop_event(TaskLoopEventType.STARTED, snapshot)]

    result = run_chat_auto_loop(snapshot, initial_events=events, max_steps=4)

    assert result.done_reason == "task_loop_completed"
    assert result.snapshot.state.value == "completed"
    assert result.snapshot.step_index == 4
    assert result.content.count("Zwischenstand:") == 4
    assert [event["type"] for event in result.events].count("task_loop_reflection") == 4


def test_run_chat_auto_loop_stops_when_max_steps_reached_with_pending_step():
    snapshot = TaskLoopSnapshot(
        objective_id="obj-1",
        conversation_id="conv-1",
        plan_id="plan-1",
        current_plan=["one", "two", "three"],
        pending_step="one",
    )

    result = run_chat_auto_loop(snapshot, max_steps=2)

    assert result.done_reason == "task_loop_max_steps_reached"
    assert result.snapshot.state.value == "waiting_for_user"
    assert result.snapshot.stop_reason.value == "max_steps_reached"
    assert "Stopgrund: max_steps_reached" in result.content


def test_run_chat_auto_loop_uses_product_answers_for_validation_steps():
    snapshot = create_task_loop_snapshot_from_plan(
        "Bitte schrittweise arbeiten: Pruefe kurz den neuen Multistep Loop",
        "conv-1",
        thinking_plan={
            "intent": "unknown",
            "reasoning": "Fallback - Analyse fehlgeschlagen",
            "suggested_tools": [],
        },
    )

    result = run_chat_auto_loop(snapshot, max_steps=4)

    assert "Pruefziel: Pruefe kurz den neuen Multistep Loop" in result.content
    assert "Beobachtbare Kriterien:" in result.content
    assert "Befund: Der aktuelle Pfad bleibt sicher" in result.content
    assert "Ziel:" not in result.content
    assert "Erfuellt:" not in result.content
    assert "Fallback - Analyse fehlgeschlagen" not in result.content


def test_internal_loop_analysis_prompt_does_not_risk_gate_task_loop_from_raw_runtime_tool_drift():
    snapshot = create_task_loop_snapshot_from_plan(
        "Task-Loop: Pruefe kurz den neuen Multistep Loop und zeige mir sichere Zwischenstaende",
        "conv-1",
        thinking_plan={
            "intent": "Aktuellen Status des neuen Multistep Loop-Prozesses abfragen und sichere Zwischenstaende pruefen",
            "needs_memory": True,
            "memory_keys": [
                "multistep_loop_status",
                "current_iteration",
                "last_checkpoint",
                "loop_progress",
            ],
            "resolution_strategy": "active_container_capability",
            "strategy_hints": ["loop_validation", "intermediate_checkpoints", "runtime_state"],
            "suggested_tools": ["container_inspect", "exec_in_container", "container_logs"],
            "hallucination_risk": "medium",
            "needs_sequential_thinking": True,
            "sequential_complexity": 8,
        },
    )

    result = run_chat_auto_loop(snapshot, max_steps=4)

    assert result.done_reason == "task_loop_completed"
    assert result.snapshot.state.value == "completed"
    assert result.snapshot.stop_reason is None
    assert "Task-Loop pausiert." not in result.content
    assert "Stopgrund: risk_gate_required" not in result.content


@pytest.mark.asyncio
async def test_stream_chat_auto_loop_yields_plan_header_then_step_deltas():
    snapshot = TaskLoopSnapshot(
        objective_id="obj-1",
        conversation_id="conv-1",
        plan_id="plan-1",
        current_plan=["one", "two"],
        pending_step="one",
    )
    initial_events = [make_task_loop_event(TaskLoopEventType.STARTED, snapshot)]

    chunks = [
        chunk
        async for chunk in stream_chat_auto_loop(
            snapshot,
            initial_events=initial_events,
            max_steps=4,
        )
    ]

    assert chunks[0].content_delta.startswith("Task-Loop gestartet.\n\nPlan:\n1. [naechstes] one")
    assert chunks[0].events == initial_events
    assert chunks[0].is_final is False
    assert chunks[1].content_delta.startswith("\nZwischenstand:\nSchritt 1 abgeschlossen: one")
    assert chunks[1].content_delta != chunks[0].snapshot.last_user_visible_answer
    assert chunks[-1].is_final is True
    assert chunks[-1].done_reason == "task_loop_completed"
    assert "Finaler Planstatus:" in chunks[-1].content_delta


@pytest.mark.asyncio
async def test_stream_chat_auto_loop_uses_control_and_output_runtime_when_provided():
    class _Control:
        def __init__(self) -> None:
            self.calls = []

        async def verify(self, user_text, thinking_plan, retrieved_memory="", response_mode="interactive"):
            self.calls.append((user_text, thinking_plan, retrieved_memory, response_mode))
            return {
                "approved": True,
                "decision_class": "allow",
                "warnings": [],
                "final_instruction": "Bleibe konkret und kurz.",
            }

    class _Output:
        def __init__(self) -> None:
            self.calls = []

        async def generate_stream(
            self,
            user_text,
            verified_plan,
            memory_data="",
            model=None,
            memory_required_but_missing=False,
            chat_history=None,
            control_decision=None,
            execution_result=None,
        ):
            self.calls.append((user_text, verified_plan, memory_data, control_decision))
            yield "Konkreter Befund fuer diesen Schritt."

    snapshot = create_task_loop_snapshot_from_plan(
        "Task-Loop: Pruefe kurz den neuen Multistep Loop und zeige mir sichere Zwischenstaende",
        "conv-1",
        thinking_plan={
            "intent": "Multistep Loop pruefen",
            "hallucination_risk": "low",
            "suggested_tools": [],
        },
    )
    control = _Control()
    output = _Output()

    chunks = [
        chunk
        async for chunk in stream_chat_auto_loop(
            snapshot,
            initial_events=[make_task_loop_event(TaskLoopEventType.STARTED, snapshot)],
            control_layer=control,
            output_layer=output,
        )
    ]

    assert control.calls
    assert output.calls
    output_prompt, step_plan, _, control_decision = output.calls[0]
    assert "Task-Loop Schritt 1/" in output_prompt
    assert step_plan.get("_loop_trace_mode") == "internal_loop_analysis"
    assert step_plan.get("_task_loop_step_runtime") is True
    assert step_plan.get("needs_memory") is False
    assert step_plan.get("suggested_tools") is None
    assert step_plan.get("response_length_hint") == "short"
    assert control_decision is not None
    streamed_contents = [chunk.content_delta for chunk in chunks if chunk.content_delta]
    assert any(
        "Konkreter Befund fuer diesen Schritt." in content for content in streamed_contents
    )
    assert all("Pruefziel:" not in content for content in streamed_contents)


@pytest.mark.asyncio
async def test_stream_chat_auto_loop_exposes_step_runtime_fallback_diagnostics():
    class _Control:
        async def verify(self, user_text, thinking_plan, retrieved_memory="", response_mode="interactive"):
            return {
                "approved": True,
                "decision_class": "allow",
                "warnings": [],
                "final_instruction": "",
            }

    class _Output:
        async def generate_stream(
            self,
            user_text,
            verified_plan,
            memory_data="",
            model=None,
            memory_required_but_missing=False,
            chat_history=None,
            control_decision=None,
            execution_result=None,
        ):
            raise RuntimeError("boom")
            yield ""

    snapshot = create_task_loop_snapshot_from_plan(
        "Task-Loop: Analysiere kurz warum der Multistep Loop jetzt besser funktioniert",
        "conv-1",
        thinking_plan={
            "intent": "Analyse des Grundes, warum der Multistep Loop jetzt besser funktioniert",
            "hallucination_risk": "low",
            "suggested_tools": [],
        },
    )

    chunks = [
        chunk
        async for chunk in stream_chat_auto_loop(
            snapshot,
            initial_events=[make_task_loop_event(TaskLoopEventType.STARTED, snapshot)],
            control_layer=_Control(),
            output_layer=_Output(),
        )
    ]

    runtime_updates = [chunk.step_runtime or {} for chunk in chunks if chunk.step_runtime]
    assert runtime_updates
    assert any(update.get("used_fallback") is True for update in runtime_updates)
    assert any("stream_exception:RuntimeError:boom" in str(update.get("fallback_reason") or "") for update in runtime_updates)
