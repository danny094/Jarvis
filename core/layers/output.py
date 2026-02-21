# core/layers/output.py
"""
LAYER 3: OutputLayer v3.0
- Native Ollama Tool Calling via /api/chat
- Automatic tool loop (call → result → continue)
- Dynamic tool injection from MCPHub
- Streaming support with tool interrupts
"""

import json
import httpx
from typing import Dict, Any, Optional, AsyncGenerator, List
from config import OLLAMA_BASE, OUTPUT_MODEL
from utils.logger import log_info, log_error, log_debug, log_warning
from core.persona import get_persona
from mcp_registry import get_enabled_tools
from mcp.hub import get_hub


def _is_small_model_mode() -> bool:
    """Lazy import to avoid circular imports at module load."""
    try:
        from config import get_small_model_mode
        return get_small_model_mode()
    except Exception:
        return False

MAX_TOOL_ITERATIONS = 5


class OutputLayer:
    def __init__(self):
        self.ollama_base = OLLAMA_BASE
    
    def _get_ollama_tools(self) -> List[Dict]:
        """Baut Ollama-native Tool-Definitionen aus MCPHub."""
        hub = get_hub()
        hub.initialize()
        tool_defs = hub.list_tools()
        
        ollama_tools = []
        for tool_def in tool_defs:
            name = tool_def.get("name", "")
            desc = tool_def.get("description", "")
            input_schema = tool_def.get("inputSchema", {})
            
            if not name:
                continue
            
            # Convert MCP format → Ollama format
            ollama_tool = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": desc,
                    "parameters": input_schema if input_schema else {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            }
            ollama_tools.append(ollama_tool)
        
        log_debug(f"[OutputLayer] {len(ollama_tools)} tools prepared for Ollama")
        return ollama_tools
    
    def _build_system_prompt(
        self, 
        verified_plan: Dict[str, Any], 
        memory_data: str,
        memory_required_but_missing: bool = False,
        needs_chat_history: bool = False
    ) -> str:
        """Baut den System-Prompt mit Persona und Kontext."""
        persona = get_persona()
        prompt_parts = []
        
        # Persona-Basis mit dynamischen Tools
        available_tools = get_enabled_tools()
        dynamic_context = {"tools": available_tools} if available_tools else None
        prompt_parts.append(persona.build_system_prompt(dynamic_context=dynamic_context))
        
        # Tool-Confidence: echte Daten verfügbar → positive Instruktion
        if verified_plan.get("_tool_confidence") == "high":
            prompt_parts.append("\n### ECHTE DATEN VERFÜGBAR:")
            prompt_parts.append("Du hast ECHTE Tool-Ergebnisse (siehe TOOL-ERGEBNISSE unten).")
            prompt_parts.append("Gib die Daten direkt und natürlich aus. Kein Zögern, keine Ausreden.")
        # Anti-Halluzination (nur wenn wirklich keine Daten vorliegen)
        elif memory_required_but_missing:
            prompt_parts.append("\n### ANTI-HALLUZINATION:")
            prompt_parts.append("Diese Info ist NICHT gespeichert. ERFINDE NICHTS.")
            prompt_parts.append("Sage: 'Das habe ich leider nicht gespeichert.'")
        
        # Chat-History Hinweis
        if needs_chat_history:
            prompt_parts.append("\n### CHAT-HISTORY:")
            prompt_parts.append("Beantworte basierend auf der bisherigen Konversation.")
        
        # Control-Layer Anweisung
        instruction = verified_plan.get("_final_instruction", "")
        if instruction:
            prompt_parts.append(f"\n### ANWEISUNG:\n{instruction}")
        
        # Memory-Daten
        # In small mode: inject once here (capped orchestrator context_text).
        # The temporal-protocol re-extraction into the user message is suppressed
        # separately in _build_messages to prevent the duplicate.
        if memory_data:
            is_temporal = bool(verified_plan.get("time_reference"))
            if is_temporal:
                prompt_parts.append(f"\n### TAGESPROTOKOLL (PFLICHT-QUELLE):\n{memory_data}")
                prompt_parts.append("Dies ist das vollständige Tagesprotokoll. Du MUSST deine Antwort AUSSCHLIEßLICH darauf stützen. ERFINDE NICHTS.")
            else:
                prompt_parts.append(f"\n### FAKTEN AUS DEM GEDÄCHTNIS:\n{memory_data}")
                prompt_parts.append("NUTZE diese Fakten!")
        
        # Warnungen
        warnings = verified_plan.get("_warnings", [])
        if warnings:
            prompt_parts.append("\n### WARNUNGEN:")
            for w in warnings:
                prompt_parts.append(f"- {w}")
        
        # Sequential Thinking Ergebnisse
        sequential_result = verified_plan.get("_sequential_result")
        if sequential_result and sequential_result.get("success"):
            prompt_parts.append("\n### VORAB-ANALYSE (Sequential Thinking):")
            full_response = sequential_result.get("full_response", "")
            if full_response and not full_response.startswith("[Ollama Error"):
                prompt_parts.append(full_response[:4000])
            else:
                steps = sequential_result.get("steps", [])
                for step in steps[:10]:
                    step_num = step.get("step", "?")
                    title = step.get("title", "")
                    thought = step.get("thought", "")[:500]
                    prompt_parts.append(f"**Step {step_num}: {title}**")
                    prompt_parts.append(thought)
            prompt_parts.append("\nFASSE diese Analyse zusammen und formuliere eine klare Antwort.")
        
        # ── Commit 1: Tool-Ergebnisse kommen ausschließlich über memory_data (single channel). ──
        # _tool_results wird NICHT separat in den System-Prompt injiziert, um Dreifach-Injektion
        # zu vermeiden. tool_context ist bereits über _append_context_block in memory_data enthalten.

        # Stil
        style = verified_plan.get("suggested_response_style", "")
        if style:
            prompt_parts.append(f"\n### STIL: Antworte {style}.")
        
        return "\n".join(prompt_parts)
    
    def _build_messages(
        self,
        user_text: str,
        verified_plan: Dict[str, Any],
        memory_data: str = "",
        memory_required_but_missing: bool = False,
        chat_history: list = None
    ) -> List[Dict[str, str]]:
        """Baut Messages-Array für /api/chat (statt prompt für /api/generate)."""
        
        needs_chat_history = verified_plan.get("needs_chat_history", False)
        system_prompt = self._build_system_prompt(
            verified_plan, memory_data, memory_required_but_missing,
            needs_chat_history=needs_chat_history
        )
        
        messages = [{"role": "system", "content": system_prompt}]
        
        # Chat-History einbauen
        if chat_history and len(chat_history) > 1:
            history_to_show = chat_history[-11:-1] if len(chat_history) > 11 else chat_history[:-1]
            for msg in history_to_show:
                role = msg.role.value if hasattr(msg.role, 'value') else str(msg.role)
                content = msg.content
                if role == "user":
                    messages.append({"role": "user", "content": content})
                elif role == "assistant":
                    messages.append({"role": "assistant", "content": content})
        
        # ── Commit 1: User-Message enthält nur den reinen User-Text (single channel). ──
        # Tool-Ergebnisse und Protokoll-Kontext kommen ausschließlich über den System-Prompt
        # (via memory_data → ### FAKTEN / ### TAGESPROTOKOLL). Keine Doppel-Injektion mehr.
        messages.append({"role": "user", "content": user_text})

        return messages
    
    # ═══════════════════════════════════════════════════════════
    # ASYNC STREAMING WITH TOOL LOOP
    # ═══════════════════════════════════════════════════════════
    async def generate_stream(
        self,
        user_text: str,
        verified_plan: Dict[str, Any],
        memory_data: str = "",
        model: str = None,
        memory_required_but_missing: bool = False,
        chat_history: list = None
    ) -> AsyncGenerator[str, None]:
        """
        Generiert Antwort als Stream MIT nativem Tool Calling.
        
        Flow:
        1. Sende Messages + Tools an Ollama /api/chat
        2. Wenn Modell Tool aufruft: execute via MCPHub
        3. Injiziere Ergebnis als tool-message
        4. Wiederhole bis Text-Antwort kommt (max MAX_TOOL_ITERATIONS)
        5. Streame die Text-Antwort zum Frontend
        """
        model = model or OUTPUT_MODEL
        messages = self._build_messages(
            user_text, verified_plan, memory_data,
            memory_required_but_missing, chat_history
        )

        # === [CTX-FINAL]: real provider payload size, after persona/instructions/history are added ===
        _ctx_trace = verified_plan.get("_ctx_trace", {})
        _payload_chars = sum(len(m.get("content") or "") for m in messages)
        log_info(
            f"[CTX-FINAL] mode={_ctx_trace.get('mode', 'unknown')} "
            f"context_sources={','.join(_ctx_trace.get('context_sources', []))} "
            f"payload_chars={_payload_chars} "
            f"retrieval_count={_ctx_trace.get('retrieval_count', 0)}"
        )

        # === Tool-Ergebnisse sind bereits im memory_data/verified_plan vom Orchestrator ===
        # === Kein Tool Loop nötig — Orchestrator hat Tools schon ausgeführt ===

        try:
            # === STREAMING RESPONSE via /api/chat ===
            log_debug(f"[OutputLayer] Streaming response with {model}...")
            total_chars = 0
            
            async with httpx.AsyncClient(timeout=120.0) as client:
                # Final request: stream=true, KEINE tools (erzwingt Text-Antwort)
                payload = {
                    "model": model,
                    "messages": messages,
                    "stream": True,
                    "keep_alive": "5m",
                }
                
                async with client.stream(
                    "POST",
                    f"{self.ollama_base}/api/chat",
                    json=payload
                ) as response:
                    response.raise_for_status()
                    
                    async for line in response.aiter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                msg = data.get("message", {})
                                chunk = msg.get("content", "")
                                if chunk:
                                    total_chars += len(chunk)
                                    yield chunk
                                if data.get("done"):
                                    break
                            except json.JSONDecodeError:
                                continue
            
            log_info(f"[OutputLayer] Streamed {total_chars} chars (no tool loop)")
                
        except httpx.TimeoutException:
            log_error(f"[OutputLayer] Stream Timeout nach 120s")
            yield "Entschuldigung, die Anfrage hat zu lange gedauert."
        except httpx.HTTPStatusError as e:
            log_error(f"[OutputLayer] Stream HTTP Error: {e.response.status_code}")
            yield f"Entschuldigung, Server-Fehler: {e.response.status_code}"
        except httpx.ConnectError as e:
            log_error(f"[OutputLayer] Connection Error: {e}")
            yield "Entschuldigung, konnte keine Verbindung zum Model herstellen."
        except Exception as e:
            log_error(f"[OutputLayer] Error: {type(e).__name__}: {e}")
            yield f"Entschuldigung, es gab einen Fehler: {str(e)}"
    
    async def _chat_check_tools(
        self, 
        model: str, 
        messages: List[Dict], 
        tools: List[Dict]
    ) -> Optional[Dict]:
        """
        NON-STREAMING /api/chat call um zu prüfen ob Tool-Calls kommen.
        Returns: {"content": "...", "tool_calls": [...]} oder None
        """
        if not tools:
            return None
        
        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "keep_alive": "5m",
        }
        
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(
                    f"{self.ollama_base}/api/chat",
                    json=payload
                )
                response.raise_for_status()
                data = response.json()
            
            msg = data.get("message", {})
            tool_calls = msg.get("tool_calls", [])
            content = msg.get("content", "")
            
            if tool_calls:
                return {"content": content, "tool_calls": tool_calls}
            
            return None  # Keine Tool-Calls → Text-Antwort
            
        except Exception as e:
            log_error(f"[OutputLayer] Tool check failed: {e}")
            return None
    
    # ═══════════════════════════════════════════════════════════
    # LEGACY: _build_full_prompt für Backward-Kompatibilität
    # ═══════════════════════════════════════════════════════════
    def _build_full_prompt(
        self,
        user_text: str,
        verified_plan: Dict[str, Any],
        memory_data: str = "",
        memory_required_but_missing: bool = False,
        chat_history: list = None
    ) -> str:
        """Legacy prompt builder für /api/generate Kompatibilität."""
        needs_chat_history = verified_plan.get("needs_chat_history", False)
        system_prompt = self._build_system_prompt(
            verified_plan, memory_data, memory_required_but_missing,
            needs_chat_history=needs_chat_history
        )
        prompt_parts = [system_prompt]
        
        if chat_history and len(chat_history) > 1:
            prompt_parts.append("\n\n### BISHERIGE KONVERSATION:")
            history_to_show = chat_history[-11:-1] if len(chat_history) > 11 else chat_history[:-1]
            for msg in history_to_show:
                role = msg.role.value if hasattr(msg.role, 'value') else str(msg.role)
                if role == "user":
                    prompt_parts.append(f"USER: {msg.content}")
                elif role == "assistant":
                    prompt_parts.append(f"ASSISTANT: {msg.content}")
        
        # ── Commit 1: Kein separater _tool_results-Block — bereits in memory_data (System-Prompt). ──
        prompt_parts.append(f"\n\n### USER:\n{user_text}")
        prompt_parts.append("\n\n### DEINE ANTWORT:")
        return "\n".join(prompt_parts)
    
    # ═══════════════════════════════════════════════════════════
    # SYNC STREAMING (Legacy SSE-Kompatibilität)
    # ═══════════════════════════════════════════════════════════
    def generate_stream_sync(
        self,
        user_text: str,
        verified_plan: Dict[str, Any],
        memory_data: str = "",
        model: str = None,
        memory_required_but_missing: bool = False,
        chat_history: list = None
    ):
        """Synchroner Stream Generator. ACHTUNG: Blockiert! Nur in ThreadPool."""
        model = model or OUTPUT_MODEL
        full_prompt = self._build_full_prompt(
            user_text, verified_plan, memory_data,
            memory_required_but_missing, chat_history
        )

        # ── Commit 5: [CTX-FINAL] parity — same marker in sync and stream paths ──
        _ctx_trace = verified_plan.get("_ctx_trace", {})
        _payload_chars = len(full_prompt)
        log_info(
            f"[CTX-FINAL] mode={_ctx_trace.get('mode', 'unknown')} "
            f"context_sources={','.join(_ctx_trace.get('context_sources', []))} "
            f"payload_chars={_payload_chars} "
            f"retrieval_count={_ctx_trace.get('retrieval_count', 0)}"
        )

        payload = {
            "model": model,
            "prompt": full_prompt,
            "stream": True,
            "keep_alive": "5m",
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
            
        except Exception as e:
            log_error(f"[OutputLayer] Sync stream error: {e}")
            yield f"Fehler: {str(e)}"

    async def generate(
        self,
        user_text: str,
        verified_plan: Dict[str, Any],
        memory_data: str = '',
        model: str = None,
        memory_required_but_missing: bool = False,
        chat_history: list = None
    ) -> str:
        """Non-streaming generate (sammelt alle chunks)."""
        result = []
        async for chunk in self.generate_stream(
            user_text=user_text,
            verified_plan=verified_plan,
            memory_data=memory_data,
            model=model,
            memory_required_but_missing=memory_required_but_missing,
            chat_history=chat_history
        ):
            result.append(chunk)
        return ''.join(result)
