from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, List, Optional

from core.task_loop.contracts import (
    StopReason,
    TaskLoopSnapshot,
    TaskLoopState,
    transition_task_loop,
)
from core.task_loop.events import (
    TaskLoopEventType,
    make_task_loop_event,
    persist_task_loop_workspace_event,
)
from core.task_loop.runner import run_chat_auto_loop
from core.task_loop.planner import (
    build_task_loop_steps,
    create_task_loop_snapshot_from_plan,
)
from core.task_loop.store import TaskLoopStore, get_task_loop_store


@dataclass(frozen=True)
class TaskLoopChatTurn:
    content: str
    done_reason: str
    snapshot: TaskLoopSnapshot
    events: List[Dict[str, Any]]
    workspace_updates: List[Dict[str, Any]]


_EXPLICIT_TEXT_STARTERS = (
    "task-loop",
    "task loop",
    "taskloop",
    "trion task-loop",
    "trion task loop",
)
_EXPLICIT_TEXT_PHRASES = (
    "task-loop modus",
    "task loop modus",
    "im task-loop modus",
    "im task loop modus",
    "mit task-loop",
    "mit task loop",
    "im multistep modus",
    "multi-step modus",
    "multistep modus",
    "planungsmodus",
)

_CONTINUE_MARKERS = {
    "weiter",
    "weiter machen",
    "mach weiter",
    "fortsetzen",
    "continue",
    "go on",
    "ja",
    "ja bitte",
    "ok weiter",
    "okay weiter",
}

_CANCEL_MARKERS = {
    "stop",
    "stopp",
    "stoppen",
    "abbrechen",
    "cancel",
    "canceln",
    "beenden",
}


def is_task_loop_candidate(user_text: str, raw_request: Optional[Dict[str, Any]] = None) -> bool:
    raw = raw_request if isinstance(raw_request, dict) else {}
    flag = raw.get("task_loop") or raw.get("task_loop_candidate")
    mode = str(raw.get("task_loop_mode") or "").strip().lower()
    if flag is True or mode in {"start", "on", "chat"}:
        return True

    lower = " ".join(str(user_text or "").strip().lower().split())
    if not lower:
        return False
    command = lower.removeprefix("bitte ").strip()
    for starter in _EXPLICIT_TEXT_STARTERS:
        if command == starter or command.startswith(starter + ":") or command.startswith(starter + " "):
            return True
    return any(phrase in lower for phrase in _EXPLICIT_TEXT_PHRASES)


def is_task_loop_continue(user_text: str) -> bool:
    lower = " ".join(str(user_text or "").strip().lower().split())
    return lower in _CONTINUE_MARKERS


def is_task_loop_cancel(user_text: str) -> bool:
    lower = " ".join(str(user_text or "").strip().lower().split())
    return lower in _CANCEL_MARKERS


def should_restart_task_loop(
    user_text: str,
    raw_request: Optional[Dict[str, Any]] = None,
) -> bool:
    if is_task_loop_continue(user_text) or is_task_loop_cancel(user_text):
        return False
    return is_task_loop_candidate(user_text, raw_request)


def build_initial_chat_plan(user_text: str) -> List[str]:
    return [step.title for step in build_task_loop_steps(user_text)]


def create_task_loop_snapshot(
    user_text: str,
    conversation_id: str,
    *,
    thinking_plan: Optional[Dict[str, Any]] = None,
    max_steps: int = 4,
) -> TaskLoopSnapshot:
    return create_task_loop_snapshot_from_plan(
        user_text,
        conversation_id,
        thinking_plan=thinking_plan,
        max_steps=max_steps,
    )


def _format_plan(snapshot: TaskLoopSnapshot) -> str:
    lines = []
    completed = set(snapshot.completed_steps)
    for idx, step in enumerate(snapshot.current_plan, start=1):
        marker = "erledigt" if step in completed else "naechstes" if step == snapshot.pending_step else "offen"
        lines.append(f"{idx}. [{marker}] {step}")
    return "\n".join(lines)


def _persist_events(
    events: List[Dict[str, Any]],
    *,
    conversation_id: str,
    save_workspace_entry_fn: Optional[Callable[..., Optional[Dict[str, Any]]]],
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


def start_chat_task_loop(
    user_text: str,
    conversation_id: str,
    *,
    store: Optional[TaskLoopStore] = None,
    save_workspace_entry_fn: Optional[Callable[..., Optional[Dict[str, Any]]]] = None,
    max_steps: int = 4,
    auto_continue: bool = True,
    thinking_plan: Optional[Dict[str, Any]] = None,
) -> TaskLoopChatTurn:
    store = store or get_task_loop_store()
    snapshot = create_task_loop_snapshot(
        user_text,
        conversation_id,
        thinking_plan=thinking_plan,
        max_steps=max_steps,
    )
    events: List[Dict[str, Any]] = [
        make_task_loop_event(TaskLoopEventType.STARTED, snapshot),
        make_task_loop_event(TaskLoopEventType.PLAN_UPDATED, snapshot),
    ]

    if auto_continue:
        run = run_chat_auto_loop(snapshot, initial_events=events, max_steps=max_steps)
        event_ids, workspace_updates = _persist_events(
            run.events,
            conversation_id=conversation_id,
            save_workspace_entry_fn=save_workspace_entry_fn,
        )
        final_snapshot = replace(run.snapshot, workspace_event_ids=event_ids)
        store.put(final_snapshot)
        return TaskLoopChatTurn(
            content=run.content,
            done_reason=run.done_reason,
            snapshot=final_snapshot,
            events=run.events,
            workspace_updates=workspace_updates,
        )

    executing = transition_task_loop(snapshot, TaskLoopState.EXECUTING)
    events.append(make_task_loop_event(TaskLoopEventType.STEP_STARTED, executing))

    completed_step = executing.pending_step
    next_step = executing.current_plan[1] if len(executing.current_plan) > 1 else ""
    answered = replace(
        executing,
        step_index=1,
        completed_steps=[completed_step],
        pending_step=next_step,
    )
    answer = (
        "Task-Loop gestartet.\n\n"
        "Plan:\n"
        f"{_format_plan(answered)}\n\n"
        "Zwischenstand:\n"
        f"Schritt 1 abgeschlossen: {completed_step}\n\n"
        "Naechster Schritt:\n"
        f"{next_step or 'kein weiterer sicherer Schritt offen'}"
    )
    answered = replace(answered, last_user_visible_answer=answer)
    events.append(make_task_loop_event(TaskLoopEventType.STEP_COMPLETED, answered))

    if next_step:
        waiting = transition_task_loop(
            answered,
            TaskLoopState.WAITING_FOR_USER,
            stop_reason=StopReason.USER_DECISION_REQUIRED,
        )
        events.append(make_task_loop_event(TaskLoopEventType.WAITING_FOR_USER, waiting))
        answer += "\n\nIch warte auf `weiter`, `stoppen` oder eine Planaenderung."
        final_snapshot = replace(waiting, last_user_visible_answer=answer)
        done_reason = "task_loop_waiting_for_user"
    else:
        completed = transition_task_loop(answered, TaskLoopState.COMPLETED)
        events.append(make_task_loop_event(TaskLoopEventType.COMPLETED, completed))
        final_snapshot = replace(completed, last_user_visible_answer=answer)
        done_reason = "task_loop_completed"

    event_ids, workspace_updates = _persist_events(
        events,
        conversation_id=conversation_id,
        save_workspace_entry_fn=save_workspace_entry_fn,
    )
    final_snapshot = replace(final_snapshot, workspace_event_ids=event_ids)
    store.put(final_snapshot)
    return TaskLoopChatTurn(
        content=answer,
        done_reason=done_reason,
        snapshot=final_snapshot,
        events=events,
        workspace_updates=workspace_updates,
    )


def continue_chat_task_loop(
    snapshot: TaskLoopSnapshot,
    user_text: str,
    *,
    store: Optional[TaskLoopStore] = None,
    save_workspace_entry_fn: Optional[Callable[..., Optional[Dict[str, Any]]]] = None,
) -> TaskLoopChatTurn:
    store = store or get_task_loop_store()
    conversation_id = snapshot.conversation_id

    if is_task_loop_cancel(user_text):
        cancelled = transition_task_loop(
            snapshot,
            TaskLoopState.CANCELLED,
            stop_reason=StopReason.USER_CANCELLED,
        )
        events = [make_task_loop_event(TaskLoopEventType.CANCELLED, cancelled)]
        event_ids, workspace_updates = _persist_events(
            events,
            conversation_id=conversation_id,
            save_workspace_entry_fn=save_workspace_entry_fn,
        )
        cancelled = replace(cancelled, workspace_event_ids=snapshot.workspace_event_ids + event_ids)
        store.put(cancelled)
        return TaskLoopChatTurn(
            content="Task-Loop gestoppt. Es wurden keine weiteren Schritte ausgefuehrt.",
            done_reason="task_loop_cancelled",
            snapshot=cancelled,
            events=events,
            workspace_updates=workspace_updates,
        )

    if not is_task_loop_continue(user_text):
        waiting = replace(
            snapshot,
            stop_reason=StopReason.USER_DECISION_REQUIRED,
            last_user_visible_answer=(
                "Der Task-Loop wartet weiter.\n\n"
                "Sag `weiter`, `stoppen` oder beschreibe, wie der Plan geaendert werden soll."
            ),
        )
        events = [make_task_loop_event(TaskLoopEventType.WAITING_FOR_USER, waiting)]
        _, workspace_updates = _persist_events(
            events,
            conversation_id=conversation_id,
            save_workspace_entry_fn=save_workspace_entry_fn,
        )
        store.put(waiting)
        return TaskLoopChatTurn(
            content=waiting.last_user_visible_answer,
            done_reason="task_loop_waiting_for_user",
            snapshot=waiting,
            events=events,
            workspace_updates=workspace_updates,
        )

    executing = transition_task_loop(snapshot, TaskLoopState.EXECUTING, stop_reason=None)
    events = [make_task_loop_event(TaskLoopEventType.STEP_STARTED, executing)]
    completed_step = executing.pending_step or "Naechsten sicheren Schritt ausfuehren"
    completed_steps = list(executing.completed_steps)
    if completed_step not in completed_steps:
        completed_steps.append(completed_step)
    next_index = len(completed_steps)
    next_step = (
        executing.current_plan[next_index]
        if next_index < len(executing.current_plan)
        else ""
    )
    content = (
        "Zwischenstand:\n"
        f"Schritt {next_index} abgeschlossen: {completed_step}\n\n"
    )
    advanced = replace(
        executing,
        step_index=next_index,
        completed_steps=completed_steps,
        pending_step=next_step,
        last_user_visible_answer=content,
    )
    events.append(make_task_loop_event(TaskLoopEventType.STEP_COMPLETED, advanced))

    if next_step:
        waiting = transition_task_loop(
            advanced,
            TaskLoopState.WAITING_FOR_USER,
            stop_reason=StopReason.USER_DECISION_REQUIRED,
        )
        content += "Plan:\n" + _format_plan(waiting) + "\n\n"
        content += f"Naechster Schritt: {next_step}\n\nIch warte auf `weiter`, `stoppen` oder eine Planaenderung."
        final_snapshot = replace(waiting, last_user_visible_answer=content)
        events.append(make_task_loop_event(TaskLoopEventType.WAITING_FOR_USER, final_snapshot))
        done_reason = "task_loop_waiting_for_user"
    else:
        completed = transition_task_loop(advanced, TaskLoopState.COMPLETED)
        content += "Task-Loop abgeschlossen."
        final_snapshot = replace(completed, last_user_visible_answer=content)
        events.append(make_task_loop_event(TaskLoopEventType.COMPLETED, final_snapshot))
        done_reason = "task_loop_completed"

    event_ids, workspace_updates = _persist_events(
        events,
        conversation_id=conversation_id,
        save_workspace_entry_fn=save_workspace_entry_fn,
    )
    final_snapshot = replace(
        final_snapshot,
        workspace_event_ids=list(snapshot.workspace_event_ids) + event_ids,
    )
    store.put(final_snapshot)
    return TaskLoopChatTurn(
        content=content,
        done_reason=done_reason,
        snapshot=final_snapshot,
        events=events,
        workspace_updates=workspace_updates,
    )


def maybe_handle_chat_task_loop_turn(
    user_text: str,
    conversation_id: str,
    *,
    raw_request: Optional[Dict[str, Any]] = None,
    store: Optional[TaskLoopStore] = None,
    save_workspace_entry_fn: Optional[Callable[..., Optional[Dict[str, Any]]]] = None,
    thinking_plan: Optional[Dict[str, Any]] = None,
) -> Optional[TaskLoopChatTurn]:
    store = store or get_task_loop_store()
    active = store.get_active(conversation_id)
    if active is not None:
        if should_restart_task_loop(user_text, raw_request):
            raw = raw_request if isinstance(raw_request, dict) else {}
            mode = str(raw.get("task_loop_mode") or "").strip().lower()
            return start_chat_task_loop(
                user_text,
                conversation_id,
                store=store,
                save_workspace_entry_fn=save_workspace_entry_fn,
                auto_continue=mode not in {"manual", "step", "wait"},
                thinking_plan=thinking_plan,
            )
        return continue_chat_task_loop(
            active,
            user_text,
            store=store,
            save_workspace_entry_fn=save_workspace_entry_fn,
        )

    if not is_task_loop_candidate(user_text, raw_request):
        return None

    raw = raw_request if isinstance(raw_request, dict) else {}
    mode = str(raw.get("task_loop_mode") or "").strip().lower()
    return start_chat_task_loop(
        user_text,
        conversation_id,
        store=store,
        save_workspace_entry_fn=save_workspace_entry_fn,
        auto_continue=mode not in {"manual", "step", "wait"},
        thinking_plan=thinking_plan,
    )
