"""
Helpers for workspace timeline summaries/persistence.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Tuple


def build_sequential_workspace_summary(event: Dict[str, Any]) -> Tuple[str, str]:
    """
    Build compact planning telemetry rows for workspace_events.
    Returns tuple: (entry_type, content).
    """
    if not isinstance(event, dict):
        return ("planning_event", "invalid_event")

    event_type = str(event.get("type", "") or "").strip()
    task_id = str(event.get("task_id", "") or "").strip()

    if event_type == "sequential_start":
        complexity = event.get("complexity", "unknown")
        reasoning_type = str(event.get("reasoning_type", "unknown") or "unknown").strip()
        parts = [f"task_id={task_id or 'unknown'}", f"complexity={complexity}", f"reasoning_type={reasoning_type}"]
        return ("planning_start", " | ".join(parts))

    if event_type == "sequential_step":
        step_number = event.get("step_number") or event.get("step_num") or event.get("step") or "?"
        title = str(event.get("title", "") or "").strip()
        thought = str(event.get("thought", "") or event.get("content", "") or "").strip()
        thought_len = len(thought)
        parts = [f"task_id={task_id or 'unknown'}", f"step={step_number}"]
        if title:
            parts.append(f"title={title[:80]}")
        parts.append(f"thought_len={thought_len}")
        return ("planning_step", " | ".join(parts))

    if event_type == "sequential_done":
        steps = event.get("steps", [])
        step_count = len(steps) if isinstance(steps, list) else 0
        summary = str(event.get("summary", "") or "").strip()
        parts = [f"task_id={task_id or 'unknown'}", f"steps={step_count}"]
        if summary:
            parts.append(f"summary={summary[:120]}")
        return ("planning_done", " | ".join(parts))

    if event_type == "sequential_error":
        error_text = str(event.get("error", "unknown") or "unknown").strip()
        return ("planning_error", f"task_id={task_id or 'unknown'} | error={error_text[:200]}")

    return ("planning_event", f"task_id={task_id or 'unknown'} | type={event_type or 'unknown'}")


def persist_sequential_workspace_event(
    save_workspace_entry: Callable[..., Optional[Dict[str, Any]]],
    conversation_id: str,
    event: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Persist sequential planning milestones to workspace_events.
    Returns workspace_update SSE payload or None.
    """
    if not conversation_id or not isinstance(event, dict):
        return None
    event_type = str(event.get("type", "") or "").strip()
    if event_type not in {"sequential_start", "sequential_step", "sequential_done", "sequential_error"}:
        return None

    entry_type, content = build_sequential_workspace_summary(event)
    return save_workspace_entry(
        conversation_id=conversation_id,
        content=content,
        entry_type=entry_type,
        source_layer="sequential",
    )
