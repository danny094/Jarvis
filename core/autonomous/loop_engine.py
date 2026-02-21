"""
LoopEngine: ReAct-Loop für komplexe Multi-Step Aufgaben

Anstatt den vollen Pipeline N-mal aufzurufen (= 3N LLM-Calls),
bleibt der OutputLayer in einer aktiven Tool-Calling-Session:

    OutputLayer Session:
      Runde 1: Modell → "Ich brauche home_list('notes')"
               Tool ausgeführt → Ergebnis zurückgegeben
      Runde 2: Modell → "Jetzt lese ich file.md"
               Tool ausgeführt → Ergebnis zurückgegeben
      Runde N: Modell → "Fertig, hier die Zusammenfassung: ..."
               → DONE

LLM-Aufrufe: 1 (OutputLayer bleibt warm) × N Runden
vs. Full Pipeline: 3 × N (ThinkingLayer + ControlLayer + OutputLayer × N)

Trigger-Bedingung (im Orchestrator geprüft):
  sequential_complexity >= 7
  ODER (needs_sequential_thinking == True UND 2+ Tools empfohlen)

Max-Loop-Schutz: MAX_LOOP_ITERATIONS (Standard: 5)
"""

import json
import re
import hashlib
import httpx
from typing import AsyncGenerator, Tuple, Dict, Any, List, Optional
from config import OLLAMA_BASE, OUTPUT_MODEL
from utils.logger import log_info, log_error, log_debug, log_warn


MAX_LOOP_ITERATIONS = 5
MAX_SAME_RESULT = 2  # Wie oft dasselbe Ergebnis vor STUCK-Erkennung

# Fehler-Pattern → konkrete Alternativen für das LLM
_STUCK_ALTERNATIVES: List[Dict] = [
    {
        "patterns": ["gputil", "no module named 'gputil'"],
        "hint": (
            "GPUtil ist nicht installiert. Versuche stattdessen:\n"
            "  1. exec_in_container mit Befehl: 'nvidia-smi' (zeigt GPU direkt)\n"
            "  2. exec_in_container: 'python3 -c \"import subprocess; "
            "r=subprocess.run([chr(110)+chr(118)+chr(105)+chr(100)+chr(105)+chr(97)+'-smi'],"
            "capture_output=True,text=True); print(r.stdout)\"'\n"
            "  3. autonomous_skill_task: Erstelle GPU-Skill der nvidia-smi via subprocess nutzt"
        ),
    },
    {
        "patterns": ["no module named", "modulenotfounderror", "importerror"],
        "hint": (
            "Ein Python-Modul fehlt. Alternativen:\n"
            "  1. exec_in_container: 'pip install <modulname>' dann erneut versuchen\n"
            "  2. create_skill: Erstelle neuen Skill ohne die fehlende Abhängigkeit\n"
            "  3. Erkläre dem User welches Paket fehlt und wie es installiert wird"
        ),
    },
    {
        "patterns": ["connection refused", "connectionrefusederror", "connect call failed", "could not connect"],
        "hint": (
            "Verbindung verweigert. Versuche:\n"
            "  1. container_stats prüfen ob der Ziel-Container läuft\n"
            "  2. list_containers um verfügbare Container zu sehen\n"
            "  3. Dem User melden welcher Dienst nicht erreichbar ist"
        ),
    },
    {
        "patterns": ["permission denied", "permissionerror", "access denied"],
        "hint": (
            "Keine Berechtigung. Versuche:\n"
            "  1. home_list um verfügbare Pfade zu prüfen\n"
            "  2. exec_in_container falls Root-Rechte benötigt werden"
        ),
    },
    {
        "patterns": ["timeout", "timed out", "read timeout"],
        "hint": (
            "Timeout aufgetreten. Versuche:\n"
            "  1. Eine einfachere/kürzere Version der Anfrage\n"
            "  2. container_stats statt exec_in_container\n"
            "  3. Dem User den Timeout melden und alternative Methode vorschlagen"
        ),
    },
    {
        "patterns": ["not found", "no such file", "filenotfounderror", "404"],
        "hint": (
            "Datei/Ressource nicht gefunden. Versuche:\n"
            "  1. home_list um vorhandene Pfade zu erkunden\n"
            "  2. memory_search nach dem korrekten Ressourcennamen\n"
            "  3. list_skills oder list_containers für verfügbare Ressourcen"
        ),
    },
]


class _StuckTracker:
    """
    Verfolgt Tool-Ergebnis-Signaturen um wiederholte identische Outputs zu erkennen.
    Klassifiziert Fehler-Typen und generiert Alternativ-Hinweise für das LLM.
    """

    def __init__(self):
        self._result_hashes: Dict[str, List[str]] = {}
        self._error_log: List[Dict] = []
        self._stuck_log: List[Dict] = []
        self._last_error: Dict[str, str] = {}

    def _simplify(self, result_str: str) -> str:
        """Normalisiert dynamische Teile (Zahlen, Timestamps, IDs) für stabilen Vergleich."""
        s = re.sub(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[.\d]*Z?', 'TS', result_str)
        s = re.sub(r'[0-9a-f]{16,}', 'ID', s)
        s = re.sub(r'\d+\.\d+', 'N', s)
        s = re.sub(r'\b\d+\b', 'N', s)
        s = re.sub(r'\s+', '', s)
        return s[:300]

    def record_result(self, tool_name: str, result_str: str, iteration: int) -> bool:
        """
        Speichert ein Tool-Ergebnis. Returns True wenn dieses Tool jetzt STUCK ist
        (gleiche vereinfachte Ausgabe >= MAX_SAME_RESULT mal gesehen).
        """
        sig = hashlib.md5(self._simplify(result_str).encode()).hexdigest()[:8]
        hashes = self._result_hashes.setdefault(tool_name, [])
        hashes.append(sig)
        if len(hashes) >= MAX_SAME_RESULT and len(set(hashes[-MAX_SAME_RESULT:])) == 1:
            self._stuck_log.append({"tool": tool_name, "iteration": iteration, "sig": sig})
            return True
        return False

    def record_error(self, tool_name: str, error_str: str, iteration: int):
        """Speichert einen Fehler für die spätere Zusammenfassung."""
        self._last_error[tool_name] = error_str
        self._error_log.append({
            "tool": tool_name,
            "error": error_str[:150],
            "iteration": iteration
        })

    def get_hint_for_error(self, error_str: str) -> Optional[str]:
        """Gibt konkreten Hinweis-Text zurück wenn ein bekanntes Fehlermuster erkannt wird."""
        lower = error_str.lower()
        for rule in _STUCK_ALTERNATIVES:
            if any(p in lower for p in rule["patterns"]):
                return rule["hint"]
        return None

    def build_stuck_injection(self, tool_name: str) -> str:
        """Baut den Injektions-Text der an das Tool-Ergebnis angehängt wird wenn STUCK."""
        last_err = self._last_error.get(tool_name, "")
        hint = self.get_hint_for_error(last_err) if last_err else None
        lines = [
            f"\n⚠️ [STUCK-DETECTION] '{tool_name}' liefert wiederholt dasselbe Ergebnis.",
            "Dieses Tool liefert keinen Fortschritt — NICHT erneut aufrufen!",
        ]
        if hint:
            lines.append(f"\n💡 Konkrete Alternativen:\n{hint}")
        else:
            lines.append(
                "\n💡 Versuche einen anderen Ansatz:"
                "\n  - Ein anderes Tool für das gleiche Ziel"
                "\n  - exec_in_container für direkte Systembefehle"
                "\n  - autonomous_skill_task um einen neuen Skill zu erstellen"
                "\n  - Erkläre dem User was du herausgefunden hast"
            )
        return "\n".join(lines)

    def build_summary(self) -> str:
        """Für den Force-Finish: Übersicht was versucht wurde und was gescheitert ist."""
        if not self._error_log and not self._stuck_log:
            return ""
        parts = ["📋 Was wurde versucht (Protokoll):"]
        seen = set()
        for e in self._error_log:
            key = f"{e['tool']}:{e['error'][:50]}"
            if key not in seen:
                parts.append(f"  • Runde {e['iteration']}: {e['tool']} → Fehler: {e['error'][:100]}")
                seen.add(key)
        for s in self._stuck_log:
            parts.append(
                f"  • Runde {s['iteration']}: {s['tool']} → "
                f"gleiche Ausgabe {MAX_SAME_RESULT}× (kein Fortschritt)"
            )
        # Unique hints für den User
        shown_hints = set()
        user_hints = []
        for e in self._error_log:
            hint = self.get_hint_for_error(e["error"])
            if hint and hint not in shown_hints:
                user_hints.append(hint)
                shown_hints.add(hint)
        if user_hints:
            parts.append("\n💡 Mögliche nächste Schritte für den User:")
            for h in user_hints:
                parts.append(f"  {h}")
        return "\n".join(parts)


_LOOP_SYSTEM_SUFFIX = """

### AUTONOMER MODUS (LoopEngine):
Du arbeitest selbstständig an einer mehrstufigen Aufgabe.
Nutze Tools Schritt für Schritt, bis die Aufgabe vollständig erledigt ist.
Wenn du fertig bist, gib eine klare, vollständige Antwort.

STOPPE wenn:
  (a) Aufgabe erledigt — gib Ergebnis zurück
  (b) Keine weiteren Tools nötig
  (c) Max {max_loops} Tool-Runden erreicht (aktuelle Runde: {current})

PROBLEM-SOLVING REGELN (WICHTIG!):
  1. Rufe NIEMALS dasselbe Tool zweimal mit denselben Argumenten auf.
  2. Wenn ein Tool ein ⚠️ [STUCK-DETECTION] Signal zurückgibt → sofort anderen Ansatz wählen.
  3. Wenn ein Fehler auftritt → lies den [ALTERNATIVE-HINWEIS] und folge ihm.
  4. Wenn du nach 2 Runden keinen Fortschritt siehst → erkläre dem User das Problem direkt.
  5. Denke kreativ: exec_in_container, autonomous_skill_task, create_skill sind oft Alternativen.
"""


class LoopEngine:
    """
    ReAct-Loop: OutputLayer bleibt über mehrere Tool-Call-Runden aktiv.

    Sicherheits-Mechanismen:
      - max_iterations: Verhindert endlose Loops (Standard: 5)
      - seen_tool_calls: Verhindert identische Wiederholungen
      - force_finish: Nach max_iterations wird eine abschließende Antwort erzwungen
    """

    def __init__(self, ollama_base: str = None, model: str = None):
        self.ollama_base = ollama_base or OLLAMA_BASE
        self.model = model or OUTPUT_MODEL
        self._hub = None

    def _get_hub(self):
        if self._hub is None:
            from mcp.hub import get_hub
            self._hub = get_hub()
            self._hub.initialize()
        return self._hub

    def _get_ollama_tools(self) -> List[Dict]:
        """Holt Tools aus MCPHub im Ollama-Format."""
        hub = self._get_hub()
        tool_defs = hub.list_tools()

        ollama_tools = []
        for t in tool_defs:
            name = t.get("name", "")
            if not name:
                continue
            ollama_tools.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": t.get("description", ""),
                    "parameters": t.get("inputSchema", {}) or {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            })

        log_debug(f"[LoopEngine] {len(ollama_tools)} tools available")
        return ollama_tools

    async def run_stream(
        self,
        user_text: str,
        system_prompt: str,
        initial_tool_context: str = "",
        max_iterations: int = MAX_LOOP_ITERATIONS,
    ) -> AsyncGenerator[Tuple[str, bool, Dict[str, Any]], None]:
        """
        Führt den ReAct-Loop aus und streamt die finale Antwort.

        Yields: (text_chunk, is_done, metadata)
        metadata.type Werte:
          - "loop_iteration"    : neue Runde gestartet
          - "loop_tool_call"    : Tool wird aufgerufen
          - "loop_tool_result"  : Tool-Ergebnis erhalten
          - "loop_max_reached"  : Max-Iterationen erreicht
          - "content"           : Text-Chunk der Antwort
          - "done"              : Fertig
        """
        hub = self._get_hub()
        tools = self._get_ollama_tools()

        # Seen-Tool-Calls für Loop-Schutz (identische Call-Signatur)
        _seen_calls: set = set()
        # Stuck-Tracker für wiederholte identische Ergebnisse
        _stuck = _StuckTracker()

        # System Prompt mit Loop-Suffix
        full_system = system_prompt + _LOOP_SYSTEM_SUFFIX.format(
            max_loops=max_iterations, current=0
        )
        messages: List[Dict] = [{"role": "system", "content": full_system}]

        # Initiale User-Message mit vorherigen Tool-Ergebnissen
        if initial_tool_context:
            user_msg = (
                f"{user_text}\n\n"
                f"--- Bisherige Tool-Ergebnisse (bereits ausgeführt) ---\n"
                f"{initial_tool_context}\n"
                f"--- Ende der Ergebnisse ---\n\n"
                f"Analysiere die Ergebnisse. Falls nötig, rufe weitere Tools auf. "
                f"Wenn alles erledigt ist, gib eine vollständige Antwort."
            )
        else:
            user_msg = (
                f"{user_text}\n\n"
                f"Erledige diese Aufgabe Schritt für Schritt mit den verfügbaren Tools."
            )

        messages.append({"role": "user", "content": user_msg})

        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            log_info(f"[LoopEngine] === Runde {iteration}/{max_iterations} ===")
            yield ("", False, {
                "type": "loop_iteration",
                "iteration": iteration,
                "max": max_iterations
            })

            # LLM-Call: stream=False um Tool-Calls zu erkennen
            try:
                async with httpx.AsyncClient(timeout=90.0) as client:
                    response = await client.post(
                        f"{self.ollama_base}/api/chat",
                        json={
                            "model": self.model,
                            "messages": messages,
                            "tools": tools,
                            "stream": False,
                            "keep_alive": "5m",
                        }
                    )
                    response.raise_for_status()
                    data = response.json()

            except httpx.TimeoutException:
                log_error(f"[LoopEngine] Timeout auf Runde {iteration}")
                yield ("", False, {"type": "loop_error", "error": "timeout", "iteration": iteration})
                break
            except Exception as e:
                log_error(f"[LoopEngine] LLM-Fehler Runde {iteration}: {e}")
                yield ("", False, {"type": "loop_error", "error": str(e), "iteration": iteration})
                break

            msg = data.get("message", {})
            tool_calls = msg.get("tool_calls", [])
            content = msg.get("content", "")

            # Antwort zur History hinzufügen
            assistant_msg: Dict = {"role": "assistant", "content": content or ""}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            if tool_calls:
                # ── TOOL-CALL-RUNDE ──
                tool_results_msgs: List[Dict] = []

                for tc in tool_calls:
                    fn = tc.get("function", {})
                    tool_name = fn.get("name", "")
                    tool_args = fn.get("arguments", {})

                    # Arguments können als String ankommen
                    if isinstance(tool_args, str):
                        try:
                            tool_args = json.loads(tool_args)
                        except Exception:
                            tool_args = {}

                    # Loop-Schutz: identische Calls überspringen
                    call_key = f"{tool_name}::{json.dumps(tool_args, sort_keys=True, default=str)}"
                    if call_key in _seen_calls:
                        log_warn(f"[LoopEngine] Doppelter Call übersprungen: {tool_name}")
                        tool_results_msgs.append({
                            "role": "tool",
                            "content": f"ALREADY_EXECUTED: {tool_name} wurde bereits mit diesen Argumenten aufgerufen.",
                        })
                        continue
                    _seen_calls.add(call_key)

                    log_info(f"[LoopEngine] Tool: {tool_name}({tool_args})")
                    yield ("", False, {
                        "type": "loop_tool_call",
                        "tool": tool_name,
                        "args": tool_args,
                        "iteration": iteration
                    })

                    try:
                        result = hub.call_tool(tool_name, tool_args)
                        # ToolResult-Objekt entpacken
                        if hasattr(result, 'content') and result.content is not None:
                            result_data = result.content
                        else:
                            result_data = result
                        result_str = (
                            json.dumps(result_data, ensure_ascii=False, default=str)
                            if isinstance(result_data, (dict, list))
                            else str(result_data)
                        )
                        log_info(f"[LoopEngine] Tool {tool_name} OK: {len(result_str)} chars")

                        # STUCK Detection: prüfe ob dieses Tool wiederholt gleiches Ergebnis liefert
                        is_stuck = _stuck.record_result(tool_name, result_str, iteration)

                        yield ("", False, {
                            "type": "loop_tool_result",
                            "tool": tool_name,
                            "success": True,
                            "stuck": is_stuck,
                            "iteration": iteration
                        })

                        tool_msg_content = result_str
                        if is_stuck:
                            log_warn(f"[LoopEngine] STUCK: {tool_name} liefert {MAX_SAME_RESULT}× gleiches Ergebnis")
                            yield ("", False, {
                                "type": "loop_stuck_detected",
                                "tool": tool_name,
                                "iteration": iteration
                            })
                            tool_msg_content = result_str + _stuck.build_stuck_injection(tool_name)

                        tool_results_msgs.append({
                            "role": "tool",
                            "content": tool_msg_content,
                        })

                    except Exception as te:
                        err_str = str(te)
                        _stuck.record_error(tool_name, err_str, iteration)
                        log_warn(f"[LoopEngine] Tool {tool_name} fehlgeschlagen: {err_str}")
                        yield ("", False, {
                            "type": "loop_tool_result",
                            "tool": tool_name,
                            "success": False,
                            "error": err_str,
                            "iteration": iteration
                        })
                        # Alternativ-Hinweis wenn bekanntes Fehlermuster erkannt
                        hint = _stuck.get_hint_for_error(err_str)
                        err_content = f"ERROR: {err_str}"
                        if hint:
                            err_content += f"\n\n[ALTERNATIVE-HINWEIS] {hint}"
                        tool_results_msgs.append({
                            "role": "tool",
                            "content": err_content,
                        })

                # Tool-Ergebnisse zur History → nächste Runde
                messages.extend(tool_results_msgs)

            else:
                # ── FINALE ANTWORT (keine Tool-Calls mehr) ──
                log_info(f"[LoopEngine] Finale Antwort nach {iteration} Runde(n), {len(content)} chars")

                if content:
                    # Streaming simulieren (content kommt als ganzes, da stream=False)
                    chunk_size = 60
                    for i in range(0, len(content), chunk_size):
                        yield (content[i:i + chunk_size], False, {"type": "content"})

                yield ("", True, {"type": "done", "iterations": iteration})
                return

        # ── MAX ITERATIONS ERREICHT ──
        log_warn(f"[LoopEngine] Max Runden ({max_iterations}) erreicht → erzwinge Abschluss")
        yield ("", False, {"type": "loop_max_reached", "iterations": max_iterations})

        # Abschließende Antwort erzwingen (ohne Tools, mit echtem Streaming)
        stuck_summary = _stuck.build_summary()
        force_finish_content = (
            f"Du hast die maximale Anzahl an Tool-Runden ({max_iterations}) erreicht. "
            "Gib jetzt eine vollständige Antwort — ohne weitere Tools.\n\n"
        )
        if stuck_summary:
            force_finish_content += (
                f"{stuck_summary}\n\n"
                "Erkläre dem User:\n"
                "  1. Was du herausgefunden hast\n"
                "  2. Was nicht funktioniert hat und warum\n"
                "  3. Was er selbst als nächstes tun kann\n"
            )
        else:
            force_finish_content += "Fasse alles bisher Erarbeitete zusammen."
        messages.append({
            "role": "user",
            "content": force_finish_content
        })

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    f"{self.ollama_base}/api/chat",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "stream": True,
                        "keep_alive": "5m",
                    }
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line:
                            try:
                                d = json.loads(line)
                                chunk = d.get("message", {}).get("content", "")
                                if chunk:
                                    yield (chunk, False, {"type": "content"})
                                if d.get("done"):
                                    break
                            except Exception:
                                continue

        except Exception as e:
            log_error(f"[LoopEngine] Force-finish Stream fehlgeschlagen: {e}")
            yield (
                f"Aufgabe nach {max_iterations} Schritten teilweise abgeschlossen.",
                False,
                {"type": "content"}
            )

        yield ("", True, {"type": "done", "iterations": max_iterations, "forced": True})
