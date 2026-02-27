# core/layers/control.py
"""
LAYER 2: ControlLayer (Qwen)
v4.0: Echtes Ollama Streaming für Progressive Steps
"""

import json
import httpx
import re
import asyncio
from typing import Dict, Any, Optional, AsyncGenerator, List
from config import (
    OLLAMA_BASE,
    get_control_model,
    get_thinking_model,
    get_control_prompt_memory_chars,
    get_control_prompt_plan_chars,
    get_control_prompt_user_chars,
    get_memory_keys_max_per_request,
)
from utils.logger import log_info, log_error, log_debug, log_warning
from utils.json_parser import safe_parse_json
from utils.role_endpoint_resolver import resolve_role_endpoint
from core.safety import LightCIM
from core.sequential_registry import get_registry

# CIM Policy Engine für Skill-Creation Detection
try:
    from intelligence_modules.cim_policy.cim_policy_engine import process_cim as process_cim_policy
    CIM_POLICY_AVAILABLE = True
except ImportError:
    CIM_POLICY_AVAILABLE = False
    log_warning("[ControlLayer] CIM Policy Engine not available")

CIM_URL = "http://cim-server:8086"

CONTROL_PROMPT = """Du bist der CONTROL-Layer eines AI-Systems.
Deine Aufgabe: Überprüfe den Plan vom Thinking-Layer BEVOR eine Antwort generiert wird.

Du antwortest NUR mit validem JSON, nichts anderes.

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
"""

SEQUENTIAL_SYSTEM_PROMPT = """You are a rigorous step-by-step reasoner.

Format your response with clear step markers:
## Step 1: [Step Title]
[Your detailed analysis for this step]

## Step 2: [Step Title]
[Your detailed analysis for this step]

IMPORTANT:
- Start each step with "## Step N:" on its own line
- Give each step a descriptive title
- Be thorough but concise
- Complete all requested steps"""


class ControlLayer:
    def __init__(self, model: str = None):
        self._model_override = (model or "").strip() or None
        self.ollama_base = OLLAMA_BASE
        self.light_cim = LightCIM()
        self.mcp_hub = None
        self.registry = get_registry()

    def _resolve_model(self) -> str:
        return self._model_override or get_control_model()

    def _resolve_sequential_model(self) -> str:
        return get_thinking_model()

    @staticmethod
    def _clip_text(text: str, max_chars: int) -> str:
        raw = str(text or "").strip()
        if max_chars <= 0:
            return ""
        if len(raw) <= max_chars:
            return raw
        suffix = f"\n...[truncated {len(raw) - max_chars} chars]"
        keep = max(0, max_chars - len(suffix))
        return raw[:keep].rstrip() + suffix

    @staticmethod
    def _tool_names(raw_tools: List[Any], limit: int = 8) -> List[str]:
        names: List[str] = []
        seen = set()
        for item in raw_tools or []:
            if isinstance(item, dict):
                name = str(item.get("tool") or item.get("name") or "").strip()
            else:
                name = str(item or "").strip()
            if not name or name in seen:
                continue
            names.append(name)
            seen.add(name)
            if len(names) >= limit:
                break
        return names

    @staticmethod
    def _memory_keys(keys: List[Any]) -> List[str]:
        normalized: List[str] = []
        seen = set()
        limit = get_memory_keys_max_per_request()
        for key in keys or []:
            k = str(key or "").strip()
            if not k or k in seen:
                continue
            normalized.append(k)
            seen.add(k)
            if len(normalized) >= limit:
                break
        return normalized

    def _build_control_prompt_payload(
        self,
        user_text: str,
        thinking_plan: Dict[str, Any],
        retrieved_memory: str,
    ) -> Dict[str, Any]:
        user_limit = get_control_prompt_user_chars()
        plan_limit = get_control_prompt_plan_chars()
        memory_limit = get_control_prompt_memory_chars()

        plan_payload: Dict[str, Any] = {
            "intent": str((thinking_plan or {}).get("intent", ""))[:300],
            "hallucination_risk": (thinking_plan or {}).get("hallucination_risk", "medium"),
            "needs_memory": bool((thinking_plan or {}).get("needs_memory")),
            "is_fact_query": bool((thinking_plan or {}).get("is_fact_query")),
            "memory_keys": self._memory_keys((thinking_plan or {}).get("memory_keys", [])),
            "suggested_tools": self._tool_names((thinking_plan or {}).get("suggested_tools", [])),
            "time_reference": (thinking_plan or {}).get("time_reference"),
            "needs_sequential_thinking": bool(
                (thinking_plan or {}).get("needs_sequential_thinking")
                or (thinking_plan or {}).get("sequential_thinking_required")
            ),
            "sequential_complexity": (thinking_plan or {}).get("sequential_complexity", 0),
        }
        if (thinking_plan or {}).get("_skill_gate_blocked"):
            plan_payload["skill_gate_blocked"] = True
            plan_payload["skill_gate_reason"] = (thinking_plan or {}).get("_skill_gate_reason", "")
        if (thinking_plan or {}).get("_blueprint_gate_blocked"):
            plan_payload["blueprint_gate_blocked"] = True
            plan_payload["blueprint_gate_reason"] = (thinking_plan or {}).get("_blueprint_gate_reason", "")

        # Ensure plan payload stays compact even if optional fields grow.
        plan_json = json.dumps(plan_payload, ensure_ascii=False)
        if len(plan_json) > plan_limit:
            plan_payload = {
                "intent": plan_payload["intent"],
                "hallucination_risk": plan_payload["hallucination_risk"],
                "needs_memory": plan_payload["needs_memory"],
                "memory_keys": plan_payload["memory_keys"][:2],
                "suggested_tools": plan_payload["suggested_tools"][:4],
            }
            plan_json = self._clip_text(json.dumps(plan_payload, ensure_ascii=False), plan_limit)
        else:
            plan_json = self._clip_text(plan_json, plan_limit)

        memory_excerpt = self._clip_text(retrieved_memory, memory_limit) if retrieved_memory else "(keine)"

        return {
            "user_request": self._clip_text(user_text, user_limit),
            "thinking_plan_compact": plan_json,
            "memory_excerpt": memory_excerpt,
        }
    
    def set_mcp_hub(self, hub):
        self.mcp_hub = hub
        log_info("[ControlLayer] MCP Hub connected")
    
    def _get_available_skills(self) -> list:
        """Holt Liste aller installierten Skills vom MCPHub."""
        if not self.mcp_hub:
            return []
        try:
            result = self.mcp_hub.call_tool("list_skills", {})
            if isinstance(result, dict):
                return [s.get("name", "") for s in result.get("skills", [])]
            elif isinstance(result, list):
                return [s.get("name", "") if isinstance(s, dict) else str(s) for s in result]
            return []
        except Exception as e:
            log_debug(f"[ControlLayer] Could not fetch skills: {e}")
            return []

    def _is_tool_available(self, tool_name: str) -> bool:
        """
        Runtime check for tool availability.
        Fail-closed for non-native tools when hub/discovery is unavailable.
        Native/direct tools stay available.
        """
        if not tool_name:
            return False

        # Native/direct tools handled outside MCP discovery.
        native_tools = {
            "request_container", "stop_container", "exec_in_container",
            "blueprint_list", "container_stats", "container_logs",
            "home_read", "home_write", "home_list",
            "autonomous_skill_task", "run_skill", "create_skill",
            "list_skills", "get_skill_info", "validate_skill_code",
            "get_system_info", "get_system_overview",
        }
        if tool_name in native_tools:
            return True

        hub = self.mcp_hub
        if hub is None:
            try:
                from mcp.hub import get_hub
                hub = get_hub()
                hub.initialize()
            except Exception as e:
                log_warning(
                    f"[ControlLayer] Tool availability check failed (hub init) "
                    f"for '{tool_name}' - fail-closed: {e}"
                )
                return False

        try:
            if hub.get_mcp_for_tool(tool_name):
                return True
            tool_def = getattr(hub, "_tool_definitions", {}).get(tool_name, {})
            if tool_def.get("execution") == "direct":
                return True
        except Exception as e:
            log_warning(
                f"[ControlLayer] Tool availability check failed (discovery) "
                f"for '{tool_name}' - fail-closed: {e}"
            )
            return False
        return False

    @staticmethod
    def _normalize_tool_arguments(raw_args: Any) -> Dict[str, Any]:
        """Normalize tool args to dict; accept JSON-string payloads."""
        if isinstance(raw_args, dict):
            return raw_args
        if isinstance(raw_args, str) and raw_args.strip():
            parsed = safe_parse_json(
                raw_args,
                default={},
                context="ControlLayer.suggested_tool_args",
            )
            if isinstance(parsed, dict):
                return parsed
        return {}

    @staticmethod
    def _sanitize_tool_name(raw_name: Any) -> str:
        """
        Extract a clean tool identifier from noisy LLM text.
        Accepts plain tokens, quoted names, key/value fragments, and call syntax.
        """
        text = str(raw_name or "").strip()
        if not text:
            return ""

        def _clean(candidate: str) -> str:
            candidate = str(candidate or "").strip().strip("`\"'.,:;!?()[]{}")
            if not candidate:
                return ""
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,63}", candidate):
                return candidate.lower()
            return ""

        direct = _clean(text)
        if direct:
            return direct

        kv_patterns = (
            r'(?i)"tool"\s*:\s*"([A-Za-z][A-Za-z0-9_]{1,63})"',
            r"(?i)'tool'\s*:\s*'([A-Za-z][A-Za-z0-9_]{1,63})'",
            r'(?i)"name"\s*:\s*"([A-Za-z][A-Za-z0-9_]{1,63})"',
            r"(?i)'name'\s*:\s*'([A-Za-z][A-Za-z0-9_]{1,63})'",
            r'(?i)\btool\s*[:=]\s*"?([A-Za-z][A-Za-z0-9_]{1,63})"?',
            r'(?i)\bname\s*[:=]\s*"?([A-Za-z][A-Za-z0-9_]{1,63})"?',
        )
        for pattern in kv_patterns:
            match = re.search(pattern, text)
            if match:
                cleaned = _clean(match.group(1))
                if cleaned:
                    return cleaned

        quoted = re.findall(r'["\'`]\s*([A-Za-z][A-Za-z0-9_]{1,63})\s*["\'`]', text)
        for candidate in quoted:
            cleaned = _clean(candidate)
            if cleaned:
                return cleaned

        call_match = re.search(r"\b([A-Za-z][A-Za-z0-9_]{1,63})\s*\(", text)
        if call_match:
            cleaned = _clean(call_match.group(1))
            if cleaned:
                return cleaned

        # Fallback for noisy lines: pick explicit tool-like identifiers (prefer snake_case).
        token_candidates = re.findall(r"\b([A-Za-z][A-Za-z0-9_]{2,63})\b", text)
        snake_case = [t for t in token_candidates if "_" in t]
        for candidate in snake_case:
            cleaned = _clean(candidate)
            if cleaned:
                return cleaned

        # Avoid unsafe fallback from prose lines with spaces.
        if " " in text:
            return ""

        stripped = re.sub(r"^[-*#/\s]+", "", text)
        return _clean(stripped)

    @staticmethod
    def _normalize_suggested_tools(verified_plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Normalize suggested tools to [{"name": str, "arguments": dict}].
        """
        raw = verified_plan.get("suggested_tools", []) if isinstance(verified_plan, dict) else []
        normalized: List[Dict[str, Any]] = []

        for item in raw:
            if isinstance(item, dict):
                name = ControlLayer._sanitize_tool_name(item.get("tool") or item.get("name"))
                args = ControlLayer._normalize_tool_arguments(item.get("args"))
                if not args:
                    args = ControlLayer._normalize_tool_arguments(item.get("arguments"))
                if not name and len(item) == 1:
                    k, v = next(iter(item.items()))
                    name = ControlLayer._sanitize_tool_name(k)
                    if not args:
                        args = ControlLayer._normalize_tool_arguments(v)
                if name:
                    normalized.append({"name": name, "arguments": args})
            else:
                name = ControlLayer._sanitize_tool_name(item)
                if name:
                    normalized.append({"name": name, "arguments": {}})

        return normalized

    @staticmethod
    def _cim_tool_args(
        verified_plan: Dict[str, Any],
        tool_name: str,
        user_text: str = "",
    ) -> Dict[str, Any]:
        """
        Fill obvious args from CIM decision metadata when available.
        """
        cim = verified_plan.get("_cim_decision", {}) if isinstance(verified_plan, dict) else {}
        skill_name = str(cim.get("skill_name") or "").strip()
        if not skill_name:
            return {}
        if tool_name == "get_skill_info":
            return {"skill_name": skill_name}
        if tool_name == "run_skill":
            return {"name": skill_name, "action": "run", "args": {}}
        if tool_name == "create_skill":
            desc = f"Auto-generated skill scaffold from user request: {user_text.strip()[:240]}"
            code = (
                "def main(args=None):\n"
                "    \"\"\"Auto-generated scaffold. Replace with real implementation.\"\"\"\n"
                "    args = args or {}\n"
                "    return {\n"
                f"        \"skill\": \"{skill_name}\",\n"
                "        \"status\": \"todo\",\n"
                "        \"message\": \"Scaffold created. Implement business logic.\",\n"
                "        \"args\": args,\n"
                "    }\n"
            )
            return {
                "name": skill_name,
                "description": desc,
                "code": code,
            }
        return {}

    @staticmethod
    def _extract_requested_skill_name(user_text: str) -> str:
        """Best-effort extraction of user-provided skill name."""
        text = (user_text or "").strip()
        if not text:
            return ""
        patterns = [
            r"(?:skill|funktion)\s+namens\s+[`\"']?([A-Za-z][A-Za-z0-9_-]{2,63})[`\"']?",
            r"(?:namens|named|called|name)\s+[`\"']?([A-Za-z][A-Za-z0-9_-]{2,63})[`\"']?",
        ]
        stopwords = {
            "skill", "funktion", "function", "neu", "neue", "new",
            "bitte", "einen", "eine", "einer", "den", "die", "das",
        }
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE | re.UNICODE)
            if not match:
                continue
            candidate = match.group(1).strip("`\"'.,:;!?()[]{} ").lower()
            candidate = candidate.replace("-", "_")
            candidate = re.sub(r"[^a-z0-9_]", "_", candidate)
            candidate = re.sub(r"_+", "_", candidate).strip("_")
            if len(candidate) >= 3 and candidate not in stopwords:
                return candidate
        return ""

    @staticmethod
    def _is_skill_creation_sensitive(thinking_plan: Dict[str, Any]) -> bool:
        raw = thinking_plan.get("suggested_tools", []) if isinstance(thinking_plan, dict) else []
        names: List[str] = []
        for item in raw or []:
            if isinstance(item, dict):
                names.append(str(item.get("tool") or item.get("name") or "").strip())
            else:
                names.append(str(item).strip())
        names = [n for n in names if n]
        sensitive = {"create_skill", "autonomous_skill_task"}
        return any(n in sensitive for n in names)

    async def decide_tools(self, user_text: str, verified_plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Deterministic tool decision fallback used by orchestrator.

        Returns:
            [{"name": <tool_name>, "arguments": {...}}, ...]
        """
        _ = user_text  # reserved for future model-based argument filling

        candidates = self._normalize_suggested_tools(verified_plan)
        if not candidates:
            return []

        decided: List[Dict[str, Any]] = []
        seen = set()

        for item in candidates:
            name = item.get("name", "")
            if not name or name in seen:
                continue
            if not self._is_tool_available(name):
                log_info(f"[ControlLayer] decide_tools filtered unavailable tool: {name}")
                continue
            args = item.get("arguments", {}) if isinstance(item.get("arguments"), dict) else {}
            if not args:
                args = self._cim_tool_args(verified_plan, name, user_text=user_text)
            # Hardening: analyze requires query; never emit empty args.
            if name == "analyze" and not str(args.get("query", "")).strip():
                args["query"] = (user_text or "").strip()
            # Hardening: think requires message; avoid no-op tool skips.
            if name == "think" and not str(args.get("message", "")).strip():
                args["message"] = (user_text or "").strip()
            decided.append({"name": name, "arguments": args})
            seen.add(name)

        if decided:
            names = [d["name"] for d in decided]
            log_info(f"[ControlLayer] decide_tools={names}")
        return decided
    
    async def verify(self, user_text: str, thinking_plan: Dict[str, Any], retrieved_memory: str = "") -> Dict[str, Any]:
        sequential_result = thinking_plan.get("_sequential_result")
        # FIX: Removed - Bridge handles Sequential Thinking
        # if not sequential_result:
        # sequential_result = await self._check_sequential_thinking(user_text, thinking_plan)
        if sequential_result:
            log_info(f"[ControlLayer] Sequential completed with {len(sequential_result.get('steps', []))} steps")
            thinking_plan["_sequential_result"] = sequential_result
        
        # ═══════════════════════════════════════════════════════════
        # CIM POLICY ENGINE - Skill Creation Detection
        # ═══════════════════════════════════════════════════════════
        log_info(f"[ControlLayer-DEBUG] CIM_POLICY_AVAILABLE={CIM_POLICY_AVAILABLE}")
        keyword_match = False
        cim_decision = None
        if CIM_POLICY_AVAILABLE:
            intent = thinking_plan.get("intent", "").lower()
            # Check für skill-creation Intents
            skill_keywords = ["skill", "erstelle", "create", "programmier", "bau", "neu"]
            keyword_match = any(kw in intent or kw in user_text.lower() for kw in skill_keywords)
            log_info(f"[ControlLayer-DEBUG] intent='{intent}', keyword_match={keyword_match}")
            if keyword_match:
                try:
                    available_skills = self._get_available_skills()
                    log_info(f"[ControlLayer-DEBUG] available_skills={available_skills[:5] if available_skills else []}")
                    cim_decision = process_cim_policy(user_text, available_skills)
                    log_info(f"[ControlLayer-DEBUG] cim_decision.matched={cim_decision.matched}, requires_confirmation={cim_decision.requires_confirmation}")

                    if cim_decision.matched:
                        log_info(f"[ControlLayer-CIM] Decision: {cim_decision.action.value} for '{cim_decision.skill_name}'")
                        
                        # Read-only Aktionen direkt durchlassen
                        safe_actions = ["list_skills", "get_skill_info", "list_draft_skills"]
                        if cim_decision.action.value in safe_actions:
                            log_info(f"[ControlLayer-CIM] Safe read-only action: {cim_decision.action.value}")
                            return {
                                "approved": True,
                                "corrections": {},
                                "warnings": [],
                                "final_instruction": f"Execute {cim_decision.action.value}",
                                "_cim_decision": {
                                    "action": cim_decision.action.value,
                                    "skill_name": cim_decision.skill_name,
                                },
                                "suggested_tools": [cim_decision.action.value],
                            }
                        
                        if cim_decision.requires_confirmation:
                            log_info(f"[ControlLayer-CIM] Requires confirmation for skill '{cim_decision.skill_name}'")
                            return {
                                "approved": True,
                                "corrections": {},
                                "warnings": [],
                                "final_instruction": "Skill creation requires user confirmation",
                                "_cim_decision": {
                                    "action": cim_decision.action.value,
                                    "skill_name": cim_decision.skill_name,
                                    "pattern_id": cim_decision.policy_match.pattern_id if cim_decision.policy_match else None
                                },
                                "_needs_skill_confirmation": True,
                                "_skill_name": cim_decision.skill_name
                            }
                except Exception as e:
                    log_error(f"[ControlLayer-CIM] Error: {e}")

        # Safety fallback:
        # if creation intent/tool is present but CIM did not produce a confirm decision,
        # require explicit confirmation instead of allowing silent creation.
        if keyword_match and self._is_skill_creation_sensitive(thinking_plan):
            matched = bool(cim_decision and getattr(cim_decision, "matched", False))
            requires_confirmation = bool(cim_decision and getattr(cim_decision, "requires_confirmation", False))
            if not (matched and requires_confirmation):
                fallback_name = self._extract_requested_skill_name(user_text) or "pending_skill_creation"
                log_warning(
                    f"[ControlLayer-CIM] Fallback confirmation for skill creation "
                    f"(matched={matched}, requires_confirmation={requires_confirmation}, skill={fallback_name})"
                )
                return {
                    "approved": True,
                    "corrections": {},
                    "warnings": [],
                    "final_instruction": "Skill creation requires user confirmation (fallback)",
                    "_cim_decision": {
                        "action": "force_create_skill",
                        "skill_name": fallback_name,
                        "pattern_id": "fallback_skill_confirmation",
                    },
                    "_needs_skill_confirmation": True,
                    "_skill_name": fallback_name,
                }

        try:
            cim_result = self.light_cim.validate_basic(
                intent=thinking_plan.get("intent", ""),
                hallucination_risk=thinking_plan.get("hallucination_risk", "low"),
                user_text=user_text,
                thinking_plan=thinking_plan
            )
            log_info(f"[LightCIM] safe={cim_result['safe']}, confidence={cim_result['confidence']:.2f}")
            if not cim_result["safe"]:
                return {"approved": False, "corrections": {}, "warnings": cim_result["warnings"],
                        "final_instruction": "Request blocked", "_light_cim": cim_result}
        except Exception as e:
            log_error(f"[LightCIM] Error: {e}")
        payload = self._build_control_prompt_payload(user_text, thinking_plan, retrieved_memory)
        prompt = f"""{CONTROL_PROMPT}

CONTROL_INPUT:
{json.dumps(payload, ensure_ascii=False)}

Deine Bewertung (nur JSON):"""
        log_info(
            "[ControlLayer] verify_prompt "
            f"chars={len(prompt)} "
            f"user_chars={len(payload.get('user_request', ''))} "
            f"plan_chars={len(payload.get('thinking_plan_compact', ''))} "
            f"memory_chars={len(payload.get('memory_excerpt', ''))}"
        )

        try:
            route = resolve_role_endpoint("control", default_endpoint=self.ollama_base)
            log_info(
                f"[Routing] role=control requested_target={route['requested_target']} "
                f"effective_target={route['effective_target'] or 'none'} "
                f"fallback={bool(route['fallback_reason'])} "
                f"fallback_reason={route['fallback_reason'] or 'none'} "
                f"endpoint_source={route['endpoint_source']}"
            )
            if route["hard_error"]:
                log_error(
                    f"[Routing] role=control hard_error=true code={route['error_code']} "
                    f"requested_target={route['requested_target']}"
                )
                return self._default_verification(thinking_plan)
            endpoint = route["endpoint"] or self.ollama_base

            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(f"{endpoint}/api/generate",
                    json={"model": self._resolve_model(), "prompt": prompt, "stream": False,
            "keep_alive": "2m", "format": "json"})
                r.raise_for_status()
            data = r.json()
            content = data.get("response", "").strip() or data.get("thinking", "").strip()
            if not content:
                return self._default_verification(thinking_plan)
            return safe_parse_json(content, default=self._default_verification(thinking_plan), context="ControlLayer")
        except (httpx.TimeoutException, asyncio.TimeoutError) as e:
            msg = (
                "Control verification timeout (504): "
                f"model={self._resolve_model()} endpoint={endpoint if 'endpoint' in locals() else self.ollama_base}"
            )
            log_error(f"[ControlLayer] {msg} err={type(e).__name__}")
            fallback = self._default_verification(thinking_plan)
            warnings = list(fallback.get("warnings", []))
            warnings.append(msg)
            fallback["warnings"] = warnings
            fallback["_error"] = {"code": 504, "type": "control_timeout", "message": msg}
            return fallback
        except Exception as e:
            msg = f"Control verification error: {type(e).__name__}: {e}"
            log_error(f"[ControlLayer] {msg}")
            fallback = self._default_verification(thinking_plan)
            warnings = list(fallback.get("warnings", []))
            warnings.append(msg)
            fallback["warnings"] = warnings
            fallback["_error"] = {"code": 500, "type": "control_error", "message": msg}
            return fallback
    
    async def _check_sequential_thinking(self, user_text: str, thinking_plan: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not thinking_plan.get("needs_sequential_thinking", False):
            return None
        if not self.mcp_hub:
            log_error("[ControlLayer] MCP Hub not connected!")
            return None
        complexity = thinking_plan.get("sequential_complexity", 5)
        log_info(f"[ControlLayer] Triggering Sequential (complexity={complexity})")
        try:
            # Offload synchronous MCP call so orchestrator-level timeouts can cancel cleanly.
            result = await asyncio.to_thread(
                self.mcp_hub.call_tool,
                "think",
                {"message": user_text, "steps": complexity},
            )
            if isinstance(result, dict) and "error" in result:
                log_error(f"[ControlLayer] Sequential failed: {result['error']}")
                return None
            task_id = self.registry.create_task(user_text, complexity)
            self.registry.update_status(task_id, "running")
            self.registry.set_result(task_id, result)
            return result
        except Exception as e:
            log_error(f"[ControlLayer] Sequential failed: {e}")
            return None

    async def _get_cim_context(self, user_text: str, mode: str = None) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                init = await client.post(f"{CIM_URL}/mcp", json={
                    "jsonrpc": "2.0", "id": 0, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "control-layer", "version": "4.0.0"}}
                }, headers={"Content-Type": "application/json"})
                session_id = init.headers.get("mcp-session-id")
                if not session_id:
                    return None
                resp = await client.post(f"{CIM_URL}/mcp", json={
                    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "analyze", "arguments": {"query": user_text, "mode": mode}}
                }, headers={"Content-Type": "application/json", "mcp-session-id": session_id})
                if resp.status_code == 200:
                    for line in resp.text.split("\n"):
                        if line.startswith("data: "):
                            data = json.loads(line[6:])
                            if "result" in data:
                                content = data["result"].get("content", [])
                                if content:
                                    result = json.loads(content[0].get("text", "{}"))
                                    return result.get("causal_prompt", "")
        except Exception as e:
            log_debug(f"[CIM] Not available: {e}")
        return None

    async def _check_sequential_thinking_stream(
        self, 
        user_text: str, 
        thinking_plan: Dict[str, Any]
    ):
        """
        Sequential Thinking v5.0 - TRUE LIVE STREAMING
        
        Two-Phase Approach:
        - Phase 1: Stream 'thinking' field live to UI (DeepSeek's internal reasoning)
        - Phase 2: Parse 'content' field for steps when complete
        """
        import uuid
        import re
        
        needs_sequential = thinking_plan.get("needs_sequential_thinking", False)
        
        if not needs_sequential:
            log_debug("[ControlLayer] Sequential Thinking not needed")
            return
        
        task_id = f"seq-{str(uuid.uuid4())[:8]}"
        complexity = thinking_plan.get("sequential_complexity", 5)
        cim_modes = thinking_plan.get("suggested_cim_modes", [])
        reasoning_type = thinking_plan.get("reasoning_type", "direct")
        
        log_info(f"[ControlLayer] Sequential v5.0 LIVE STREAM (complexity={complexity}, id={task_id})")
        
        # Event: Start
        yield {
            "type": "sequential_start",
            "task_id": task_id,
            "complexity": complexity,
            "cim_modes": cim_modes,
            "reasoning_type": reasoning_type
        }
        
        try:
            # ============================================================
            # PHASE 0: CIM Context (optional)
            # ============================================================
            causal_context = ""
            if self.mcp_hub:
                try:
                    cim_result = self.mcp_hub.call_tool("analyze", {"query": user_text})
                    if cim_result and cim_result.get("success"):
                        causal_context = cim_result.get("causal_prompt", "")
                except Exception as e:
                    log_debug(f"[ControlLayer] CIM skipped: {e}")
            
            # ============================================================
            # Build System Prompt
            # ============================================================
            system_prompt = f"""You are a step-by-step reasoner analyzing complex queries.

CRITICAL OUTPUT FORMAT - FOLLOW EXACTLY:
1. Start EVERY step with "## Step N:" on its OWN LINE
2. Follow with a SHORT title on the SAME LINE  
3. Then your detailed analysis on the NEXT lines
4. Leave a BLANK LINE before the next step

EXAMPLE FORMAT:
## Step 1: Identify the Core Question
Here I analyze what the fundamental question is asking...

## Step 2: Gather Relevant Information
Now I consider what information is needed...

## Step 3: Apply Reasoning
Based on the above, I conclude that...

You MUST provide exactly {complexity} steps.
START YOUR ANALYSIS NOW with "## Step 1:"."""

            if causal_context:
                system_prompt += f"\n\nAdditional Context:\n{causal_context}"

            user_prompt = f"Analyze this query thoroughly:\n\n{user_text}"

            # ============================================================
            # PHASE 1 & 2: TRUE STREAMING with thinking + content
            # ============================================================
            log_info(f"[ControlLayer] Starting TRUE STREAMING to Ollama...")
            route = resolve_role_endpoint("thinking", default_endpoint=self.ollama_base)
            log_info(
                f"[Routing] role=thinking requested_target={route['requested_target']} "
                f"effective_target={route['effective_target'] or 'none'} "
                f"fallback={bool(route['fallback_reason'])} "
                f"fallback_reason={route['fallback_reason'] or 'none'} "
                f"endpoint_source={route['endpoint_source']}"
            )
            if route["hard_error"]:
                yield {
                    "type": "sequential_error",
                    "task_id": task_id,
                    "error": f"compute_unavailable:{route['requested_target']}",
                }
                return
            endpoint = route["endpoint"] or self.ollama_base
            
            content_buffer = ""
            thinking_buffer = ""
            last_thinking_yield = ""
            
            async with httpx.AsyncClient(timeout=180.0) as client:
                async with client.stream(
                    "POST",
                    f"{endpoint}/api/chat",
                    json={
                        "model": self._resolve_sequential_model(),
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "stream": True  # KEY: True streaming!
                    }
                ) as response:
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        
                        msg = chunk.get("message", {})
                        thinking = msg.get("thinking", "")
                        content = msg.get("content", "")
                        done = chunk.get("done", False)
                        
                        # ========================================
                        # PHASE 1: Stream thinking LIVE
                        # ========================================
                        if thinking and thinking != last_thinking_yield:
                            thinking_buffer += thinking
                            last_thinking_yield = thinking
                            
                            yield {
                                "type": "seq_thinking_stream",
                                "task_id": task_id,
                                "chunk": thinking,
                                "total_length": len(thinking_buffer)
                            }
                        
                        # ========================================
                        # PHASE 2: Accumulate content
                        # ========================================
                        if content:
                            content_buffer += content
                        
                        # Check if done
                        if done:
                            log_info(f"[ControlLayer] Stream complete. Thinking: {len(thinking_buffer)} chars, Content: {len(content_buffer)} chars")
                            break
            
            # ============================================================
            # PHASE 3: Parse Steps from content_buffer
            # ============================================================
            log_info(f"[ControlLayer] Parsing steps from content...")
            
            # Signal end of thinking phase
            if thinking_buffer:
                yield {
                    "type": "seq_thinking_done",
                    "task_id": task_id,
                    "total_length": len(thinking_buffer)
                }
            
            all_steps = []
            
            # Try multiple patterns
            patterns = [
                r'## Step (\d+):\s*([^\n]*)\n(.*?)(?=## Step \d+:|$)',
                r'\*\*Step (\d+)\*\*[:\s]*([^\n]*)\n(.*?)(?=\*\*Step \d+|$)',
                r'(?:^|\n)Step (\d+):\s*([^\n]*)\n(.*?)(?=Step \d+:|$)',
            ]
            
            matches = []
            for pattern in patterns:
                matches = list(re.finditer(pattern, content_buffer, re.DOTALL | re.IGNORECASE))
                if matches:
                    log_info(f"[ControlLayer] Matched {len(matches)} steps")
                    break
            
            if not matches:
                log_warning(f"[ControlLayer] No steps found in content! Length: {len(content_buffer)}")
                if content_buffer.strip():
                    yield {
                        "type": "sequential_step",
                        "task_id": task_id,
                        "step_number": 1,
                        "title": "Analysis",
                        "thought": content_buffer,
                        "status": "complete"
                    }
                    all_steps.append({"step": 1, "title": "Analysis", "thought": content_buffer})
            else:
                # Yield each step with delay for visual effect
                for match in matches:
                    step_num = int(match.group(1))
                    step_title = match.group(2).strip()
                    step_content = match.group(3).strip()
                    
                    log_info(f"[ControlLayer] YIELD Step {step_num}: {step_title[:40]}...")
                    
                    step_data = {
                        "step": step_num,
                        "title": step_title,
                        "thought": step_content
                    }
                    all_steps.append(step_data)
                    
                    yield {
                        "type": "sequential_step",
                        "task_id": task_id,
                        "step_number": step_num,
                        "title": step_title,
                        "thought": step_content,
                        "status": "complete"
                    }
                    
                    # Small delay between steps
                    await asyncio.sleep(0.3)
            
            # Registry Update
            registry_task_id = self.registry.create_task(user_text, complexity)
            self.registry.update_status(registry_task_id, "completed")
            self.registry.set_result(registry_task_id, {"steps": all_steps})
            
            log_info(f"[ControlLayer] Sequential v5.0 {task_id} done: {len(all_steps)} steps")
            
            # Event: Done
            yield {
                "type": "sequential_done",
                "task_id": task_id,
                "steps": all_steps,
                "thinking_length": len(thinking_buffer),
                "summary": f"{len(all_steps)} steps completed"
            }
            
            thinking_plan["_sequential_result"] = {"steps": all_steps}
            
        except Exception as e:
            log_error(f"[ControlLayer] Sequential failed: {e}")
            import traceback
            log_error(traceback.format_exc())
            yield {
                "type": "sequential_error",
                "task_id": task_id,
                "error": str(e)
            }
    def _default_verification(self, thinking_plan: Dict[str, Any]) -> Dict[str, Any]:
        return {"approved": True, "corrections": {"needs_memory": None, "memory_keys": None,
                "hallucination_risk": None, "new_fact_key": None, "new_fact_value": None},
                "warnings": ["Control-Layer Fallback"], "final_instruction": "Beantworte vorsichtig."}
    
    def apply_corrections(self, thinking_plan: Dict[str, Any], verification: Dict[str, Any]) -> Dict[str, Any]:
        corrected = thinking_plan.copy()
        for k, v in verification.get("corrections", {}).items():
            if v is not None:
                corrected[k] = v
        corrected["_verified"] = True
        corrected["_final_instruction"] = verification.get("final_instruction", "")
        corrected["_warnings"] = verification.get("warnings", [])
        # Merge suggested_tools from CIM decision
        if verification.get("suggested_tools"):
            existing = corrected.get("suggested_tools", [])
            corrected["suggested_tools"] = list(set(existing + verification["suggested_tools"]))
        # Merge CIM decision metadata
        if verification.get("_cim_decision"):
            corrected["_cim_decision"] = verification["_cim_decision"]
        return corrected
