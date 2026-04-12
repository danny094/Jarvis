from __future__ import annotations

from typing import Any, Dict, Optional


async def build_task_loop_planning_context(
    orch: Any,
    user_text: str,
    *,
    tone_signal: Optional[Dict[str, Any]] = None,
    log_warn_fn: Any = None,
) -> Dict[str, Any]:
    try:
        thinking = getattr(orch, "thinking", None)
        analyze = getattr(thinking, "analyze", None)
        if analyze is None:
            return {}
        plan = await analyze(
            user_text,
            memory_context="",
            available_tools=[],
            tone_signal=tone_signal,
        )
        return plan if isinstance(plan, dict) else {}
    except Exception as exc:
        if log_warn_fn:
            log_warn_fn(f"[TaskLoop] Thinking planning context skipped: {exc}")
        return {}
