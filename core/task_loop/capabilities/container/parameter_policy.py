"""Container parameter policy.

Ziel:
- fehlende Pflichtfelder bestimmen
- gezielte Rueckfrage fuer Container/Python-Container erzeugen
- keine Discovery-Entscheidungen, keine Recovery-Replans
"""

from __future__ import annotations

from typing import Any, Dict

from core.task_loop.capabilities.container.context import (
    capability_request_params,
    merge_container_context,
)
from core.task_loop.contracts import TaskLoopSnapshot
from intelligence_modules.prompt_manager import load_prompt


def build_container_parameter_context(
    snapshot: TaskLoopSnapshot,
    *,
    requested_capability: Dict[str, Any],
    selected_blueprint: Dict[str, Any] | None = None,
    capability_context: Dict[str, Any] | None = None,
    user_reply: str = "",
) -> Dict[str, Any]:
    capability_action = str(requested_capability.get("capability_action") or "").strip().lower()
    if capability_action != "request_container":
        return {
            "params": {},
            "missing_fields": [],
            "requires_user_input": False,
            "waiting_message": "",
        }

    selected_blueprint = dict(selected_blueprint or {})
    merged_context = merge_container_context(
        capability_context,
        snapshot=snapshot,
        user_reply=user_reply,
        selected_blueprint=selected_blueprint,
    )
    params = capability_request_params(merged_context)
    missing_fields: list[str] = []
    if not str(selected_blueprint.get("blueprint_id") or "").strip():
        missing_fields.append("blueprint")
    request_family = str(merged_context.get("request_family") or "generic_container").strip().lower()
    if request_family == "python_container":
        if not str(params.get("python_version") or "").strip():
            missing_fields.append("python_version")
        if not str(params.get("dependency_spec") or "").strip():
            missing_fields.append("dependency_spec")
        if not str(params.get("build_or_runtime") or "").strip():
            missing_fields.append("build_or_runtime")
    elif not any(key in params for key in ("cpu_cores", "ram", "gpu", "runtime")):
        missing_fields.append("ressourcenprofil")

    requires_user_input = bool(missing_fields)
    waiting_message = ""
    if requires_user_input:
        recognized_line = ""
        if params:
            recognized_line = load_prompt(
                "task_loop",
                "container_recognized_parameters",
                recognized_params=", ".join(f"{key}={value}" for key, value in params.items()),
            )
        if request_family == "python_container":
            waiting_message = load_prompt(
                "task_loop",
                "container_python_missing_parameters",
                recognized_line=recognized_line,
            )
        else:
            waiting_message = load_prompt(
                "task_loop",
                "container_generic_missing_parameters",
                recognized_line=recognized_line,
            )

    return {
        "params": params,
        "missing_fields": missing_fields,
        "requires_user_input": requires_user_input,
        "waiting_message": waiting_message,
    }


__all__ = ["build_container_parameter_context"]
