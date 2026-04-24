from __future__ import annotations

from typing import Any, Dict, List

from intelligence_modules.prompt_manager import load_prompt

from core.task_loop.action_resolution.read_first_policy import split_read_vs_action_tools
from core.task_loop.contracts import (
    TaskLoopSnapshot,
    TaskLoopStepRequest,
    TaskLoopStepStatus,
    TaskLoopStepType,
)
from core.task_loop.step_runtime.render_contract import (
    claim_guard_block,
    focus_block,
    output_shape_block,
    response_style_block,
)


def _clip(text: Any, limit: int = 400) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


def _step_type_from_meta(step_meta: Dict[str, Any]) -> TaskLoopStepType:
    raw = str(step_meta.get("step_type") or "").strip().lower()
    try:
        return TaskLoopStepType(raw)
    except Exception:
        return TaskLoopStepType.ANALYSIS


def _requested_capability(step_meta: Dict[str, Any]) -> Dict[str, Any]:
    raw = step_meta.get("requested_capability")
    return dict(raw) if isinstance(raw, dict) else {}


def _suggested_tools(step_meta: Dict[str, Any]) -> List[str]:
    return [
        str(item or "").strip()
        for item in step_meta.get("suggested_tools") or []
        if str(item or "").strip()
    ]


def _latest_user_reply_from_artifacts(snapshot: TaskLoopSnapshot) -> str:
    for artifact in reversed(list(snapshot.verified_artifacts or [])):
        if not isinstance(artifact, dict):
            continue
        if str(artifact.get("artifact_type") or "").strip().lower() != "user_reply":
            continue
        return str(artifact.get("content") or "").strip()
    return ""


def _effective_step_status(snapshot: TaskLoopSnapshot, step_type: TaskLoopStepType) -> TaskLoopStepStatus:
    current_status = snapshot.current_step_status
    if current_status is not TaskLoopStepStatus.RUNNING:
        return current_status
    last_result = snapshot.last_step_result if isinstance(snapshot.last_step_result, dict) else {}
    last_type = str(last_result.get("step_type") or "").strip().lower()
    last_status = str(last_result.get("status") or "").strip().lower()
    if last_type == step_type.value:
        try:
            return TaskLoopStepStatus(last_status)
        except Exception:
            return current_status
    return current_status


def _latest_selected_blueprint(snapshot: TaskLoopSnapshot) -> Dict[str, str]:
    for artifact in reversed(list(snapshot.verified_artifacts or [])):
        if not isinstance(artifact, dict):
            continue
        if str(artifact.get("artifact_type") or "").strip().lower() != "blueprint_selection":
            continue
        blueprint_id = str(artifact.get("blueprint_id") or "").strip()
        label = str(artifact.get("content") or blueprint_id).strip()
        if blueprint_id or label:
            return {"blueprint_id": blueprint_id, "label": label or blueprint_id}
    return {}


def _latest_request_params(snapshot: TaskLoopSnapshot) -> Dict[str, Any]:
    for artifact in reversed(list(snapshot.verified_artifacts or [])):
        if not isinstance(artifact, dict):
            continue
        if str(artifact.get("artifact_type") or "").strip().lower() != "container_request_params":
            continue
        params = artifact.get("params")
        if isinstance(params, dict) and params:
            return dict(params)
    return {}


def _latest_execution_result(snapshot: TaskLoopSnapshot) -> Dict[str, Any]:
    for artifact in reversed(list(snapshot.verified_artifacts or [])):
        if not isinstance(artifact, dict):
            continue
        if str(artifact.get("artifact_type") or "").strip().lower() != "execution_result":
            continue
        return dict(artifact)
    return {}


def _format_tool_statuses(execution_result: Dict[str, Any]) -> str:
    compact: List[str] = []
    for row in list(execution_result.get("tool_statuses") or []):
        if not isinstance(row, dict):
            continue
        tool_name = str(row.get("tool_name") or row.get("tool") or "").strip()
        status = str(row.get("status") or "").strip().lower()
        if not tool_name and not status:
            continue
        if tool_name and status:
            compact.append(f"{tool_name}={status}")
        else:
            compact.append(tool_name or status)
        if len(compact) >= 4:
            break
    return ", ".join(compact)


def _grounding_fact_lines(execution_result: Dict[str, Any]) -> List[str]:
    metadata = execution_result.get("metadata")
    if not isinstance(metadata, dict):
        return []
    facts: List[str] = []
    for item in list(metadata.get("grounding_evidence") or []):
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool_name") or "").strip()
        status = str(item.get("status") or "").strip().lower()
        key_facts = [
            _clip(fact, 120)
            for fact in list(item.get("key_facts") or [])
            if str(fact or "").strip()
        ]
        if not key_facts:
            structured = item.get("structured")
            if isinstance(structured, dict):
                if isinstance(structured.get("blueprints"), list):
                    names = [
                        str(row.get("name") or row.get("blueprint_id") or "").strip()
                        for row in structured.get("blueprints") or []
                        if isinstance(row, dict) and str(row.get("name") or row.get("blueprint_id") or "").strip()
                    ]
                    if names:
                        key_facts = ["Blueprints: " + ", ".join(names[:4])]
                elif isinstance(structured.get("containers"), list):
                    names = [
                        str(row.get("name") or row.get("container_id") or "").strip()
                        for row in structured.get("containers") or []
                        if isinstance(row, dict) and str(row.get("name") or row.get("container_id") or "").strip()
                    ]
                    if names:
                        key_facts = ["Container: " + ", ".join(names[:4])]
                else:
                    for key in ("output", "result", "description", "status", "name"):
                        value = structured.get(key)
                        if str(value or "").strip():
                            key_facts = [_clip(value, 120)]
                            break
        if not key_facts:
            continue
        prefix = tool_name or "tool"
        if status:
            prefix = f"{prefix} [{status}]"
        facts.append(f"{prefix}: {'; '.join(key_facts[:3])}")
        if len(facts) >= 3:
            break
    return facts


def _execution_result_context_lines(snapshot: TaskLoopSnapshot) -> List[str]:
    execution_result = _latest_execution_result(snapshot)
    if not execution_result:
        return []

    lines: List[str] = []
    done_reason = str(execution_result.get("done_reason") or "").strip().lower()
    if done_reason:
        lines.append(f"Zuletzt verifizierter Tool-Status: {done_reason}")

    tool_statuses = _format_tool_statuses(execution_result)
    if tool_statuses:
        lines.append(f"Letzte Tool-Statuses: {tool_statuses}")

    direct_response = str(execution_result.get("direct_response") or "").strip()
    if direct_response:
        lines.append(f"Zuletzt verifizierte Tool-Antwort: {_clip(direct_response, 220)}")

    grounding_lines = _grounding_fact_lines(execution_result)
    if grounding_lines:
        lines.append("Verifizierte Tool-Fakten:")
        lines.extend(f"- {line}" for line in grounding_lines)
    return lines


def _verified_context_block(snapshot: TaskLoopSnapshot, *, user_reply: str = "") -> str:
    lines: List[str] = []
    if str(user_reply or "").strip():
        lines.append(f"Neue User-Antwort fuer diesen offenen Schritt: {str(user_reply).strip()}")
    else:
        latest_user_reply = _latest_user_reply_from_artifacts(snapshot)
        if latest_user_reply:
            lines.append(f"Zuletzt bestaetigte User-Angabe: {latest_user_reply}")
    selected_blueprint = _latest_selected_blueprint(snapshot)
    selected_label = str(selected_blueprint.get("label") or selected_blueprint.get("blueprint_id") or "").strip()
    if selected_label:
        lines.append(f"Aktuell gewaehlter Blueprint: {selected_label}")
    request_params = _latest_request_params(snapshot)
    if request_params:
        lines.append(
            "Erkannte Request-Parameter: " + ", ".join(f"{key}={value}" for key, value in request_params.items())
        )
    lines.extend(_execution_result_context_lines(snapshot))
    if not lines:
        return ""
    return "\n".join(lines) + "\n\n"


def _next_step_guard_block(
    step_title: str,
    snapshot: TaskLoopSnapshot,
) -> str:
    current_plan = list(snapshot.current_plan or [])
    plan_steps = [dict(step) for step in list(snapshot.plan_steps or []) if isinstance(step, dict)]
    try:
        current_index = current_plan.index(step_title)
    except ValueError:
        current_index = int(snapshot.step_index or 0)
    next_index = current_index + 1
    if next_index >= len(current_plan):
        return ""

    next_title = str(current_plan[next_index] or "").strip()
    next_step_meta = plan_steps[next_index] if next_index < len(plan_steps) else {}
    next_step_type = str(next_step_meta.get("step_type") or "").strip()
    next_tools = [
        str(item or "").strip()
        for item in next_step_meta.get("suggested_tools") or []
        if str(item or "").strip()
    ]
    lines = [f"Geplanter Folgeschritt: {next_title or 'unbekannt'}"]
    if next_step_type:
        lines.append(f"Geplanter Folgeschritt-Typ: {next_step_type}")
    if next_tools:
        lines.append("Geplante Folgeschritt-Tools: " + ", ".join(next_tools))
    query_tools, action_tools = split_read_vs_action_tools(next_tools)
    if next_step_type == TaskLoopStepType.TOOL_EXECUTION.value and query_tools and not action_tools:
        lines.append(
            "Vor einer User-Rueckfrage wird zuerst dieser sichere Discovery-Schritt ausgefuehrt."
        )
    return "\n".join(lines) + "\n\n"


def _system_addon_context_block(step_request: TaskLoopStepRequest | None) -> str:
    if step_request is None:
        return ""
    cap_ctx = dict(step_request.capability_context or {})
    ctx = str(cap_ctx.get("system_addon_context") or "").strip()
    if not ctx:
        return ""
    docs = [str(d).strip() for d in list(cap_ctx.get("system_addon_docs") or []) if str(d).strip()]
    lines = ["SYSTEM-SELBSTWISSEN (statische Fakten — kein Live-Zustand):"]
    if docs:
        lines.append(f"Quellen: {', '.join(docs)}")
    lines.append(ctx)
    lines.append(
        "Hinweis: Diese Fakten beschreiben wo Daten liegen und wie Services erreichbar sind. "
        "Live-Zustand (ob ein Service läuft) kommt ausschließlich aus Tool-Ergebnissen."
    )
    return "\n".join(lines) + "\n\n"


def _auto_clarify_block(step_request: TaskLoopStepRequest | None) -> str:
    if step_request is None:
        return ""
    reasoning_context = dict(step_request.reasoning_context or {})
    mode = str(reasoning_context.get("auto_clarify_mode") or "").strip()
    if not mode:
        return ""

    lines: List[str] = [f"Auto-Clarify-Entscheid: {mode}"]
    resolved_fields = list(reasoning_context.get("auto_clarify_resolved_fields") or [])
    if resolved_fields:
        compact = []
        for item in resolved_fields:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            compact.append(f"{name}={item.get('value')}")
        if compact:
            lines.append("Sicher ergaenzte oder bestaetigte Felder: " + ", ".join(compact))
    missing_fields = [
        str(item or "").strip()
        for item in reasoning_context.get("auto_clarify_missing_fields") or []
        if str(item or "").strip()
    ]
    if missing_fields:
        lines.append("Noch offen: " + ", ".join(missing_fields))
    next_tools = [
        str(item or "").strip()
        for item in reasoning_context.get("auto_clarify_next_tools") or []
        if str(item or "").strip()
    ]
    if next_tools:
        lines.append("Auto-Clarify naechster sicherer Schritt: " + ", ".join(next_tools))
    if mode == "self_discover":
        lines.append(
            "Frage den User noch nicht nach diesen Feldern, solange der sichere Discovery-Schritt noch aussteht."
        )
    elif mode == "ask_user":
        ask_user_message = str(reasoning_context.get("auto_clarify_ask_user_message") or "").strip()
        if ask_user_message:
            lines.append("Gezielte Rueckfrage nur falls weiterhin noetig: " + ask_user_message)
    return "\n".join(lines) + "\n\n"


def build_task_loop_step_prompt(
    step_title: str,
    step_meta: Dict[str, Any],
    snapshot: TaskLoopSnapshot,
    *,
    user_reply: str = "",
    step_request: TaskLoopStepRequest | None = None,
) -> str:
    objective = str(step_meta.get("objective") or "").strip() or snapshot.pending_step.strip() or "Aufgabe"
    goal = str(step_meta.get("goal") or "").strip()
    done_criteria = str(step_meta.get("done_criteria") or "").strip()
    step_type = _step_type_from_meta(step_meta)
    suggested_tools = _suggested_tools(step_meta)
    completed = [str(item or "").strip() for item in snapshot.completed_steps if str(item or "").strip()]
    completed_text = ", ".join(completed) if completed else "keiner"
    current_step_index = int(snapshot.step_index or 0) + 1
    total_steps = max(len(snapshot.current_plan), current_step_index)
    verified_context_block = _verified_context_block(snapshot, user_reply=user_reply)
    next_step_guard_block = _next_step_guard_block(step_title, snapshot)
    auto_clarify_block = _auto_clarify_block(step_request)
    system_addon_block = _system_addon_context_block(step_request)
    response_style = response_style_block(step_type)

    return load_prompt(
        "task_loop",
        "step_runtime",
        current_step_index=current_step_index,
        total_steps=total_steps,
        objective=objective,
        step_title=step_title,
        step_type=step_type.value,
        goal=goal or "Konkreten Zwischenstand fuer diesen Schritt liefern.",
        done_criteria=done_criteria or "Der Schritt liefert einen klaren, belastbaren Zwischenstand.",
        completed_text=completed_text,
        verified_context_block=verified_context_block,
        system_addon_block=system_addon_block,
        next_step_guard_block=next_step_guard_block,
        auto_clarify_block=auto_clarify_block,
        claim_guard_block=claim_guard_block(step_type=step_type),
        focus_block=focus_block(step_type, suggested_tools),
        output_shape_block=output_shape_block(step_type),
        response_style=response_style,
    ) + "\n"


__all__ = [
    "_clip",
    "_effective_step_status",
    "_latest_user_reply_from_artifacts",
    "_requested_capability",
    "_step_type_from_meta",
    "_suggested_tools",
    "build_task_loop_step_prompt",
]
