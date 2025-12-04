# core/layers/output.py
"""
LAYER 3: OutputLayer (beliebiges Model)

Formuliert die finale Antwort basierend auf dem verifizierten Plan.
- Folgt den Anweisungen vom Control-Layer
- Nutzt Memory-Daten wenn vorhanden
- Nutzt Persona-Konfiguration für Persönlichkeit
- Generiert NUR die Antwort, denkt nicht selbst nach
- Unterstützt STREAMING für natürlichere UX
"""

import json
import httpx
from typing import Dict, Any, Optional, Generator, AsyncGenerator
from config import OLLAMA_BASE, OUTPUT_MODEL
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
    
    def _build_full_prompt(
        self,
        user_text: str,
        verified_plan: Dict[str, Any],
        memory_data: str = "",
        memory_required_but_missing: bool = False
    ) -> str:
        """Baut den vollständigen Prompt."""
        system_prompt = self._build_system_prompt(
            verified_plan, 
            memory_data,
            memory_required_but_missing
        )
        return f"{system_prompt}\n\n### USER:\n{user_text}\n\n### DEINE ANTWORT:"

    # ═══════════════════════════════════════════════════════════
    # ASYNC STREAMING GENERATOR
    # ═══════════════════════════════════════════════════════════
    async def generate_stream(
        self,
        user_text: str,
        verified_plan: Dict[str, Any],
        memory_data: str = "",
        model: str = None,
        memory_required_but_missing: bool = False
    ) -> AsyncGenerator[str, None]:
        """
        Generiert die Antwort als ASYNC STREAM (Token für Token).
        
        Nutzt httpx.AsyncClient für non-blocking streaming.
        
        Yields:
            Einzelne Text-Chunks wie sie vom Model kommen
        """
        model = model or OUTPUT_MODEL
        full_prompt = self._build_full_prompt(
            user_text, verified_plan, memory_data, memory_required_but_missing
        )
        
        payload = {
            "model": model,
            "prompt": full_prompt,
            "stream": True,  # STREAMING!
        }
        
        try:
            log_debug(f"[OutputLayer] Async streaming with {model}...")
            
            total_chars = 0
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    f"{self.ollama_base}/api/generate",
                    json=payload
                ) as response:
                    response.raise_for_status()
                    
                    async for line in response.aiter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                chunk = data.get("response", "")
                                if chunk:
                                    total_chars += len(chunk)
                                    yield chunk
                                
                                # Check if done
                                if data.get("done"):
                                    break
                            except json.JSONDecodeError:
                                continue
            
            log_info(f"[OutputLayer] Streamed {total_chars} chars")
                
        except httpx.TimeoutException:
            log_error(f"[OutputLayer] Stream Timeout nach 120s")
            yield "Entschuldigung, die Anfrage hat zu lange gedauert."
        except httpx.HTTPStatusError as e:
            log_error(f"[OutputLayer] Stream HTTP Error: {e.response.status_code}")
            yield f"Entschuldigung, Server-Fehler: {e.response.status_code}"
        except httpx.ConnectError as e:
            log_error(f"[OutputLayer] Stream Connection Error: {e}")
            yield "Entschuldigung, konnte keine Verbindung zum Model herstellen."
        except Exception as e:
            log_error(f"[OutputLayer] Stream Error: {type(e).__name__}: {e}")
            yield f"Entschuldigung, es gab einen Fehler: {str(e)}"

    # ═══════════════════════════════════════════════════════════
    # SYNC STREAMING (für SSE-Kompatibilität)
    # ═══════════════════════════════════════════════════════════
    def generate_stream_sync(
        self,
        user_text: str,
        verified_plan: Dict[str, Any],
        memory_data: str = "",
        model: str = None,
        memory_required_but_missing: bool = False
    ) -> Generator[str, None, None]:
        """
        Synchroner Stream Generator für SSE-Endpoints.
        
        HINWEIS: Blockiert den Event-Loop! Nur in ThreadPool verwenden
        oder wenn SSE sync Generator erwartet.
        """
        model = model or OUTPUT_MODEL
        full_prompt = self._build_full_prompt(
            user_text, verified_plan, memory_data, memory_required_but_missing
        )
        
        payload = {
            "model": model,
            "prompt": full_prompt,
            "stream": True,
        }
        
        try:
            log_debug(f"[OutputLayer] Sync streaming with {model}...")
            
            total_chars = 0
            with httpx.Client(timeout=120.0) as client:
                with client.stream(
                    "POST",
                    f"{self.ollama_base}/api/generate",
                    json=payload
                ) as response:
                    response.raise_for_status()
                    
                    for line in response.iter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                chunk = data.get("response", "")
                                if chunk:
                                    total_chars += len(chunk)
                                    yield chunk
                                
                                if data.get("done"):
                                    break
                            except json.JSONDecodeError:
                                continue
            
            log_info(f"[OutputLayer] Sync streamed {total_chars} chars")
                
        except httpx.TimeoutException:
            log_error(f"[OutputLayer] Sync Stream Timeout")
            yield "Entschuldigung, die Anfrage hat zu lange gedauert."
        except httpx.HTTPStatusError as e:
            log_error(f"[OutputLayer] Sync Stream HTTP Error: {e.response.status_code}")
            yield f"Entschuldigung, Server-Fehler: {e.response.status_code}"
        except Exception as e:
            log_error(f"[OutputLayer] Sync Stream Error: {type(e).__name__}: {e}")
            yield f"Entschuldigung, es gab einen Fehler: {str(e)}"

    # ═══════════════════════════════════════════════════════════
    # NON-STREAMING ASYNC
    # ═══════════════════════════════════════════════════════════
    async def generate(
        self,
        user_text: str,
        verified_plan: Dict[str, Any],
        memory_data: str = "",
        model: str = None,
        memory_required_but_missing: bool = False
    ) -> str:
        """
        Generiert die finale Antwort (NON-STREAMING, ASYNC).
        
        Nutzt httpx.AsyncClient für non-blocking HTTP.
        """
        model = model or OUTPUT_MODEL
        full_prompt = self._build_full_prompt(
            user_text, verified_plan, memory_data, memory_required_but_missing
        )
        
        payload = {
            "model": model,
            "prompt": full_prompt,
            "stream": False,
        }
        
        try:
            log_debug(f"[OutputLayer] Generating with {model}...")
            
            async with httpx.AsyncClient(timeout=120.0) as client:
                r = await client.post(
                    f"{self.ollama_base}/api/generate",
                    json=payload
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
            
        except httpx.TimeoutException:
            log_error(f"[OutputLayer] Timeout nach 120s")
            return "Entschuldigung, die Anfrage hat zu lange gedauert."
        except httpx.HTTPStatusError as e:
            log_error(f"[OutputLayer] HTTP Error: {e.response.status_code}")
            return f"Entschuldigung, Server-Fehler: {e.response.status_code}"
        except httpx.ConnectError as e:
            log_error(f"[OutputLayer] Connection Error: {e}")
            return "Entschuldigung, konnte keine Verbindung zum Model herstellen."
        except Exception as e:
            log_error(f"[OutputLayer] Error: {type(e).__name__}: {e}")
            return f"Entschuldigung, es gab einen Fehler: {str(e)}"
