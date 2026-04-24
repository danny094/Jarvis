from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any, AsyncGenerator, Dict, List

from core.task_loop.contracts import (
    RiskLevel,
    StopReason,
    TaskLoopSnapshot,
    TaskLoopState,
    TaskLoopStepExecutionSource,
    TaskLoopStepResult,
    TaskLoopStepStatus,
    TaskLoopStepType,
    transition_task_loop,
    transition_task_loop_step,
)
from core.task_loop.events import TaskLoopEventType, make_task_loop_event
from core.task_loop.completion_policy import build_completion_message
from core.task_loop.reflection import ReflectionAction, reflect_after_chat_step
from core.task_loop.runner.chat_async import _run_chat_auto_loop_step_async
from core.task_loop.runner.chat_sync import _effective_max_steps, _run_chat_auto_loop_step
from core.task_loop.runner.messages import (
    _msg_control_soft_block,
    _msg_hard_block,
    _msg_risk_gate,
    _msg_verify_before_complete,
    _msg_waiting,
)
from core.task_loop.runner.snapshot_state import (
    _append_visible_content,
    _done_reason_for_stop,
    _inject_follow_up_step,
    _merge_verified_artifacts,
    _prime_next_step,
    _risk_for_step,
    _set_step_running,
    _step_meta,
    _step_type_for_step,
)
from core.task_loop.step_answers import answer_for_chat_step
from core.task_loop.step_runtime import (
    prepare_task_loop_step_runtime,
    stream_task_loop_step_events,
)
from core.task_loop.step_runtime.execution import check_tool_request_preconditions
from core.task_loop.step_runtime.prompting import _effective_step_status
from core.task_loop.tool_step_policy import should_execute_tool_via_orchestrator
from utils.logger import log_warn


@dataclass(frozen=True)
class TaskLoopStreamChunk:
    content_delta: str
    thinking_delta: str
    snapshot: TaskLoopSnapshot
    events: List[Dict[str, Any]]
    is_final: bool
    done_reason: str
    emit_update: bool = True
    step_runtime: Dict[str, Any] | None = None


async def stream_chat_auto_loop(
    initial_snapshot: TaskLoopSnapshot,
    *,
    initial_events: List[Dict[str, Any]] | None = None,
    max_steps: int | None = None,
    max_errors: int = 4,
    max_no_progress: int = 2,
    control_layer: Any = None,
    output_layer: Any = None,
    orchestrator_bridge: Any = None,
    emit_header: bool = True,
    resume_user_text: str = "",
) -> AsyncGenerator[TaskLoopStreamChunk, None]:
    snapshot = initial_snapshot
    _max_steps = _effective_max_steps(snapshot, max_steps)
    current_content = str(snapshot.last_user_visible_answer or "")
    current_resume_user_text = str(resume_user_text or "")
    if emit_header:
        header = ""
        header_snapshot = replace(snapshot, last_user_visible_answer=header)
        yield TaskLoopStreamChunk(
            content_delta=header,
            thinking_delta="",
            snapshot=header_snapshot,
            events=list(initial_events or []),
            is_final=False,
            done_reason="",
            emit_update=True,
        )
        await asyncio.sleep(0.05)
        current_content = header
    elif initial_events:
        yield TaskLoopStreamChunk(
            content_delta="",
            thinking_delta="",
            snapshot=replace(snapshot, last_user_visible_answer=current_content),
            events=list(initial_events or []),
            is_final=False,
            done_reason="",
            emit_update=True,
        )
        await asyncio.sleep(0.05)
    if snapshot.state == TaskLoopState.BLOCKED:
        snapshot = transition_task_loop(
            snapshot,
            TaskLoopState.WAITING_FOR_USER,
            stop_reason=StopReason.NO_CONCRETE_NEXT_STEP,
        )

    while True:
        step_type = (
            _step_type_for_step(snapshot, snapshot.pending_step.strip())
            if snapshot.pending_step.strip()
            else TaskLoopStepType.ANALYSIS
        )
        execution_step = should_execute_tool_via_orchestrator(step_type)
        if output_layer is not None and not (execution_step and orchestrator_bridge is not None):
            final_chunk: TaskLoopStreamChunk | None = None
            async for streamed_chunk in _stream_chat_auto_loop_step_async(
                snapshot,
                max_steps=_max_steps,
                max_errors=max_errors,
                max_no_progress=max_no_progress,
                current_content=current_content,
                control_layer=control_layer,
                output_layer=output_layer,
                orchestrator_bridge=orchestrator_bridge,
                resume_user_text=current_resume_user_text,
            ):
                yield streamed_chunk
                await asyncio.sleep(0.05)
                snapshot = streamed_chunk.snapshot
                current_content = streamed_chunk.snapshot.last_user_visible_answer
                final_chunk = streamed_chunk
            if final_chunk is not None and final_chunk.is_final:
                return
            current_resume_user_text = ""
            continue
        elif execution_step and orchestrator_bridge is not None:
            running_snap = _set_step_running(snapshot, snapshot.pending_step.strip()) if snapshot.pending_step.strip() else snapshot
            yield TaskLoopStreamChunk(
                content_delta="",
                thinking_delta="",
                snapshot=running_snap,
                events=[make_task_loop_event(TaskLoopEventType.STEP_STARTED, running_snap)],
                is_final=False,
                done_reason="",
                emit_update=True,
            )
            await asyncio.sleep(0.05)
            step_result = await _run_chat_auto_loop_step_async(
                snapshot,
                max_steps=_max_steps,
                max_errors=max_errors,
                max_no_progress=max_no_progress,
                current_content=current_content,
                control_layer=control_layer,
                output_layer=output_layer,
                orchestrator_bridge=orchestrator_bridge,
                resume_user_text=current_resume_user_text,
            )
            yield TaskLoopStreamChunk(
                content_delta=step_result.content_delta,
                thinking_delta=getattr(step_result, "thinking_delta", ""),
                snapshot=step_result.snapshot,
                events=step_result.events,
                is_final=step_result.is_final,
                done_reason=step_result.done_reason,
                emit_update=True,
                step_runtime={
                    "step_title": snapshot.pending_step.strip(),
                    "step_type": step_type.value,
                    "step_execution_source": str(
                        (step_result.snapshot.last_step_result or {}).get("step_execution_source")
                        or step_result.snapshot.step_execution_source.value
                    ),
                    "step_status": str(
                        (step_result.snapshot.last_step_result or {}).get("status")
                        or step_result.snapshot.current_step_status.value
                    ),
                },
            )
            await asyncio.sleep(0.05)
            snapshot = step_result.snapshot
            current_content = step_result.snapshot.last_user_visible_answer
            current_resume_user_text = ""
            if step_result.is_final:
                return
            continue
        else:
            step_result = _run_chat_auto_loop_step(
                snapshot,
                max_steps=_max_steps,
                max_errors=max_errors,
                max_no_progress=max_no_progress,
                current_content=current_content,
            )
            yield TaskLoopStreamChunk(
                content_delta=step_result.content_delta,
                thinking_delta=getattr(step_result, "thinking_delta", ""),
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


async def _stream_chat_auto_loop_step_async(
    snapshot: TaskLoopSnapshot,
    *,
    max_steps: int,
    max_errors: int,
    max_no_progress: int,
    current_content: str,
    control_layer: Any = None,
    output_layer: Any = None,
    orchestrator_bridge: Any = None,
    resume_user_text: str = "",
) -> AsyncGenerator[TaskLoopStreamChunk, None]:
    events: List[Dict[str, Any]] = []
    working_snapshot = snapshot

    if working_snapshot.state != TaskLoopState.EXECUTING:
        working_snapshot = transition_task_loop(working_snapshot, TaskLoopState.EXECUTING)
    if working_snapshot.pending_step.strip():
        working_snapshot = _set_step_running(working_snapshot, working_snapshot.pending_step.strip())
    events.append(make_task_loop_event(TaskLoopEventType.STEP_STARTED, working_snapshot))
    yield TaskLoopStreamChunk(
        content_delta="",
        thinking_delta="",
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
        delta = "Alle Schritte abgeschlossen."
        yield TaskLoopStreamChunk(
            content_delta=delta,
            thinking_delta="",
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

    step_meta = _step_meta(working_snapshot, completed_step)
    prepared = await prepare_task_loop_step_runtime(
        completed_step,
        step_meta,
        working_snapshot,
        control_layer=control_layer,
        user_reply=resume_user_text,
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
            delta = _msg_hard_block(detail)
            yield TaskLoopStreamChunk(
                content_delta=delta,
                thinking_delta="",
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
        delta = _msg_control_soft_block(detail)
        yield TaskLoopStreamChunk(
            content_delta=delta,
            thinking_delta="",
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

    streamed_step_content = ""
    current_snapshot = replace(
        working_snapshot,
        last_user_visible_answer=_append_visible_content(current_content, streamed_step_content),
    )
    yield TaskLoopStreamChunk(
        content_delta=streamed_step_content,
        thinking_delta="",
        snapshot=current_snapshot,
        events=[],
        is_final=False,
        done_reason="",
        emit_update=False,
    )

    # Pre-check: TOOL_REQUEST-Schritte auf fehlende Blueprint/Parameter prüfen
    # bevor der LLM-Stream startet — verhindert Halluzinationen statt Waits.
    if prepared.step_request.step_type is TaskLoopStepType.TOOL_REQUEST:
        resume_completed = _effective_step_status(working_snapshot, TaskLoopStepType.TOOL_REQUEST) in {
            TaskLoopStepStatus.WAITING_FOR_APPROVAL,
            TaskLoopStepStatus.WAITING_FOR_USER,
        }
        gate_status, gate_msg = check_tool_request_preconditions(
            working_snapshot,
            prepared.step_request,
            user_reply=resume_user_text,
            resume_completed=resume_completed,
        )
        if gate_status is not None:
            waiting_text = gate_msg or prepared.fallback_text
            waiting_snap = transition_task_loop(
                working_snapshot,
                TaskLoopState.WAITING_FOR_USER,
                stop_reason=StopReason.USER_DECISION_REQUIRED,
            )
            wait_events = [make_task_loop_event(TaskLoopEventType.WAITING_FOR_USER, waiting_snap)]
            yield TaskLoopStreamChunk(
                content_delta=waiting_text,
                thinking_delta="",
                snapshot=replace(
                    waiting_snap,
                    last_user_visible_answer=_append_visible_content(current_content, waiting_text),
                ),
                events=wait_events,
                is_final=True,
                done_reason="task_loop_waiting_for_user",
                emit_update=True,
            )
            return

    model_chunks: List[str] = []
    thinking_chunks: List[str] = []
    used_fallback = False
    fallback_reason = ""
    stream_chunk_count = 0
    thinking_chunk_count = 0
    try:
        async for out_event in stream_task_loop_step_events(prepared, output_layer=output_layer):
            event_type = str(out_event.get("type") or "").strip().lower()
            streamed_piece = str(out_event.get("chunk") or "")
            if not streamed_piece:
                continue
            current_snapshot = replace(
                working_snapshot,
                last_user_visible_answer=_append_visible_content(current_content, streamed_step_content),
            )
            if event_type == "thinking":
                thinking_chunks.append(streamed_piece)
                thinking_chunk_count += 1
                yield TaskLoopStreamChunk(
                    content_delta="",
                    thinking_delta=streamed_piece,
                    snapshot=current_snapshot,
                    events=[],
                    is_final=False,
                    done_reason="",
                    emit_update=False,
                )
                continue
            model_chunks.append(streamed_piece)
            stream_chunk_count += 1
            streamed_step_content += streamed_piece
            current_snapshot = replace(
                working_snapshot,
                last_user_visible_answer=_append_visible_content(current_content, streamed_step_content),
            )
            yield TaskLoopStreamChunk(
                content_delta=streamed_piece,
                thinking_delta="",
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
            thinking_delta="",
            snapshot=current_snapshot,
            events=[],
            is_final=False,
            done_reason="",
            emit_update=False,
        )
    else:
        visible_text = " ".join(visible_text.split())

    step_result = TaskLoopStepResult(
        turn_id=prepared.step_request.turn_id,
        loop_id=prepared.step_request.loop_id,
        step_id=prepared.step_request.step_id,
        step_type=prepared.step_request.step_type,
        status=TaskLoopStepStatus.COMPLETED,
        control_decision=prepared.control_decision.to_dict(),
        execution_result={},
        verified_artifacts=list(snapshot.verified_artifacts),
        user_visible_summary=visible_text,
        next_action="reflect_next_step",
        warnings=list(prepared.control_decision.warnings),
        trace_reason="task_loop_stream_step",
        step_execution_source=(
            TaskLoopStepExecutionSource.FALLBACK
            if used_fallback
            else TaskLoopStepExecutionSource.LOOP
        ),
    )

    step_runtime_meta = {
        "step_title": completed_step,
        "step_type": prepared.step_request.step_type.value,
        "used_fallback": used_fallback,
        "fallback_reason": fallback_reason,
        "stream_chunk_count": stream_chunk_count,
        "thinking_chunk_count": thinking_chunk_count,
        "thinking_chars": sum(len(chunk) for chunk in thinking_chunks),
        "has_thinking_stream": bool(thinking_chunks),
        "control_approved": bool(prepared.control_decision.approved),
        "step_execution_source": step_result.step_execution_source.value,
        "step_status": step_result.status.value,
    }

    streamed_step_content += "\n"
    current_snapshot = replace(
        working_snapshot,
        last_user_visible_answer=_append_visible_content(current_content, streamed_step_content),
    )
    yield TaskLoopStreamChunk(
        content_delta="\n",
        thinking_delta="",
        snapshot=current_snapshot,
        events=[],
        is_final=False,
        done_reason="",
        emit_update=False,
    )

    answered = transition_task_loop_step(
        replace(
            working_snapshot,
            step_index=next_index,
            completed_steps=completed_steps,
            pending_step=next_step,
            last_user_visible_answer=visible_text,
            risk_level=next_risk,
        ),
        next_step_type=step_result.step_type,
        next_step_status=TaskLoopStepStatus.COMPLETED,
        step_execution_source=step_result.step_execution_source,
        verified_artifacts=_merge_verified_artifacts(
            working_snapshot,
            step_result.verified_artifacts,
        ),
        last_step_result=step_result.to_dict(),
    )
    answered_events = [
        make_task_loop_event(TaskLoopEventType.STEP_ANSWERED, answered),
        make_task_loop_event(TaskLoopEventType.STEP_COMPLETED, answered),
    ]

    reflecting = transition_task_loop(
        _prime_next_step(answered, next_step),
        TaskLoopState.REFLECTING,
    )
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
                    "next_step_override": decision.next_step_override,
                }
            },
        )
    )

    if decision.action is ReflectionAction.CONTINUE:
        continued_snapshot = (
            _inject_follow_up_step(reflecting, decision.next_step_override)
            if decision.next_step_override
            else reflecting
        )
        content_delta = ""
        visible_tail = streamed_step_content
        if decision.next_step_override:
            content_delta = _msg_verify_before_complete(decision.detail)
            visible_tail += content_delta
        continued = replace(
            continued_snapshot,
            last_user_visible_answer=_append_visible_content(current_content, visible_tail),
        )
        yield TaskLoopStreamChunk(
            content_delta=content_delta,
            thinking_delta="",
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
        tail = build_completion_message(completed)
        final_snapshot = replace(
            completed,
            last_user_visible_answer=_append_visible_content(current_content, streamed_step_content + tail),
        )
        yield TaskLoopStreamChunk(
            content_delta=tail,
            thinking_delta="",
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
        if stop_reason is StopReason.RISK_GATE_REQUIRED:
            next_pending = reflecting.pending_step.strip()
            tail = _msg_risk_gate(next_pending or completed_step)
        else:
            tail = _msg_waiting(decision.detail)
        final_snapshot = replace(
            waiting,
            last_user_visible_answer=_append_visible_content(current_content, streamed_step_content + tail),
        )
        yield TaskLoopStreamChunk(
            content_delta=tail,
            thinking_delta="",
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
    tail = _msg_hard_block(decision.detail)
    final_snapshot = replace(
        blocked,
        last_user_visible_answer=_append_visible_content(current_content, streamed_step_content + tail),
    )
    yield TaskLoopStreamChunk(
        content_delta=tail,
        thinking_delta="",
        snapshot=final_snapshot,
        events=answered_events,
        is_final=True,
        done_reason=_done_reason_for_stop(stop_reason),
        emit_update=True,
        step_runtime=step_runtime_meta,
    )


__all__ = [
    "TaskLoopStreamChunk",
    "_stream_chat_auto_loop_step_async",
    "stream_chat_auto_loop",
]
