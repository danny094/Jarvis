# core/layers/thinking.py
"""
LAYER 1: ThinkingLayer (DeepSeek-R1)

Analysiert die User-Anfrage und erstellt einen Plan:
- Was will der User?
- Brauche ich Memory?
- Braucht es einen Sandbox-Container?
- Soll das Code-Model genutzt werden?
- Halluzinations-Risiko?

STREAMING: Zeigt das "Nachdenken" live an!
"""

import httpx
from typing import Dict, Any, AsyncGenerator, Tuple
from config import OLLAMA_BASE, THINKING_MODEL
from utils.logger import log_info, log_error, log_debug
from utils.json_parser import safe_parse_json

# KOMPAKTER Prompt für schnellere Verarbeitung
THINKING_PROMPT = """Analysiere die User-Anfrage. Antworte NUR mit JSON.

REGELN:
- Persönliche Fakten (Alter, Name, Geburtstag) → needs_memory: true, hallucination_risk: high
- Chat-Fragen ("Was haben wir besprochen?") → needs_chat_history: true
- Allgemeinwissen → needs_memory: false, hallucination_risk: low
- Tool-Fragen ("Welche Tools hast du?") → needs_memory: true, memory_keys: ["available_mcp_tools"]
- Neue Fakten ("Ich bin 25") → is_new_fact: true, new_fact_key + new_fact_value setzen

AUTO-EXECUTE REGELN (WICHTIG!):
Wenn die Nachricht einen Code-Block (```) enthält UND einer dieser Fälle zutrifft → needs_container: true:

1. EXPLIZITE AUSFÜHRUNG:
   - "teste", "ausführen", "run", "execute", "probier", "starte"
   
2. IMPLIZITE AUSFÜHRUNG (Code-Block vorhanden + diese Phrasen):
   - "was gibt das aus?" / "was ist das Ergebnis?" / "was kommt raus?"
   - "funktioniert das?" / "läuft das?" / "geht das?"
   - "ist das korrekt?" / "stimmt das?" / "richtig so?"
   - "hier ist mein Code" + Frage
   - "schau dir das an" + Code
   - "kannst du das checken?"
   - Nur Code-Block ohne weitere Erklärung (User will Output sehen)
   
3. KEINE AUSFÜHRUNG (auch wenn Code-Block da):
   - "erkläre" / "erklär mir" / "was macht dieser Code?"
   - "wie funktioniert" / "warum" 
   - "verbessere" / "optimiere" / "refactor" (erst analysieren!)
   - "schreib mir" / "erstelle" (Code generieren, nicht ausführen)
   - "was ist falsch?" (erst analysieren, dann ggf. fixen+testen)

CONTAINER-REGELN:
- Code ausführen/testen → needs_container: true, container_name: "code-sandbox"
- Code nur analysieren/erklären → needs_container: false, use_code_model: true
- Normales Gespräch → needs_container: false, use_code_model: false

JSON-FORMAT:
```json
{
    "intent": "kurze Beschreibung",
    "needs_memory": true/false,
    "memory_keys": ["key1", "key2"],
    "needs_chat_history": true/false,
    "is_fact_query": true/false,
    "is_new_fact": true/false,
    "new_fact_key": "key oder null",
    "new_fact_value": "value oder null",
    "hallucination_risk": "low/medium/high",
    "suggested_response_style": "kurz/ausführlich",
    "needs_container": true/false,
    "container_name": "code-sandbox/web-research/file-processor/null",
    "container_task": "execute/analyze/test/convert/null",
    "use_code_model": true/false,
    "code_language": "python/javascript/bash/null",
    "reasoning": "Begründung"
}
```

BEISPIELE:

"```python
print('hello')
```
Was gibt das aus?" 
→ {"intent":"Code-Output-Frage","needs_container":true,"container_name":"code-sandbox","container_task":"execute","use_code_model":true,"code_language":"python","reasoning":"User fragt nach Output - muss ausgeführt werden"}

"Hier mein Code:
```python
x = [1,2,3]
print(sum(x))
```"
→ {"intent":"Code-Präsentation","needs_container":true,"container_name":"code-sandbox","container_task":"execute","use_code_model":true,"code_language":"python","reasoning":"User zeigt Code ohne weitere Frage - will vermutlich Output sehen"}

"Funktioniert das?
```python
def fib(n): return n if n<2 else fib(n-1)+fib(n-2)
print(fib(10))
```"
→ {"intent":"Code-Validierung","needs_container":true,"container_name":"code-sandbox","container_task":"execute","use_code_model":true,"code_language":"python","reasoning":"User fragt ob es funktioniert - Ausführung zeigt es"}

"Erkläre mir diesen Code:
```python
lambda x: x*2
```"
→ {"intent":"Code-Erklärung","needs_container":false,"use_code_model":true,"code_language":"python","reasoning":"User will Erklärung, keine Ausführung"}

"Schreib mir eine Funktion die Primzahlen findet"
→ {"intent":"Code-Generierung","needs_container":false,"use_code_model":true,"reasoning":"Code schreiben - keine Ausführung nötig"}

"Was ist 2+2?"
→ {"intent":"Mathe","needs_container":false,"use_code_model":false,"reasoning":"Triviale Frage"}

"Hallo, wie geht's?"
→ {"intent":"Smalltalk","needs_container":false,"use_code_model":false,"reasoning":"Normales Gespräch"}
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
            
            log_info(f"[ThinkingLayer] Plan: intent={plan.get('intent')}, needs_memory={plan.get('needs_memory')}, needs_container={plan.get('needs_container')}, use_code_model={plan.get('use_code_model')}")
            
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
            # Stelle sicher dass neue Felder existieren
            plan.setdefault("needs_container", False)
            plan.setdefault("container_name", None)
            plan.setdefault("container_task", None)
            plan.setdefault("use_code_model", False)
            plan.setdefault("code_language", None)
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
            "reasoning": "Fallback - Analyse fehlgeschlagen",
            # Neue Felder
            "needs_container": False,
            "container_name": None,
            "container_task": None,
            "use_code_model": False,
            "code_language": None
        }
