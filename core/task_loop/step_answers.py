from __future__ import annotations

from typing import Any, Dict, List

from intelligence_modules.prompt_manager import load_prompt


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _title_focus(title: str) -> str:
    if ":" not in title:
        return _text(title)
    return _text(title.split(":", 1)[1])


def _objective(meta: Dict[str, Any], step: str) -> str:
    objective = _text(meta.get("objective"))
    return (objective or _title_focus(step) or _text(step)).rstrip(" .!?:;")


def _prior_context(completed_steps: List[str]) -> str:
    if not completed_steps:
        return "Es gibt noch keinen vorherigen Loop-Schritt."
    cleaned = [_text(step).rstrip(" .!?:;") for step in completed_steps]
    return "Bisher abgeschlossen: " + "; ".join(cleaned) + "."


def _validation_answer(
    step_index: int,
    step: str,
    meta: Dict[str, Any],
    completed_steps: List[str],
) -> str:
    objective = _objective(meta, step)
    if step_index == 1:
        return load_prompt("task_loop", "chat_validation_step_1", objective=objective)
    if step_index == 2:
        return load_prompt("task_loop", "chat_validation_step_2")
    if step_index == 3:
        return load_prompt(
            "task_loop",
            "chat_validation_step_3",
            prior_context=_prior_context(completed_steps),
        )
    return load_prompt("task_loop", "chat_validation_fallback")


def _implementation_answer(
    step_index: int,
    step: str,
    meta: Dict[str, Any],
    completed_steps: List[str],
) -> str:
    objective = _objective(meta, step)
    if step_index == 1:
        return load_prompt("task_loop", "chat_implementation_step_1", objective=objective)
    if step_index == 2:
        return load_prompt("task_loop", "chat_implementation_step_2")
    if step_index == 3:
        return load_prompt(
            "task_loop",
            "chat_implementation_step_3",
            prior_context=_prior_context(completed_steps),
        )
    return load_prompt("task_loop", "chat_implementation_fallback")


def _analysis_answer(
    step_index: int,
    step: str,
    meta: Dict[str, Any],
    completed_steps: List[str],
) -> str:
    objective = _objective(meta, step)
    if step_index == 1:
        return load_prompt("task_loop", "chat_analysis_step_1", objective=objective)
    if step_index == 2:
        return load_prompt("task_loop", "chat_analysis_step_2")
    if step_index == 3:
        return load_prompt(
            "task_loop",
            "chat_analysis_step_3",
            prior_context=_prior_context(completed_steps),
        )
    return load_prompt("task_loop", "chat_analysis_fallback")


def _default_answer(
    step_index: int,
    step: str,
    meta: Dict[str, Any],
    completed_steps: List[str],
) -> str:
    objective = _objective(meta, step)
    if step_index == 1:
        return load_prompt("task_loop", "chat_default_step_1", objective=objective)
    if step_index == 2:
        return load_prompt("task_loop", "chat_default_step_2")
    if step_index == 3:
        return load_prompt(
            "task_loop",
            "chat_default_step_3",
            prior_context=_prior_context(completed_steps),
        )
    return load_prompt("task_loop", "chat_default_fallback")


def answer_for_chat_step(
    step_index: int,
    step: str,
    meta: Dict[str, Any],
    completed_steps: List[str],
) -> str:
    kind = _text(meta.get("task_kind")) or "default"
    if kind == "validation":
        return _validation_answer(step_index, step, meta, completed_steps)
    if kind == "implementation":
        return _implementation_answer(step_index, step, meta, completed_steps)
    if kind == "analysis":
        return _analysis_answer(step_index, step, meta, completed_steps)
    return _default_answer(step_index, step, meta, completed_steps)
