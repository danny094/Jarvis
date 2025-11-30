# core/bridge.py
"""
Core-Bridge: Orchestriert die drei Layer.

Pipeline:
1. ThinkingLayer (DeepSeek) → Analysiert und plant
2. Memory Retrieval → Holt relevante Fakten
3. ControlLayer (Qwen) → Verifiziert den Plan
4. OutputLayer (beliebig) → Formuliert die Antwort
5. Memory Save → Speichert neue Fakten
"""

from typing import Optional, Dict, Any, Generator, Tuple, AsyncGenerator

from .models import CoreChatRequest, CoreChatResponse
from .layers import ThinkingLayer, ControlLayer, OutputLayer

from config import OLLAMA_BASE, ENABLE_CONTROL_LAYER, SKIP_CONTROL_ON_LOW_RISK
from utils.logger import log_debug, log_error, log_info, log_warn
from mcp.client import (
    autosave_assistant,
    get_fact_for_query,
    search_memory_fallback,
    semantic_search,
    graph_search,
    call_tool,
)


class CoreBridge:
    """
    Zentrale Bridge-Klasse mit 3-Layer-Architektur.
    """
    
    def __init__(self):
        self.thinking = ThinkingLayer()
        self.control = ControlLayer()
        self.output = OutputLayer()
        self.ollama_base = OLLAMA_BASE
    
    async def process(self, request: CoreChatRequest) -> CoreChatResponse:
        """
        Hauptmethode: Verarbeitet einen CoreChatRequest.
        
        Pipeline:
        1. ThinkingLayer → Plan erstellen
        2. Memory holen basierend auf Plan
        3. ControlLayer → Plan verifizieren
        4. OutputLayer → Antwort generieren
        5. Memory speichern wenn nötig
        """
        log_info(f"[CoreBridge] Processing from adapter={request.source_adapter}")
        
        user_text = request.get_last_user_message()
        conversation_id = request.conversation_id

        # ═══════════════════════════════════════════════════════════
        # LAYER 1: THINKING (DeepSeek)
        # ═══════════════════════════════════════════════════════════
        log_info("[CoreBridge] === LAYER 1: THINKING ===")
        
        thinking_plan = await self.thinking.analyze(user_text)
        
        log_info(f"[CoreBridge-Thinking] intent={thinking_plan.get('intent')}")
        log_info(f"[CoreBridge-Thinking] needs_memory={thinking_plan.get('needs_memory')}")
        log_info(f"[CoreBridge-Thinking] memory_keys={thinking_plan.get('memory_keys')}")
        log_info(f"[CoreBridge-Thinking] hallucination_risk={thinking_plan.get('hallucination_risk')}")
        
        # ═══════════════════════════════════════════════════════════
        # MEMORY RETRIEVAL basierend auf Plan
        # ═══════════════════════════════════════════════════════════
        retrieved_memory = ""
        memory_used = False
        
        if thinking_plan.get("needs_memory") or thinking_plan.get("is_fact_query"):
            memory_keys = thinking_plan.get("memory_keys", [])

            for key in memory_keys:
                log_info(f"[CoreBridge-Memory] Suche key='{key}'") 

                # 1. Erst in Facts suchen 
                fact_value = get_fact_for_query(conversation_id, key)
                if fact_value:
                    retrieved_memory += f"{key}: {fact_value}\n"
                    memory_used = True
                    log_info(f"[CoreBridge-Memory] Found fact: {key}={fact_value}")
                else:
                    # Graph search
                    log_info(f"[CoreBridge-Memory] Trying graph search for '{key}'")
                    graph_results = graph_search(conversation_id, key)

                    if graph_results:
                        for res in graph_results[:3]:
                            content = res.get("content", "")
                            log_info(f"[CoreBridge-Memory] Graph match: {content[:50]}")
                            retrieved_memory += f"{content}\n"
                        memory_used = True
                    else:
                        # 3. Sematic search Fallback
                        log_info(f"[CoreBridge-Memory] Trying semantic search for '{key}'")
                        semantic_results = semantic_search(conversation_id, key)

                        if semantic_results:
                            for res in semantic_results[:3]:
                                content = res.get("content", "")
                                sim = res.get("similarity", 0)
                                log_info(f"[CoreBridge-Memory] Semantic match (sim={sim}): {content[:50]}")
                                retrieved_memory += f"{content}\n"
                            memory_used = True
                        else:
                            # 4. Text-Fallback
                            fallback = search_memory_fallback(conversation_id, key)
                            if fallback:
                                retrieved_memory += f"{key}: {fallback}\n"
                                memory_used = True
                                log_info(f"[CoreBridge-Memory] Found in text: {key}")

                        



        # ═══════════════════════════════════════════════════════════
        # LAYER 2: CONTROL (Qwen) - Verifiziert BEVOR Output!
        # ═══════════════════════════════════════════════════════════
        
        # Skip ControlLayer wenn:
        # 1. Komplett deaktiviert ODER
        # 2. Skip bei low-risk aktiviert UND hallucination_risk == "low"
        skip_control = False
        hallucination_risk = thinking_plan.get("hallucination_risk", "medium")
        
        if not ENABLE_CONTROL_LAYER:
            skip_control = True
            log_info("[CoreBridge] === LAYER 2: CONTROL === DISABLED (config)")
        elif SKIP_CONTROL_ON_LOW_RISK and hallucination_risk == "low":
            skip_control = True
            log_info("[CoreBridge] === LAYER 2: CONTROL === SKIPPED (low-risk)")
        
        if skip_control:
            # Verwende ThinkingPlan direkt
            verified_plan = thinking_plan.copy()
            verified_plan["_verified"] = False
            verified_plan["_skipped"] = True
            verified_plan["_final_instruction"] = ""
            verified_plan["_warnings"] = []
            verification = {"approved": True, "corrections": {}}
        else:
            log_info("[CoreBridge] === LAYER 2: CONTROL ===")
            
            verification = await self.control.verify(
                user_text,
                thinking_plan,
                retrieved_memory
            )
            
            log_info(f"[CoreBridge-Control] approved={verification.get('approved')}")
            log_info(f"[CoreBridge-Control] warnings={verification.get('warnings', [])}")
            
            # Korrekturen anwenden
            verified_plan = self.control.apply_corrections(thinking_plan, verification)
        
        # Wenn nicht approved und keine Memory-Daten bei high risk
        if not verification.get("approved"):
            if thinking_plan.get("hallucination_risk") == "high" and not memory_used:
                log_warn("[CoreBridge-Control] BLOCKED - High hallucination risk ohne Memory")
                return CoreChatResponse(
                    model=request.model,
                    content="Das kann ich leider nicht beantworten, da ich diese Information nicht gespeichert habe.",
                    conversation_id=conversation_id,
                    done=True,
                    done_reason="blocked",
                    memory_used=False,
                )
        
        # Zusätzliche Memory-Suche wenn Control-Layer korrigiert hat
        if verification.get("corrections", {}).get("memory_keys"):
            extra_keys = verification["corrections"]["memory_keys"]
            for key in extra_keys:
                if key not in thinking_plan.get("memory_keys", []):
                    log_info(f"[CoreBridge-Control] Extra memory lookup: {key}")
                    fact_value = get_fact_for_query(conversation_id, key)
                    if fact_value:
                        retrieved_memory += f"{key}: {fact_value}\n"
                        memory_used = True

        # ═══════════════════════════════════════════════════════════
        # LAYER 3: OUTPUT (User's Model)
        # ═══════════════════════════════════════════════════════════
        log_info("[CoreBridge] === LAYER 3: OUTPUT ===")
        
        # Check: Memory war nötig aber wurde nicht gefunden?
        needs_memory = thinking_plan.get("needs_memory") or thinking_plan.get("is_fact_query")
        high_risk = thinking_plan.get("hallucination_risk") == "high"
        memory_required_but_missing = needs_memory and high_risk and not memory_used
        
        if memory_required_but_missing:
            log_info("[CoreBridge-Output] WARNUNG: Memory benötigt aber nicht gefunden!")
        
        answer = await self.output.generate(
            user_text=user_text,
            verified_plan=verified_plan,
            memory_data=retrieved_memory,
            model=request.model,
            memory_required_but_missing=memory_required_but_missing
        )
        
        log_info(f"[CoreBridge-Output] Generated {len(answer)} chars")
        
        # ═══════════════════════════════════════════════════════════
        # MEMORY SAVE wenn neuer Fakt
        # ═══════════════════════════════════════════════════════════
        if verified_plan.get("is_new_fact"):
            fact_key = verified_plan.get("new_fact_key")
            fact_value = verified_plan.get("new_fact_value")
            
            if fact_key and fact_value:
                log_info(f"[CoreBridge-Save] Saving fact: {fact_key}={fact_value}")
                
                try:
                    # Fakt speichern
                    fact_args = {
                        "conversation_id": conversation_id,
                        "subject": "Danny",
                        "key": fact_key,
                        "value": fact_value,
                        "layer": "ltm",
                    }
                    call_tool("memory_fact_save", fact_args)
                    
                except Exception as e:
                    log_error(f"[CoreBridge-Save] Error: {e}")
        
        # Antwort auch in Memory speichern
        try:
            autosave_assistant(
                conversation_id=conversation_id,
                content=answer,
                layer="stm",
            )
        except Exception as e:
            log_error(f"[CoreBridge-Autosave] Error: {e}")

        # ═══════════════════════════════════════════════════════════
        # RESPONSE
        # ═══════════════════════════════════════════════════════════
        return CoreChatResponse(
            model=request.model,
            content=answer,
            conversation_id=conversation_id,
            done=True,
            done_reason="stop",
            classifier_result=None,  # Nicht mehr verwendet
            memory_used=memory_used,
            validation_passed=True,  # Control-Layer hat approved
        )

    # ═══════════════════════════════════════════════════════════════
    # STREAMING VERSION
    # ═══════════════════════════════════════════════════════════════
    async def process_stream(self, request: CoreChatRequest) -> AsyncGenerator[Tuple[str, bool, Dict], None]:
        """
        Streaming-Version von process().
        
        Führt Layer 1+2 aus, dann streamt Layer 3.
        
        Yields:
            Tuple[str, bool, Dict]: (chunk, is_done, metadata)
            - chunk: Text-Chunk
            - is_done: True wenn fertig
            - metadata: Info über memory_used etc.
        """
        log_info(f"[CoreBridge] Processing STREAM from adapter={request.source_adapter}")
        
        user_text = request.get_last_user_message()
        conversation_id = request.conversation_id

        # ═══════════════════════════════════════════════════════════
        # LAYER 1: THINKING (DeepSeek) - Non-Streaming
        # ═══════════════════════════════════════════════════════════
        log_info("[CoreBridge] === LAYER 1: THINKING ===")
        
        thinking_plan = await self.thinking.analyze(user_text)
        
        log_info(f"[CoreBridge-Thinking] intent={thinking_plan.get('intent')}")
        log_info(f"[CoreBridge-Thinking] hallucination_risk={thinking_plan.get('hallucination_risk')}")
        
        # ═══════════════════════════════════════════════════════════
        # MEMORY RETRIEVAL - Non-Streaming
        # ═══════════════════════════════════════════════════════════
        retrieved_memory = ""
        memory_used = False
        
        if thinking_plan.get("needs_memory") or thinking_plan.get("is_fact_query"):
            memory_keys = thinking_plan.get("memory_keys", [])

            for key in memory_keys:
                log_info(f"[CoreBridge-Memory] Suche key='{key}'") 

                fact_value = get_fact_for_query(conversation_id, key)
                if fact_value:
                    retrieved_memory += f"{key}: {fact_value}\n"
                    memory_used = True
                    log_info(f"[CoreBridge-Memory] Found fact: {key}={fact_value}")
                else:
                    log_info(f"[CoreBridge-Memory] Trying graph search for '{key}'")
                    graph_results = graph_search(conversation_id, key)

                    if graph_results:
                        for res in graph_results[:3]:
                            content = res.get("content", "")
                            log_info(f"[CoreBridge-Memory] Graph match: {content[:50]}")
                            retrieved_memory += f"{content}\n"
                        memory_used = True
                    else:
                        log_info(f"[CoreBridge-Memory] Trying semantic search for '{key}'")
                        semantic_results = semantic_search(conversation_id, key)

                        if semantic_results:
                            for res in semantic_results[:3]:
                                content = res.get("content", "")
                                retrieved_memory += f"{content}\n"
                            memory_used = True
                        else:
                            fallback = search_memory_fallback(conversation_id, key)
                            if fallback:
                                retrieved_memory += f"{key}: {fallback}\n"
                                memory_used = True

        # ═══════════════════════════════════════════════════════════
        # LAYER 2: CONTROL - Non-Streaming (optional skip)
        # ═══════════════════════════════════════════════════════════
        skip_control = False
        hallucination_risk = thinking_plan.get("hallucination_risk", "medium")
        
        if not ENABLE_CONTROL_LAYER:
            skip_control = True
            log_info("[CoreBridge] === LAYER 2: CONTROL === DISABLED")
        elif SKIP_CONTROL_ON_LOW_RISK and hallucination_risk == "low":
            skip_control = True
            log_info("[CoreBridge] === LAYER 2: CONTROL === SKIPPED (low-risk)")
        
        if skip_control:
            verified_plan = thinking_plan.copy()
            verified_plan["_verified"] = False
            verified_plan["_skipped"] = True
            verified_plan["_final_instruction"] = ""
            verified_plan["_warnings"] = []
        else:
            log_info("[CoreBridge] === LAYER 2: CONTROL ===")
            
            verification = await self.control.verify(
                user_text,
                thinking_plan,
                retrieved_memory
            )
            
            log_info(f"[CoreBridge-Control] approved={verification.get('approved')}")
            verified_plan = self.control.apply_corrections(thinking_plan, verification)

        # ═══════════════════════════════════════════════════════════
        # LAYER 3: OUTPUT - STREAMING! 🚀
        # ═══════════════════════════════════════════════════════════
        log_info("[CoreBridge] === LAYER 3: OUTPUT (STREAMING) ===")
        
        needs_memory = thinking_plan.get("needs_memory") or thinking_plan.get("is_fact_query")
        high_risk = thinking_plan.get("hallucination_risk") == "high"
        memory_required_but_missing = needs_memory and high_risk and not memory_used
        
        # Sammle komplette Antwort für Memory-Save
        full_answer = ""
        
        # Streame die Antwort
        for chunk in self.output.generate_stream(
            user_text=user_text,
            verified_plan=verified_plan,
            memory_data=retrieved_memory,
            model=request.model,
            memory_required_but_missing=memory_required_but_missing
        ):
            full_answer += chunk
            yield (chunk, False, {"memory_used": memory_used})
        
        log_info(f"[CoreBridge-Output] Streamed {len(full_answer)} chars")
        
        # ═══════════════════════════════════════════════════════════
        # MEMORY SAVE (nach Stream)
        # ═══════════════════════════════════════════════════════════
        if verified_plan.get("is_new_fact"):
            fact_key = verified_plan.get("new_fact_key")
            fact_value = verified_plan.get("new_fact_value")
            
            if fact_key and fact_value:
                log_info(f"[CoreBridge-Save] Saving fact: {fact_key}={fact_value}")
                try:
                    fact_args = {
                        "conversation_id": conversation_id,
                        "subject": "Danny",
                        "key": fact_key,
                        "value": fact_value,
                        "layer": "ltm",
                    }
                    call_tool("memory_fact_save", fact_args)
                except Exception as e:
                    log_error(f"[CoreBridge-Save] Error: {e}")
        
        # Antwort in Memory speichern
        try:
            autosave_assistant(
                conversation_id=conversation_id,
                content=full_answer,
                layer="stm",
            )
        except Exception as e:
            log_error(f"[CoreBridge-Autosave] Error: {e}")
        
        # Final done signal
        yield ("", True, {"memory_used": memory_used, "done_reason": "stop"})


# Singleton-Instanz
_bridge_instance: Optional[CoreBridge] = None

def get_bridge() -> CoreBridge:
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = CoreBridge()
    return _bridge_instance
