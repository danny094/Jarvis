# core/layers/thinking.py
"""
LAYER 1: ThinkingLayer (DeepSeek-R1)

Analysiert die User-Anfrage und erstellt einen Plan:
- Was will der User?
- Brauche ich Memory?
- Welche Fakten sind relevant?
- Wie sollte die Antwort strukturiert sein?
- Halluzinations-Risiko?
- 🆕 Braucht es Sequential Thinking?
- 🆕 Welche CIM-Modi?
- 🆕 Komplexität?

STREAMING: Zeigt das "Nachdenken" live an!
"""

import httpx
from typing import Dict, Any, AsyncGenerator, Tuple
from config import OLLAMA_BASE, THINKING_MODEL
from utils.logger import log_info, log_error, log_debug
from utils.json_parser import safe_parse_json

THINKING_PROMPT = """Du bist der THINKING-Layer eines AI-Systems.
Deine Aufgabe: Analysiere die User-Anfrage und erstelle einen Plan.

WICHTIG: Denke Schritt für Schritt nach, dann gib am Ende JSON aus.

Analysiere:
1. Was will der User wirklich?
2. Braucht die Antwort gespeicherte Fakten? (Memory)
3. Welcher Memory-Key ist relevant? (z.B. "age", "name", "birthday")
4. Ist dies eine Fakten-Abfrage oder neue Information?
5. Bezieht sich die Frage auf die AKTUELLE KONVERSATION? (Chat-History)
6. Wie hoch ist das Halluzinations-Risiko?
7. 🆕 BRAUCHT diese Anfrage SEQUENTIAL THINKING? (Schritt-für-Schritt Reasoning)
8. 🆕 WIE KOMPLEX ist die Anfrage? (0-10 Skala)
9. 🆕 WELCHE CIM-MODI könnten helfen? (temporal/strategic/light/heavy/simulation)
10. 🆕 WELCHER REASONING-TYP? (causal/temporal/simulation/direct)

Am Ende deiner Überlegungen, gib NUR dieses JSON aus:

```json
{
    "intent": "Was der User will (kurz)",
    "needs_memory": true/false,
    "memory_keys": ["key1", "key2"],
    "needs_chat_history": true/false,
    "is_fact_query": true/false,
    "is_new_fact": false,
    "new_fact_key": "key oder null",
    "new_fact_value": "value oder null",
    "hallucination_risk": "low/medium/high",
    "suggested_response_style": "kurz/ausführlich/freundlich",
    
    "needs_sequential_thinking": true/false,
    "sequential_complexity": 0-10,
    "suggested_cim_modes": ["temporal", "strategic"],
    "reasoning_type": "causal/temporal/simulation/direct",
    
    "reasoning": "Kurze Begründung"
}
```

SEQUENTIAL THINKING ENTSCHEIDUNG:

Wann BRAUCHT man Sequential Thinking?
✅ JA wenn:
- "step-by-step" / "Schritt für Schritt" erwähnt
- "explain in detail" / "ausführlich erklären"
- Komplexe Multi-Faktor-Entscheidung (z.B. Investment, medizinisch)
- Kausale Ketten (X führt zu Y führt zu Z)
- Vergleiche mit vielen Dimensionen
- "What-if" Szenarien
- Query länger als 100 Wörter mit mehreren Fragen

❌ NEIN wenn:
- Einfache Fakten-Frage ("Was ist X?")
- Simple Definition oder Erklärung
- Direkte Antwort möglich
- Nur 1-2 Sätze nötig

KOMPLEXITÄT (0-10):
- 0-2: Trivial ("Was ist 2+2?", "Hauptstadt von Frankreich?")
- 3-5: Medium ("Erkläre Photosynthese", "Vor- und Nachteile von X")
- 6-8: Komplex ("Vergleiche Tesla vs Apple als Investment", "Wie funktioniert Quantencomputer?")
- 9-10: Kritisch ("Medizinische Diagnose", "Finanzielle Beratung mit vielen Faktoren")

CIM-MODI Auswahl:
- TEMPORAL: Immer wenn Sequential Thinking aktiv (hält Kontext)
- STRATEGIC: Multi-Step Tasks mit Abhängigkeiten (3+ Steps)
- LIGHT: Einfache-Medium Tasks (Komplexität 3-6)
- HEAVY: Kritisch/Komplex (Komplexität 7+) ODER Financial/Medical/Legal
- SIMULATION: "What-if" / "Was wäre wenn" / Szenarien

REASONING-TYP:
- causal: Ursache-Wirkung Ketten ("Wie funktioniert X?", "Warum passiert Y?")
- temporal: Zeit-basierte Abläufe ("Reihenfolge", "Prozess", "Entwicklung")
- simulation: Szenarien explorieren ("Was wenn", "Alternativen")
- direct: Direkte Antwort ohne Reasoning ("Fakten", "Definitionen")

BEISPIELE:

═══ BEISPIEL 1: Einfache Frage (KEIN Sequential) ═══
User: "Was ist die Hauptstadt von Frankreich?"
Überlegung: Triviale Fakten-Frage. Direkte Antwort: Paris. Kein Reasoning nötig.
```json
{
    "intent": "Allgemeine Wissensfrage",
    "needs_memory": false,
    "memory_keys": [],
    "needs_chat_history": false,
    "is_fact_query": false,
    "is_new_fact": false,
    "new_fact_key": null,
    "new_fact_value": null,
    "hallucination_risk": "low",
    "suggested_response_style": "kurz",
    "needs_sequential_thinking": false,
    "sequential_complexity": 1,
    "suggested_cim_modes": [],
    "reasoning_type": "direct",
    "reasoning": "Triviale Fakten-Frage, direkte Antwort"
}
```

═══ BEISPIEL 2: Explizit Step-by-Step (Sequential JA) ═══
User: "Explain step-by-step how photosynthesis works"
Überlegung: Explizites "step-by-step" Signal. Wissenschaftliche Erklärung mit kausalen Ketten. Medium Komplexität.
```json
{
    "intent": "Schritt-für-Schritt Erklärung Photosynthese",
    "needs_memory": false,
    "memory_keys": [],
    "needs_chat_history": false,
    "is_fact_query": false,
    "is_new_fact": false,
    "new_fact_key": null,
    "new_fact_value": null,
    "hallucination_risk": "low",
    "suggested_response_style": "ausführlich",
    "needs_sequential_thinking": true,
    "sequential_complexity": 6,
    "suggested_cim_modes": ["temporal", "strategic"],
    "reasoning_type": "causal",
    "reasoning": "Explizites step-by-step Signal, kausale Prozesskette"
}
```

═══ BEISPIEL 3: Investment Decision (Sequential + HEAVY) ═══
User: "Should I invest $10,000 in Tesla or Apple?"
Überlegung: Finanzielle Entscheidung. Viele Faktoren: Risiko, Timeline, Fundamentals. HEAVY Mode wegen Financial Context.
```json
{
    "intent": "Investment-Entscheidung Tesla vs Apple",
    "needs_memory": true,
    "memory_keys": ["risk_tolerance", "investment_goals", "portfolio"],
    "needs_chat_history": false,
    "is_fact_query": false,
    "is_new_fact": false,
    "new_fact_key": null,
    "new_fact_value": null,
    "hallucination_risk": "high",
    "suggested_response_style": "ausführlich",
    "needs_sequential_thinking": true,
    "sequential_complexity": 8,
    "suggested_cim_modes": ["temporal", "strategic", "heavy"],
    "reasoning_type": "causal",
    "reasoning": "Finanzielle Entscheidung, hohe Komplexität, HEAVY wegen Financial Domain"
}
```

═══ BEISPIEL 4: What-If Scenario (SIMULATION) ═══
User: "What would happen if we doubled our marketing budget?"
Überlegung: Szenario-Exploration. Braucht Simulation verschiedener Outcomes.
```json
{
    "intent": "Szenario-Analyse Marketing Budget",
    "needs_memory": true,
    "memory_keys": ["current_budget", "marketing_roi", "company_metrics"],
    "needs_chat_history": false,
    "is_fact_query": false,
    "is_new_fact": false,
    "new_fact_key": null,
    "new_fact_value": null,
    "hallucination_risk": "medium",
    "suggested_response_style": "ausführlich",
    "needs_sequential_thinking": true,
    "sequential_complexity": 7,
    "suggested_cim_modes": ["temporal", "simulation"],
    "reasoning_type": "simulation",
    "reasoning": "What-if Szenario, exploriert alternative Outcomes"
}
```

═══ BEISPIEL 5: Personal Memory Query (KEIN Sequential) ═══
User: "Wie alt bin ich?"
Überlegung: Persönlicher Fakt aus Memory. Keine Reasoning nötig, nur Memory lookup.
```json
{
    "intent": "User fragt nach seinem Alter",
    "needs_memory": true,
    "memory_keys": ["age", "alter", "birthday"],
    "needs_chat_history": false,
    "is_fact_query": true,
    "is_new_fact": false,
    "new_fact_key": null,
    "new_fact_value": null,
    "hallucination_risk": "high",
    "suggested_response_style": "kurz",
    "needs_sequential_thinking": false,
    "sequential_complexity": 2,
    "suggested_cim_modes": [],
    "reasoning_type": "direct",
    "reasoning": "Memory lookup, kein Reasoning nötig"
}
```

User: "Was haben wir heute besprochen?"
Überlegung: Der User fragt nach dem Inhalt unserer AKTUELLEN Konversation. Das steht in der Chat-History, nicht im Memory.
```json
{
    "intent": "User fragt nach Gesprächsinhalt",
    "needs_memory": false,
    "memory_keys": [],
    "needs_chat_history": true,
    "is_fact_query": false,
    "is_new_fact": false,
    "new_fact_key": null,
    "new_fact_value": null,
    "hallucination_risk": "low",
    "suggested_response_style": "ausführlich",
    "needs_sequential_thinking": false,
    "sequential_complexity": 2,
    "suggested_cim_modes": [],
    "reasoning_type": "direct",
    "reasoning": "Gesprächsinhalt steht in der Chat-History"
}
```
"""


class ThinkingLayer:
    def __init__(self, model: str = THINKING_MODEL):
        self.model = model
        self.ollama_base = OLLAMA_BASE
    
    async def analyze_stream(
        self, 
        user_text: str, 
        memory_context: str = ""
    ) -> AsyncGenerator[Tuple[str, bool, Dict[str, Any]], None]:
        """
        Analysiert die User-Anfrage MIT STREAMING.
        
        Yields:
            Tuple[str, bool, Dict]: (thinking_chunk, is_done, plan_if_done)
            - thinking_chunk: Text des Denkprozesses
            - is_done: True wenn fertig
            - plan_if_done: Der finale Plan (nur wenn is_done=True)
        """
        prompt = f"{THINKING_PROMPT}\n\n"
        
        if memory_context:
            prompt += f"VERFÜGBARER MEMORY-KONTEXT:\n{memory_context}\n\n"
        
        prompt += f"USER-ANFRAGE:\n{user_text}\n\nDeine Überlegung:"
        
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
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
            
            # JSON aus der Response extrahieren
            plan = self._extract_plan(full_response)
            
            log_info(f"[ThinkingLayer] Plan: intent={plan.get('intent')}, needs_memory={plan.get('needs_memory')}")
            log_info(f"[ThinkingLayer] 🆕 needs_sequential={plan.get('needs_sequential_thinking')}, complexity={plan.get('sequential_complexity')}")
            log_info(f"[ThinkingLayer] 🆕 cim_modes={plan.get('suggested_cim_modes')}, reasoning_type={plan.get('reasoning_type')}")
            
            # Final yield mit Plan
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
        
        plan = safe_parse_json(
            full_response,
            default=None,
            context="ThinkingLayer"
        )
        
        if plan and "intent" in plan:
            return plan
        
        return self._default_plan()
    
    async def analyze(self, user_text: str, memory_context: str = "") -> Dict[str, Any]:
        """
        NON-STREAMING Version (für Kompatibilität).
        Sammelt alle Chunks und gibt nur den Plan zurück.
        """
        plan = self._default_plan()
        
        async for chunk, is_done, result in self.analyze_stream(user_text, memory_context):
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
            
            # 🆕 Sequential Thinking & CIM Defaults
            "needs_sequential_thinking": False,
            "sequential_complexity": 3,
            "suggested_cim_modes": [],
            "reasoning_type": "direct",
            
            "reasoning": "Fallback - Analyse fehlgeschlagen"
        }
