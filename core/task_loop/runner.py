from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any, AsyncGenerator, Dict, List

from core.task_loop.contracts import (
    RiskLevel,
    StopReason,
    TaskLoopSnapshot,
    TaskLoopState,
    transition_task_loop,
)
from core.task_loop.events import TaskLoopEventType, make_task_loop_event
from core.task_loop.reflection import ReflectionAction, reflect_after_chat_step
from core.task_loop.step_answers import answer_for_chat_step
from core.task_loop.step_runtime import (
    execute_task_loop_step,
    prepare_task_loop_step_runtime,
    stream_task_loop_step_output,
)
from utils.logger import log_warn


@dataclass(frozen=True)
class TaskLoopRunResult:
    snapshot: TaskLoopSnapshot
    events: List[Dict[str, Any]]
    content: str
    done_reason: str


@dataclass(frozen=True)
class TaskLoopStreamChunk:
    content_delta: str
    snapshot: TaskLoopSnapshot
    events: List[Dict[str, Any]]
    is_final: bool
    done_reason: str
    emit_update: bool = True
    step_runtime: Dict[str, Any] | None = None


def _format_plan(snapshot: TaskLoopSnapshot) -> str:
    completed = set(snapshot.completed_steps)
    lines = []
    for idx, step in enumerate(snapshot.current_plan, start=1):
        marker = (
            "erledigt"
            if step in completed
            else "naechstes"
            if step == snapshot.pending_step
            else "offen"
        )
        lines.append(f"{idx}. [{marker}] {step}")
    return "\n".join(lines)


def _step_meta(snapshot: TaskLoopSnapshot, title: str) -> Dict[str, Any]:
    for step in snapshot.plan_steps:
        if isinstance(step, dict) and str(step.get("title") or "") == title:
            return step
    return {}


def _risk_for_step(snapshot: TaskLoopSnapshot, title: str) -> RiskLevel:
    meta = _step_meta(snapshot, title)
    raw = str(meta.get("risk_level") or RiskLevel.SAFE.value).strip().lower()
    try:
        return RiskLevel(raw)
    except Exception:
        return RiskLevel.SAFE


def _done_reason_for_stop(reason: StopReason) -> str:
    return f"task_loop_{reason.value}"


def _append_visible_content(current: str, delta: str) -> str:
    if not delta:
        return current
    if not current:
        return delta
    if current.endswith("\n") or delta.startswith("\n"):
        return current + delta
    return current + "\n" + delta


@dataclass(frozen=True)
class _TaskLoopStepResult:
    snapshot: TaskLoopSnapshot
    events: List[Dict[str, Any]]
    content_delta: str
    is_final: bool
    done_reason: str


def _run_chat_auto_loop_step(
    snapshot: TaskLoopSnapshot,
    *,
    max_steps: int,
    max_errors: int,
    max_no_progress: int,
    current_content: str,
) -> _TaskLoopStepResult:
    events: List[Dict[str, Any]] = []
    working_snapshot = snapshot

    if working_snapshot.state != TaskLoopState.EXECUTING:
        working_snapshot = transition_task_loop(working_snapshot, TaskLoopState.EXECUTING)
    events.append(make_task_loop_event(TaskLoopEventType.STEP_STARTED, working_snapshot))

    completed_step = working_snapshot.pending_step.strip()
    if not completed_step:
        completed = transition_task_loop(working_snapshot, TaskLoopState.COMPLETED)
        events.append(make_task_loop_event(TaskLoopEventType.COMPLETED, completed))
        delta = "Task-Loop abgeschlossen."
        return _TaskLoopStepResult(
            snapshot=replace(
                completed,
                last_user_visible_answer=_append_visible_content(current_content, delta),
            ),
            events=events,
            content_delta=delta,
            is_final=True,
            done_reason="task_loop_completed",
        )

    current_risk = _risk_for_step(working_snapshot, completed_step)
    if current_risk in {RiskLevel.NEEDS_CONFIRMATION, RiskLevel.RISKY}:
        gated = replace(working_snapshot, risk_level=current_risk)
        waiting = transition_task_loop(
            gated,
            TaskLoopState.WAITING_FOR_USER,
            stop_reason=StopReason.RISK_GATE_REQUIRED,
        )
        events.append(make_task_loop_event(TaskLoopEventType.WAITING_FOR_USER, waiting))
        delta = (
            "\nZwischenstand:\n"
            "Task-Loop pausiert.\n"
            "Stopgrund: risk_gate_required\n"
            f"Detail: Schritt braucht Freigabe: {completed_step}"
        )
        return _TaskLoopStepResult(
            snapshot=replace(
                waiting,
                last_user_visible_answer=_append_visible_content(current_content, delta),
            ),
            events=events,
            content_delta=delta,
            is_final=True,
            done_reason="task_loop_risk_gate_required",
        )

    completed_steps = list(working_snapshot.completed_steps)
    if completed_step not in completed_steps:
        completed_steps.append(completed_step)
    next_index = len(completed_steps)
    next_step = (
        working_snapshot.current_plan[next_index]
        if next_index < len(working_snapshot.current_plan)
        else ""
    )
    step_answer = answer_for_chat_step(
        next_index,
        completed_step,
        _step_meta(working_snapshot, completed_step),
        completed_steps[:-1],
    )
    next_risk = _risk_for_step(working_snapshot, next_step) if next_step else RiskLevel.SAFE
    answered = replace(
        working_snapshot,
        step_index=next_index,
        completed_steps=completed_steps,
        pending_step=next_step,
        last_user_visible_answer=step_answer,
        risk_level=next_risk,
    )
    events.append(make_task_loop_event(TaskLoopEventType.STEP_ANSWERED, answered))
    events.append(make_task_loop_event(TaskLoopEventType.STEP_COMPLETED, answered))
    step_delta = (
        "\nZwischenstand:\n"
        f"Schritt {next_index} abgeschlossen: {completed_step}\n"
        f"Ergebnis: {step_answer}\n"
    )

    reflecting = transition_task_loop(answered, TaskLoopState.REFLECTING)
    decision = reflect_after_chat_step(
        reflecting,
        max_steps=max_steps,
        max_errors=max_errors,
        max_no_progress=max_no_progress,
    )
    events.append(
        make_task_loop_event(
            TaskLoopEventType.REFLECTION,
            reflecting,
            event_data={
                "reflection": {
                    "action": decision.action.value,
                    "reason": decision.reason.value if decision.reason else None,
                    "detail": decision.detail,
                    "progress_made": decision.progress_made,
                }
            },
        )
    )

    step_content = step_delta
    if decision.action is ReflectionAction.CONTINUE:
        continued = replace(
            reflecting,
            last_user_visible_answer=_append_visible_content(current_content, step_content),
        )
        return _TaskLoopStepResult(
            snapshot=continued,
            events=events,
            content_delta=step_content,
            is_final=False,
            done_reason="",
        )

    if decision.action is ReflectionAction.COMPLETED:
        completed = transition_task_loop(reflecting, TaskLoopState.COMPLETED)
        events.append(make_task_loop_event(TaskLoopEventType.COMPLETED, completed))
        step_content += "\nFinaler Planstatus:\n" + _format_plan(completed) + "\n\nTask-Loop abgeschlossen."
        return _TaskLoopStepResult(
            snapshot=replace(
                completed,
                last_user_visible_answer=_append_visible_content(current_content, step_content),
            ),
            events=events,
            content_delta=step_content,
            is_final=True,
            done_reason="task_loop_completed",
        )

    stop_reason = decision.reason or StopReason.NO_CONCRETE_NEXT_STEP
    if decision.action is ReflectionAction.WAITING_FOR_USER:
        waiting = transition_task_loop(
            reflecting,
            TaskLoopState.WAITING_FOR_USER,
            stop_reason=stop_reason,
        )
        events.append(make_task_loop_event(TaskLoopEventType.WAITING_FOR_USER, waiting))
        step_content += (
            "\nTask-Loop pausiert.\n"
            f"Stopgrund: {stop_reason.value}\n"
            f"Detail: {decision.detail}"
        )
        return _TaskLoopStepResult(
            snapshot=replace(
                waiting,
                last_user_visible_answer=_append_visible_content(current_content, step_content),
            ),
            events=events,
            content_delta=step_content,
            is_final=True,
            done_reason=_done_reason_for_stop(stop_reason),
        )

    blocked = transition_task_loop(
        reflecting,
        TaskLoopState.BLOCKED,
        stop_reason=stop_reason,
    )
    events.append(make_task_loop_event(TaskLoopEventType.BLOCKED, blocked))
    step_content += (
        "\nTask-Loop blockiert.\n"
        f"Stopgrund: {stop_reason.value}\n"
        f"Detail: {decision.detail}"
    )
    return _TaskLoopStepResult(
        snapshot=replace(
            blocked,
            last_user_visible_answer=_append_visible_content(current_content, step_content),
        ),
        events=events,
        content_delta=step_content,
        is_final=True,
        done_reason=_done_reason_for_stop(stop_reason),
    )


def run_chat_auto_loop(
    initial_snapshot: TaskLoopSnapshot,
    *,
    initial_events: List[Dict[str, Any]] | None = None,
    max_steps: int = 4,
    max_errors: int = 4,
    max_no_progress: int = 2,
) -> TaskLoopRunResult:
    events: List[Dict[str, Any]] = list(initial_events or [])
    snapshot = initial_snapshot
    content = f"Task-Loop gestartet.\n\nPlan:\n{_format_plan(snapshot)}\n"

    while True:
        step_result = _run_chat_auto_loop_step(
            snapshot,
            max_steps=max_steps,
            max_errors=max_errors,
            max_no_progress=max_no_progress,
            current_content=content,
        )
        events.extend(step_result.events)
        content = step_result.snapshot.last_user_visible_answer
        snapshot = step_result.snapshot
        if step_result.is_final:
            return TaskLoopRunResult(
                snapshot=snapshot,
                events=events,
                content=content,
                done_reason=step_result.done_reason,
            )


async def stream_chat_auto_loop(
    initial_snapshot: TaskLoopSnapshot,
    *,
    initial_events: List[Dict[str, Any]] | None = None,
    max_steps: int = 4,
    max_errors: int = 4,
    max_no_progress: int = 2,
    control_layer: Any = None,
    output_layer: Any = None,
) -> AsyncGenerator[TaskLoopStreamChunk, None]:
    snapshot = initial_snapshot
    header = f"Task-Loop gestartet.\n\nPlan:\n{_format_plan(snapshot)}\n"
    header_snapshot = replace(snapshot, last_user_visible_answer=header)
    yield TaskLoopStreamChunk(
        content_delta=header,
        snapshot=header_snapshot,
        events=list(initial_events or []),
        is_final=False,
        done_reason="",
        emit_update=True,
    )
    await asyncio.sleep(0.05)

    current_content = header
    while True:
        if output_layer is not None:
            final_chunk: TaskLoopStreamChunk | None = None
            async for streamed_chunk in _stream_chat_auto_loop_step_async(
                snapshot,
                max_steps=max_steps,
                max_errors=max_errors,
                max_no_progress=max_no_progress,
                current_content=current_content,
                control_layer=control_layer,
                output_layer=output_layer,
            ):
                yield streamed_chunk
                await asyncio.sleep(0.05)
                snapshot = streamed_chunk.snapshot
                current_content = streamed_chunk.snapshot.last_user_visible_answer
                final_chunk = streamed_chunk
            if final_chunk is not None and final_chunk.is_final:
                return
            continue
        else:
            step_result = _run_chat_auto_loop_step(
                snapshot,
                max_steps=max_steps,
                max_errors=max_errors,
                max_no_progress=max_no_progress,
                current_content=current_content,
            )
            yield TaskLoopStreamChunk(
                content_delta=step_result.content_delta,
                snapshot=step_result.snapshot,
                events=step_result.events,
                is_final=step_result.is_final,
                done_reason=step_result.done_reason,
                emit_update=True,
            )
            await asyncio.sleep(0.05)
            snapshot = step_result.snapshot
            current_content = step_result.snapshot.last_user_visible_answer
            if step_result.is_final:
                return
            continue


async def _run_chat_auto_loop_step_async(
    snapshot: TaskLoopSnapshot,
    *,
    max_steps: int,
    max_errors: int,
    max_no_progress: int,
    current_content: str,
    control_layer: Any = None,
    output_layer: Any = None,
) -> _TaskLoopStepResult:
    events: List[Dict[str, Any]] = []
    working_snapshot = snapshot

    if working_snapshot.state != TaskLoopState.EXECUTING:
        working_snapshot = transition_task_loop(working_snapshot, TaskLoopState.EXECUTING)
    events.append(make_task_loop_event(TaskLoopEventType.STEP_STARTED, working_snapshot))

    completed_step = working_snapshot.pending_step.strip()
    if not completed_step:
        completed = transition_task_loop(working_snapshot, TaskLoopState.COMPLETED)
        events.append(make_task_loop_event(TaskLoopEventType.COMPLETED, completed))
        delta = "Task-Loop abgeschlossen."
        return _TaskLoopStepResult(
            snapshot=replace(
                completed,
                last_user_visible_answer=_append_visible_content(current_content, delta),
            ),
            events=events,
            content_delta=delta,
            is_final=True,
            done_reason="task_loop_completed",
        )

    current_risk = _risk_for_step(working_snapshot, completed_step)
    if current_risk in {RiskLevel.NEEDS_CONFIRMATION, RiskLevel.RISKY}:
        gated = replace(working_snapshot, risk_level=current_risk)
        waiting = transition_task_loop(
            gated,
            TaskLoopState.WAITING_FOR_USER,
            stop_reason=StopReason.RISK_GATE_REQUIRED,
        )
        events.append(make_task_loop_event(TaskLoopEventType.WAITING_FOR_USER, waiting))
        delta = (
            "\nZwischenstand:\n"
            "Task-Loop pausiert.\n"
            "Stopgrund: risk_gate_required\n"
            f"Detail: Schritt braucht Freigabe: {completed_step}"
        )
        return _TaskLoopStepResult(
            snapshot=replace(
                waiting,
                last_user_visible_answer=_append_visible_content(current_content, delta),
            ),
            events=events,
            content_delta=delta,
            is_final=True,
            done_reason="task_loop_risk_gate_required",
        )

    step_meta = _step_meta(working_snapshot, completed_step)
    runtime_result = await execute_task_loop_step(
        completed_step,
        step_meta,
        working_snapshot,
        control_layer=control_layer,
        output_layer=output_layer,
        fallback_fn=answer_for_chat_step,
    )
    if not runtime_result.control_decision.approved:
        detail = (
            runtime_result.control_decision.final_instruction
            or runtime_result.control_decision.reason
            or ", ".join(str(item) for item in runtime_result.control_decision.warnings)
            or "step_control_denied"
        )
        if runtime_result.control_decision.hard_block:
            blocked = transition_task_loop(
                working_snapshot,
                TaskLoopState.BLOCKED,
                stop_reason=StopReason.RISK_GATE_REQUIRED,
            )
            events.append(make_task_loop_event(TaskLoopEventType.BLOCKED, blocked))
            delta = (
                "\nZwischenstand:\n"
                "Task-Loop blockiert.\n"
                "Stopgrund: risk_gate_required\n"
                f"Detail: {detail}"
            )
            return _TaskLoopStepResult(
                snapshot=replace(
                    blocked,
                    last_user_visible_answer=_append_visible_content(current_content, delta),
                ),
                events=events,
                content_delta=delta,
                is_final=True,
                done_reason="task_loop_risk_gate_required",
            )
        waiting = transition_task_loop(
            working_snapshot,
            TaskLoopState.WAITING_FOR_USER,
            stop_reason=StopReason.RISK_GATE_REQUIRED,
        )
        events.append(make_task_loop_event(TaskLoopEventType.WAITING_FOR_USER, waiting))
        delta = (
            "\nZwischenstand:\n"
            "Task-Loop pausiert.\n"
            "Stopgrund: risk_gate_required\n"
            f"Detail: {detail}"
        )
        return _TaskLoopStepResult(
            snapshot=replace(
                waiting,
                last_user_visible_answer=_append_visible_content(current_content, delta),
            ),
            events=events,
            content_delta=delta,
            is_final=True,
            done_reason="task_loop_risk_gate_required",
        )

    completed_steps = list(working_snapshot.completed_steps)
    if completed_step not in completed_steps:
        completed_steps.append(completed_step)
    next_index = len(completed_steps)
    next_step = (
        working_snapshot.current_plan[next_index]
        if next_index < len(working_snapshot.current_plan)
        else ""
    )
    next_risk = _risk_for_step(working_snapshot, next_step) if next_step else RiskLevel.SAFE
    answered = replace(
        working_snapshot,
        step_index=next_index,
        completed_steps=completed_steps,
        pending_step=next_step,
        last_user_visible_answer=runtime_result.visible_text,
        risk_level=next_risk,
    )
    events.append(make_task_loop_event(TaskLoopEventType.STEP_ANSWERED, answered))
    events.append(make_task_loop_event(TaskLoopEventType.STEP_COMPLETED, answered))
    step_delta = (
        "\nZwischenstand:\n"
        f"Schritt {next_index} abgeschlossen: {completed_step}\n"
        f"Ergebnis: {runtime_result.visible_text}\n"
    )

    reflecting = transition_task_loop(answered, TaskLoopState.REFLECTING)
    decision = reflect_after_chat_step(
        reflecting,
        max_steps=max_steps,
        max_errors=max_errors,
        max_no_progress=max_no_progress,
    )
    events.append(
        make_task_loop_event(
            TaskLoopEventType.REFLECTION,
            reflecting,
            event_data={
                "reflection": {
                    "action": decision.action.value,
                    "reason": decision.reason.value if decision.reason else None,
                    "detail": decision.detail,
                    "progress_made": decision.progress_made,
                    "used_fallback": runtime_result.used_fallback,
                }
            },
        )
    )

    step_content = step_delta
    if decision.action is ReflectionAction.CONTINUE:
        continued = replace(
            reflecting,
            last_user_visible_answer=_append_visible_content(current_content, step_content),
        )
        return _TaskLoopStepResult(
            snapshot=continued,
            events=events,
            content_delta=step_content,
            is_final=False,
            done_reason="",
        )

    if decision.action is ReflectionAction.COMPLETED:
        completed = transition_task_loop(reflecting, TaskLoopState.COMPLETED)
        events.append(make_task_loop_event(TaskLoopEventType.COMPLETED, completed))
        step_content += "\nFinaler Planstatus:\n" + _format_plan(completed) + "\n\nTask-Loop abgeschlossen."
        return _TaskLoopStepResult(
            snapshot=replace(
                completed,
                last_user_visible_answer=_append_visible_content(current_content, step_content),
            ),
            events=events,
            content_delta=step_content,
            is_final=True,
            done_reason="task_loop_completed",
        )

    stop_reason = decision.reason or StopReason.NO_CONCRETE_NEXT_STEP
    if decision.action is ReflectionAction.WAITING_FOR_USER:
        waiting = transition_task_loop(
            reflecting,
            TaskLoopState.WAITING_FOR_USER,
            stop_reason=stop_reason,
        )
        events.append(make_task_loop_event(TaskLoopEventType.WAITING_FOR_USER, waiting))
        step_content += (
            "\nTask-Loop pausiert.\n"
            f"Stopgrund: {stop_reason.value}\n"
            f"Detail: {decision.detail}"
        )
        return _TaskLoopStepResult(
            snapshot=replace(
                waiting,
                last_user_visible_answer=_append_visible_content(current_content, step_content),
            ),
            events=events,
            content_delta=step_content,
            is_final=True,
            done_reason=_done_reason_for_stop(stop_reason),
        )

    blocked = transition_task_loop(
        reflecting,
        TaskLoopState.BLOCKED,
        stop_reason=stop_reason,
    )
    events.append(make_task_loop_event(TaskLoopEventType.BLOCKED, blocked))
    step_content += (
        "\nTask-Loop blockiert.\n"
        f"Stopgrund: {stop_reason.value}\n"
        f"Detail: {decision.detail}"
    )
    return _TaskLoopStepResult(
        snapshot=replace(
            blocked,
            last_user_visible_answer=_append_visible_content(current_content, step_content),
        ),
        events=events,
        content_delta=step_content,
        is_final=True,
        done_reason=_done_reason_for_stop(stop_reason),
    )


async def _stream_chat_auto_loop_step_async(
    snapshot: TaskLoopSnapshot,
    *,
    max_steps: int,
    max_errors: int,
    max_no_progress: int,
    current_content: str,
    control_layer: Any = None,
    output_layer: Any = None,
) -> AsyncGenerator[TaskLoopStreamChunk, None]:
    events: List[Dict[str, Any]] = []
    working_snapshot = snapshot

    if working_snapshot.state != TaskLoopState.EXECUTING:
        working_snapshot = transition_task_loop(working_snapshot, TaskLoopState.EXECUTING)
    events.append(make_task_loop_event(TaskLoopEventType.STEP_STARTED, working_snapshot))
    yield TaskLoopStreamChunk(
        content_delta="",
        snapshot=working_snapshot,
        events=list(events),
        is_final=False,
        done_reason="",
        emit_update=True,
    )

    completed_step = working_snapshot.pending_step.strip()
    if not completed_step:
        completed = transition_task_loop(working_snapshot, TaskLoopState.COMPLETED)
        done_events = [make_task_loop_event(TaskLoopEventType.COMPLETED, completed)]
        delta = "Task-Loop abgeschlossen."
        yield TaskLoopStreamChunk(
            content_delta=delta,
            snapshot=replace(
                completed,
                last_user_visible_answer=_append_visible_content(current_content, delta),
            ),
            events=done_events,
            is_final=True,
            done_reason="task_loop_completed",
            emit_update=True,
        )
        return

    current_risk = _risk_for_step(working_snapshot, completed_step)
    if current_risk in {RiskLevel.NEEDS_CONFIRMATION, RiskLevel.RISKY}:
        gated = replace(working_snapshot, risk_level=current_risk)
        waiting = transition_task_loop(
            gated,
            TaskLoopState.WAITING_FOR_USER,
            stop_reason=StopReason.RISK_GATE_REQUIRED,
        )
        wait_events = [make_task_loop_event(TaskLoopEventType.WAITING_FOR_USER, waiting)]
        delta = (
            "\nZwischenstand:\n"
            "Task-Loop pausiert.\n"
            "Stopgrund: risk_gate_required\n"
            f"Detail: Schritt braucht Freigabe: {completed_step}"
        )
        yield TaskLoopStreamChunk(
            content_delta=delta,
            snapshot=replace(
                waiting,
                last_user_visible_answer=_append_visible_content(current_content, delta),
            ),
            events=wait_events,
            is_final=True,
            done_reason="task_loop_risk_gate_required",
            emit_update=True,
        )
        return

    step_meta = _step_meta(working_snapshot, completed_step)
    prepared = await prepare_task_loop_step_runtime(
        completed_step,
        step_meta,
        working_snapshot,
        control_layer=control_layer,
        fallback_fn=answer_for_chat_step,
    )
    if not prepared.control_decision.approved:
        detail = (
            prepared.control_decision.final_instruction
            or prepared.control_decision.reason
            or ", ".join(str(item) for item in prepared.control_decision.warnings)
            or "step_control_denied"
        )
        if prepared.control_decision.hard_block:
            blocked = transition_task_loop(
                working_snapshot,
                TaskLoopState.BLOCKED,
                stop_reason=StopReason.RISK_GATE_REQUIRED,
            )
            block_events = [make_task_loop_event(TaskLoopEventType.BLOCKED, blocked)]
            delta = (
                "\nZwischenstand:\n"
                "Task-Loop blockiert.\n"
                "Stopgrund: risk_gate_required\n"
                f"Detail: {detail}"
            )
            yield TaskLoopStreamChunk(
                content_delta=delta,
                snapshot=replace(
                    blocked,
                    last_user_visible_answer=_append_visible_content(current_content, delta),
                ),
                events=block_events,
                is_final=True,
                done_reason="task_loop_risk_gate_required",
                emit_update=True,
            )
            return
        waiting = transition_task_loop(
            working_snapshot,
            TaskLoopState.WAITING_FOR_USER,
            stop_reason=StopReason.RISK_GATE_REQUIRED,
        )
        wait_events = [make_task_loop_event(TaskLoopEventType.WAITING_FOR_USER, waiting)]
        delta = (
            "\nZwischenstand:\n"
            "Task-Loop pausiert.\n"
            "Stopgrund: risk_gate_required\n"
            f"Detail: {detail}"
        )
        yield TaskLoopStreamChunk(
            content_delta=delta,
            snapshot=replace(
                waiting,
                last_user_visible_answer=_append_visible_content(current_content, delta),
            ),
            events=wait_events,
            is_final=True,
            done_reason="task_loop_risk_gate_required",
            emit_update=True,
        )
        return

    completed_steps = list(working_snapshot.completed_steps)
    if completed_step not in completed_steps:
        completed_steps.append(completed_step)
    next_index = len(completed_steps)
    next_step = (
        working_snapshot.current_plan[next_index]
        if next_index < len(working_snapshot.current_plan)
        else ""
    )
    next_risk = _risk_for_step(working_snapshot, next_step) if next_step else RiskLevel.SAFE

    streamed_step_content = (
        "\nZwischenstand:\n"
        f"Schritt {next_index} abgeschlossen: {completed_step}\n"
        "Ergebnis: "
    )
    current_snapshot = replace(
        working_snapshot,
        last_user_visible_answer=_append_visible_content(current_content, streamed_step_content),
    )
    yield TaskLoopStreamChunk(
        content_delta=streamed_step_content,
        snapshot=current_snapshot,
        events=[],
        is_final=False,
        done_reason="",
        emit_update=False,
    )

    model_chunks: List[str] = []
    used_fallback = False
    fallback_reason = ""
    stream_chunk_count = 0
    try:
        async for out_chunk in stream_task_loop_step_output(prepared, output_layer=output_layer):
            model_chunks.append(str(out_chunk))
            stream_chunk_count += 1
            streamed_piece = str(out_chunk)
            streamed_step_content += streamed_piece
            current_snapshot = replace(
                working_snapshot,
                last_user_visible_answer=_append_visible_content(current_content, streamed_step_content),
            )
            yield TaskLoopStreamChunk(
                content_delta=streamed_piece,
                snapshot=current_snapshot,
                events=[],
                is_final=False,
                done_reason="",
                emit_update=False,
            )
    except Exception as exc:
        used_fallback = True
        fallback_reason = f"stream_exception:{type(exc).__name__}:{str(exc or '').strip()}"
        log_warn(
            "[TaskLoop] step runtime fallback "
            f"step={completed_step!r} reason={fallback_reason}"
        )

    visible_text = "".join(model_chunks).strip()
    if not visible_text:
        used_fallback = True
        if not fallback_reason:
            fallback_reason = "empty_step_output"
        visible_text = prepared.fallback_text
        fallback_piece = prepared.fallback_text
        streamed_step_content += fallback_piece
        current_snapshot = replace(
            working_snapshot,
            last_user_visible_answer=_append_visible_content(current_content, streamed_step_content),
        )
        yield TaskLoopStreamChunk(
            content_delta=fallback_piece,
            snapshot=current_snapshot,
            events=[],
            is_final=False,
            done_reason="",
            emit_update=False,
        )
    else:
        visible_text = " ".join(visible_text.split())

    step_runtime_meta = {
        "step_title": completed_step,
        "used_fallback": used_fallback,
        "fallback_reason": fallback_reason,
        "stream_chunk_count": stream_chunk_count,
        "control_approved": bool(prepared.control_decision.approved),
    }

    streamed_step_content += "\n"
    current_snapshot = replace(
        working_snapshot,
        last_user_visible_answer=_append_visible_content(current_content, streamed_step_content),
    )
    yield TaskLoopStreamChunk(
        content_delta="\n",
        snapshot=current_snapshot,
        events=[],
        is_final=False,
        done_reason="",
        emit_update=False,
    )

    answered = replace(
        working_snapshot,
        step_index=next_index,
        completed_steps=completed_steps,
        pending_step=next_step,
        last_user_visible_answer=visible_text,
        risk_level=next_risk,
    )
    answered_events = [
        make_task_loop_event(TaskLoopEventType.STEP_ANSWERED, answered),
        make_task_loop_event(TaskLoopEventType.STEP_COMPLETED, answered),
    ]

    reflecting = transition_task_loop(answered, TaskLoopState.REFLECTING)
    decision = reflect_after_chat_step(
        reflecting,
        max_steps=max_steps,
        max_errors=max_errors,
        max_no_progress=max_no_progress,
    )
    answered_events.append(
        make_task_loop_event(
            TaskLoopEventType.REFLECTION,
            reflecting,
            event_data={
                "reflection": {
                    "action": decision.action.value,
                    "reason": decision.reason.value if decision.reason else None,
                    "detail": decision.detail,
                    "progress_made": decision.progress_made,
                    "used_fallback": used_fallback,
                }
            },
        )
    )

    if decision.action is ReflectionAction.CONTINUE:
        continued = replace(
            reflecting,
            last_user_visible_answer=_append_visible_content(current_content, streamed_step_content),
        )
        yield TaskLoopStreamChunk(
            content_delta="",
            snapshot=continued,
            events=answered_events,
            is_final=False,
            done_reason="",
            emit_update=True,
            step_runtime=step_runtime_meta,
        )
        return

    if decision.action is ReflectionAction.COMPLETED:
        completed = transition_task_loop(reflecting, TaskLoopState.COMPLETED)
        answered_events.append(make_task_loop_event(TaskLoopEventType.COMPLETED, completed))
        tail = "\nFinaler Planstatus:\n" + _format_plan(completed) + "\n\nTask-Loop abgeschlossen."
        final_snapshot = replace(
            completed,
            last_user_visible_answer=_append_visible_content(current_content, streamed_step_content + tail),
        )
        yield TaskLoopStreamChunk(
            content_delta=tail,
            snapshot=final_snapshot,
            events=answered_events,
            is_final=True,
            done_reason="task_loop_completed",
            emit_update=True,
            step_runtime=step_runtime_meta,
        )
        return

    stop_reason = decision.reason or StopReason.NO_CONCRETE_NEXT_STEP
    if decision.action is ReflectionAction.WAITING_FOR_USER:
        waiting = transition_task_loop(
            reflecting,
            TaskLoopState.WAITING_FOR_USER,
            stop_reason=stop_reason,
        )
        answered_events.append(make_task_loop_event(TaskLoopEventType.WAITING_FOR_USER, waiting))
        tail = (
            "\nTask-Loop pausiert.\n"
            f"Stopgrund: {stop_reason.value}\n"
            f"Detail: {decision.detail}"
        )
        final_snapshot = replace(
            waiting,
            last_user_visible_answer=_append_visible_content(current_content, streamed_step_content + tail),
        )
        yield TaskLoopStreamChunk(
            content_delta=tail,
            snapshot=final_snapshot,
            events=answered_events,
            is_final=True,
            done_reason=_done_reason_for_stop(stop_reason),
            emit_update=True,
            step_runtime=step_runtime_meta,
        )
        return

    blocked = transition_task_loop(
        reflecting,
        TaskLoopState.BLOCKED,
        stop_reason=stop_reason,
    )
    answered_events.append(make_task_loop_event(TaskLoopEventType.BLOCKED, blocked))
    tail = (
        "\nTask-Loop blockiert.\n"
        f"Stopgrund: {stop_reason.value}\n"
        f"Detail: {decision.detail}"
    )
    final_snapshot = replace(
        blocked,
        last_user_visible_answer=_append_visible_content(current_content, streamed_step_content + tail),
    )
    yield TaskLoopStreamChunk(
        content_delta=tail,
        snapshot=final_snapshot,
        events=answered_events,
        is_final=True,
        done_reason=_done_reason_for_stop(stop_reason),
        emit_update=True,
        step_runtime=step_runtime_meta,
    )
