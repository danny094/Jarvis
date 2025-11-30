# core/layers/output.py
"""
LAYER 3: OutputLayer (beliebiges Model)

Formuliert die finale Antwort basierend auf dem verifizierten Plan.
- Folgt den Anweisungen vom Control-Layer
- Nutzt Memory-Daten wenn vorhanden
- Nutzt Persona-Konfiguration für Persönlichkeit
- Generiert NUR die Antwort, denkt nicht selbst nach
"""

import json
import requests
from typing import Dict, Any, Optional
from config import OLLAMA_BASE
from utils.logger import log_info, log_error, log_debug
from core.persona import get_persona


class OutputLayer:
    def __init__(self):
        self.ollama_base = OLLAMA_BASE
    
    def _build_system_prompt(
        self, 
        verified_plan: Dict[str, Any], 
        memory_data: str,
        memory_required_but_missing: bool = False
    ) -> str:
        """Baut den System-Prompt mit Persona und Kontext."""
        
        # Persona laden
        persona = get_persona()
        
        prompt_parts = []
        
        # Persona-Basis
        prompt_parts.append(persona.build_system_prompt())
        
        # KRITISCH: Anti-Halluzination wenn Memory fehlt
        if memory_required_but_missing:
            prompt_parts.append("\n### WICHTIG - ANTI-HALLUZINATION:")
            prompt_parts.append("Der User fragt nach persönlichen Informationen.")
            prompt_parts.append("Diese Information ist NICHT in deinem Gedächtnis gespeichert.")
            prompt_parts.append("Du MUSST ehrlich sagen, dass du diese Information nicht hast.")
            prompt_parts.append("ERFINDE NIEMALS persönliche Daten wie Geburtstage, Alter, Namen, etc.")
            prompt_parts.append("Antworte stattdessen: 'Das habe ich leider nicht gespeichert.' oder ähnlich.")
        
        # Anweisung vom Control-Layer
        instruction = verified_plan.get("_final_instruction", "")
        if instruction:
            prompt_parts.append(f"\n### AKTUELLE ANWEISUNG:\n{instruction}")
        
        # Memory-Daten
        if memory_data:
            prompt_parts.append(f"\n### FAKTEN AUS DEM GEDÄCHTNIS:\n{memory_data}")
            prompt_parts.append("NUTZE diese Fakten in deiner Antwort!")
        
        # Warnungen
        warnings = verified_plan.get("_warnings", [])
        if warnings:
            prompt_parts.append(f"\n### WARNUNGEN:")
            for w in warnings:
                prompt_parts.append(f"- {w}")
        
        # Style-Hinweis
        style = verified_plan.get("suggested_response_style", "")
        if style:
            prompt_parts.append(f"\n### STIL: Antworte {style}.")
        
        return "\n".join(prompt_parts)
    
    async def generate(
        self,
        user_text: str,
        verified_plan: Dict[str, Any],
        memory_data: str = "",
        model: str = "deepseek-r1:8b",
        memory_required_but_missing: bool = False
    ) -> str:
        """
        Generiert die finale Antwort basierend auf dem verifizierten Plan.
        
        Args:
            memory_required_but_missing: True wenn Memory gebraucht wurde aber nichts gefunden
        """
        
        system_prompt = self._build_system_prompt(
            verified_plan, 
            memory_data,
            memory_required_but_missing
        )
        
        # Vollständiger Prompt
        full_prompt = f"{system_prompt}\n\n### USER:\n{user_text}\n\n### DEINE ANTWORT:"
        
        payload = {
            "model": model,
            "prompt": full_prompt,
            "stream": False,
        }
        
        try:
            log_debug(f"[OutputLayer] Generating with {model}...")
            
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
                persona = get_persona()
                return f"Entschuldigung, ich konnte keine Antwort generieren. - {persona.name}"
            
            log_info(f"[OutputLayer] Generated {len(response)} chars")
            return response
            
        except Exception as e:
            log_error(f"[OutputLayer] Error: {e}")
            return f"Entschuldigung, es gab einen Fehler: {str(e)}"
