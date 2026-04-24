# core/layers/thinking.py
"""
LAYER 1: ThinkingLayer (DeepSeek-R1)
v3.0: Entschlackter Prompt, keine doppelten Felder

Analysiert die User-Anfrage und erstellt einen Plan.
STREAMING: Zeigt das "Nachdenken" live an!
"""

from typing import Dict, Any, AsyncGenerator, Tuple, Optional
from config import OLLAMA_BASE, get_thinking_model, get_thinking_provider
from utils.logger import log_info, log_error, log_debug
from utils.json_parser import safe_parse_json
from utils.role_endpoint_resolver import resolve_role_endpoint
from core.llm_provider_client import resolve_role_provider, stream_prompt
from intelligence_modules.prompt_manager import load_prompt


THINKING_PROMPT = load_prompt("layers", "thinking")


class ThinkingLayer:
    def __init__(self, model: str = None):
        self._model_override = (model or "").strip() or None
        self.ollama_base = OLLAMA_BASE

    def _resolve_model(self) -> str:
        return self._model_override or get_thinking_model()
    
    async def analyze_stream(
        self,
        user_text: str,
        memory_context: str = "",
        available_tools: list = None,
        tone_signal: Optional[Dict[str, Any]] = None,
        tool_hints: Optional[str] = None,
    ) -> AsyncGenerator[Tuple[str, bool, Dict[str, Any]], None]:
        """
        Analysiert die User-Anfrage MIT STREAMING.
        Yields: (thinking_chunk, is_done, plan_if_done)
        """
        prompt = f"{THINKING_PROMPT}\n\n"
        
        if memory_context:
            prompt += load_prompt(
                "layers",
                "thinking_memory_context",
                memory_context=memory_context,
            ) + "\n\n"
        
        if available_tools:
            import json
            tools_json = json.dumps(available_tools, indent=1)
            prompt += load_prompt(
                "layers",
                "thinking_available_tools",
                tools_json=tools_json,
            ) + "\n\n"

        if tone_signal:
            import json
            tone_json = json.dumps(tone_signal, ensure_ascii=False, indent=1)
            prompt += load_prompt(
                "layers",
                "thinking_tone_signal",
                tone_json=tone_json,
            ) + "\n\n"
        
        if tool_hints:
            prompt += f"{tool_hints}\n\n"
            log_debug(f"[ThinkingLayer] Injected detection hints ({len(tool_hints)} chars)")

        prompt += load_prompt("layers", "thinking_user_request", user_text=user_text)

        model_name = self._resolve_model()
        provider = resolve_role_provider("thinking", default=get_thinking_provider())
        full_response = ""
        
        try:
            endpoint = self.ollama_base
            if provider == "ollama":
                route = resolve_role_endpoint("thinking", default_endpoint=self.ollama_base)
                log_info(
                    f"[Routing] role=thinking provider=ollama requested_target={route['requested_target']} "
                    f"effective_target={route['effective_target'] or 'none'} "
                    f"fallback={bool(route['fallback_reason'])} "
                    f"fallback_reason={route['fallback_reason'] or 'none'} "
                    f"endpoint_source={route['endpoint_source']}"
                )
                if route["hard_error"]:
                    log_error(
                        f"[Routing] role=thinking hard_error=true code={route['error_code']} "
                        f"requested_target={route['requested_target']}"
                    )
                    yield ("", True, self._default_plan())
                    return
                endpoint = route["endpoint"] or self.ollama_base
            else:
                log_info(f"[Routing] role=thinking provider={provider} endpoint=cloud")

            log_debug(
                f"[ThinkingLayer] Streaming analysis provider={provider} model={model_name}: "
                f"{user_text[:50]}..."
            )

            async for chunk in stream_prompt(
                provider=provider,
                model=model_name,
                prompt=prompt,
                timeout_s=90.0,
                ollama_endpoint=endpoint,
            ):
                if chunk:
                    full_response += chunk
                    yield (chunk, False, {})
            
            plan = self._extract_plan(full_response)
            log_info(f"[ThinkingLayer] Plan: intent={plan.get('intent')}, needs_memory={plan.get('needs_memory')}")
            log_info(f"[ThinkingLayer] sequential={plan.get('needs_sequential_thinking')}, complexity={plan.get('sequential_complexity')}")
            yield ("", True, plan)
                
        except Exception as e:
            err_type = type(e).__name__
            log_error(f"[ThinkingLayer] Error ({err_type}): {e}")
            yield ("", True, self._default_plan())
    
    def _extract_plan(self, full_response: str) -> Dict[str, Any]:
        """Extrahiert den JSON-Plan aus der Thinking-Response."""
        plan = safe_parse_json(full_response, default=None, context="ThinkingLayer")
        if plan and "intent" in plan:
            return plan
        return self._default_plan()
    
    async def analyze(
        self,
        user_text: str,
        memory_context: str = "",
        available_tools: list = None,
        tone_signal: Optional[Dict[str, Any]] = None,
        tool_hints: Optional[str] = None,
    ) -> Dict[str, Any]:
        """NON-STREAMING Version (Kompatibilität)."""
        plan = self._default_plan()
        async for chunk, is_done, result in self.analyze_stream(
            user_text,
            memory_context,
            available_tools,
            tone_signal=tone_signal,
            tool_hints=tool_hints,
        ):
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
            "resolution_strategy": None,
            "strategy_hints": [],
            "time_reference": None,
            "is_new_fact": False,
            "new_fact_key": None,
            "new_fact_value": None,
            "hallucination_risk": "medium",
            "suggested_response_style": "freundlich",
            "dialogue_act": "request",
            "response_tone": "neutral",
            "response_length_hint": "medium",
            "tone_confidence": 0.55,
            "needs_sequential_thinking": False,
            "sequential_complexity": 3,
            "task_loop_candidate": False,
            "task_loop_kind": "none",
            "task_loop_confidence": 0.0,
            "estimated_steps": 0,
            "needs_visible_progress": False,
            "task_loop_reason": None,
            "suggested_cim_modes": [],
            "suggested_tools": [],
            "reasoning_type": "direct",
            "reasoning": "Fallback - Analyse fehlgeschlagen"
        }
