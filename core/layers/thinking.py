# core/layers/thinking.py
"""
LAYER 1: ThinkingLayer (DeepSeek-R1)

Analysiert die User-Anfrage und erstellt einen Plan:
- Was will der User?
- Brauche ich Memory?
- Welche Fakten sind relevant?
- Wie sollte die Antwort strukturiert sein?
- Halluzinations-Risiko?
"""

import json
import requests
from typing import Dict, Any, Optional
from config import OLLAMA_BASE
from utils.logger import log_info, log_error, log_debug

THINKING_MODEL = "deepseek-r1:8b"

THINKING_PROMPT = """Du bist der THINKING-Layer eines AI-Systems.
Deine Aufgabe: Analysiere die User-Anfrage und erstelle einen Plan.

Du antwortest NUR mit validem JSON, nichts anderes.

Analysiere:
1. Was will der User wirklich?
2. Braucht die Antwort gespeicherte Fakten? (Memory)
3. Welcher Memory-Key ist relevant? (z.B. "age", "name", "birthday")
4. Ist dies eine Fakten-Abfrage oder neue Information?
5. Wie hoch ist das Halluzinations-Risiko?

JSON-Format:
{
    "intent": "Was der User will (kurz)",
    "needs_memory": true/false,
    "memory_keys": ["key1", "key2"],
    "is_fact_query": true/false,
    "is_new_fact": true/false,
    "new_fact_key": "key oder null",
    "new_fact_value": "value oder null",
    "hallucination_risk": "low/medium/high",
    "suggested_response_style": "kurz/ausführlich/freundlich",
    "reasoning": "Kurze Begründung"
}

BEISPIELE:

User: "Wie alt bin ich?"
{
    "intent": "User fragt nach seinem Alter",
    "needs_memory": true,
    "memory_keys": ["age"],
    "is_fact_query": true,
    "is_new_fact": false,
    "new_fact_key": null,
    "new_fact_value": null,
    "hallucination_risk": "high",
    "suggested_response_style": "kurz",
    "reasoning": "Alter ist persönlicher Fakt, muss aus Memory kommen"
}

User: "Ich bin 31 Jahre alt"
{
    "intent": "User teilt sein Alter mit",
    "needs_memory": false,
    "memory_keys": [],
    "is_fact_query": false,
    "is_new_fact": true,
    "new_fact_key": "age",
    "new_fact_value": "31",
    "hallucination_risk": "low",
    "suggested_response_style": "freundlich",
    "reasoning": "Neuer Fakt zum Speichern"
}

User: "Was ist die Hauptstadt von Frankreich?"
{
    "intent": "Allgemeine Wissensfrage",
    "needs_memory": false,
    "memory_keys": [],
    "is_fact_query": false,
    "is_new_fact": false,
    "new_fact_key": null,
    "new_fact_value": null,
    "hallucination_risk": "low",
    "suggested_response_style": "kurz",
    "reasoning": "Allgemeinwissen, kein persönlicher Fakt"
}

WICHTIG:
- NUR JSON ausgeben
- KEIN Text vor oder nach dem JSON
- Bei Unsicherheit: hallucination_risk = "high"
"""


class ThinkingLayer:
    def __init__(self, model: str = THINKING_MODEL):
        self.model = model
        self.ollama_base = OLLAMA_BASE
    
    async def analyze(self, user_text: str, memory_context: str = "") -> Dict[str, Any]:
        """
        Analysiert die User-Anfrage und erstellt einen Plan.
        """
        prompt = f"{THINKING_PROMPT}\n\n"
        
        if memory_context:
            prompt += f"VERFÜGBARER MEMORY-KONTEXT:\n{memory_context}\n\n"
        
        prompt += f"USER-ANFRAGE:\n{user_text}\n\nDein JSON-Plan:"
        
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }
        
        try:
            log_debug(f"[ThinkingLayer] Analyzing: {user_text[:50]}...")
            
            r = requests.post(
                f"{self.ollama_base}/api/generate",
                json=payload,
                timeout=60
            )
            r.raise_for_status()
            
            data = r.json()
            content = data.get("response", "").strip()
            
            # Qwen/DeepSeek manchmal "thinking" statt "response"
            if not content and data.get("thinking"):
                content = data.get("thinking", "").strip()
            
            if not content:
                log_error(f"[ThinkingLayer] Leere Antwort")
                return self._default_plan()
            
            # JSON extrahieren
            try:
                # Falls das Model zusätzlichen Text drumrum schreibt
                if "{" in content:
                    start = content.index("{")
                    end = content.rindex("}") + 1
                    content = content[start:end]
                
                result = json.loads(content)
                log_info(f"[ThinkingLayer] Plan: intent={result.get('intent')}, needs_memory={result.get('needs_memory')}")
                return result
                
            except json.JSONDecodeError as e:
                log_error(f"[ThinkingLayer] JSON Parse Error: {e}, Content: {content[:200]}")
                return self._default_plan()
                
        except Exception as e:
            log_error(f"[ThinkingLayer] Error: {e}")
            return self._default_plan()
    
    def _default_plan(self) -> Dict[str, Any]:
        """Fallback-Plan wenn Analyse fehlschlägt."""
        return {
            "intent": "unknown",
            "needs_memory": False,
            "memory_keys": [],
            "is_fact_query": False,
            "is_new_fact": False,
            "new_fact_key": None,
            "new_fact_value": None,
            "hallucination_risk": "medium",
            "suggested_response_style": "freundlich",
            "reasoning": "Fallback - Analyse fehlgeschlagen"
        }
