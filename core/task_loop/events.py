from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple

from core.task_loop.contracts import TaskLoopSnapshot


class TaskLoopEventType(str, Enum):
    STARTED = "task_loop_started"
    PLAN_UPDATED = "task_loop_plan_updated"
    STEP_STARTED = "task_loop_step_started"
    STEP_ANSWERED = "task_loop_step_answered"
    STEP_COMPLETED = "task_loop_step_completed"
    REFLECTION = "task_loop_reflection"
    WAITING_FOR_USER = "task_loop_waiting_for_user"
    BLOCKED = "task_loop_blocked"
    COMPLETED = "task_loop_completed"
    CANCELLED = "task_loop_cancelled"


TASK_LOOP_EVENT_TYPES = {item.value for item in TaskLoopEventType}


def make_task_loop_event(
    event_type: TaskLoopEventType,
    snapshot: TaskLoopSnapshot,
    *,
    event_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = snapshot.to_dict()
    if event_data:
        payload.update(event_data)
    return {
        "type": event_type.value,
        "source_layer": "task_loop",
        "objective_id": snapshot.objective_id,
        "conversation_id": snapshot.conversation_id,
        "plan_id": snapshot.plan_id,
        "step_index": snapshot.step_index,
        "state": snapshot.state.value,
        "stop_reason": snapshot.stop_reason.value if snapshot.stop_reason else None,
        "event_data": payload,
    }


def build_task_loop_workspace_summary(event: Dict[str, Any]) -> Tuple[str, str]:
    if not isinstance(event, dict):
        return ("task_loop_event", "invalid_event")

    event_type = str(event.get("type", "") or "").strip()
    if event_type not in TASK_LOOP_EVENT_TYPES:
        return ("task_loop_event", f"type={event_type or 'unknown'}")

    event_data = event.get("event_data", {})
    if not isinstance(event_data, dict):
        event_data = {}

    objective_id = str(event.get("objective_id") or event_data.get("objective_id") or "unknown")
    plan_id = str(event.get("plan_id") or event_data.get("plan_id") or "unknown")
    state = str(event.get("state") or event_data.get("state") or "unknown")
    step_index = event.get("step_index", event_data.get("step_index", "?"))
    pending_step = str(event_data.get("pending_step") or "").strip()
    stop_reason = str(event.get("stop_reason") or event_data.get("stop_reason") or "").strip()

    parts = [
        f"objective_id={objective_id}",
        f"plan_id={plan_id}",
        f"state={state}",
        f"step={step_index}",
    ]
    if pending_step:
        parts.append(f"pending={pending_step[:120]}")
    if stop_reason:
        parts.append(f"stop_reason={stop_reason}")
    return (event_type, " | ".join(parts))


def persist_task_loop_workspace_event(
    save_workspace_entry: Callable[..., Optional[Dict[str, Any]]],
    conversation_id: str,
    event: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if not conversation_id or not isinstance(event, dict):
        return None
    if str(event.get("type", "") or "").strip() not in TASK_LOOP_EVENT_TYPES:
        return None

    entry_type, content = build_task_loop_workspace_summary(event)
    return save_workspace_entry(
        conversation_id=conversation_id,
        content=content,
        entry_type=entry_type,
        source_layer="task_loop",
    )
