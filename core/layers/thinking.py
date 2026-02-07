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
    "reasoning": "Kurze Begründung"
}
```

REGELN:

Sequential Thinking:
- JA: "Schritt für Schritt", komplexe Vergleiche, Multi-Faktor, Was-wäre-wenn
- NEIN: Einfache Fakten, Definitionen, kurze Antworten

Komplexität: 0-2 trivial, 3-5 medium, 6-8 komplex, 9-10 kritisch

Tool-Erkennung:
- "merken/speichern/remember" → ["memory_save"]
- "erinnern/was weißt du" → ["memory_graph_search"]
- "skill erstellen/create skill" → ["create_skill"]
- "skills zeigen" → ["list_skills"]
- "skill ausführen" → ["run_skill"]

Container Commander Tools:
- "blueprints/container-typen/sandbox" → ["blueprint_list"]
- "starte container/deploy/brauche sandbox" → ["request_container"]
- "stoppe container/beende container" → ["stop_container"]
- "führe aus/execute/run code" → ["request_container", "exec_in_container"]
- "container stats/auslastung" → ["container_stats"]
- "container logs" → ["container_logs"]
- "snapshot/backup" → ["snapshot_list"]
- "optimiere container" → ["optimize_container"]

Memory:
- Persönliche Fragen → needs_memory: true
- Neue Fakten über User → is_new_fact: true + key/value
- Allgemeinwissen → needs_memory: false
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
        
        # Dynamic MCP Detection Rules
        try:
            mcp_rules = get_hub().get_system_knowledge("mcp_detection_rules")
            if mcp_rules:
                prompt += f"{mcp_rules}\n\n"
                log_debug(f"[ThinkingLayer] Injected detection rules ({len(mcp_rules)} chars)")
        except Exception as e:
            log_error(f"[ThinkingLayer] Failed to inject detection rules: {e}")

        prompt += f"USER-ANFRAGE:\n{user_text}\n\nDeine Überlegung:"

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "keep_alive": "2m",
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
            "reasoning": "Fallback - Analyse fehlgeschlagen"
        }
