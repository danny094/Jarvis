from __future__ import annotations

from intelligence_modules.prompt_manager import load_prompt


def _msg_risk_gate(step_name: str) -> str:
    """Risk gate fired before executing a step (plan-level NEEDS_CONFIRMATION)."""
    return "\n" + load_prompt("task_loop", "risk_gate", step_name=step_name)


def _msg_control_soft_block(detail: str) -> str:
    """Control Layer denied the step but it's not a hard block."""
    return "\n" + load_prompt(
        "task_loop",
        "control_soft_block",
        detail_suffix=f": {detail}" if detail else "",
    )


def _msg_hard_block(detail: str) -> str:
    """Control Layer hard-blocked the step."""
    return "\n" + load_prompt(
        "task_loop",
        "hard_block",
        detail_suffix=f": {detail}" if detail else "",
    )


def _msg_waiting(detail: str) -> str:
    """Reflection loop decided it needs user input."""
    if detail:
        return f"\n{detail}"
    return "\n" + load_prompt("task_loop", "waiting")


def _msg_verify_before_complete(detail: str) -> str:
    """Loop adds a verification step before final completion."""
    return "\n" + load_prompt(
        "task_loop",
        "verify_before_complete",
        detail_line=str(detail or "").strip(),
    ).rstrip()


__all__ = [
    "_msg_control_soft_block",
    "_msg_hard_block",
    "_msg_risk_gate",
    "_msg_verify_before_complete",
    "_msg_waiting",
]
