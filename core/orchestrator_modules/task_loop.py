from __future__ import annotations

from dataclasses import replace
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from core.task_loop.chat_runtime import (
    create_task_loop_snapshot,
    is_task_loop_candidate,
    is_task_loop_cancel,
    is_task_loop_continue,
    maybe_handle_chat_task_loop_turn,
    should_restart_task_loop,
)
from core.task_loop.active_turn_policy import (
    ACTIVE_TASK_LOOP_REASON_BLOCKED,
    ACTIVE_TASK_LOOP_REASON_CANCEL,
    ACTIVE_TASK_LOOP_REASON_CONTEXT_ONLY,
    ACTIVE_TASK_LOOP_REASON_CONTINUE,
    ACTIVE_TASK_LOOP_REASON_MODE_SHIFT,
    ACTIVE_TASK_LOOP_REASON_RESTART,
    can_keep_active_task_loop_in_background,
    classify_active_task_loop_routing,
    explain_active_task_loop_routing,
    is_independent_tool_turn_candidate,
    is_authoritative_task_loop_turn,
    is_runtime_resume_candidate,
    is_task_loop_meta_turn,
    runtime_resume_user_text,
)
from core.task_loop.events import (
    TaskLoopEventType,
    make_task_loop_event,
    persist_task_loop_workspace_event,
)
from core.task_loop.pipeline_adapter import build_task_loop_planning_context
from core.task_loop.runner import run_chat_auto_loop_async, stream_chat_auto_loop
from core.task_loop.store import get_task_loop_store
from core.task_loop.unresolved_context import (
    build_seeded_followup_user_text,
    build_unresolved_task_response,
    enrich_followup_thinking_plan,
    maybe_build_unresolved_task_context,
)
from core.work_context.selectors import (
    has_open_work_context,
    should_execute_from_work_context,
    should_explain_from_work_context,
)
from core.work_context.service import load_work_context


def get_active_task_loop_snapshot(conversation_id: str) -> Optional[Any]:
    store = get_task_loop_store()
    return store.get_active(str(conversation_id or "").strip())


def has_active_task_loop(request: Any) -> bool:
    conversation_id = str(getattr(request, "conversation_id", "") or "")
    return get_active_task_loop_snapshot(conversation_id) is not None


def is_task_loop_request(user_text: str, request: Any) -> bool:
    if has_active_task_loop(request):
        return True
    return is_task_loop_candidate(user_text, getattr(request, "raw_request", None))


def inject_active_task_loop_context(
    thinking_plan: Optional[Dict[str, Any]],
    snapshot: Optional[Any],
    *,
    user_text: str,
    raw_request: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    plan = dict(thinking_plan) if isinstance(thinking_plan, dict) else {}
    if snapshot is None:
        return plan
    plan["_task_loop_active"] = True
    plan["_task_loop_active_state"] = str(snapshot.state.value)
    plan["_task_loop_active_pending_step"] = str(snapshot.pending_step or "")
    plan["_task_loop_active_step_index"] = int(snapshot.step_index or 0)
    plan["_task_loop_continue_requested"] = is_task_loop_continue(user_text)
    plan["_task_loop_cancel_requested"] = is_task_loop_cancel(user_text)
    plan["_task_loop_restart_requested"] = should_restart_task_loop(user_text, raw_request)
    plan["_task_loop_runtime_resume_candidate"] = is_runtime_resume_candidate(
        snapshot,
        user_text,
        raw_request=raw_request,
        verified_plan=plan,
    )
    plan["_task_loop_background_preservable"] = can_keep_active_task_loop_in_background(snapshot)
    plan["_task_loop_active_topic"] = str(getattr(snapshot, "objective_summary", "") or snapshot.pending_step or "")
    plan["_task_loop_meta_turn"] = is_task_loop_meta_turn(user_text)
    plan["_task_loop_independent_tool_turn_candidate"] = is_independent_tool_turn_candidate(snapshot, plan)
    plan["_task_loop_last_step_type"] = str(snapshot.current_step_type.value)
    plan["_task_loop_last_step_status"] = str(snapshot.current_step_status.value)
    plan["_task_loop_stop_reason"] = str(snapshot.stop_reason.value) if snapshot.stop_reason else ""
    plan["_task_loop_active_reason"] = ACTIVE_TASK_LOOP_REASON_CONTINUE
    active_explanation = explain_active_task_loop_routing(
        user_text,
        snapshot,
        plan,
        raw_request=raw_request,
    )
    plan["_task_loop_active_reason"] = str(active_explanation.get("reason") or ACTIVE_TASK_LOOP_REASON_CONTINUE)
    plan["_task_loop_active_reason_detail"] = str(active_explanation.get("detail") or "").strip()
    return plan


def clear_active_task_loop(conversation_id: str) -> None:
    get_task_loop_store().clear(conversation_id)


def _resolve_unresolved_followup(
    store: Any,
    conversation_id: str,
    user_text: str,
    *,
    thinking_plan: Optional[Dict[str, Any]] = None,
) -> tuple[Optional[str], Optional[str], Optional[Dict[str, Any]]]:
    last_snapshot = store.get(conversation_id)
    unresolved = maybe_build_unresolved_task_context(last_snapshot)
    if unresolved is None:
        return None, None, None
    work_context = load_work_context(
        conversation_id=conversation_id,
        task_loop_snapshot=last_snapshot,
    )
    if not has_open_work_context(work_context):
        return None, None, None
    if should_explain_from_work_context(user_text, work_context):
        return "explain", build_unresolved_task_response(unresolved), None
    if should_execute_from_work_context(user_text, work_context):
        return (
            "loop",
            build_seeded_followup_user_text(user_text, unresolved),
            enrich_followup_thinking_plan(thinking_plan, unresolved),
        )
    return None, None, None


def _persist_stream_chunk_events(
    events: List[Dict[str, Any]],
    *,
    conversation_id: str,
    save_workspace_entry_fn: Any = None,
) -> tuple[List[str], List[Dict[str, Any]]]:
    event_ids: List[str] = []
    workspace_updates: List[Dict[str, Any]] = []
    if save_workspace_entry_fn is None:
        return event_ids, workspace_updates
    for event in events:
        saved = persist_task_loop_workspace_event(
            save_workspace_entry_fn,
            conversation_id,
            event,
        )
        if isinstance(saved, dict):
            workspace_updates.append(saved)
            event_id = saved.get("entry_id") or saved.get("id")
            if event_id:
                event_ids.append(str(event_id))
    return event_ids, workspace_updates


def _serialize_task_loop_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    serialized: List[Dict[str, Any]] = []
    for event in list(events or []):
        if not isinstance(event, dict):
            continue
        payload = dict(event)
        event_data = payload.get("event_data")
        payload["event_data"] = dict(event_data) if isinstance(event_data, dict) else {}
        serialized.append(payload)
    return serialized


async def maybe_handle_task_loop_sync(
    orch: Any,
    request: Any,
    user_text: str,
    conversation_id: str,
    *,
    core_chat_response_cls: Any,
    log_info_fn: Any,
    log_warn_fn: Any = None,
    tone_signal: Optional[Dict[str, Any]] = None,
    thinking_plan: Optional[Dict[str, Any]] = None,
    force_start: bool = False,
) -> Optional[Any]:
    store = get_task_loop_store()
    active = store.get_active(conversation_id)
    raw_request = getattr(request, "raw_request", None)
    effective_plan = dict(thinking_plan) if isinstance(thinking_plan, dict) else {}
    if active is None:
        unresolved_mode, unresolved_value, unresolved_plan = _resolve_unresolved_followup(
            store,
            conversation_id,
            user_text,
            thinking_plan=effective_plan,
        )
        if unresolved_mode == "explain" and unresolved_value:
            log_info_fn("[TaskLoop] answered unresolved follow-up directly from preserved context")
            return core_chat_response_cls(
                model=request.model,
                content=unresolved_value,
                conversation_id=conversation_id,
                done=True,
                done_reason="unresolved_task_context_explained",
                memory_used=False,
                validation_passed=True,
            )
        if unresolved_mode == "loop" and unresolved_value:
            user_text = unresolved_value
            effective_plan = unresolved_plan if isinstance(unresolved_plan, dict) else effective_plan
            force_start = True
    if active is None and not (
        force_start
        or is_task_loop_candidate(user_text, getattr(request, "raw_request", None))
    ):
        return None
    if active is not None and not force_start:
        if not is_task_loop_cancel(user_text):
            # All active-loop continues use the async runner with real control/output layers.
            # The AI reasons through each step (incl. filling gaps with sensible defaults).
            # Only irreversible TOOL_REQUEST steps (risk=needs_confirmation) will pause.
            resume_text = runtime_resume_user_text(active, user_text)
            run = await run_chat_auto_loop_async(
                active,
                initial_events=[],
                control_layer=getattr(orch, "control", None),
                output_layer=getattr(orch, "output", None),
                orchestrator_bridge=orch,
                emit_header=False,
                resume_user_text=resume_text,
            )
            event_ids, workspace_updates = _persist_stream_chunk_events(
                run.events,
                conversation_id=conversation_id,
                save_workspace_entry_fn=getattr(orch, "_save_workspace_entry", None),
            )
            final_snapshot = replace(run.snapshot, workspace_event_ids=list(active.workspace_event_ids) + event_ids)
            store.put(final_snapshot)
            log_info_fn(
                "[TaskLoop] handled sync continue via async runner "
                f"state={final_snapshot.state.value} done_reason={run.done_reason}"
            )
            return core_chat_response_cls(
                model=request.model,
                content=run.content,
                conversation_id=conversation_id,
                done=True,
                done_reason=run.done_reason,
                memory_used=False,
                validation_passed=True,
            )
    if active is None and not effective_plan:
        thinking_plan = await build_task_loop_planning_context(
            orch,
            user_text,
            conversation_id=conversation_id,
            request=request,
            tone_signal=tone_signal,
            log_info_fn=log_info_fn,
            log_warn_fn=log_warn_fn,
        )
        effective_plan = thinking_plan if isinstance(thinking_plan, dict) else {}
    result = maybe_handle_chat_task_loop_turn(
        user_text,
        conversation_id,
        raw_request=raw_request,
        store=store,
        save_workspace_entry_fn=getattr(orch, "_save_workspace_entry", None),
        thinking_plan=effective_plan,
        force_start=force_start,
    )
    if result is None:
        return None

    log_info_fn(
        "[TaskLoop] handled sync turn "
        f"state={result.snapshot.state.value} done_reason={result.done_reason}"
    )
    return core_chat_response_cls(
        model=request.model,
        content=result.content,
        conversation_id=conversation_id,
        done=True,
        done_reason=result.done_reason,
        memory_used=False,
        validation_passed=True,
    )


async def maybe_build_task_loop_stream_events(
    orch: Any,
    request: Any,
    user_text: str,
    conversation_id: str,
    *,
    log_info_fn: Any,
    log_warn_fn: Any = None,
    tone_signal: Optional[Dict[str, Any]] = None,
    thinking_plan: Optional[Dict[str, Any]] = None,
    force_start: bool = False,
) -> Optional[List[Tuple[str, bool, Dict[str, Any]]]]:
    store = get_task_loop_store()
    active = store.get_active(conversation_id)
    effective_plan = dict(thinking_plan) if isinstance(thinking_plan, dict) else {}
    if active is None:
        unresolved_mode, unresolved_value, unresolved_plan = _resolve_unresolved_followup(
            store,
            conversation_id,
            user_text,
            thinking_plan=effective_plan,
        )
        if unresolved_mode == "explain" and unresolved_value:
            log_info_fn("[TaskLoop] answered unresolved follow-up directly from preserved context (stream shim)")
            return [
                (unresolved_value, False, {"type": "content"}),
                ("", True, {"type": "done", "done_reason": "unresolved_task_context_explained"}),
            ]
        if unresolved_mode == "loop" and unresolved_value:
            user_text = unresolved_value
            effective_plan = unresolved_plan if isinstance(unresolved_plan, dict) else effective_plan
            force_start = True
    if active is None and not (force_start or is_task_loop_candidate(user_text, getattr(request, "raw_request", None))):
        return None
    if active is None and not effective_plan:
        thinking_plan = await build_task_loop_planning_context(
            orch,
            user_text,
            conversation_id=conversation_id,
            request=request,
            tone_signal=tone_signal,
            log_info_fn=log_info_fn,
            log_warn_fn=log_warn_fn,
        )
        effective_plan = thinking_plan if isinstance(thinking_plan, dict) else {}
    result = maybe_handle_chat_task_loop_turn(
        user_text,
        conversation_id,
        raw_request=getattr(request, "raw_request", None),
        store=store,
        save_workspace_entry_fn=getattr(orch, "_save_workspace_entry", None),
        thinking_plan=effective_plan,
        force_start=force_start,
    )
    if result is None:
        return None

    log_info_fn(
        "[TaskLoop] handled stream turn "
        f"state={result.snapshot.state.value} done_reason={result.done_reason}"
    )

    items: List[Tuple[str, bool, Dict[str, Any]]] = [
        (
            "",
            False,
            {
                "type": "task_loop_update",
                "state": result.snapshot.state.value,
                "done_reason": result.done_reason,
                "task_loop": result.snapshot.to_dict(),
                "event_types": [str(event.get("type") or "") for event in result.events],
                "events": _serialize_task_loop_events(result.events),
            },
        )
    ]
    for workspace_update in result.workspace_updates:
        items.append(("", False, workspace_update))
    items.append((result.content, False, {"type": "content"}))
    items.append(
        (
            "",
            True,
            {
                "type": "done",
                "done_reason": result.done_reason,
                "task_loop": result.snapshot.to_dict(),
            },
        )
    )
    return items


async def stream_task_loop_events(
    orch: Any,
    request: Any,
    user_text: str,
    conversation_id: str,
    *,
    log_info_fn: Any,
    log_warn_fn: Any = None,
    tone_signal: Optional[Dict[str, Any]] = None,
    thinking_plan: Optional[Dict[str, Any]] = None,
    force_start: bool = False,
) -> AsyncGenerator[Tuple[str, bool, Dict[str, Any]], None]:
    store = get_task_loop_store()
    active = store.get_active(conversation_id)
    raw_request = getattr(request, "raw_request", None)
    effective_plan = dict(thinking_plan) if isinstance(thinking_plan, dict) else {}
    if active is None:
        unresolved_mode, unresolved_value, unresolved_plan = _resolve_unresolved_followup(
            store,
            conversation_id,
            user_text,
            thinking_plan=effective_plan,
        )
        if unresolved_mode == "explain" and unresolved_value:
            log_info_fn("[TaskLoop] answered unresolved follow-up directly from preserved context (stream)")
            yield (unresolved_value, False, {"type": "content"})
            yield ("", True, {"type": "done", "done_reason": "unresolved_task_context_explained"})
            return
        if unresolved_mode == "loop" and unresolved_value:
            user_text = unresolved_value
            effective_plan = unresolved_plan if isinstance(unresolved_plan, dict) else effective_plan
            force_start = True
    if active is None and not (force_start or is_task_loop_candidate(user_text, raw_request)):
        return

    raw = raw_request if isinstance(raw_request, dict) else {}
    mode = str(raw.get("task_loop_mode") or "").strip().lower()
    save_workspace_entry_fn = getattr(orch, "_save_workspace_entry", None)

    # ── Active-loop continue: always route through stream_chat_auto_loop ────────
    # This covers both substantive resumes ("python:3.11") and plain continues
    # ("weiter", "freigeben"). The old manual_mode path is only kept for
    # explicit manual override via task_loop_mode=manual/step/wait.
    if active is not None and not force_start and not is_task_loop_cancel(user_text):
        if mode not in {"manual", "step", "wait"}:
            known_event_ids: List[str] = list(active.workspace_event_ids)
            output_layer = getattr(orch, "output", None)
            control_layer = getattr(orch, "control", None)

            async for chunk in stream_chat_auto_loop(
                active,
                initial_events=[],
                control_layer=control_layer,
                output_layer=output_layer,
                orchestrator_bridge=orch,
                emit_header=False,
                resume_user_text=runtime_resume_user_text(active, user_text),
            ):
                workspace_updates: List[Dict[str, Any]] = []
                chunk_snapshot = chunk.snapshot
                if chunk.emit_update:
                    event_ids, workspace_updates = _persist_stream_chunk_events(
                        chunk.events,
                        conversation_id=conversation_id,
                        save_workspace_entry_fn=save_workspace_entry_fn,
                    )
                    if event_ids:
                        known_event_ids.extend(event_ids)
                    chunk_snapshot = (
                        replace(chunk.snapshot, workspace_event_ids=list(known_event_ids))
                        if known_event_ids
                        else chunk.snapshot
                    )
                    yield (
                        "",
                        False,
                        {
                            "type": "task_loop_update",
                            "state": chunk_snapshot.state.value,
                            "done_reason": chunk.done_reason,
                            "task_loop": chunk_snapshot.to_dict(),
                            "event_types": [str(event.get("type") or "") for event in chunk.events],
                            "events": _serialize_task_loop_events(chunk.events),
                            "is_final": chunk.is_final,
                            "step_runtime": dict(chunk.step_runtime or {}),
                        },
                    )
                store.put(chunk_snapshot)
                for workspace_update in workspace_updates:
                    yield ("", False, workspace_update)
                if chunk.thinking_delta:
                    yield (
                        "",
                        False,
                        {
                            "type": "task_loop_thinking",
                            "chunk": chunk.thinking_delta,
                            "task_loop": chunk_snapshot.to_dict(),
                            "step_runtime": dict(chunk.step_runtime or {}),
                        },
                    )
                if chunk.content_delta:
                    yield (chunk.content_delta, False, {"type": "content"})
                if chunk.is_final:
                    log_info_fn(
                        "[TaskLoop] handled streaming active-loop continue "
                        f"state={chunk_snapshot.state.value} done_reason={chunk.done_reason}"
                    )
                    yield (
                        "",
                        True,
                        {
                            "type": "done",
                            "done_reason": chunk.done_reason,
                            "task_loop": chunk_snapshot.to_dict(),
                        },
                    )
                    return

    # ── Manual override (task_loop_mode=manual/step/wait) ────────────────────
    manual_mode = mode in {"manual", "step", "wait"}
    if manual_mode:
        result = maybe_handle_chat_task_loop_turn(
            user_text,
            conversation_id,
            raw_request=raw_request,
            store=store,
            save_workspace_entry_fn=save_workspace_entry_fn,
            force_start=force_start,
        )
        if result is None:
            return
        log_info_fn(
            "[TaskLoop] handled stream turn (manual mode) "
            f"state={result.snapshot.state.value} done_reason={result.done_reason}"
        )
        yield (
            "",
            False,
            {
                "type": "task_loop_update",
                "state": result.snapshot.state.value,
                "done_reason": result.done_reason,
                "task_loop": result.snapshot.to_dict(),
                "event_types": [str(event.get("type") or "") for event in result.events],
                "events": _serialize_task_loop_events(result.events),
                "is_final": True,
            },
        )
        for workspace_update in result.workspace_updates:
            yield ("", False, workspace_update)
        yield (result.content, False, {"type": "content"})
        yield (
            "",
            True,
            {
                "type": "done",
                "done_reason": result.done_reason,
                "task_loop": result.snapshot.to_dict(),
            },
        )
        return

    if not effective_plan:
        effective_plan = await build_task_loop_planning_context(
            orch,
            user_text,
            conversation_id=conversation_id,
            request=request,
            tone_signal=tone_signal,
            log_info_fn=log_info_fn,
            log_warn_fn=log_warn_fn,
        )
    snapshot = create_task_loop_snapshot(
        user_text,
        conversation_id,
        thinking_plan=effective_plan,
    )
    initial_events = [
        make_task_loop_event(TaskLoopEventType.STARTED, snapshot),
        make_task_loop_event(TaskLoopEventType.PLAN_UPDATED, snapshot),
    ]
    known_event_ids: List[str] = []
    output_layer = getattr(orch, "output", None)
    control_layer = getattr(orch, "control", None)

    async for chunk in stream_chat_auto_loop(
        snapshot,
        initial_events=initial_events,
        control_layer=control_layer,
        output_layer=output_layer,
        orchestrator_bridge=orch,
    ):
        workspace_updates: List[Dict[str, Any]] = []
        chunk_snapshot = chunk.snapshot
        if chunk.emit_update:
            event_ids, workspace_updates = _persist_stream_chunk_events(
                chunk.events,
                conversation_id=conversation_id,
                save_workspace_entry_fn=save_workspace_entry_fn,
            )
            if event_ids:
                known_event_ids.extend(event_ids)
            chunk_snapshot = (
                replace(chunk.snapshot, workspace_event_ids=list(known_event_ids))
                if known_event_ids
                else chunk.snapshot
            )
            yield (
                "",
                False,
                {
                    "type": "task_loop_update",
                    "state": chunk_snapshot.state.value,
                    "done_reason": chunk.done_reason,
                    "task_loop": chunk_snapshot.to_dict(),
                    "event_types": [str(event.get("type") or "") for event in chunk.events],
                    "events": _serialize_task_loop_events(chunk.events),
                    "is_final": chunk.is_final,
                    "step_runtime": dict(chunk.step_runtime or {}),
                },
            )
        store.put(chunk_snapshot)
        for workspace_update in workspace_updates:
            yield ("", False, workspace_update)
        if chunk.thinking_delta:
            yield (
                "",
                False,
                {
                    "type": "task_loop_thinking",
                    "chunk": chunk.thinking_delta,
                    "task_loop": chunk_snapshot.to_dict(),
                    "step_runtime": dict(chunk.step_runtime or {}),
                },
            )
        if chunk.content_delta:
            yield (chunk.content_delta, False, {"type": "content"})
        if chunk.is_final:
            log_info_fn(
                "[TaskLoop] handled streaming auto loop "
                f"state={chunk_snapshot.state.value} done_reason={chunk.done_reason}"
            )
            yield (
                "",
                True,
                {
                    "type": "done",
                    "done_reason": chunk.done_reason,
                    "task_loop": chunk_snapshot.to_dict(),
                },
            )
            return
