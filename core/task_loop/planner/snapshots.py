from __future__ import annotations

from hashlib import sha256
from typing import Any, Dict, Optional

from core.task_loop.contracts import (
    RiskLevel,
    TaskLoopSnapshot,
    TaskLoopStepExecutionSource,
    TaskLoopStepStatus,
    TaskLoopStepType,
)
from core.task_loop.planner.objective import clean_task_loop_objective
from core.task_loop.planner.steps import build_task_loop_steps


def _snapshot_system_state(thinking_plan: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    plan = thinking_plan if isinstance(thinking_plan, dict) else {}
    state: Dict[str, Any] = {}
    for key in (
        "_active_container_capability_context",
        "_container_capability_context",
        "_global_active_containers",
        "active_containers_context",
    ):
        value = plan.get(key)
        if isinstance(value, (dict, list)):
            state[key] = value
    return state


def create_task_loop_snapshot_from_plan(
    user_text: str,
    conversation_id: str,
    *,
    thinking_plan: Optional[Dict[str, Any]] = None,
    max_steps: int = 5,
) -> TaskLoopSnapshot:
    seed = f"{conversation_id}:{user_text}".encode("utf-8", errors="ignore")
    suffix = sha256(seed).hexdigest()[:12]
    steps = build_task_loop_steps(user_text, thinking_plan=thinking_plan, max_steps=max_steps)
    plan_titles = [step.title for step in steps]
    first = plan_titles[0] if plan_titles else ""
    objective_summary = clean_task_loop_objective(user_text)
    return TaskLoopSnapshot(
        objective_id=f"obj-{suffix}",
        conversation_id=conversation_id or "global",
        plan_id=f"plan-{suffix}",
        current_step_id=steps[0].step_id if steps else "",
        current_step_type=steps[0].step_type if steps else TaskLoopStepType.ANALYSIS,
        current_step_status=TaskLoopStepStatus.PENDING,
        step_execution_source=TaskLoopStepExecutionSource.LOOP,
        current_plan=plan_titles,
        plan_steps=[step.to_dict() for step in steps],
        pending_step=first,
        risk_level=RiskLevel.SAFE,
        objective_summary=objective_summary,
        system_state=_snapshot_system_state(thinking_plan),
    )


__all__ = ["create_task_loop_snapshot_from_plan"]
