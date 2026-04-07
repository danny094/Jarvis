"""
shell_context_bridge.py — Chat↔Shell Kontext-Brücke

Verantwortlichkeiten:
- Mission State aus Chat-Kontext für Shell-Start aufbauen
- Shell-Session-Summaries als typisierte Workspace-Events speichern
- Shell-Checkpoints als typisierte Workspace-Events speichern

Bewusst NICHT hier:
- PTY-Logik / Shell-Control (containers.py)
- Compact-Context-Rendering (context_cleanup.py)
- MCP-Tool-Dispatch (mcp_tools.py)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_MISSION_STATE_MAX_CHARS = 800


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_saved_event_id(result: Any) -> int | str | None:
    """Parse the event id returned by workspace_event_save across result shapes."""
    if hasattr(result, "content"):
        try:
            content = result.content
            if isinstance(content, str):
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    return parsed.get("id")
        except Exception:
            return None
    if isinstance(result, dict):
        raw = result.get("structuredContent", result)
        if isinstance(raw, dict):
            return raw.get("id")
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict):
                return parsed.get("id")
        except Exception:
            return None
    return None


def _emit_workspace_update(
    *,
    conversation_id: str,
    entry_id: int | str | None,
    content: str,
    entry_type: str,
    event_data: dict[str, Any],
    source_layer: str = "shell",
) -> None:
    """
    Mirror a persisted workspace event into the live terminal/web UI path.

    The chat UI already emits `workspace_update` over its SSE stream. TRION shell
    runs over the Commander websocket, so we emit the same normalized payload via
    Commander activity events and let the terminal frontend bridge it into the
    global `sse-event` bus.
    """
    if entry_id is None:
        return
    try:
        from container_commander.ws_stream import emit_activity

        emit_activity(
            "workspace_update",
            level="info",
            message="workspace update",
            source="event",
            entry_id=entry_id,
            content=str(content or "").strip(),
            entry_type=entry_type,
            event_data=event_data,
            conversation_id=conversation_id,
            source_layer=source_layer,
            timestamp=_utc_now(),
        )
    except Exception as exc:
        logger.debug("[ShellContextBridge] Failed to emit workspace_update mirror: %s", exc)


def _build_shell_checkpoint_content(
    *,
    goal: str,
    finding: str,
    action_taken: str,
    blocker: str,
    step_count: int,
    raw_summary: str = "",
) -> str:
    text = str(raw_summary or "").strip()
    if text:
        return text[:600]
    parts: list[str] = []
    if goal:
        parts.append(f"Goal: {str(goal).strip()[:160]}")
    if finding:
        parts.append(f"Assessment: {str(finding).strip()[:260]}")
    if action_taken:
        parts.append(f"Action: {str(action_taken).strip()[:220]}")
    if blocker:
        parts.append(f"Blocker: {str(blocker).strip()[:180]}")
    if step_count:
        parts.append(f"Step: {int(step_count)}")
    return "\n".join(parts)[:600]


# ---------------------------------------------------------------------------
# Phase 2 — Chat → Shell: Mission State aufbauen
# ---------------------------------------------------------------------------

async def build_mission_state(conversation_id: str) -> str:
    """
    Baut den Mission State für eine neue Shell-Session aus drei Quellen:

    1. Persona — user_name, language, user_context (immer verfügbar, sync)
    2. SQL-Memory — user_facts Key für persönliche Fakten (async-wrapped, 2s timeout)
    3. Workspace Compact Context — NOW/RULES/NEXT aus Chat-Events

    Fail-open: Jede Quelle ist unabhängig. Bei Fehler wird sie übersprungen.
    Maximal 800 Zeichen gesamt.
    """
    if not conversation_id or conversation_id == "global":
        return ""
    try:
        import asyncio as _asyncio
        parts: list[str] = []

        # --- 1. User identity from persona (sync, immer verfügbar) ---
        try:
            from core.persona import get_persona
            persona = get_persona()
            user_name = str(persona.user_name or "").strip()
            user_lang = str(persona.language or "").strip()
            user_ctx = list(persona.user_context or [])
            identity_parts: list[str] = []
            if user_name and user_name not in ("unknown", ""):
                identity_parts.append(f"User: {user_name}")
            if user_lang and user_lang not in ("auto-detect", ""):
                identity_parts.append(f"Language: {user_lang}")
            if user_ctx:
                ctx_str = ", ".join(str(c) for c in user_ctx[:3])
                identity_parts.append(f"Context: {ctx_str}")
            if identity_parts:
                parts.append("User identity: " + " | ".join(identity_parts))
        except Exception:
            pass

        # --- 2. User memory facts (async-wrapped sync hub call, 2s timeout) ---
        try:
            from mcp.client import get_fact_for_query
            user_facts: str | None = await _asyncio.to_thread(
                get_fact_for_query, conversation_id, "user_facts", 2.0
            )
            if not user_facts:
                user_facts = await _asyncio.to_thread(
                    get_fact_for_query, "global", "user_facts", 2.0
                )
            if user_facts:
                snippet = str(user_facts).strip()[:200]
                parts.append(f"Memory: {snippet}")
        except Exception:
            pass

        # --- 3. Workspace compact context (NOW/RULES/NEXT) ---
        try:
            from core.bridge import get_bridge
            bridge = get_bridge()
            text: str = bridge.orchestrator.context.build_small_model_context(
                conversation_id=conversation_id,
                limits={"now_max": 3, "rules_max": 2, "next_max": 2},
            )
            text = str(text or "").strip()
            if text:
                parts.append(text)
        except Exception as exc:
            logger.debug("[ShellContextBridge] build_small_model_context failed: %s", exc)

        if not parts:
            return ""

        result = "\n".join(parts)
        if len(result) > _MISSION_STATE_MAX_CHARS:
            result = result[:_MISSION_STATE_MAX_CHARS].rsplit("\n", 1)[0] + "\n[...]"
        return result
    except Exception as exc:
        logger.debug("[ShellContextBridge] build_mission_state failed (ok, fail-open): %s", exc)
        return ""


# ---------------------------------------------------------------------------
# Phase 1 — Shell → Chat: Workspace-Events speichern
# ---------------------------------------------------------------------------

def save_shell_session_summary(
    *,
    conversation_id: str,
    container_id: str,
    blueprint_id: str,
    container_name: str,
    goal: str,
    findings: str,
    changes_applied: str,
    open_blocker: str,
    step_count: int,
    commands: list[str],
    user_requests: list[str],
    final_stop_reason: str = "",
    summary_parts: dict[str, Any] | None = None,
    raw_summary: str = "",
) -> None:
    """
    Speichert shell_session_summary als Workspace-Event.

    Ersetzt _save_shell_summary_event() in containers.py.
    Rückwärtskompatibilität: context_cleanup.py akzeptiert beide Event-Types
    ('shell_session_summary' und altes 'trion_shell_summary').
    """
    try:
        event_data = {
            "container_id": container_id,
            "blueprint_id": blueprint_id,
            "container_name": container_name,
            "goal": str(goal or "").strip()[:300],
            "findings": str(findings or "").strip()[:400],
            "changes_applied": str(changes_applied or "").strip()[:300],
            "open_blocker": str(open_blocker or "").strip()[:200],
            "step_count": int(step_count or 0),
            "commands": list(commands or [])[:12],
            "user_requests": list(user_requests or [])[:12],
            "final_stop_reason": str(final_stop_reason or "").strip(),
            "summary_parts": dict(summary_parts or {}),
            "content": str(raw_summary or "").strip()[:600],
            "saved_at": _utc_now(),
        }
        from core.workspace_event_emitter import get_workspace_emitter
        get_workspace_emitter().persist_and_broadcast(
            conversation_id=conversation_id,
            event_type="shell_session_summary",
            event_data=event_data,
            content=str(event_data.get("content") or ""),
        )
        logger.debug(
            "[ShellContextBridge] shell_session_summary saved for conv=%s container=%s",
            conversation_id, container_id,
        )
    except Exception as exc:
        logger.error("[ShellContextBridge] Failed to save shell_session_summary: %s", exc)


def save_shell_checkpoint(
    *,
    conversation_id: str,
    container_id: str,
    blueprint_id: str = "",
    goal: str,
    finding: str,
    action_taken: str,
    blocker: str = "",
    step_count: int = 0,
    raw_summary: str = "",
) -> None:
    """
    Speichert shell_checkpoint als leichtgewichtiges Workspace-Event.

    Nur bei tatsächlichen Zustandsänderungen aufrufen (z.B. alle 5 Steps
    oder bei shell_change_applied) — nicht nach jedem Step, um den
    Compact Context nicht mit Shell-Telemetrie zu überfluten.
    """
    try:
        content = _build_shell_checkpoint_content(
            goal=goal,
            finding=finding,
            action_taken=action_taken,
            blocker=blocker,
            step_count=step_count,
            raw_summary=raw_summary,
        )
        event_data = {
            "container_id": container_id,
            "blueprint_id": blueprint_id,
            "goal": str(goal or "").strip()[:200],
            "finding": str(finding or "").strip()[:300],
            "action_taken": str(action_taken or "").strip()[:200],
            "blocker": str(blocker or "").strip()[:200],
            "step_count": int(step_count or 0),
            "content": content,
            "saved_at": _utc_now(),
        }
        from core.workspace_event_emitter import get_workspace_emitter
        get_workspace_emitter().persist_and_broadcast(
            conversation_id=conversation_id,
            event_type="shell_checkpoint",
            event_data=event_data,
            content=content,
        )
        logger.debug(
            "[ShellContextBridge] shell_checkpoint saved for conv=%s container=%s step=%d",
            conversation_id, container_id, step_count,
        )
    except Exception as exc:
        logger.error("[ShellContextBridge] Failed to save shell_checkpoint: %s", exc)
