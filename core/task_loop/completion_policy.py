from __future__ import annotations

from intelligence_modules.prompt_manager import load_prompt

from core.task_loop.contracts import TaskLoopSnapshot


def _format_completion_plan(snapshot: TaskLoopSnapshot) -> str:
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


def is_task_loop_complete(snapshot: TaskLoopSnapshot) -> bool:
    return not str(snapshot.pending_step or "").strip()


def completion_detail(snapshot: TaskLoopSnapshot) -> str:
    if is_task_loop_complete(snapshot):
        return "plan_complete"
    return f"pending_step={str(snapshot.pending_step or '').strip()[:120]}"


def build_completion_message(snapshot: TaskLoopSnapshot) -> str:
    return "\n" + load_prompt(
        "task_loop",
        "status",
        plan_status=_format_completion_plan(snapshot),
    )


__all__ = [
    "build_completion_message",
    "completion_detail",
    "is_task_loop_complete",
]
