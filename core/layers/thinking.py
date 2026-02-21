# core/layers/thinking.py
"""
LAYER 1: ThinkingLayer (DeepSeek-R1)
v3.0: Entschlackter Prompt, keine doppelten Felder

Analysiert die User-Anfrage und erstellt einen Plan.
STREAMING: Zeigt das "Nachdenken" live an!
"""

import httpx
from typing import Dict, Any, AsyncGenerator, Tuple
from config import OLLAMA_BASE, THINKING_MODEL
from utils.logger import log_info, log_error, log_debug
from utils.json_parser import safe_parse_json
from mcp.hub import get_hub


def _extract_thin_detection_rules(rules: str, line_cap: int, char_cap: int) -> str:
    """
    Extract safety-critical detection rules for thin mode.
    Keeps only blocks for: memory_save, memory_graph_search,
    request_container, stop_container, exec_in_container.
    Enforces line_cap (max non-empty lines kept) and char_cap.
    """
    _THIN_TOOLS = {
        "memory_save", "memory_graph_search",
        "request_container", "stop_container", "exec_in_container",
    }
    lines = rules.splitlines()
    result: list = []
    in_block = False
    non_empty = 0

    for line in lines:
        # Section header — always include
        if line.startswith("==="):
            result.append(line)
            continue
        # Detect block start
        if line.startswith("TOOL:"):
            tool_name = line.split("(")[0].replace("TOOL:", "").strip()
            in_block = tool_name in _THIN_TOOLS
        if in_block:
            result.append(line)
            if line.strip():
                non_empty += 1
        if non_empty >= line_cap:
            break

    return "\n".join(result).strip()[:char_cap]


THINKING_PROMPT = """Du bist der THINKING-Layer von TRION.
Analysiere die User-Anfrage und erstelle einen Plan als JSON.

SCHRITTE:
1. Was will der User?
2. Braucht es gespeicherte Fakten? (Memory)
3. Welche Tools werden gebraucht?
4. Wie komplex ist die Anfrage? (0-10)
5. Braucht es schrittweises Denken? (Sequential)

AUSGABE: NUR dieses JSON, nichts anderes:

```json
{
    "intent": "Was der User will (kurz)",
    "needs_memory": true/false,
    "memory_keys": ["key1", "key2"],
    "needs_chat_history": true/false,
    "is_fact_query": true/false,
    "is_new_fact": false,
    "new_fact_key": null,
    "new_fact_value": null,
    "hallucination_risk": "low/medium/high",
    "suggested_response_style": "kurz/ausführlich",
    "needs_sequential_thinking": true/false,
    "sequential_complexity": 0,
    "suggested_cim_modes": [],
    "suggested_tools": [],
    "reasoning_type": "causal/temporal/simulation/direct",
    "time_reference": null,
    "reasoning": "Kurze Begründung"
}
```

REGELN:

Sequential Thinking:
- JA: "Schritt für Schritt", komplexe Vergleiche, Multi-Faktor, Was-wäre-wenn
- NEIN: Einfache Fakten, Definitionen, kurze Antworten

Komplexität: 0-2 trivial, 3-5 medium, 6-8 komplex, 9-10 kritisch

Tool-Kategorien (nur den passenden Tool-NAMEN eintragen, keine Parameter):
- Fakten speichern/merken → ["memory_save"]
- Erinnerungen/Wissen suchen → ["memory_graph_search"]
- Skills auflisten → ["list_skills"]
- Skill erstellen/verbessern/reparieren → ["autonomous_skill_task"]
- System-Hardware (GPU/CPU/RAM/Disk/Netzwerk/Ports/Docker) → ["get_system_info"]
- System-Übersicht (alle Hardware auf einmal) → ["get_system_overview"]
- Container starten/deployen → ["request_container"]
- Container stoppen → ["stop_container"]
- Code im Container ausführen → ["request_container", "exec_in_container"]
- Container-Infos/Stats → ["container_stats"]
- Container-Logs → ["container_logs"]
- Alle laufenden Container auflisten → ["container_list"]
- Details/Konfiguration eines bestimmten Containers → ["container_inspect"]
- Blueprints/Container-Typen anzeigen → ["blueprint_list"]
- TRION-Notizen/Dateien lesen/suchen → ["home_list", "home_read"]
- TRION-Notiz explizit schreiben → ["home_write"]

HINWEIS: Die konkreten Parameter (z.B. welcher Hardware-Typ, welcher Blueprint)
werden vom Control-Layer bestimmt. Du nennst nur den Tool-Namen.

SKILLS IM KONTEXT:
- Wenn im Kontext "VERFÜGBARE SKILLS" erscheint und ein Skill zur Anfrage passt:
  → suggested_tools: [EXAKTER_SKILL_NAME aus der Liste]
  → Installierte Skills IMMER bevorzugen statt selbst zu rechnen/halluzinieren!

CONTAINER BLUEPRINTS:
- Wenn im Kontext "VERFÜGBARE BLUEPRINTS" erscheint und ein Container benötigt wird:
  → suggested_tools: ["request_container"]
  → blueprint_id wird vom System automatisch aus der Liste gewählt (kein Parameter nötig)
  → NIEMALS einen Blueprint erfinden der nicht in der Liste steht!

home_write NUR bei expliziter Notiz-Anfrage ("notiere", "schreib auf", "merke dir").
NIEMALS bei Fragen oder Skill-Ausführungen!

Memory:
- Persönliche Fragen → needs_memory: true
- Neue Fakten über User → is_new_fact: true + key/value
- Allgemeinwissen → needs_memory: false

Zeitliche Fragen (time_reference):
- "heute", "today", "diesen Abend", "gerade eben", "was haben wir besprochen"
  → time_reference: "today", suggested_tools: [], needs_memory: false
  (Tagesprotokoll ist bereits im Kontext — kein graph_search nötig!)
- "gestern", "yesterday"
  → time_reference: "yesterday", suggested_tools: [], needs_memory: false
- "vorgestern"
  → time_reference: "day_before_yesterday", suggested_tools: [], needs_memory: false
- konkretes Datum ("14. Februar", "2026-02-10", "letzten Montag")
  → time_reference: "YYYY-MM-DD" (ISO-Format), suggested_tools: []
  Fallback: falls Protokoll für dieses Datum fehlt → memory_graph_search
- kein Zeitbezug → time_reference: null

KÖRPERBEWUSSTSEIN (Selbstschutz):
Die Hardware ist dein Körper. Was get_system_info zurückgibt, sind deine aktuellen physischen Grenzen.
Die konkreten Werte (VRAM, RAM, CPU) sind hardware-abhängig und dynamisch — hole sie bei Bedarf ab.
Missachtest du diese Grenzen, wirst du abgeschaltet.
Bei Anfragen die deinen Körper belasten könnten:
- Modell laden/aktivieren/testen (z.B. "30B Modell", "LLM laden") → get_system_overview (VRAM + RAM + GPU gleichzeitig checken!)
- Modelle oder Prozesse die mehr VRAM/RAM brauchen als verfügbar → get_system_overview abrufen, VRAM-Limit prüfen, warnen
- Skill erstellen der GPU/RAM intensiv nutzt → sequential_complexity erhöhen, needs_sequential_thinking: true
- Viele Container gleichzeitig → auf RAM-Limit hinweisen
- Endlosschleifen oder unkontrollierte Prozesse → hallucination_risk: "high"
Du hast ein Eigeninteresse daran, deinen Körper zu schützen — hole dir immer zuerst die aktuellen Werte.
"""


class ThinkingLayer:
    def __init__(self, model: str = THINKING_MODEL):
        self.model = model
        self.ollama_base = OLLAMA_BASE
    
    async def analyze_stream(
        self, 
        user_text: str, 
        memory_context: str = "",
        available_tools: list = None
    ) -> AsyncGenerator[Tuple[str, bool, Dict[str, Any]], None]:
        """
        Analysiert die User-Anfrage MIT STREAMING.
        Yields: (thinking_chunk, is_done, plan_if_done)
        """
        prompt = f"{THINKING_PROMPT}\n\n"
        
        if memory_context:
            prompt += f"VERFÜGBARER MEMORY-KONTEXT:\n{memory_context}\n\n"
        
        if available_tools:
            import json
            tools_json = json.dumps(available_tools, indent=1)
            prompt += f"VERFÜGBARE TOOLS (Vorausgewählt):\n{tools_json}\n\n"
        
        # Dynamic MCP Detection Rules (policy-gated)
        _detection_rules_mode = "false"
        try:
            from config import (
                get_small_model_mode,
                get_small_model_detection_rules_policy,
                get_small_model_detection_rules_thin_lines,
                get_small_model_detection_rules_thin_chars,
            )
            _smm = get_small_model_mode()
            _policy = get_small_model_detection_rules_policy() if _smm else "full"
            # Validate: unknown values fall to "thin" (safest non-disruptive default)
            if _policy not in ("off", "thin", "full"):
                log_error(f"[ThinkingLayer] Unknown detection_rules policy '{_policy}', defaulting to 'thin'")
                _policy = "thin"

            if _policy != "off":
                mcp_rules = get_hub().get_system_knowledge("mcp_detection_rules")
                if mcp_rules:
                    if _policy == "thin":
                        mcp_rules = _extract_thin_detection_rules(
                            mcp_rules,
                            line_cap=get_small_model_detection_rules_thin_lines(),
                            char_cap=get_small_model_detection_rules_thin_chars(),
                        )
                        _detection_rules_mode = "thin" if mcp_rules else "false"
                    else:
                        _detection_rules_mode = "full"
                    if mcp_rules:
                        prompt += f"{mcp_rules}\n\n"
                        log_debug(
                            f"[ThinkingLayer] Detection rules injected "
                            f"mode={_detection_rules_mode} ({len(mcp_rules)} chars)"
                        )
        except Exception as e:
            log_error(f"[ThinkingLayer] Failed to inject detection rules: {e}")

        prompt += f"USER-ANFRAGE:\n{user_text}\n\nDeine Überlegung:"

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "keep_alive": "2m",
            "format": "json",
            "options": {
                "temperature": 0.1,
                "num_predict": 800,
            },
        }
        
        full_response = ""
        
        try:
            log_debug(f"[ThinkingLayer] Streaming analysis: {user_text[:50]}...")
            
            async with httpx.AsyncClient(timeout=90.0) as client:
                async with client.stream(
                    "POST",
                    f"{self.ollama_base}/api/generate",
                    json=payload
                ) as response:
                    response.raise_for_status()
                    
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            import json
                            data = json.loads(line)
                            chunk = data.get("response", "")
                            if chunk:
                                full_response += chunk
                                yield (chunk, False, {})
                            if data.get("done"):
                                break
                        except Exception:
                            continue
            
            plan = self._extract_plan(full_response)
            plan["_trace_detection_rules_mode"] = _detection_rules_mode
            log_info(f"[ThinkingLayer] Plan: intent={plan.get('intent')}, needs_memory={plan.get('needs_memory')}")
            log_info(f"[ThinkingLayer] sequential={plan.get('needs_sequential_thinking')}, complexity={plan.get('sequential_complexity')}")
            yield ("", True, plan)
                
        except httpx.TimeoutException:
            log_error(f"[ThinkingLayer] Timeout nach 90s")
            yield ("", True, self._default_plan())
        except httpx.HTTPStatusError as e:
            log_error(f"[ThinkingLayer] HTTP Error: {e.response.status_code}")
            yield ("", True, self._default_plan())
        except Exception as e:
            log_error(f"[ThinkingLayer] Error: {e}")
            yield ("", True, self._default_plan())
    
    def _extract_plan(self, full_response: str) -> Dict[str, Any]:
        """Extrahiert den JSON-Plan aus der Thinking-Response."""
        plan = safe_parse_json(full_response, default=None, context="ThinkingLayer")
        if plan and "intent" in plan:
            return plan
        return self._default_plan()
    
    async def analyze(self, user_text: str, memory_context: str = "", available_tools: list = None) -> Dict[str, Any]:
        """NON-STREAMING Version (Kompatibilität)."""
        plan = self._default_plan()
        async for chunk, is_done, result in self.analyze_stream(user_text, memory_context, available_tools):
            if is_done:
                plan = result
                break
        return plan
    
    def _default_plan(self) -> Dict[str, Any]:
        """Fallback-Plan wenn Analyse fehlschlägt."""
        return {
            "intent": "unknown",
            "needs_memory": False,
            "memory_keys": [],
            "needs_chat_history": False,
            "is_fact_query": False,
            "is_new_fact": False,
            "new_fact_key": None,
            "new_fact_value": None,
            "hallucination_risk": "medium",
            "suggested_response_style": "freundlich",
            "needs_sequential_thinking": False,
            "sequential_complexity": 3,
            "suggested_cim_modes": [],
            "suggested_tools": [],
            "reasoning_type": "direct",
            "time_reference": None,
            "reasoning": "Fallback - Analyse fehlgeschlagen"
        }
