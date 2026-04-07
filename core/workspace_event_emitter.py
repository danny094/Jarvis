"""
workspace_event_emitter.py — Zentrale Workspace-Event-Persistierung und -Emission.

Konsolidiert drei vormals separate Emissionspfade:

  Chat/Stream-Pfad:
    orchestrator._save_workspace_entry → Fast-Lane + SSE-dict zurück

  Chat/Sync-Pfad:
    [Lücke] — wird in Phase 2 geschlossen

  Shell-Pfad (Container Commander):
    shell_context_bridge → Fast-Lane + emit_activity (WebSocket-Mirror)

Transportentscheidung bleibt beim Aufrufer:
  Stream:  result = emitter.persist(...)
           if result.sse_dict: yield ("", False, result.sse_dict)

  Sync:    result = emitter.persist(...)
           # kein yield — Entry landet in DB

  Shell:   emitter.persist_and_broadcast(...)
           # WebSocket-Broadcast intern im Emitter

Was hier NICHT geändert wird:
  - SSE-yield-Mechanismus (bleibt in stream_flow_utils)
  - WebSocket-Transport (bleibt via emit_activity)
  - Fast-Lane-Tool workspace_event_save (kein Change am MCP-Tool)
  - Control/Thinking/Output Layer (keine direkte Emission)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_entry_id(result: Any) -> Optional[Any]:
    """
    Robuste Parse-Logik für den entry_id aus einem Fast-Lane workspace_event_save Ergebnis.

    Unterstützte Shapes:
      - ToolResult mit .content als JSON-String: '{"id": 42, "status": "saved"}'
      - dict mit "structuredContent" oder direktem "id"-Key
      - Plain JSON-String
    """
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


# ---------------------------------------------------------------------------
# Result-Contract
# ---------------------------------------------------------------------------

@dataclass
class WorkspaceEventResult:
    """
    Rückgabe jeder persist*()-Methode.

    entry_id:  DB-ID des gespeicherten Events (None bei Fehler).
    sse_dict:  SSE-Payload für workspace_update (None im Shell-Pfad — kein SSE-Stream).
    """
    entry_id: Optional[Any]
    sse_dict: Optional[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Emitter
# ---------------------------------------------------------------------------

class WorkspaceEventEmitter:
    """
    Einziger Punkt für Workspace-Event-Persistierung.

    Instanz-Lebensdauer: Singleton via get_workspace_emitter().
    Kein State — alle Methoden sind zustandslos gegenüber einander.
    """

    def persist(
        self,
        conversation_id: str,
        content: str,
        entry_type: str,
        source_layer: str,
    ) -> WorkspaceEventResult:
        """
        Persistiert ein Workspace-Event via Fast-Lane.

        Verwendung:
          - Stream-Pfad: result.sse_dict → yield in SSE-Generator
          - Sync-Pfad:   Entry in DB, kein yield nötig

        Entspricht dem bisherigen orchestrator._save_workspace_entry().
        """
        try:
            from mcp.hub import get_hub
            hub = get_hub()
            hub.initialize()
            result = hub.call_tool("workspace_event_save", {
                "conversation_id": conversation_id,
                "event_type": entry_type,
                "event_data": {
                    "content": content,
                    "source_layer": source_layer,
                },
            })
            entry_id = _parse_entry_id(result)
            if entry_id is not None:
                sse_dict: Dict[str, Any] = {
                    "type": "workspace_update",
                    "source": "event",
                    "entry_id": entry_id,
                    "content": content,
                    "entry_type": entry_type,
                    "source_layer": source_layer,
                    "conversation_id": conversation_id,
                    "timestamp": _utc_now_iso(),
                }
                return WorkspaceEventResult(entry_id=entry_id, sse_dict=sse_dict)
        except Exception as exc:
            logger.error("[WorkspaceEventEmitter] persist failed: %s", exc)
        return WorkspaceEventResult(entry_id=None, sse_dict=None)

    def persist_container(
        self,
        conversation_id: str,
        container_evt: Dict[str, Any],
    ) -> WorkspaceEventResult:
        """
        Persistiert ein Container-Lifecycle-Event via Fast-Lane.

        container_evt muss enthalten: event_type (str), event_data (dict).
        Entspricht dem bisherigen orchestrator._save_container_event().
        """
        event_type = container_evt.get("event_type", "container_event")
        event_data = container_evt.get("event_data", {})
        try:
            from mcp.hub import get_hub
            hub = get_hub()
            hub.initialize()
            result = hub.call_tool("workspace_event_save", {
                "conversation_id": conversation_id,
                "event_type": event_type,
                "event_data": event_data,
            })
            entry_id = _parse_entry_id(result)
            if entry_id is not None:
                _summary = event_data.get("purpose") or event_data.get("command", "")
                _cid = event_data.get("container_id", "")
                _bp = event_data.get("blueprint_id", "")
                _content = f"{_bp}/{_cid[:12]}: {_summary[:120]}" if _cid else event_type
                sse_dict = {
                    "type": "workspace_update",
                    "source": "event",
                    "entry_id": entry_id,
                    "content": _content,
                    "entry_type": event_type,
                    "event_data": event_data,
                    "conversation_id": conversation_id,
                    "timestamp": _utc_now_iso(),
                }
                return WorkspaceEventResult(entry_id=entry_id, sse_dict=sse_dict)
        except Exception as exc:
            logger.error("[WorkspaceEventEmitter] persist_container failed: %s", exc)
        return WorkspaceEventResult(entry_id=None, sse_dict=None)

    def persist_and_broadcast(
        self,
        conversation_id: str,
        event_type: str,
        event_data: Dict[str, Any],
        content: str,
        source_layer: str = "shell",
    ) -> WorkspaceEventResult:
        """
        Persistiert und spiegelt ein Shell-Event via WebSocket (Shell-Pfad).

        Kein SSE-Stream vorhanden → sse_dict ist immer None.
        Entspricht dem bisherigen hub.call_tool() + _emit_workspace_update()
        in shell_context_bridge.

        Verwendung: ausschliesslich von shell_context_bridge.
        """
        try:
            from mcp.hub import get_hub
            hub = get_hub()
            hub.initialize()
            result = hub.call_tool("workspace_event_save", {
                "conversation_id": conversation_id,
                "event_type": event_type,
                "event_data": event_data,
            })
            entry_id = _parse_entry_id(result)
            if entry_id is not None:
                try:
                    from container_commander.ws_stream import emit_activity
                    emit_activity(
                        "workspace_update",
                        level="info",
                        message="workspace update",
                        source="event",
                        entry_id=entry_id,
                        content=str(content or "").strip(),
                        entry_type=event_type,
                        event_data=event_data,
                        conversation_id=conversation_id,
                        source_layer=source_layer,
                        timestamp=_utc_now_iso(),
                    )
                except Exception as exc:
                    logger.debug(
                        "[WorkspaceEventEmitter] emit_activity failed (non-fatal): %s", exc
                    )
                return WorkspaceEventResult(entry_id=entry_id, sse_dict=None)
        except Exception as exc:
            logger.error("[WorkspaceEventEmitter] persist_and_broadcast failed: %s", exc)
        return WorkspaceEventResult(entry_id=None, sse_dict=None)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_emitter: Optional[WorkspaceEventEmitter] = None


def get_workspace_emitter() -> WorkspaceEventEmitter:
    global _emitter
    if _emitter is None:
        _emitter = WorkspaceEventEmitter()
    return _emitter
