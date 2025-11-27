# core/layers/output.py
"""
LAYER 3: OutputLayer (beliebiges Model)

Formuliert die finale Antwort basierend auf dem verifizierten Plan.
- Folgt den Anweisungen vom Control-Layer
- Nutzt Memory-Daten wenn vorhanden
- Generiert NUR die Antwort, denkt nicht selbst nach
"""

import json
import requests
from typing import Dict, Any, Optional
from config import OLLAMA_BASE
from utils.logger import log_info, log_error, log_debug

OUTPUT_SYSTEM_PROMPT = """Du bist ein freundlicher Assistent.
Du folgst den Anweisungen die dir gegeben werden.

WICHTIGE REGELN:
1. Wenn dir Memory-Daten gegeben werden, nutze sie!
2. Wenn du etwas nicht weißt und keine Memory-Daten hast, sag ehrlich "Das weiß ich nicht"
3. Erfinde KEINE persönlichen Fakten über den User
4. Sei freundlich und hilfreich
5. Antworte in der Sprache des Users
"""


class OutputLayer:
    def __init__(self):
        self.ollama_base = OLLAMA_BASE
    
    async def generate(
        self,
        user_text: str,
        verified_plan: Dict[str, Any],
        memory_data: str = "",
        model: str = "deepseek-r1:8b"
    ) -> str:
        """
        Generiert die finale Antwort basierend auf dem verifizierten Plan.
        """
        
        # Baue den Prompt basierend auf dem Plan
        instruction = verified_plan.get("_final_instruction", "Beantworte die Anfrage.")
        intent = verified_plan.get("intent", "")
        style = verified_plan.get("suggested_response_style", "freundlich")
        
        prompt_parts = [OUTPUT_SYSTEM_PROMPT]
        
        # Anweisung vom Control-Layer
        prompt_parts.append(f"\n### ANWEISUNG:\n{instruction}")
        
        # Memory-Daten wenn vorhanden
        if memory_data:
            prompt_parts.append(f"\n### FAKTEN AUS DEM GEDÄCHTNIS:\n{memory_data}")
            prompt_parts.append("\nNUTZE diese Fakten in deiner Antwort!")
        
        # Warnungen
        warnings = verified_plan.get("_warnings", [])
        if warnings:
            prompt_parts.append(f"\n### WARNUNGEN:\n" + "\n".join(f"- {w}" for w in warnings))
        
        # Style-Hinweis
        prompt_parts.append(f"\n### STIL:\nAntworte {style}.")
        
        # User-Anfrage
        prompt_parts.append(f"\n### USER-ANFRAGE:\n{user_text}")
        
        prompt_parts.append("\n### DEINE ANTWORT:")
        
        full_prompt = "\n".join(prompt_parts)
        
        payload = {
            "model": model,
            "prompt": full_prompt,
            "stream": False,
        }
        
        try:
            log_debug(f"[OutputLayer] Generating response with {model}...")
            
            r = requests.post(
                f"{self.ollama_base}/api/generate",
                json=payload,
                timeout=120
            )
            r.raise_for_status()
            
            data = r.json()
            response = data.get("response", "").strip()
            
            if not response:
                log_error("[OutputLayer] Leere Antwort")
                return "Entschuldigung, ich konnte keine Antwort generieren."
            
            log_info(f"[OutputLayer] Generated {len(response)} chars")
            return response
            
        except Exception as e:
            log_error(f"[OutputLayer] Error: {e}")
            return f"Entschuldigung, es gab einen Fehler: {str(e)}"
