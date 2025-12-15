# core/bridge.py
"""
Core-Bridge: Orchestriert die drei Layer.

Pipeline:
1. ThinkingLayer (Mistral) → Analysiert und plant
2. Memory Retrieval → Holt relevante Fakten PARALLEL (inkl. System-Wissen!)
3. Container Execution → Führt Code in Sandbox aus (wenn nötig)
4. ControlLayer (Qwen) → Verifiziert den Plan (optional skip bei low-risk)
5. OutputLayer (beliebig) → Formuliert die Antwort (nutzt CODE_MODEL wenn Code)
6. Memory Save → Speichert neue Fakten (async, blockiert nicht)
"""

import asyncio
import httpx
import re
from typing import Optional, Dict, Any, Generator, Tuple, AsyncGenerator, List
from concurrent.futures import ThreadPoolExecutor

from .models import CoreChatRequest, CoreChatResponse
from .layers import ThinkingLayer, ControlLayer, OutputLayer

from config import (
    OLLAMA_BASE, 
    ENABLE_CONTROL_LAYER, 
    SKIP_CONTROL_ON_LOW_RISK,
    CONTAINER_MANAGER_URL,
    ENABLE_CONTAINER_MANAGER,
    CODE_MODEL,
)
from utils.logger import log_debug, log_error, log_info, log_warn, log_warning
from mcp.client import (
    autosave_assistant,
    get_fact_for_query,
    search_memory_fallback,
    semantic_search,
    graph_search,
    call_tool,
)

# System conversation_id für Tool-Wissen
SYSTEM_CONV_ID = "system"


class CoreBridge:
    """
    Zentrale Bridge-Klasse mit 3-Layer-Architektur.
    """
    
    def __init__(self):
        self.thinking = ThinkingLayer()
        self.control = ControlLayer()
        self.output = OutputLayer()
        self.ollama_base = OLLAMA_BASE
        self.container_manager_url = CONTAINER_MANAGER_URL
    
    # ═══════════════════════════════════════════════════════════════
    # CONTAINER HELPERS: Sandbox Container Management
    # ═══════════════════════════════════════════════════════════════
    
    async def _execute_in_container(
        self,
        container_name: str,
        code: str,
        task: str = "execute",
        keep_alive: bool = False,
        enable_ttyd: bool = False
    ) -> Dict[str, Any]:
        """
        Führt Code in einem Sandbox-Container aus.
        
        Args:
            container_name: Name des Containers (z.B. "code-sandbox")
            code: Der auszuführende Code
            task: "execute", "analyze", "test"
            keep_alive: Container nach Ausführung behalten (für Sessions)
            enable_ttyd: Live Terminal aktivieren
            
        Returns:
            Dict mit stdout, stderr, exit_code, session (wenn keep_alive)
        """
        if not ENABLE_CONTAINER_MANAGER:
            log_warning("[CoreBridge-Container] Container-Manager disabled")
            return {"error": "Container-Manager ist deaktiviert"}
        
        try:
            log_info(f"[CoreBridge-Container] Starting {container_name} for task={task} (keep_alive={keep_alive}, ttyd={enable_ttyd})")
            
            async with httpx.AsyncClient(timeout=120.0) as client:
                # Container starten und Code ausführen
                response = await client.post(
                    f"{self.container_manager_url}/containers/start",
                    json={
                        "container_name": container_name,
                        "code": code,
                        "timeout": 60,
                        "keep_alive": keep_alive,
                        "enable_ttyd": enable_ttyd,
                        "ttl_seconds": 300  # 5 Minuten default
                    }
                )
                
                if response.status_code == 403:
                    error_data = response.json()
                    log_error(f"[CoreBridge-Container] Not allowed: {error_data}")
                    return {"error": f"Container '{container_name}' nicht erlaubt"}
                
                response.raise_for_status()
                result = response.json()
                
                # Container-Manager handhabt jetzt Cleanup selbst (wenn keep_alive=false)
                # Nur Session-Info extrahieren wenn vorhanden
                session_info = result.get("session")
                container_id = result.get("container_id")
                
                if keep_alive and session_info:
                    log_info(f"[CoreBridge-Container] Session created: {session_info.get('session_id', 'unknown')[:8]}")
                
                execution_result = result.get("execution_result") or {}
                log_info(f"[CoreBridge-Container] Exit code: {execution_result.get('exit_code')}")
                
                # Session-Info zum Result hinzufügen
                if session_info:
                    execution_result["session"] = session_info
                
                # Falls kein Result, leeres Dict mit Hinweis
                if not execution_result:
                    execution_result = {"error": "Keine Ausführung durchgeführt (kein Code?)"}
                
                return execution_result
                
        except httpx.TimeoutException:
            log_error("[CoreBridge-Container] Timeout nach 120s")
            return {"error": "Container-Ausführung Timeout (120s)"}
        except httpx.HTTPStatusError as e:
            log_error(f"[CoreBridge-Container] HTTP Error: {e.response.status_code}")
            return {"error": f"Container-Manager Fehler: {e.response.status_code}"}
        except Exception as e:
            log_error(f"[CoreBridge-Container] Error: {e}")
            return {"error": str(e)}
    
    def _extract_code_from_message(self, text: str) -> Optional[str]:
        """
        Extrahiert Code aus einer User-Nachricht.
        Sucht nach Code-Blöcken (```...```) oder inline Code.
        """
        log_info(f"[CoreBridge-Container] Extracting code from: {text[:100]}...")
        
        # Code-Block mit Sprache (mit oder ohne Newline nach Sprache)
        match = re.search(r'```(\w+)[\s\n](.*?)```', text, re.DOTALL)
        if match:
            code = match.group(2).strip()
            log_info(f"[CoreBridge-Container] Found code block with language '{match.group(1)}': {len(code)} chars")
            return code
        
        # Code-Block ohne Sprache
        match = re.search(r'```\n?(.*?)```', text, re.DOTALL)
        if match:
            code = match.group(1).strip()
            log_info(f"[CoreBridge-Container] Found code block without language: {len(code)} chars")
            return code
        
        # Inline Code (nur wenn es wie Code aussieht)
        if '`' in text:
            match = re.search(r'`([^`]+)`', text)
            if match and len(match.group(1)) > 10:
                code = match.group(1).strip()
                log_info(f"[CoreBridge-Container] Found inline code: {len(code)} chars")
                return code
        
        log_warning(f"[CoreBridge-Container] No code found in message")
        return None
    
    def _should_auto_execute_code(self, text: str, thinking_plan: Dict[str, Any]) -> bool:
        """
        Heuristik: Soll Code automatisch ausgeführt werden?
        
        Wird als FALLBACK verwendet, wenn ThinkingLayer needs_container=false sagt,
        aber der Kontext eine Ausführung nahelegt.
        
        Returns:
            True wenn Code ausgeführt werden sollte
        """
        # Wenn ThinkingLayer schon ja gesagt hat, nicht überschreiben
        if thinking_plan.get("needs_container"):
            return True
        
        # Prüfen ob überhaupt Code vorhanden ist
        has_code_block = '```' in text
        if not has_code_block:
            return False
        
        text_lower = text.lower()
        
        # POSITIVE Trigger: Diese Phrasen deuten auf Ausführungswunsch hin
        execute_triggers = [
            # Explizit
            "teste", "test", "ausführen", "führe aus", "run", "execute",
            "probier", "starte", "laufen lassen",
            # Implizit - Output-Fragen
            "was gibt", "was kommt", "was ist das ergebnis", "was passiert",
            "output", "ausgabe", "ergebnis",
            # Implizit - Validierung
            "funktioniert", "läuft", "geht das", "klappt",
            "korrekt", "richtig", "stimmt",
            # Implizit - Check
            "check", "prüf", "validier",
            # Kurze Präsentation (Code mit wenig Text drumrum)
            "hier", "schau", "guck",
        ]
        
        # NEGATIVE Trigger: Diese Phrasen deuten auf KEINE Ausführung hin
        no_execute_triggers = [
            "erklär", "erkläre", "explain", "was macht", "wie funktioniert",
            "warum", "wieso", "weshalb",
            "verbessere", "optimiere", "refactor", "improve",
            "schreib mir", "erstelle", "generiere", "create", "write",
            "was ist falsch", "fehler finden", "debug",  # Erst analysieren
            "verstehe nicht", "versteh nicht",
        ]
        
        # Erst negative Trigger prüfen (haben Vorrang)
        for trigger in no_execute_triggers:
            if trigger in text_lower:
                log_info(f"[CoreBridge-AutoExec] NO - found negative trigger: '{trigger}'")
                return False
        
        # Dann positive Trigger prüfen
        for trigger in execute_triggers:
            if trigger in text_lower:
                log_info(f"[CoreBridge-AutoExec] YES - found positive trigger: '{trigger}'")
                return True
        
        # Sonderfall: Nur Code-Block mit sehr wenig Text (< 50 Zeichen außerhalb)
        # User will vermutlich Output sehen
        text_without_code = re.sub(r'```[\s\S]*?```', '', text).strip()
        if len(text_without_code) < 50 and has_code_block:
            log_info(f"[CoreBridge-AutoExec] YES - minimal text with code block ({len(text_without_code)} chars)")
            return True
        
        log_info(f"[CoreBridge-AutoExec] NO - no triggers matched")
        return False
    
    # ═══════════════════════════════════════════════════════════════
    # MEMORY HELPERS: Sucht in User UND System Kontext
    # ═══════════════════════════════════════════════════════════════
    
    def _search_memory_multi_context(
        self, 
        key: str, 
        conversation_id: str,
        include_system: bool = True
    ) -> Tuple[str, bool]:
        """
        Sucht Memory in mehreren Kontexten:
        1. User's conversation_id
        2. System-Wissen (Tool-Infos, Anleitungen)
        
        Returns:
            Tuple[str, bool]: (gefundener Content, wurde etwas gefunden)
        """
        found_content = ""
        found = False
        
        # Kontexte die durchsucht werden
        contexts = [conversation_id]
        if include_system and conversation_id != SYSTEM_CONV_ID:
            contexts.append(SYSTEM_CONV_ID)
        
        for ctx in contexts:
            ctx_label = "system" if ctx == SYSTEM_CONV_ID else "user"
            
            # 1. Facts suchen
            fact_value = get_fact_for_query(ctx, key)
            if fact_value:
                found_content += f"{key}: {fact_value}\n"
                found = True
                log_info(f"[CoreBridge-Memory] Found fact ({ctx_label}): {key}={fact_value[:50]}...")
                continue  # Nächster Kontext
            
            # 2. Graph search
            graph_results = graph_search(ctx, key)
            if graph_results:
                for res in graph_results[:3]:
                    content = res.get("content", "")
                    log_info(f"[CoreBridge-Memory] Graph match ({ctx_label}): {content[:50]}")
                    found_content += f"{content}\n"
                found = True
                continue
            
            # 3. Semantic search (nur für User-Kontext, System ist meist Fakten)
            if ctx != SYSTEM_CONV_ID:
                semantic_results = semantic_search(ctx, key)
                if semantic_results:
                    for res in semantic_results[:3]:
                        content = res.get("content", "")
                        found_content += f"{content}\n"
                    found = True
                    continue
            
            # 4. Text-Fallback (nur User)
            if ctx != SYSTEM_CONV_ID:
                fallback = search_memory_fallback(ctx, key)
                if fallback:
                    found_content += f"{key}: {fallback}\n"
                    found = True
        
        return found_content, found
    
    async def _search_memory_parallel(
        self,
        memory_keys: List[str],
        conversation_id: str,
        include_system: bool = True
    ) -> Tuple[str, bool]:
        """
        Sucht ALLE Memory-Keys PARALLEL statt sequentiell.
        
        Performance: 4 Keys × 0.5s = 2s sequentiell → 0.5s parallel!
        """
        if not memory_keys:
            return "", False
        
        log_info(f"[CoreBridge-Memory] Parallel search for {len(memory_keys)} keys: {memory_keys}")
        
        # Führe alle Suchen parallel aus
        loop = asyncio.get_event_loop()
        
        async def search_single_key(key: str) -> Tuple[str, bool, str]:
            """Wrapper für einzelne Key-Suche."""
            # _search_memory_multi_context ist sync, also in ThreadPool
            content, found = await loop.run_in_executor(
                None,  # Default ThreadPoolExecutor
                lambda: self._search_memory_multi_context(key, conversation_id, include_system)
            )
            return content, found, key
        
        # Alle Suchen gleichzeitig starten
        tasks = [search_single_key(key) for key in memory_keys]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Ergebnisse sammeln
        all_content = ""
        any_found = False
        
        for result in results:
            if isinstance(result, Exception):
                log_error(f"[CoreBridge-Memory] Parallel search error: {result}")
                continue
            
            content, found, key = result
            if found:
                all_content += content
                any_found = True
                log_info(f"[CoreBridge-Memory] Found key '{key}'")
        
        return all_content, any_found
    
    def _search_system_tools(self, query: str) -> str:
        """
        Sucht speziell nach Tool-Wissen im System-Kontext.
        
        Nur bei EXPLIZITEN Tool-Fragen, nicht bei allgemeinen Begriffen.
        """
        query_lower = query.lower()
        
        # PRÄZISE Patterns - nur explizite Tool-Fragen
        explicit_tool_patterns = [
            "welche tools",
            "welche mcp",
            "liste tools",
            "list tools", 
            "available tools",
            "verfügbare tools",
            "was für tools",
            "auf welche tools",
            "mcp tools",
            "zeig mir die tools",
            "tool übersicht",
            "was kannst du alles",  # Nur als volle Phrase
            "was sind deine fähigkeiten",
        ]
        
        # Nur triggern wenn explizites Pattern matcht
        is_tool_query = any(pattern in query_lower for pattern in explicit_tool_patterns)
        
        if not is_tool_query:
            return ""
        
        log_info(f"[CoreBridge-Memory] Explicit tool query detected: {query}")
        
        # Lade Tool-Übersicht (mit Limit)
        tools_info = get_fact_for_query(SYSTEM_CONV_ID, "available_mcp_tools")
        if tools_info:
            # Truncate auf max 1500 chars
            if len(tools_info) > 1500:
                tools_info = tools_info[:1500] + "..."
            return f"Verfügbare Tools: {tools_info}\n"
        
        return ""
    
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
        # MEMORY RETRIEVAL basierend auf Plan (PARALLEL!)
        # ═══════════════════════════════════════════════════════════
        retrieved_memory = ""
        memory_used = False
        
        # Erst: System-Tools checken wenn relevant
        system_tools = self._search_system_tools(user_text)
        if system_tools:
            retrieved_memory += system_tools
            memory_used = True
            log_info(f"[CoreBridge-Memory] Found system tool info")
        
        if thinking_plan.get("needs_memory") or thinking_plan.get("is_fact_query"):
            memory_keys = thinking_plan.get("memory_keys", [])
            
            if memory_keys:
                # PARALLEL Memory-Suche für alle Keys gleichzeitig! ⚡
                parallel_content, parallel_found = await self._search_memory_parallel(
                    memory_keys,
                    conversation_id,
                    include_system=True
                )
                
                if parallel_found:
                    retrieved_memory += parallel_content
                    memory_used = True

        # ═══════════════════════════════════════════════════════════
        # MEMORY SIZE LIMIT - Verhindert Prompt-Überflutung
        # ═══════════════════════════════════════════════════════════
        MAX_MEMORY_CHARS = 2500
        if len(retrieved_memory) > MAX_MEMORY_CHARS:
            log_warning(f"[CoreBridge-Memory] Truncating memory: {len(retrieved_memory)} → {MAX_MEMORY_CHARS} chars")
            retrieved_memory = retrieved_memory[:MAX_MEMORY_CHARS] + "\n[... weitere Einträge gekürzt]"
        
        if retrieved_memory:
            log_info(f"[CoreBridge-Memory] Total retrieved: {len(retrieved_memory)} chars")
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
            memory_required_but_missing=memory_required_but_missing,
            chat_history=request.messages  # ← NEU: History für Kontext!
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
    # STREAMING VERSION MIT LIVE THINKING
    # ═══════════════════════════════════════════════════════════════
    async def process_stream(self, request: CoreChatRequest) -> AsyncGenerator[Tuple[str, bool, Dict], None]:
        """
        Streaming-Version von process() MIT LIVE THINKING.
        
        Zeigt das "Nachdenken" live an, wie bei Claude Extended Thinking.
        
        Yields:
            Tuple[str, bool, Dict]: (chunk, is_done, metadata)
            - chunk: Text-Chunk
            - is_done: True wenn fertig
            - metadata: Info über type, thinking, memory_used etc.
        """
        log_info(f"[CoreBridge] Processing STREAM from adapter={request.source_adapter}")
        
        user_text = request.get_last_user_message()
        conversation_id = request.conversation_id

        # ═══════════════════════════════════════════════════════════
        # LAYER 1: THINKING (DeepSeek) - LIVE STREAMING! 🧠
        # ═══════════════════════════════════════════════════════════
        log_info("[CoreBridge] === LAYER 1: THINKING (STREAMING) ===")
        
        thinking_plan = {}
        thinking_text = ""
        
        async for chunk, is_done, plan in self.thinking.analyze_stream(user_text):
            if not is_done:
                # Live thinking chunk
                thinking_text += chunk
                yield ("", False, {
                    "type": "thinking_stream",
                    "thinking_chunk": chunk
                })
            else:
                # Thinking fertig - Plan erhalten
                thinking_plan = plan
                
                # Sende "Thinking Done" Signal
                yield ("", False, {
                    "type": "thinking_done",
                    "thinking": {
                        "intent": thinking_plan.get("intent", ""),
                        "needs_memory": thinking_plan.get("needs_memory", False),
                        "memory_keys": thinking_plan.get("memory_keys", []),
                        "needs_chat_history": thinking_plan.get("needs_chat_history", False),
                        "hallucination_risk": thinking_plan.get("hallucination_risk", "medium"),
                        "reasoning": thinking_plan.get("reasoning", ""),
                        "is_fact_query": thinking_plan.get("is_fact_query", False),
                        "is_new_fact": thinking_plan.get("is_new_fact", False),
                        # Container & Code Model Felder
                        "needs_container": thinking_plan.get("needs_container", False),
                        "container_name": thinking_plan.get("container_name"),
                        "container_task": thinking_plan.get("container_task"),
                        "use_code_model": thinking_plan.get("use_code_model", False),
                        "code_language": thinking_plan.get("code_language"),
                    }
                })
        
        log_info(f"[CoreBridge-Thinking] intent={thinking_plan.get('intent')}")
        log_info(f"[CoreBridge-Thinking] hallucination_risk={thinking_plan.get('hallucination_risk')}")
        
        # ═══════════════════════════════════════════════════════════
        # AUTO-EXECUTE HEURISTIK: Fallback wenn ThinkingLayer unsicher
        # ═══════════════════════════════════════════════════════════
        if self._should_auto_execute_code(user_text, thinking_plan):
            if not thinking_plan.get("needs_container"):
                log_info(f"[CoreBridge-AutoExec] Overriding: needs_container = True (heuristic)")
                thinking_plan["needs_container"] = True
                thinking_plan["container_name"] = thinking_plan.get("container_name") or "code-sandbox"
                thinking_plan["container_task"] = thinking_plan.get("container_task") or "execute"
        
        # ═══════════════════════════════════════════════════════════
        # MEMORY RETRIEVAL - PARALLEL! ⚡
        # ═══════════════════════════════════════════════════════════
        retrieved_memory = ""
        memory_used = False
        
        # Erst: System-Tools checken wenn relevant
        system_tools = self._search_system_tools(user_text)
        if system_tools:
            retrieved_memory += system_tools
            memory_used = True
            log_info(f"[CoreBridge-Memory] Found system tool info")
        
        if thinking_plan.get("needs_memory") or thinking_plan.get("is_fact_query"):
            memory_keys = thinking_plan.get("memory_keys", [])
            
            if memory_keys:
                # PARALLEL Memory-Suche für alle Keys gleichzeitig! ⚡
                parallel_content, parallel_found = await self._search_memory_parallel(
                    memory_keys,
                    conversation_id,
                    include_system=True
                )
                
                if parallel_found:
                    retrieved_memory += parallel_content
                    memory_used = True

        # ═══════════════════════════════════════════════════════════
        # MEMORY SIZE LIMIT - Verhindert Prompt-Überflutung
        # ═══════════════════════════════════════════════════════════
        MAX_MEMORY_CHARS = 2500
        if len(retrieved_memory) > MAX_MEMORY_CHARS:
            log_warning(f"[CoreBridge-Memory] Truncating memory: {len(retrieved_memory)} → {MAX_MEMORY_CHARS} chars")
            retrieved_memory = retrieved_memory[:MAX_MEMORY_CHARS] + "\n[... weitere Einträge gekürzt]"
        
        if retrieved_memory:
            log_info(f"[CoreBridge-Memory] Total retrieved: {len(retrieved_memory)} chars")

        # ═══════════════════════════════════════════════════════════
        # CONTAINER EXECUTION (wenn ThinkingLayer es angefordert hat)
        # ═══════════════════════════════════════════════════════════
        container_result = None
        
        if thinking_plan.get("needs_container") and ENABLE_CONTAINER_MANAGER:
            container_name = thinking_plan.get("container_name")
            container_task = thinking_plan.get("container_task", "execute")
            
            if container_name:
                log_info(f"[CoreBridge] === CONTAINER EXECUTION: {container_name} ===")
                
                # Signal an Client: Container wird gestartet
                log_info(f"[CoreBridge-Container] Yielding container_start event")
                yield ("", False, {
                    "type": "container_start",
                    "container": container_name,
                    "task": container_task
                })
                
                # Code aus der Nachricht extrahieren
                code = self._extract_code_from_message(user_text)
                
                if code:
                    log_info(f"[CoreBridge-Container] Executing {len(code)} chars of code")
                    
                    # Code in Container ausführen
                    container_result = await self._execute_in_container(
                        container_name=container_name,
                        code=code,
                        task=container_task
                    )
                    
                    log_info(f"[CoreBridge-Container] Execution done, result: {container_result}")
                    
                    # Signal an Client: Container fertig
                    yield ("", False, {
                        "type": "container_done",
                        "result": container_result
                    })
                    log_info(f"[CoreBridge-Container] Yielded container_done event")
                    
                    # Container-Ergebnis zum Memory hinzufügen für OutputLayer
                    if container_result and not container_result.get("error"):
                        execution_info = f"\n\n=== CODE-AUSFÜHRUNG ({container_name}) ===\n"
                        execution_info += f"Exit-Code: {container_result.get('exit_code', 'N/A')}\n"
                        
                        stdout = container_result.get("stdout", "")
                        stderr = container_result.get("stderr", "")
                        
                        if stdout:
                            execution_info += f"Output:\n{stdout}\n"
                        if stderr:
                            execution_info += f"Errors:\n{stderr}\n"
                        
                        retrieved_memory += execution_info
                        log_info(f"[CoreBridge-Container] Added execution result to context")
                else:
                    log_warning("[CoreBridge-Container] No code found in message")
                    container_result = {"error": "Kein Code in der Nachricht gefunden"}

        # ═══════════════════════════════════════════════════════════
        # MODEL SELECTION: Code-Model wenn nötig
        # ═══════════════════════════════════════════════════════════
        use_code_model = thinking_plan.get("use_code_model", False)
        selected_model = CODE_MODEL if use_code_model else request.model
        
        if use_code_model:
            log_info(f"[CoreBridge] Using CODE_MODEL: {CODE_MODEL} (instead of {request.model})")

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
        
        # Streame die Antwort MIT Chat-History für Kontext
        # Nutzt CODE_MODEL wenn use_code_model=true
        async for chunk in self.output.generate_stream(
            user_text=user_text,
            verified_plan=verified_plan,
            memory_data=retrieved_memory,
            model=selected_model,  # ← CODE_MODEL oder request.model
            memory_required_but_missing=memory_required_but_missing,
            chat_history=request.messages
        ):
            full_answer += chunk
            yield (chunk, False, {
                "type": "content", 
                "memory_used": memory_used,
                "model": selected_model,
                "code_model_used": use_code_model
            })
        
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
        yield ("", True, {
            "memory_used": memory_used, 
            "done_reason": "stop",
            "model": selected_model,
            "code_model_used": use_code_model,
            "container_used": container_result is not None
        })


# Singleton-Instanz
_bridge_instance: Optional[CoreBridge] = None

def get_bridge() -> CoreBridge:
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = CoreBridge()
    return _bridge_instance
