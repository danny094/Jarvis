from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, List, Optional

from intelligence_modules.prompt_manager import load_prompt

from core.task_loop.contracts import (
    TERMINAL_STATES,
    StopReason,
    TaskLoopSnapshot,
    TaskLoopState,
    TaskLoopStepExecutionSource,
    TaskLoopStepStatus,
    TaskLoopStepType,
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

# Two-part semantic detector: any verb × any noun → tool call required
_TOOL_INSPECTION_VERBS = (
    # German
    "siehst du", "hast du", "kannst du", "zeig mir", "zeige mir",
    "zeigst du", "liste", "listet", "schau", "check",
    "was für", "welche", "welches", "welchen", "welchem",
    "gibt es", "sind da", "laufen",
    # English
    "show me", "list", "what are your", "do you have", "can you see",
    "which", "what",
)

_TOOL_DOMAIN_NOUNS = (
    "api key", "api keys",
    "secret", "secrets",
    "skill", "skills",
    "container",
    "cron", "cron job", "cron jobs",
    "blueprint", "blueprints",
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
    "freigeben",
    "freigabe",
    "genehmigen",
    "approve",
    "ok",
    "okay",
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
    if has_explicit_task_loop_signal(user_text, raw_request):
        return True

    flag = raw.get("task_loop_candidate")
    if flag is True:
        return True

    lower = " ".join(str(user_text or "").strip().lower().split())
    if not lower:
        return False

    # Semantic: interrogative/inspection verb + tool-domain noun -> tool call needed
    has_verb = any(v in lower for v in _TOOL_INSPECTION_VERBS)
    has_noun = any(n in lower for n in _TOOL_DOMAIN_NOUNS)
    return has_verb and has_noun


def has_explicit_task_loop_signal(
    user_text: str,
    raw_request: Optional[Dict[str, Any]] = None,
) -> bool:
    raw = raw_request if isinstance(raw_request, dict) else {}
    flag = raw.get("task_loop")
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
    if any(phrase in lower for phrase in _EXPLICIT_TEXT_PHRASES):
        return True
    return False


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
    return has_explicit_task_loop_signal(user_text, raw_request)


def build_initial_chat_plan(user_text: str) -> List[str]:
    return [step.title for step in build_task_loop_steps(user_text)]


def create_task_loop_snapshot(
    user_text: str,
    conversation_id: str,
    *,
    thinking_plan: Optional[Dict[str, Any]] = None,
    max_steps: int = 5,
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


def _needs_concrete_input(snapshot: TaskLoopSnapshot) -> bool:
    """True wenn der aktuelle Step auf konkrete User-Parameter wartet.

    Ein einfaches "weiter" reicht in diesem Fall nicht — der User muss
    die offene Frage inhaltlich beantworten.
    """
    if isinstance(snapshot.last_step_result, dict):
        status = str(snapshot.last_step_result.get("status") or "").strip().lower()
        source = str(snapshot.last_step_result.get("step_execution_source") or "").strip().lower()
        step_type = str(snapshot.last_step_result.get("step_type") or "").strip().lower()
    else:
        status = snapshot.current_step_status.value
        source = snapshot.step_execution_source.value
        step_type = snapshot.current_step_type.value

    if status != TaskLoopStepStatus.WAITING_FOR_USER.value:
        return False
    return step_type in {
        TaskLoopStepType.TOOL_REQUEST.value,
        TaskLoopStepType.TOOL_EXECUTION.value,
    } or source in {
        TaskLoopStepExecutionSource.ORCHESTRATOR.value,
        TaskLoopStepExecutionSource.APPROVAL.value,
    }



def start_chat_task_loop(
    user_text: str,
    conversation_id: str,
    *,
    store: Optional[TaskLoopStore] = None,
    save_workspace_entry_fn: Optional[Callable[..., Optional[Dict[str, Any]]]] = None,
    plan_steps: int = 5,
    auto_continue: bool = True,
    thinking_plan: Optional[Dict[str, Any]] = None,
) -> TaskLoopChatTurn:
    store = store or get_task_loop_store()
    snapshot = create_task_loop_snapshot(
        user_text,
        conversation_id,
        thinking_plan=thinking_plan,
        max_steps=plan_steps,
    )
    events: List[Dict[str, Any]] = [
        make_task_loop_event(TaskLoopEventType.STARTED, snapshot),
        make_task_loop_event(TaskLoopEventType.PLAN_UPDATED, snapshot),
    ]

    if auto_continue:
        run = run_chat_auto_loop(snapshot, initial_events=events)
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
        "Der Task-Loop laeuft jetzt.\n\n"
        f"{_format_plan(answered)}\n\n"
        f"Schritt 1 ist abgeschlossen: {completed_step}\n"
        f"Als naechstes kommt: {next_step or 'kein weiterer sicherer Schritt offen'}"
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
        answer += "\n\nIch warte jetzt auf `weiter`, `stoppen` oder eine Planaenderung."
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

    # Terminal-Guard: bereits abgeschlossene oder abgebrochene Loops unveraendert zurueckgeben
    if snapshot.state in TERMINAL_STATES:
        return TaskLoopChatTurn(
            content=snapshot.last_user_visible_answer,
            done_reason=(
                "task_loop_completed"
                if snapshot.state == TaskLoopState.COMPLETED
                else "task_loop_cancelled"
            ),
            snapshot=snapshot,
            events=[],
            workspace_updates=[],
        )

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

    # Wenn der aktuelle Step auf konkrete Parameter wartet (z.B. Blueprintauswahl,
    # Container-Parameter) und der User nur "weiter" schreibt: nicht weiter —
    # der User muss die Frage inhaltlich beantworten.
    # Schreibt der User eine echte Antwort, wird sie als resume_user_text verwendet.
    resume_text = "" if is_task_loop_continue(user_text) else user_text
    if not resume_text and _needs_concrete_input(snapshot):
        waiting = replace(
            snapshot,
            last_user_visible_answer=load_prompt("task_loop", "clarification"),
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

    # Alles andere: Loop mit User-Text als Kontext fortsetzen.
    # "weiter"/"ja"/"ok" → leerer resume_text (kein spezifischer Kontext noetig)
    # Echte Antwort → wird als resume_user_text in den naechsten Step eingespeist
    executing = transition_task_loop(snapshot, TaskLoopState.EXECUTING)
    run = run_chat_auto_loop(
        executing,
        resume_user_text=resume_text,
    )
    event_ids, workspace_updates = _persist_events(
        run.events,
        conversation_id=conversation_id,
        save_workspace_entry_fn=save_workspace_entry_fn,
    )
    final_snapshot = replace(
        run.snapshot,
        workspace_event_ids=list(snapshot.workspace_event_ids) + event_ids,
    )
    store.put(final_snapshot)
    return TaskLoopChatTurn(
        content=run.content,
        done_reason=run.done_reason,
        snapshot=final_snapshot,
        events=run.events,
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
    force_start: bool = False,
) -> Optional[TaskLoopChatTurn]:
    store = store or get_task_loop_store()
    active = store.get_active(conversation_id)
    if active is not None:
        if force_start or should_restart_task_loop(user_text, raw_request):
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

    if not force_start and not is_task_loop_candidate(user_text, raw_request):
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
