from __future__ import annotations

import unicodedata
from typing import Any

from core.task_loop.contracts import TaskLoopSnapshot
from intelligence_modules.prompt_manager import load_prompt


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().split())


def _blueprint_fields(row: dict[str, Any]) -> tuple[str, str]:
    blueprint_id = str(row.get("blueprint_id") or row.get("id") or row.get("name") or "").strip()
    label = str(row.get("name") or row.get("blueprint_id") or row.get("id") or "").strip() or blueprint_id
    return blueprint_id, label


def _row_search_blob(row: dict[str, Any]) -> str:
    tags = row.get("tags")
    tag_text = " ".join(str(item or "") for item in tags) if isinstance(tags, list) else str(tags or "")
    return _normalize(
        " ".join(
            [
                str(row.get("blueprint_id") or row.get("id") or ""),
                str(row.get("name") or ""),
                str(row.get("description") or ""),
                tag_text,
            ]
        )
    )


def extract_discovered_blueprints(snapshot: TaskLoopSnapshot) -> list[dict[str, Any]]:
    discovered: list[dict[str, Any]] = []
    for artifact in reversed(list(snapshot.verified_artifacts or [])):
        if not isinstance(artifact, dict):
            continue
        if str(artifact.get("artifact_type") or "").strip().lower() != "execution_result":
            continue
        metadata = artifact.get("metadata")
        if not isinstance(metadata, dict):
            continue
        evidence = metadata.get("grounding_evidence")
        if not isinstance(evidence, list):
            continue
        for item in evidence:
            if not isinstance(item, dict):
                continue
            if str(item.get("tool_name") or "").strip().lower() != "blueprint_list":
                continue
            structured = item.get("structured")
            rows = structured.get("blueprints") if isinstance(structured, dict) else None
            if isinstance(rows, list):
                discovered = [row for row in rows if isinstance(row, dict)]
                if discovered:
                    return discovered
    return discovered


def extract_selected_blueprint(snapshot: TaskLoopSnapshot) -> dict[str, str]:
    for artifact in reversed(list(snapshot.verified_artifacts or [])):
        if not isinstance(artifact, dict):
            continue
        if str(artifact.get("artifact_type") or "").strip().lower() != "blueprint_selection":
            continue
        blueprint_id = str(artifact.get("blueprint_id") or "").strip()
        label = str(artifact.get("content") or blueprint_id).strip()
        if blueprint_id:
            return {"blueprint_id": blueprint_id, "label": label}
    return {}


def resolve_blueprint_selection(
    snapshot: TaskLoopSnapshot,
    *,
    user_reply: str = "",
    capability_context: dict[str, Any] | None = None,
) -> dict[str, str]:
    selected = extract_selected_blueprint(snapshot)
    if selected:
        return selected
    candidates = extract_discovered_blueprints(snapshot)
    if not candidates:
        return {}
    reply = _normalize(user_reply)
    if reply:
        for row in candidates:
            blueprint_id, label = _blueprint_fields(row)
            if not blueprint_id:
                continue
            if _normalize(blueprint_id) in reply or (_normalize(label) and _normalize(label) in reply):
                return {"blueprint_id": blueprint_id, "label": label}
    request_family = str((capability_context or {}).get("request_family") or "").strip().lower()
    if request_family == "python_container":
        python_matches: list[dict[str, str]] = []
        for row in candidates:
            blueprint_id, label = _blueprint_fields(row)
            if not blueprint_id:
                continue
            blob = _row_search_blob(row)
            if "python" in blob:
                python_matches.append({"blueprint_id": blueprint_id, "label": label})
        unique_python_matches = {
            item["blueprint_id"]: item for item in python_matches if str(item.get("blueprint_id") or "").strip()
        }
        if len(unique_python_matches) == 1:
            return next(iter(unique_python_matches.values()))
    if len(candidates) == 1:
        blueprint_id, label = _blueprint_fields(candidates[0])
        if blueprint_id:
            return {"blueprint_id": blueprint_id, "label": label}
    return {}


def build_container_request_context(
    snapshot: TaskLoopSnapshot,
    *,
    requested_capability: dict[str, Any],
    user_reply: str = "",
    capability_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    capability_action = str(requested_capability.get("capability_action") or "").strip().lower()
    if capability_action != "request_container":
        return {
            "discovered_blueprints": [],
            "selected_blueprint": {},
            "requires_user_choice": False,
            "waiting_message": "",
        }
    discovered = extract_discovered_blueprints(snapshot)
    selected = resolve_blueprint_selection(
        snapshot,
        user_reply=user_reply,
        capability_context=capability_context,
    )
    # Pausieren wenn Blueprints bekannt aber keine eindeutige Auswahl:
    # - mehrere Optionen und keine Auswahl → User soll wählen
    # - genau eine Option aber kein Match (z.B. kein Python-Blueprint) → User informieren
    requires_user_choice = bool(discovered) and not selected
    if requires_user_choice:
        options = ", ".join(
            label
            for label in (
                _blueprint_fields(row)[1]
                for row in discovered[:6]
            )
            if label
        )
        if len(discovered) > 1:
            waiting_message = load_prompt(
                "task_loop",
                "container_blueprint_choice",
                options=options,
            )
        else:
            waiting_message = load_prompt(
                "task_loop",
                "container_single_blueprint_choice",
                options=options,
            )
    else:
        waiting_message = ""
    return {
        "discovered_blueprints": discovered,
        "selected_blueprint": selected,
        "requires_user_choice": requires_user_choice,
        "waiting_message": waiting_message,
    }


__all__ = [
    "build_container_request_context",
    "extract_discovered_blueprints",
    "extract_selected_blueprint",
    "resolve_blueprint_selection",
]
