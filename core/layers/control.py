# core/layers/control.py
"""
LAYER 2: ControlLayer (Qwen)

Verifiziert den Plan vom ThinkingLayer BEVOR eine Antwort generiert wird:
- Ist der Plan logisch?
- Sind die Memory-Keys korrekt?
- Wurde das Halluzinations-Risiko richtig eingeschätzt?
- Korrekturen wenn nötig
"""

import json
import requests
from typing import Dict, Any
from config import OLLAMA_BASE
from utils.logger import log_info, log_error, log_debug

CONTROL_MODEL = "qwen3:4b"

CONTROL_PROMPT = """Du bist der CONTROL-Layer eines AI-Systems.
Deine Aufgabe: Überprüfe den Plan vom Thinking-Layer BEVOR eine Antwort generiert wird.

Du antwortest NUR mit validem JSON, nichts anderes.

Prüfe:
1. Ist der Intent korrekt erkannt?
2. Sind die Memory-Keys sinnvoll?
3. Ist das Halluzinations-Risiko richtig eingeschätzt?
4. Gibt es Korrekturen?

JSON-Format:
{
    "approved": true/false,
    "corrections": {
        "needs_memory": null oder true/false,
        "memory_keys": null oder ["korrigierte", "keys"],
        "hallucination_risk": null oder "low/medium/high",
        "new_fact_key": null oder "korrigierter_key",
        "new_fact_value": null oder "korrigierter_value"
    },
    "warnings": ["Liste von Warnungen falls vorhanden"],
    "final_instruction": "Klare Anweisung für den Output-Layer"
}

REGELN:
- Wenn der Plan okay ist: approved=true, corrections alle null
- Wenn Korrekturen nötig: approved=true aber corrections ausfüllen
- Wenn der Plan gefährlich ist (hohe Halluzination ohne Memory): approved=false
- final_instruction sollte dem Output-Layer sagen was er tun soll

BEISPIEL - Plan ist okay:
{
    "approved": true,
    "corrections": {
        "needs_memory": null,
        "memory_keys": null,
        "hallucination_risk": null,
        "new_fact_key": null,
        "new_fact_value": null
    },
    "warnings": [],
    "final_instruction": "Beantworte die Frage zum Alter des Users basierend auf dem Memory-Fakt."
}

BEISPIEL - Plan braucht Korrektur:
{
    "approved": true,
    "corrections": {
        "needs_memory": true,
        "memory_keys": ["age"],
        "hallucination_risk": "high",
        "new_fact_key": null,
        "new_fact_value": null
    },
    "warnings": ["Thinking-Layer hat Memory-Bedarf nicht erkannt"],
    "final_instruction": "MUSS das Alter aus Memory holen, NICHT raten!"
}

WICHTIG:
- NUR JSON ausgeben
- KEIN Text vor oder nach dem JSON
"""


class ControlLayer:
    def __init__(self, model: str = CONTROL_MODEL):
        self.model = model
        self.ollama_base = OLLAMA_BASE
    
    async def verify(
        self, 
        user_text: str, 
        thinking_plan: Dict[str, Any],
        retrieved_memory: str = ""
    ) -> Dict[str, Any]:
        """
        Verifiziert den Plan vom ThinkingLayer.
        """
        prompt = f"""{CONTROL_PROMPT}

USER-ANFRAGE:
{user_text}

PLAN VOM THINKING-LAYER:
{json.dumps(thinking_plan, indent=2, ensure_ascii=False)}

GEFUNDENE MEMORY-DATEN:
{retrieved_memory if retrieved_memory else "(keine)"}

Deine Bewertung (nur JSON):"""

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }
        
        try:
            log_debug(f"[ControlLayer] Verifying plan...")
            
            r = requests.post(
                f"{self.ollama_base}/api/generate",
                json=payload,
                timeout=30
            )
            r.raise_for_status()
            
            data = r.json()
            content = data.get("response", "").strip()
            
            if not content and data.get("thinking"):
                content = data.get("thinking", "").strip()
            
            if not content:
                log_error(f"[ControlLayer] Leere Antwort")
                return self._default_verification(thinking_plan)
            
            try:
                if "{" in content:
                    start = content.index("{")
                    end = content.rindex("}") + 1
                    content = content[start:end]
                
                result = json.loads(content)
                log_info(f"[ControlLayer] approved={result.get('approved')}, warnings={result.get('warnings', [])}")
                return result
                
            except json.JSONDecodeError as e:
                log_error(f"[ControlLayer] JSON Parse Error: {e}")
                return self._default_verification(thinking_plan)
                
        except Exception as e:
            log_error(f"[ControlLayer] Error: {e}")
            return self._default_verification(thinking_plan)
    
    def _default_verification(self, thinking_plan: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback - Plan durchwinken mit Warnung."""
        return {
            "approved": True,
            "corrections": {
                "needs_memory": None,
                "memory_keys": None,
                "hallucination_risk": None,
                "new_fact_key": None,
                "new_fact_value": None
            },
            "warnings": ["Control-Layer Fallback - konnte Plan nicht verifizieren"],
            "final_instruction": "Beantworte die Anfrage vorsichtig."
        }
    
    def apply_corrections(
        self, 
        thinking_plan: Dict[str, Any], 
        verification: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Wendet Korrekturen auf den Plan an.
        """
        corrected_plan = thinking_plan.copy()
        corrections = verification.get("corrections", {})
        
        for key, value in corrections.items():
            if value is not None:
                corrected_plan[key] = value
                log_info(f"[ControlLayer] Korrektur: {key} = {value}")
        
        corrected_plan["_verified"] = True
        corrected_plan["_final_instruction"] = verification.get("final_instruction", "")
        corrected_plan["_warnings"] = verification.get("warnings", [])
        
        return corrected_plan
