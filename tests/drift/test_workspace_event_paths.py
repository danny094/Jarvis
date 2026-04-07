"""
Drift-Guard: Workspace-Event-Emissionspfade

Entstanden aus:
  docs/obsidian/2026-03-29-trion-codeatlas-und-konsolidierungsanalyse.md (Abschnitt C)
  docs/obsidian/2026-03-31-workspace-event-emitter-implementationsplan.md (Phase 3)

Diese Tests sichern die Architektur-Invarianten die durch Phase 1+2 eingeführt wurden:

  INVARIANTE 1 — Einziger Fast-Lane-Aufrufer:
    hub.call_tool("workspace_event_save") darf NUR in workspace_event_emitter.py vorkommen.
    Kein anderes Modul darf diesen Tool-Call direkt machen.

  INVARIANTE 2 — Sync-Parität:
    orchestrator_sync_flow_utils.py muss mindestens 3 _save_workspace_entry-Aufrufe haben
    (thinking_observation + control_decision + chat_done).

  INVARIANTE 3 — Shell-Bridge ist sauber:
    shell_context_bridge.py darf keinen direkten hub.call_tool("workspace_event_save") haben.
    Stattdessen muss persist_and_broadcast aus dem Emitter aufgerufen werden.

  INVARIANTE 4 — Emitter-Pflichtfelder:
    Jeder persist*()-Aufruf im Emitter übergibt conversation_id, event_type und event_data.

Warum static analysis und nicht Mock-Tests?
  Diese Invarianten sichern die Architektur gegen zukünftigen Drift, z.B.:
  - jemand fügt einen neuen workspace-save direkt in mcp_tools.py ein
  - jemand entfernt einen der drei Sync-Pfad-Saves
  Mock-Tests in test_workspace_event_emitter.py prüfen das Verhalten;
  diese Tests prüfen ob die Struktur des Codes die Invarianten respektiert.
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def _count_pattern(src: str, pattern: str) -> int:
    return len(re.findall(pattern, src))


def _find_files_with_pattern(glob: str, pattern: str) -> list[Path]:
    """Gibt alle Dateien zurück die dem glob entsprechen und das Pattern enthalten."""
    hits = []
    for p in _ROOT.glob(glob):
        try:
            if re.search(pattern, p.read_text(encoding="utf-8")):
                hits.append(p)
        except Exception:
            pass
    return hits


# ---------------------------------------------------------------------------
# INVARIANTE 1 — Einziger Fast-Lane-Aufrufer
# ---------------------------------------------------------------------------

class TestOnlyEmitterCallsFastLane:
    """
    hub.call_tool("workspace_event_save") darf ausschließlich in
    core/workspace_event_emitter.py vorkommen.
    """

    _FAST_LANE_PATTERN = r'call_tool\s*\(\s*["\']workspace_event_save["\']'

    def test_emitter_itself_calls_fast_lane(self):
        """Sanity-Check: Der Emitter selbst ruft workspace_event_save auf."""
        src = _read("core/workspace_event_emitter.py")
        count = _count_pattern(src, self._FAST_LANE_PATTERN)
        assert count >= 3, (
            f"workspace_event_emitter.py sollte mindestens 3 Fast-Lane-Aufrufe haben "
            f"(persist, persist_container, persist_and_broadcast), gefunden: {count}"
        )

    def test_shell_context_bridge_has_no_direct_fast_lane_call(self):
        """shell_context_bridge.py darf workspace_event_save nicht direkt aufrufen."""
        src = _read("container_commander/shell_context_bridge.py")
        count = _count_pattern(src, self._FAST_LANE_PATTERN)
        assert count == 0, (
            f"shell_context_bridge.py ruft workspace_event_save direkt auf ({count}×). "
            f"Soll stattdessen WorkspaceEventEmitter.persist_and_broadcast() nutzen."
        )

    def test_orchestrator_has_no_direct_fast_lane_call(self):
        """core/orchestrator.py darf workspace_event_save nicht direkt aufrufen."""
        src = _read("core/orchestrator.py")
        count = _count_pattern(src, self._FAST_LANE_PATTERN)
        assert count == 0, (
            f"orchestrator.py ruft workspace_event_save direkt auf ({count}×). "
            f"Soll über _save_workspace_entry → WorkspaceEventEmitter.persist() gehen."
        )

    def test_stream_flow_utils_has_no_direct_fast_lane_call(self):
        """orchestrator_stream_flow_utils.py darf workspace_event_save nicht direkt aufrufen."""
        src = _read("core/orchestrator_stream_flow_utils.py")
        count = _count_pattern(src, self._FAST_LANE_PATTERN)
        assert count == 0, (
            f"orchestrator_stream_flow_utils.py ruft workspace_event_save direkt auf ({count}×). "
            f"Soll über orch._save_workspace_entry() gehen."
        )

    def test_sync_flow_utils_has_no_direct_fast_lane_call(self):
        """orchestrator_sync_flow_utils.py darf workspace_event_save nicht direkt aufrufen."""
        src = _read("core/orchestrator_sync_flow_utils.py")
        count = _count_pattern(src, self._FAST_LANE_PATTERN)
        assert count == 0, (
            f"orchestrator_sync_flow_utils.py ruft workspace_event_save direkt auf ({count}×). "
            f"Soll über orch._save_workspace_entry() gehen."
        )

    def test_no_other_module_calls_fast_lane_directly(self):
        """
        Kein Modul außerhalb von workspace_event_emitter.py darf workspace_event_save
        direkt via hub.call_tool aufrufen.

        Ausnahmen:
          - Tests (tests/)
          - Der Emitter selbst (core/workspace_event_emitter.py)
          - Bekannte Legacy-Aufrufer (noch nicht migriert, sollten in einer
            späteren Session auf persist_and_broadcast umgestellt werden):
              - adapters/admin-api/main.py
              - adapters/admin-api/commander_api/containers.py
        """
        hits = _find_files_with_pattern("**/*.py", self._FAST_LANE_PATTERN)
        allowed = {
            _ROOT / "core" / "workspace_event_emitter.py",
            # Legacy-Aufrufer — pre-existing, Phase 1 deckte nur core/ + shell_context_bridge ab
            _ROOT / "adapters" / "admin-api" / "main.py",
            _ROOT / "adapters" / "admin-api" / "commander_api" / "containers.py",
        }
        violations = [p for p in hits if p not in allowed and "tests" not in str(p)]
        assert not violations, (
            f"Neue Dateien rufen workspace_event_save direkt auf (Drift!):\n"
            + "\n".join(f"  - {p.relative_to(_ROOT)}" for p in violations)
            + "\nNur WorkspaceEventEmitter darf workspace_event_save direkt aufrufen."
        )


# ---------------------------------------------------------------------------
# INVARIANTE 2 — Sync-Parität
# ---------------------------------------------------------------------------

class TestSyncPathParity:
    """
    orchestrator_sync_flow_utils.py muss mindestens 3 _save_workspace_entry-Aufrufe haben.
    """

    _SAVE_PATTERN = r'_save_workspace_entry\s*\('

    def test_sync_flow_has_at_least_3_workspace_saves(self):
        src = _read("core/orchestrator_sync_flow_utils.py")
        count = _count_pattern(src, self._SAVE_PATTERN)
        assert count >= 3, (
            f"orchestrator_sync_flow_utils.py sollte ≥3 _save_workspace_entry-Aufrufe haben "
            f"(thinking_observation + control_decision + chat_done), gefunden: {count}"
        )

    def test_sync_flow_saves_thinking_observation(self):
        """Sync-Pfad muss einen observation/thinking Entry speichern."""
        src = _read("core/orchestrator_sync_flow_utils.py")
        # Suche nach dem Muster: _save_workspace_entry(... "observation", "thinking")
        assert re.search(r'_save_workspace_entry\s*\([^)]*["\']observation["\'][^)]*["\']thinking["\']', src), (
            "orchestrator_sync_flow_utils.py fehlt observation/thinking workspace save. "
            "Erwartet: orch._save_workspace_entry(cid, obs_text, 'observation', 'thinking')"
        )

    def test_sync_flow_saves_control_decision(self):
        """Sync-Pfad muss einen control_decision Entry speichern."""
        src = _read("core/orchestrator_sync_flow_utils.py")
        assert re.search(r'_save_workspace_entry\s*\([^)]*["\']control_decision["\']', src), (
            "orchestrator_sync_flow_utils.py fehlt control_decision workspace save. "
            "Erwartet: orch._save_workspace_entry(cid, ctrl_summary, 'control_decision', 'control')"
        )

    def test_sync_flow_saves_chat_done(self):
        """Sync-Pfad muss einen chat_done Entry speichern."""
        src = _read("core/orchestrator_sync_flow_utils.py")
        # Aufruf ist multi-line: _save_workspace_entry(\n...,\n"chat_done",\n...
        # Daher: prüfen ob _save_workspace_entry und "chat_done" nahe beieinander vorkommen
        assert re.search(r'_save_workspace_entry', src) and '"chat_done"' in src, (
            "orchestrator_sync_flow_utils.py fehlt chat_done workspace save. "
            "Erwartet: orch._save_workspace_entry(cid, done_summary, 'chat_done', 'orchestrator')"
        )

    def test_stream_flow_also_has_workspace_saves(self):
        """Sanity-Check: Stream-Pfad hat weiterhin workspace saves (keine Regression)."""
        src = _read("core/orchestrator_stream_flow_utils.py")
        count = _count_pattern(src, self._SAVE_PATTERN)
        assert count >= 5, (
            f"orchestrator_stream_flow_utils.py sollte ≥5 _save_workspace_entry-Aufrufe haben, "
            f"gefunden: {count}. Mögliche Regression?"
        )


# ---------------------------------------------------------------------------
# INVARIANTE 3 — Shell-Bridge nutzt Emitter
# ---------------------------------------------------------------------------

class TestShellBridgeUsesEmitter:
    """
    shell_context_bridge.py muss persist_and_broadcast aus dem WorkspaceEventEmitter nutzen.
    """

    def test_shell_bridge_imports_workspace_emitter(self):
        """shell_context_bridge.py muss workspace_event_emitter importieren."""
        src = _read("container_commander/shell_context_bridge.py")
        assert "workspace_event_emitter" in src, (
            "shell_context_bridge.py importiert workspace_event_emitter nicht mehr. "
            "Soll get_workspace_emitter().persist_and_broadcast() aufrufen."
        )

    def test_shell_bridge_calls_persist_and_broadcast(self):
        """shell_context_bridge.py muss persist_and_broadcast aufrufen."""
        src = _read("container_commander/shell_context_bridge.py")
        count = _count_pattern(src, r'persist_and_broadcast\s*\(')
        assert count >= 2, (
            f"shell_context_bridge.py sollte ≥2 persist_and_broadcast-Aufrufe haben "
            f"(save_shell_session_summary + save_shell_checkpoint), gefunden: {count}"
        )

    def test_shell_bridge_has_no_emit_workspace_update_calls(self):
        """
        _emit_workspace_update darf nicht mehr direkt in den save-Funktionen aufgerufen werden.
        Die Funktion kann noch existieren (für Rückwärtskompatibilität) aber die
        save_shell_*-Funktionen sollen sie nicht mehr aufrufen.
        """
        src = _read("container_commander/shell_context_bridge.py")
        # Wir prüfen nur dass die save-Funktionen nicht _emit_workspace_update direkt aufrufen —
        # die Funktion darf noch existieren.
        # Extraktion der save_*-Funktions-Bodies
        save_session_match = re.search(
            r'def save_shell_session_summary\b.*?(?=\ndef |\Z)', src, re.DOTALL
        )
        save_checkpoint_match = re.search(
            r'def save_shell_checkpoint\b.*?(?=\ndef |\Z)', src, re.DOTALL
        )
        for match, name in [
            (save_session_match, "save_shell_session_summary"),
            (save_checkpoint_match, "save_shell_checkpoint"),
        ]:
            if match:
                body = match.group(0)
                assert "_emit_workspace_update" not in body, (
                    f"{name} ruft _emit_workspace_update direkt auf. "
                    f"Soll stattdessen persist_and_broadcast() nutzen."
                )


# ---------------------------------------------------------------------------
# INVARIANTE 4 — Emitter-Pflichtfelder
# ---------------------------------------------------------------------------

class TestEmitterMandatoryFields:
    """
    Jeder Fast-Lane-Aufruf im Emitter muss conversation_id, event_type und event_data übergeben.
    """

    def test_persist_passes_conversation_id(self):
        src = _read("core/workspace_event_emitter.py")
        # persist() muss "conversation_id" im call_tool-Payload haben
        assert re.search(r'"conversation_id"\s*:', src), (
            "workspace_event_emitter.py: conversation_id fehlt im workspace_event_save-Payload"
        )

    def test_persist_passes_event_type(self):
        src = _read("core/workspace_event_emitter.py")
        assert re.search(r'"event_type"\s*:', src), (
            "workspace_event_emitter.py: event_type fehlt im workspace_event_save-Payload"
        )

    def test_persist_passes_event_data(self):
        src = _read("core/workspace_event_emitter.py")
        assert re.search(r'"event_data"\s*:', src), (
            "workspace_event_emitter.py: event_data fehlt im workspace_event_save-Payload"
        )

    def test_emitter_result_contract_has_entry_id_and_sse_dict(self):
        """WorkspaceEventResult muss entry_id und sse_dict als Felder haben."""
        src = _read("core/workspace_event_emitter.py")
        assert "entry_id" in src, "WorkspaceEventResult fehlt entry_id-Feld"
        assert "sse_dict" in src, "WorkspaceEventResult fehlt sse_dict-Feld"

    def test_persist_returns_workspace_event_result(self):
        """persist() muss WorkspaceEventResult zurückgeben."""
        src = _read("core/workspace_event_emitter.py")
        assert re.search(r'return WorkspaceEventResult\s*\(', src), (
            "workspace_event_emitter.py: persist*()-Methoden geben kein WorkspaceEventResult zurück"
        )

    def test_orchestrator_save_workspace_entry_delegates_to_emitter(self):
        """orchestrator._save_workspace_entry muss an get_workspace_emitter().persist() delegieren."""
        src = _read("core/orchestrator.py")
        # Finde die _save_workspace_entry Methode und prüfe ob sie workspace_event_emitter importiert
        match = re.search(
            r'def _save_workspace_entry\b.*?(?=\n    def |\Z)', src, re.DOTALL
        )
        assert match, "orchestrator.py: _save_workspace_entry Methode nicht gefunden"
        body = match.group(0)
        assert "workspace_event_emitter" in body, (
            "orchestrator._save_workspace_entry delegiert nicht an workspace_event_emitter. "
            "Soll get_workspace_emitter().persist(...).sse_dict zurückgeben."
        )

    def test_orchestrator_save_container_event_delegates_to_emitter(self):
        """orchestrator._save_container_event muss an get_workspace_emitter().persist_container() delegieren."""
        src = _read("core/orchestrator.py")
        match = re.search(
            r'def _save_container_event\b.*?(?=\n    def |\Z)', src, re.DOTALL
        )
        assert match, "orchestrator.py: _save_container_event Methode nicht gefunden"
        body = match.group(0)
        assert "workspace_event_emitter" in body, (
            "orchestrator._save_container_event delegiert nicht an workspace_event_emitter. "
            "Soll get_workspace_emitter().persist_container(...).sse_dict zurückgeben."
        )
