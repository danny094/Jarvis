"""Structured container capability context.

Ziel:
- capability context fuer Container/Python-Container bauen
- bekannte Felder aus Snapshot/Artifacts/User-Reply mergen
- keine Prompt-Ausgabe und keine Recovery-Texte
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from core.task_loop.capabilities.container.extractors import (
    extract_container_identity_fields,
    extract_container_request_fields,
    extract_python_container_fields,
)
from core.task_loop.capability_policy import capability_type_from_tools, normalized_tools
from core.task_loop.contracts import TaskLoopSnapshot

_GENERIC_PARAM_FIELDS = (
    "cpu_cores",
    "ram",
    "gpu",
    "runtime",
    "ports",
    "duration",
)

_PYTHON_PARAM_FIELDS = (
    "python_version",
    "dependency_spec",
    "build_or_runtime",
    "persistent_workdir",
)


def extract_container_capability_fields_from_text(text: Any) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    fields.update(extract_container_request_fields(text))
    fields.update(extract_container_identity_fields(text))
    fields.update(extract_python_container_fields(text))
    return {key: value for key, value in fields.items() if value not in (None, "", [], {})}


def _python_requested(user_text: str, intent: str, existing_context: Dict[str, Any]) -> bool:
    if bool(existing_context.get("python_requested")):
        return True
    text = f"{str(user_text or '').lower()} {str(intent or '').lower()}"
    return any(
        token in text
        for token in ("python", "pip", "requirements.txt", "jupyter", "scipy", "pandas", "numpy")
    )


def _active_container_known_fields(source: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    ctx = source.get("_active_container_capability_context")
    if not isinstance(ctx, dict):
        return {}
    known: Dict[str, Any] = {}
    container_id = str(ctx.get("container_id") or "").strip()
    blueprint_id = str(ctx.get("blueprint_id") or "").strip()
    image = str(ctx.get("image") or "").strip()
    if container_id:
        known["container_id"] = container_id
    if blueprint_id:
        known["blueprint"] = blueprint_id
    if image:
        known["image"] = image
    return known


def build_container_context(
    user_text: str,
    *,
    thinking_plan: Optional[Dict[str, Any]] = None,
    selected_tools: Optional[list[str]] = None,
    existing_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    plan = thinking_plan if isinstance(thinking_plan, dict) else {}
    tools = normalized_tools(selected_tools or list(plan.get("suggested_tools") or []))
    if capability_type_from_tools(tools) != "container_manager":
        return dict(existing_context or {})

    context = dict(existing_context or {})
    known_fields = dict(context.get("known_fields") or {})
    known_fields.update(_active_container_known_fields(plan))
    known_fields.update(extract_container_capability_fields_from_text(user_text))
    intent = str(plan.get("intent") or "").strip()
    python_requested = _python_requested(user_text, intent, context)

    return {
        "request_family": "python_container" if python_requested else "generic_container",
        "python_requested": python_requested,
        "known_fields": {k: v for k, v in known_fields.items() if v not in (None, "", [], {})},
    }


def merge_container_context(
    base_context: Optional[Dict[str, Any]],
    *,
    snapshot: Optional[TaskLoopSnapshot] = None,
    user_reply: str = "",
    selected_blueprint: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    merged = dict(base_context or {})
    known_fields = dict(merged.get("known_fields") or {})

    if snapshot is not None:
        snapshot_context = extract_container_context(snapshot)
        known_fields.update(dict(snapshot_context.get("known_fields") or {}))
        known_fields.update(_active_container_known_fields(dict(snapshot.system_state or {})))
        for artifact in reversed(list(snapshot.verified_artifacts or [])):
            if not isinstance(artifact, dict):
                continue
            if str(artifact.get("artifact_type") or "").strip().lower() != "container_request_params":
                continue
            params = artifact.get("params")
            if isinstance(params, dict):
                known_fields.update(dict(params))
                break

    if selected_blueprint and str(selected_blueprint.get("blueprint_id") or "").strip():
        known_fields["blueprint"] = str(selected_blueprint.get("blueprint_id") or "").strip()

    known_fields.update(extract_container_capability_fields_from_text(user_reply))
    merged["known_fields"] = {k: v for k, v in known_fields.items() if v not in (None, "", [], {})}
    if "request_family" not in merged:
        merged["request_family"] = "generic_container"
    if "python_requested" not in merged:
        merged["python_requested"] = bool(
            merged["request_family"] == "python_container"
            or any(key in merged["known_fields"] for key in _PYTHON_PARAM_FIELDS)
        )
    return merged


def extract_container_context(snapshot: TaskLoopSnapshot) -> Dict[str, Any]:
    """Read persisted container capability context from artifacts."""
    for artifact in reversed(list(snapshot.verified_artifacts or [])):
        if not isinstance(artifact, dict):
            continue
        if str(artifact.get("artifact_type") or "").strip().lower() != "container_capability_context":
            continue
        context = artifact.get("context")
        if isinstance(context, dict):
            return dict(context)
    return {}


def capability_known_fields(capability_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    context = capability_context if isinstance(capability_context, dict) else {}
    return {
        key: value
        for key, value in dict(context.get("known_fields") or {}).items()
        if value not in (None, "", [], {})
    }


def capability_request_params(capability_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    known_fields = capability_known_fields(capability_context)
    allowed = set(_GENERIC_PARAM_FIELDS) | set(_PYTHON_PARAM_FIELDS)
    return {key: value for key, value in known_fields.items() if key in allowed}


__all__ = [
    "build_container_context",
    "capability_known_fields",
    "capability_request_params",
    "extract_container_capability_fields_from_text",
    "extract_container_context",
    "merge_container_context",
]
