from __future__ import annotations

from dataclasses import replace
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from core.task_loop.chat_runtime import (
    create_task_loop_snapshot,
    is_task_loop_candidate,
    maybe_handle_chat_task_loop_turn,
)
from core.task_loop.events import (
    TaskLoopEventType,
    make_task_loop_event,
    persist_task_loop_workspace_event,
)
from core.task_loop.pipeline_adapter import build_task_loop_planning_context
from core.task_loop.runner import stream_chat_auto_loop
from core.task_loop.store import get_task_loop_store


def is_task_loop_request(user_text: str, request: Any) -> bool:
    conversation_id = str(getattr(request, "conversation_id", "") or "")
    store = get_task_loop_store()
    active = store.get_active(conversation_id) if conversation_id else None
    if active is not None:
        return True
    return is_task_loop_candidate(user_text, getattr(request, "raw_request", None))


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
) -> Optional[Any]:
    store = get_task_loop_store()
    active = store.get_active(conversation_id)
    if active is None and not is_task_loop_candidate(user_text, getattr(request, "raw_request", None)):
        return None
    thinking_plan = {}
    if active is None:
        thinking_plan = await build_task_loop_planning_context(
            orch,
            user_text,
            tone_signal=tone_signal,
            log_warn_fn=log_warn_fn,
        )
    result = maybe_handle_chat_task_loop_turn(
        user_text,
        conversation_id,
        raw_request=getattr(request, "raw_request", None),
        store=store,
        save_workspace_entry_fn=getattr(orch, "_save_workspace_entry", None),
        thinking_plan=thinking_plan,
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
) -> Optional[List[Tuple[str, bool, Dict[str, Any]]]]:
    store = get_task_loop_store()
    active = store.get_active(conversation_id)
    if active is None and not is_task_loop_candidate(user_text, getattr(request, "raw_request", None)):
        return None
    thinking_plan = {}
    if active is None:
        thinking_plan = await build_task_loop_planning_context(
            orch,
            user_text,
            tone_signal=tone_signal,
            log_warn_fn=log_warn_fn,
        )
    result = maybe_handle_chat_task_loop_turn(
        user_text,
        conversation_id,
        raw_request=getattr(request, "raw_request", None),
        store=store,
        save_workspace_entry_fn=getattr(orch, "_save_workspace_entry", None),
        thinking_plan=thinking_plan,
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
) -> AsyncGenerator[Tuple[str, bool, Dict[str, Any]], None]:
    store = get_task_loop_store()
    active = store.get_active(conversation_id)
    raw_request = getattr(request, "raw_request", None)
    if active is None and not is_task_loop_candidate(user_text, raw_request):
        return

    raw = raw_request if isinstance(raw_request, dict) else {}
    mode = str(raw.get("task_loop_mode") or "").strip().lower()
    manual_mode = active is not None or mode in {"manual", "step", "wait"}
    save_workspace_entry_fn = getattr(orch, "_save_workspace_entry", None)

    if manual_mode:
        result = maybe_handle_chat_task_loop_turn(
            user_text,
            conversation_id,
            raw_request=raw_request,
            store=store,
            save_workspace_entry_fn=save_workspace_entry_fn,
        )
        if result is None:
            return
        log_info_fn(
            "[TaskLoop] handled stream turn "
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

    thinking_plan = await build_task_loop_planning_context(
        orch,
        user_text,
        tone_signal=tone_signal,
        log_warn_fn=log_warn_fn,
    )
    snapshot = create_task_loop_snapshot(
        user_text,
        conversation_id,
        thinking_plan=thinking_plan,
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
                    "is_final": chunk.is_final,
                    "step_runtime": dict(chunk.step_runtime or {}),
                },
            )
        store.put(chunk_snapshot)
        for workspace_update in workspace_updates:
            yield ("", False, workspace_update)
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
