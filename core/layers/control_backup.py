# core/layers/control.py
"""
LAYER 2: ControlLayer (Qwen)

Verifiziert den Plan vom ThinkingLayer BEVOR eine Antwort generiert wird:
- Ist der Plan logisch?
- Sind die Memory-Keys korrekt?
- Wurde das Halluzinations-Risiko richtig eingeschätzt?
- 🆕 Sequential Thinking Trigger
- Korrekturen wenn nötig
"""

import json
import httpx
from typing import Dict, Any, Optional
from config import OLLAMA_BASE, CONTROL_MODEL
from utils.logger import log_info, log_error, log_debug
from utils.json_parser import safe_parse_json
from core.safety import LightCIM
from core.sequential_registry import get_registry

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
        self.light_cim = LightCIM()  # Light CIM integration
        self.mcp_hub = None  # 🆕 Will be set by CoreBridge
        self.registry = get_registry()  # 🆕 Task Registry
    
    def set_mcp_hub(self, hub):
        """🆕 Inject MCP Hub for Sequential Thinking access"""
        self.mcp_hub = hub
        log_info("[ControlLayer] MCP Hub connected")
    
    async def verify(
        self, 
        user_text: str, 
        thinking_plan: Dict[str, Any],
        retrieved_memory: str = ""
    ) -> Dict[str, Any]:
        """
        Verifiziert den Plan vom ThinkingLayer.
        
        🆕 Checkt ob Sequential Thinking benötigt wird und triggert es.
        
        Nutzt httpx.AsyncClient für non-blocking HTTP.
        """
        # 🆕 SEQUENTIAL THINKING CHECK
        # Skip Sequential if already executed in CoreBridge
        sequential_result = thinking_plan.get("_sequential_result")
        if not sequential_result:
            # Only run if not already done
            sequential_result = await self._check_sequential_thinking(user_text, thinking_plan)
        if sequential_result:
            log_info(f"[ControlLayer] ✅ Sequential Thinking completed with {len(sequential_result.get('steps', []))} steps")
            # Add Sequential result to thinking_plan for later use
            thinking_plan["_sequential_result"] = sequential_result
        
        # NEW: Light CIM validation FIRST
        try:
            cim_result = self.light_cim.validate_basic(
                intent=thinking_plan.get("intent", ""),
                hallucination_risk=thinking_plan.get("hallucination_risk", "low"),
                user_text=user_text,
                thinking_plan=thinking_plan
            )
            
            log_info(f"[LightCIM] safe={cim_result['safe']}, confidence={cim_result['confidence']:.2f}, escalate={cim_result['should_escalate']}")
            
            # If unsafe, return early
            if not cim_result["safe"]:
                log_error(f"[LightCIM] Blocked: {cim_result['warnings']}")
                return {
                    "approved": False,
                    "corrections": {},
                    "warnings": cim_result["warnings"],
                    "final_instruction": "Request blocked by Light CIM safety checks",
                    "_light_cim": cim_result
                }
        except Exception as e:
            log_error(f"[LightCIM] Error: {e}")
            cim_result = {"safe": True, "confidence": 1.0, "warnings": [f"LightCIM error: {e}"], "should_escalate": False}
        
        # Continue with existing Qwen validation...
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
            
            # Async HTTP Request (non-blocking)
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    f"{self.ollama_base}/api/generate",
                    json=payload
                )
                r.raise_for_status()
            
            data = r.json()
            content = data.get("response", "").strip()
            
            # Qwen manchmal "thinking" statt "response"
            if not content and data.get("thinking"):
                content = data.get("thinking", "").strip()
            
            if not content:
                log_error(f"[ControlLayer] Leere Antwort")
                return self._default_verification(thinking_plan)
            
            # Robustes JSON-Parsing
            result = safe_parse_json(
                content,
                default=self._default_verification(thinking_plan),
                context="ControlLayer"
            )
            
            log_info(f"[ControlLayer] approved={result.get('approved')}, warnings={result.get('warnings', [])}")
            return result
                
        except httpx.TimeoutException:
            log_error(f"[ControlLayer] Timeout nach 30s")
            return self._default_verification(thinking_plan)
        except httpx.HTTPStatusError as e:
            log_error(f"[ControlLayer] HTTP Error: {e.response.status_code}")
            return self._default_verification(thinking_plan)
        except httpx.ConnectError as e:
            log_error(f"[ControlLayer] Connection Error: {e}")
            return self._default_verification(thinking_plan)
        except Exception as e:
            log_error(f"[ControlLayer] Unexpected Error: {type(e).__name__}: {e}")
            return self._default_verification(thinking_plan)
    
    async def _check_sequential_thinking(
        self, 
        user_text: str, 
        thinking_plan: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        🆕 CHECK: Brauchen wir Sequential Thinking?
        
        Returns:
            Sequential Thinking result wenn gebraucht, sonst None
        """
        needs_sequential = thinking_plan.get("needs_sequential_thinking", False)
        
        if not needs_sequential:
            log_debug("[ControlLayer] Sequential Thinking not needed")
            return None
        
        if not self.mcp_hub:
            log_error("[ControlLayer] ❌ MCP Hub not connected! Cannot use Sequential Thinking")
            return None
        
        # Extract parameters
        complexity = thinking_plan.get("sequential_complexity", 5)
        cim_modes = thinking_plan.get("suggested_cim_modes", [])
        reasoning_type = thinking_plan.get("reasoning_type", "direct")
        
        log_info(f"[ControlLayer] 🆕 Triggering Sequential Thinking (complexity={complexity}, modes={cim_modes})")
        
        try:
            # Call Sequential Thinking MCP
            result = self.mcp_hub.call_tool(
                "think",  # Tool name from Sequential Thinking MCP
                {
                    "message": user_text,
                    "steps": complexity
                }
            )
            
            # 🆕 Error-Check
            if isinstance(result, dict) and "error" in result:
                log_error(f"[ControlLayer] ❌ Sequential failed: {result['error']}")
                return None
            
            # 🆕 Empty result check
            if not result or (isinstance(result, dict) and not result.get("steps")):
                log_warning(f"[ControlLayer] ⚠️ No steps returned from Sequential Thinking")

            
            task_id = self.registry.create_task(user_text, complexity)
            self.registry.update_status(task_id, "running")
            self.registry.set_result(task_id, result)
            log_info(f"[ControlLayer] ✅ Task {task_id[:8]} completed")
            return result
            
        except Exception as e:
            log_error(f"[ControlLayer] ❌ Sequential Thinking failed: {e}")
            return None
    

    async def _check_sequential_thinking_stream(
        self, 
        user_text: str, 
        thinking_plan: Dict[str, Any]
    ):
        """
        🆕 Sequential Thinking mit Event-Streaming für Observability.
        
        Yields Events:
            - sequential_start
            - sequential_step (für jeden Step)
            - sequential_done
        """
        import uuid
        
        needs_sequential = thinking_plan.get("needs_sequential_thinking", False)
        
        if not needs_sequential:
            log_debug("[ControlLayer] Sequential Thinking not needed")
            return
        
        if not self.mcp_hub:
            log_error("[ControlLayer] ❌ MCP Hub not connected! Cannot use Sequential Thinking")
            return
        
        # Generate unique task ID
        task_id = f"seq-{str(uuid.uuid4())[:8]}"
        
        # Extract parameters
        complexity = thinking_plan.get("sequential_complexity", 5)
        cim_modes = thinking_plan.get("suggested_cim_modes", [])
        reasoning_type = thinking_plan.get("reasoning_type", "direct")
        
        log_info(f"[ControlLayer] 🆕 Sequential Thinking Stream (complexity={complexity}, id={task_id})")
        
        # Event: Start
        yield {
            "type": "sequential_start",
            "task_id": task_id,
            "complexity": complexity,
            "cim_modes": cim_modes,
            "reasoning_type": reasoning_type
        }
        
        try:
            # ECHTE ARBEIT: MCP Sequential Thinking aufrufen
            result = self.mcp_hub.call_tool(
                "think",
                {
                    "message": user_text,
                    "steps": complexity
                }
            )
            
            # Error-Check
            if isinstance(result, dict) and "error" in result:
                log_error(f"[ControlLayer] ❌ Sequential failed: {result['error']}")
                yield {
                    "type": "sequential_error",
                    "task_id": task_id,
                    "error": result["error"]
                }
                return
            
            # Empty result check
            if not result or (isinstance(result, dict) and not result.get("steps")):
                log_warning(f"[ControlLayer] ⚠️ No steps returned")
                yield {
                    "type": "sequential_done",
                    "task_id": task_id,
                    "steps": [],
                    "summary": "No steps generated"
                }
                return
            
            # Registry Update (State Management)
            registry_task_id = self.registry.create_task(user_text, complexity)
            self.registry.update_status(registry_task_id, "running")
            
            # Event: Steps (Observability)
            steps = result.get("steps", [])
            for i, step in enumerate(steps, 1):
                yield {
                    "type": "sequential_step",
                    "task_id": task_id,
                    "step_number": i,
                    "step": step.get("step", ""),
                    "thought": step.get("thought", ""),
                    "status": "complete"
                }
            
            # Registry Update
            self.registry.set_result(registry_task_id, result)
            log_info(f"[ControlLayer] ✅ Sequential {task_id} completed with {len(steps)} steps")
            
            # Event: Done
            yield {
                "type": "sequential_done",
                "task_id": task_id,
                "steps": steps,
                "summary": result.get("summary", f"{len(steps)} steps completed")
            }
            
            # Return final result for thinking_plan
            thinking_plan["_sequential_result"] = result
            
        except Exception as e:
            log_error(f"[ControlLayer] ❌ Sequential Thinking failed: {e}")
            yield {
                "type": "sequential_error",
                "task_id": task_id,
                "error": str(e)
            }

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
