# core/layers/thinking.py
"""
LAYER 1: ThinkingLayer (DeepSeek-R1)

Analysiert die User-Anfrage und erstellt einen Plan:
- Was will der User?
- Brauche ich Memory?
- Welche Fakten sind relevant?
- Wie sollte die Antwort strukturiert sein?
- Halluzinations-Risiko?

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
    "reasoning": "Kurze Begründung"
}
```

BEISPIELE:

User: "Wie alt bin ich?"
Überlegung: Der User fragt nach seinem Alter. Das ist ein persönlicher Fakt, den ich nicht wissen kann. Ich muss im Memory nachschauen. Wenn ich rate, ist das Halluzination.
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
    "reasoning": "Alter ist persönlicher Fakt, muss aus Memory kommen"
}
```

User: "Was haben wir heute besprochen?" / "Worüber haben wir geredet?" / "Was war meine letzte Frage?"
Überlegung: Der User fragt nach dem Inhalt unserer AKTUELLEN Konversation. Das steht in der Chat-History, nicht im Memory. Ich muss die bisherigen Nachrichten nutzen.
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
    "reasoning": "Gesprächsinhalt steht in der Chat-History, nicht im Memory"
}
```

User: "Was ist die Hauptstadt von Frankreich?"
Überlegung: Das ist Allgemeinwissen. Paris ist die Hauptstadt. Kein Memory nötig, kein Halluzinationsrisiko.
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
    "reasoning": "Allgemeinwissen, kein persönlicher Fakt"
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
            "stream": True,  # STREAMING!
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
                                # Yield thinking chunk (nicht done)
                                yield (chunk, False, {})
                            
                            if data.get("done"):
                                break
                                
                        except Exception:
                            continue
            
            # Jetzt JSON aus der Response extrahieren
            plan = self._extract_plan(full_response)
            
            log_info(f"[ThinkingLayer] Plan: intent={plan.get('intent')}, needs_memory={plan.get('needs_memory')}")
            
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
        
        # Versuche JSON zu finden
        plan = safe_parse_json(
            full_response,
            default=None,
            context="ThinkingLayer"
        )
        
        if plan and "intent" in plan:
            return plan
        
        # Fallback
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
            "reasoning": "Fallback - Analyse fehlgeschlagen"
        }
