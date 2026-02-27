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
from config import (
    OLLAMA_BASE,
    get_output_model,
    get_output_tool_injection_mode,
    get_output_tool_prompt_limit,
    get_output_char_cap_interactive,
    get_output_char_cap_deep,
    get_output_timeout_interactive_s,
    get_output_timeout_deep_s,
)
from utils.logger import log_info, log_error, log_debug, log_warning
from utils.role_endpoint_resolver import resolve_role_endpoint
from core.persona import get_persona
from mcp_registry import get_enabled_tools
from mcp.hub import get_hub

MAX_TOOL_ITERATIONS = 5


def _is_small_model_mode() -> bool:
    """Compatibility hook used by tests and feature flags."""
    try:
        from config import get_small_model_mode
        return bool(get_small_model_mode())
    except Exception:
        return False


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
        available_tools = self._resolve_tools_for_prompt(verified_plan)
        dynamic_context = {"tools": available_tools} if available_tools else None
        prompt_parts.append(persona.build_system_prompt(dynamic_context=dynamic_context))
        
        # Anti-Halluzination
        if memory_required_but_missing:
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
        if memory_data:
            prompt_parts.append(f"\n### FAKTEN AUS DEM GEDÄCHTNIS:\n{memory_data}")
            prompt_parts.append("NUTZE diese Fakten!")
        
        # Warnungen
        warnings = verified_plan.get("_warnings", [])
        if warnings:
            prompt_parts.append("\n### WARNUNGEN:")
            for w in warnings:
                prompt_parts.append(f"- {w}")

        # Runtime mode hint
        response_mode = str(verified_plan.get("_response_mode", "interactive")).lower()
        if response_mode != "deep":
            prompt_parts.append("\n### ANTWORT-BUDGET:")
            prompt_parts.append("Antworte knapp, konkret und ohne lange Ausschweifungen.")
        
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
        
        # Stil
        style = verified_plan.get("suggested_response_style", "")
        if style:
            prompt_parts.append(f"\n### STIL: Antworte {style}.")
        
        return "\n".join(prompt_parts)

    @staticmethod
    def _extract_selected_tool_names(verified_plan: Dict[str, Any]) -> List[str]:
        """
        Extract selected tool names from verified plan metadata.
        """
        raw = []
        if isinstance(verified_plan, dict):
            raw = (
                verified_plan.get("_selected_tools_for_prompt")
                or verified_plan.get("suggested_tools")
                or []
            )

        names: List[str] = []
        seen = set()
        for item in raw:
            if isinstance(item, dict):
                name = str(item.get("tool") or item.get("name") or "").strip()
            else:
                name = str(item).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)
        return names

    def _resolve_tools_for_prompt(self, verified_plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Resolve tool list injected into Output system prompt.
        """
        mode = get_output_tool_injection_mode()
        limit = get_output_tool_prompt_limit()
        all_tools = get_enabled_tools()

        if mode == "none":
            return []
        if mode == "all":
            return all_tools[:limit]

        # selected (default): only tools chosen for the current request.
        selected_names = self._extract_selected_tool_names(verified_plan)
        if not selected_names:
            return []

        selected = []
        by_name = {t.get("name"): t for t in all_tools if t.get("name")}
        for name in selected_names:
            item = by_name.get(name)
            if item:
                selected.append(item)
            else:
                selected.append({
                    "name": name,
                    "mcp": "unknown",
                    "description": "Selected for current request",
                })
            if len(selected) >= limit:
                break
        return selected
    
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
        
        # Aktuelle User-Nachricht — single-truth: no duplicate tool/protocol injection here.
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
        model = (model or "").strip() or get_output_model()
        response_mode = str(verified_plan.get("_response_mode", "interactive")).lower()
        char_cap = (
            get_output_char_cap_deep()
            if response_mode == "deep"
            else get_output_char_cap_interactive()
        )
        timeout_s = verified_plan.get("_output_time_budget_s")
        if timeout_s is None:
            timeout_s = (
                get_output_timeout_deep_s()
                if response_mode == "deep"
                else get_output_timeout_interactive_s()
            )
        try:
            timeout_s = float(timeout_s)
        except Exception:
            timeout_s = float(get_output_timeout_interactive_s())
        timeout_s = max(5.0, min(300.0, timeout_s))
        messages = self._build_messages(
            user_text, verified_plan, memory_data,
            memory_required_but_missing, chat_history
        )

        # Observability parity with sync path.
        ctx_trace = verified_plan.get("_ctx_trace", {}) if isinstance(verified_plan, dict) else {}
        mode = ctx_trace.get("mode", "unknown")
        context_sources = ctx_trace.get("context_sources", [])
        retrieval_count = ctx_trace.get("retrieval_count", 0)
        payload_chars = len(memory_data or "")
        log_info(
            f"[CTX-FINAL] mode={mode} context_sources={context_sources} "
            f"payload_chars={payload_chars} retrieval_count={retrieval_count}"
        )
        
        # === Tool-Ergebnisse sind bereits im memory_data/verified_plan vom Orchestrator ===
        # === Kein Tool Loop nötig — Orchestrator hat Tools schon ausgeführt ===
        
        try:
            route = resolve_role_endpoint("output", default_endpoint=self.ollama_base)
            log_info(
                f"[Routing] role=output requested_target={route['requested_target']} "
                f"effective_target={route['effective_target'] or 'none'} "
                f"fallback={bool(route['fallback_reason'])} "
                f"fallback_reason={route['fallback_reason'] or 'none'} "
                f"endpoint_source={route['endpoint_source']}"
            )
            if route["hard_error"]:
                yield "Entschuldigung, Output-Compute ist aktuell nicht verfügbar."
                return
            endpoint = route["endpoint"] or self.ollama_base

            # === STREAMING RESPONSE via /api/chat ===
            log_debug(f"[OutputLayer] Streaming response with {model}...")
            total_chars = 0
            truncated = False
            
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                # Final request: stream=true, KEINE tools (erzwingt Text-Antwort)
                payload = {
                    "model": model,
                    "messages": messages,
                    "stream": True,
                    "keep_alive": "5m",
                }
                
                async with client.stream(
                    "POST",
                    f"{endpoint}/api/chat",
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
                                    if char_cap > 0 and total_chars >= char_cap:
                                        truncated = True
                                        break
                                    if char_cap > 0 and total_chars + len(chunk) > char_cap:
                                        keep = max(0, char_cap - total_chars)
                                        if keep > 0:
                                            yield chunk[:keep]
                                            total_chars += keep
                                        truncated = True
                                        break
                                    total_chars += len(chunk)
                                    yield chunk
                                if data.get("done"):
                                    break
                            except json.JSONDecodeError:
                                continue

            if truncated:
                yield "\n\n[Antwort gekürzt: Interactive-Mode Output-Budget erreicht.]"
            
            log_info(f"[OutputLayer] Streamed {total_chars} chars (no tool loop)")
                
        except httpx.TimeoutException:
            log_error(f"[OutputLayer] Stream Timeout nach {timeout_s:.0f}s")
            yield "Entschuldigung, die Anfrage hat zu lange gedauert."
        except httpx.HTTPStatusError as e:
            log_error(f"[OutputLayer] Stream HTTP Error: {e.response.status_code}")
            yield f"Entschuldigung, Server-Fehler: {e.response.status_code}"
        except (httpx.ReadError, httpx.RemoteProtocolError) as e:
            log_error(f"[OutputLayer] Stream disconnected: {e}")
            yield "Verbindung zum Model wurde unterbrochen. Bitte Anfrage erneut senden."
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
            route = resolve_role_endpoint("output", default_endpoint=self.ollama_base)
            if route["hard_error"]:
                log_error(
                    f"[Routing] role=output hard_error=true code={route['error_code']} "
                    f"requested_target={route['requested_target']}"
                )
                return None
            endpoint = route["endpoint"] or self.ollama_base

            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(
                    f"{endpoint}/api/chat",
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
        model = (model or "").strip() or get_output_model()
        response_mode = str(verified_plan.get("_response_mode", "interactive")).lower()
        char_cap = (
            get_output_char_cap_deep()
            if response_mode == "deep"
            else get_output_char_cap_interactive()
        )
        timeout_s = verified_plan.get("_output_time_budget_s")
        if timeout_s is None:
            timeout_s = (
                get_output_timeout_deep_s()
                if response_mode == "deep"
                else get_output_timeout_interactive_s()
            )
        try:
            timeout_s = float(timeout_s)
        except Exception:
            timeout_s = float(get_output_timeout_interactive_s())
        timeout_s = max(5.0, min(300.0, timeout_s))
        full_prompt = self._build_full_prompt(
            user_text, verified_plan, memory_data,
            memory_required_but_missing, chat_history
        )

        # Observability parity with async path.
        ctx_trace = verified_plan.get("_ctx_trace", {}) if isinstance(verified_plan, dict) else {}
        mode = ctx_trace.get("mode", "unknown")
        context_sources = ctx_trace.get("context_sources", [])
        retrieval_count = ctx_trace.get("retrieval_count", 0)
        payload_chars = len(memory_data or "")
        log_info(
            f"[CTX-FINAL] mode={mode} context_sources={context_sources} "
            f"payload_chars={payload_chars} retrieval_count={retrieval_count}"
        )
        
        payload = {
            "model": model,
            "prompt": full_prompt,
            "stream": True,
            "keep_alive": "5m",
        }
        
        try:
            route = resolve_role_endpoint("output", default_endpoint=self.ollama_base)
            log_info(
                f"[Routing] role=output requested_target={route['requested_target']} "
                f"effective_target={route['effective_target'] or 'none'} "
                f"fallback={bool(route['fallback_reason'])} "
                f"fallback_reason={route['fallback_reason'] or 'none'} "
                f"endpoint_source={route['endpoint_source']}"
            )
            if route["hard_error"]:
                yield "Fehler: Output-Compute nicht verfuegbar."
                return
            endpoint = route["endpoint"] or self.ollama_base

            log_debug(f"[OutputLayer] Sync streaming with {model}...")
            total_chars = 0
            truncated = False
            
            with httpx.Client(timeout=timeout_s) as client:
                with client.stream(
                    "POST",
                    f"{endpoint}/api/generate",
                    json=payload
                ) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                chunk = data.get("response", "")
                                if chunk:
                                    if char_cap > 0 and total_chars >= char_cap:
                                        truncated = True
                                        break
                                    if char_cap > 0 and total_chars + len(chunk) > char_cap:
                                        keep = max(0, char_cap - total_chars)
                                        if keep > 0:
                                            yield chunk[:keep]
                                            total_chars += keep
                                        truncated = True
                                        break
                                    total_chars += len(chunk)
                                    yield chunk
                                if data.get("done"):
                                    break
                            except json.JSONDecodeError:
                                continue

            if truncated:
                yield "\n\n[Antwort gekürzt: Interactive-Mode Output-Budget erreicht.]"
            
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
