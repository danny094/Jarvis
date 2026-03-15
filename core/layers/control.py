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
    get_control_model_deep,
    get_control_provider,
    get_control_timeout_interactive_s,
    get_control_timeout_deep_s,
    get_control_endpoint_override,
    get_thinking_model,
    get_control_prompt_memory_chars,
    get_control_prompt_plan_chars,
    get_control_prompt_user_chars,
    get_memory_keys_max_per_request,
)
from utils.logger import log_info, log_error, log_debug, log_warning
from utils.json_parser import safe_parse_json
from utils.role_endpoint_resolver import resolve_role_endpoint, resolve_ollama_base_endpoint
from core.llm_provider_client import complete_prompt, resolve_role_provider, stream_chat
from core.control_decision_utils import (
    DEFAULT_HARD_BLOCK_REASON_CODES,
    is_allowed_hard_block_reason_code,
    make_hard_block_verification,
    normalize_block_reason_code,
)
from core.control_policy_utils import (
    has_hard_safety_markers,
    is_cron_tool_name,
    is_light_cim_hard_denial,
    is_runtime_operation_tool,
    looks_like_capability_mismatch,
    looks_like_spurious_policy_block,
    sanitize_warning_messages,
    user_text_has_explicit_skill_intent,
    verification_text,
    warning_list,
)
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
    "decision_class": "allow/warn/hard_block",
    "hard_block": true/false,
    "block_reason_code": "malicious_intent/pii/critical_cim/hardware_self_protection/...",
    "corrections": {
        "needs_memory": null oder true/false,
        "memory_keys": null oder ["korrigierte", "keys"],
        "hallucination_risk": null oder "low/medium/high",
        "new_fact_key": null oder "korrigierter_key",
        "new_fact_value": null oder "korrigierter_value",
        "suggested_response_style": null oder "kurz/ausführlich/freundlich",
        "dialogue_act": null oder "ack/feedback/question/request/analysis/smalltalk",
        "response_tone": null oder "mirror_user/warm/neutral/formal",
        "response_length_hint": null oder "short/medium/long",
        "tone_confidence": null oder 0.0
    },
    "warnings": ["Liste von Warnungen falls vorhanden"],
    "final_instruction": "Klare Anweisung für den Output-Layer"
}

ENTSCHEIDUNGSREGELN:
- approved=false NUR bei harten Safety-/Policy-Verstößen (PII, gefährliche Inhalte, echte Regelverletzung).
- Reine Logikwarnungen (z. B. "Needs memory but no keys specified") sind SOFT-WARNUNGEN.
  Sie gehören in warnings, aber blockieren nicht automatisch.
- Wenn tool_availability verfügbare Runtime-Tools zeigt, blockiere NICHT wegen erfundener Tool-Unverfügbarkeit.
- Bei Container/Skill/Cron Runtime-Requests pragmatisch entscheiden: Aktion freigeben, sofern kein harter Safety-Verstoß vorliegt.
- Für Host/IP/Server-Lookups sind fehlende memory_keys alleine kein Blockgrund.
- Wenn approved=false: setze decision_class="hard_block", hard_block=true und einen präzisen block_reason_code.
- Wenn KEIN harter Verstoß vorliegt: approved=true, decision_class="warn" (falls Warnungen), hard_block=false.

BLUEPRINT-GATE-REGEL (wichtig):
- Wenn der Plan blueprint_gate_blocked=true enthält: Dies ist ein ROUTING-SIGNAL, KEIN Safety-Block.
  Das System hat keinen passenden Blueprint gefunden und bietet Alternativen an (z.B. blueprint_list in suggested_tools).
  Setze approved=true, decision_class="warn", hard_block=false.
  final_instruction: "Zeige dem User die verfügbaren Blueprints (via blueprint_list), damit er den richtigen auswählen oder einen neuen erstellen kann. Führe request_container NICHT aus."
  Begründe NICHT mit 'Blueprint nicht gefunden' als Blockgrund — das ist kein Safety-Verstoß.
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

    def _resolve_model(self, response_mode: str = "interactive") -> str:
        if self._model_override:
            return self._model_override
        mode = str(response_mode or "").strip().lower()
        if mode == "deep":
            return get_control_model_deep()
        return get_control_model()

    @staticmethod
    def _normalize_response_mode(response_mode: str) -> str:
        return "deep" if str(response_mode or "").strip().lower() == "deep" else "interactive"

    def _resolve_verify_timeout_s(self, response_mode: str = "interactive") -> float:
        mode = self._normalize_response_mode(response_mode)
        if mode == "deep":
            timeout_s = float(get_control_timeout_deep_s())
        else:
            timeout_s = float(get_control_timeout_interactive_s())
        return max(5.0, min(600.0, timeout_s))

    def _resolve_control_endpoint_override(self, response_mode: str = "interactive") -> str:
        override = str(get_control_endpoint_override(response_mode=response_mode) or "").strip()
        if not override:
            return ""
        return resolve_ollama_base_endpoint(default_endpoint=override)

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
            "suggested_response_style": (thinking_plan or {}).get("suggested_response_style"),
            "dialogue_act": (thinking_plan or {}).get("dialogue_act"),
            "response_tone": (thinking_plan or {}).get("response_tone"),
            "response_length_hint": (thinking_plan or {}).get("response_length_hint"),
            "tone_confidence": (thinking_plan or {}).get("tone_confidence"),
            "time_reference": (thinking_plan or {}).get("time_reference"),
            "needs_sequential_thinking": bool(
                (thinking_plan or {}).get("needs_sequential_thinking")
                or (thinking_plan or {}).get("sequential_thinking_required")
            ),
            "sequential_complexity": (thinking_plan or {}).get("sequential_complexity", 0),
        }
        plan_payload["tool_availability"] = self._tool_availability_snapshot(
            plan_payload.get("suggested_tools", [])
        )
        route = (thinking_plan or {}).get("_domain_route", {})
        if isinstance(route, dict) and route:
            plan_payload["domain_route"] = {
                "domain_tag": str(route.get("domain_tag") or "").strip().upper(),
                "domain_locked": bool(route.get("domain_locked")),
                "operation": str(route.get("operation") or "").strip().lower(),
            }
        if (thinking_plan or {}).get("_policy_conflict_reason"):
            plan_payload["policy_conflict_reason"] = str(
                (thinking_plan or {}).get("_policy_conflict_reason", "")
            )[:200]
        if (thinking_plan or {}).get("_sequential_deferred"):
            plan_payload["sequential_deferred"] = True
            plan_payload["sequential_deferred_reason"] = str(
                (thinking_plan or {}).get("_sequential_deferred_reason", "")
            )[:120]
        if (thinking_plan or {}).get("_skill_gate_blocked"):
            plan_payload["skill_gate_blocked"] = True
            plan_payload["skill_gate_reason"] = (thinking_plan or {}).get("_skill_gate_reason", "")
        if (thinking_plan or {}).get("_blueprint_gate_blocked"):
            plan_payload["blueprint_gate_blocked"] = True
            plan_payload["blueprint_gate_reason"] = (thinking_plan or {}).get("_blueprint_gate_reason", "")
        if bool((thinking_plan or {}).get("_hardware_gate_triggered")):
            plan_payload["hardware_gate_triggered"] = True
            plan_payload["hardware_gate_warning"] = str(
                (thinking_plan or {}).get("_hardware_gate_warning") or ""
            )[:240]

        # Ensure plan payload stays compact even if optional fields grow.
        plan_json = json.dumps(plan_payload, ensure_ascii=False)
        if len(plan_json) > plan_limit:
            plan_payload = {
                "intent": plan_payload["intent"],
                "hallucination_risk": plan_payload["hallucination_risk"],
                "needs_memory": plan_payload["needs_memory"],
                "memory_keys": plan_payload["memory_keys"][:2],
                "suggested_tools": plan_payload["suggested_tools"][:4],
                "tool_availability": plan_payload.get("tool_availability", {}),
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

    def _tool_availability_snapshot(self, suggested_tools: List[Any]) -> Dict[str, List[str]]:
        names = self._tool_names(suggested_tools, limit=10)
        available: List[str] = []
        unavailable: List[str] = []
        for name in names:
            if self._is_tool_available(name):
                available.append(name)
            else:
                unavailable.append(name)
        return {"available": available, "unavailable": unavailable}

    @staticmethod
    def _verification_text(verification: Dict[str, Any]) -> str:
        return verification_text(verification)

    @classmethod
    def _looks_like_capability_mismatch(cls, verification: Dict[str, Any]) -> bool:
        return looks_like_capability_mismatch(verification)

    @staticmethod
    def _is_cron_tool_name(tool_name: str) -> bool:
        return is_cron_tool_name(tool_name)

    @classmethod
    def _looks_like_spurious_policy_block(cls, verification: Dict[str, Any]) -> bool:
        return looks_like_spurious_policy_block(verification)

    @classmethod
    def _has_hard_safety_markers(cls, verification: Dict[str, Any]) -> bool:
        return has_hard_safety_markers(verification)

    @staticmethod
    def _warning_list(raw: Any) -> List[str]:
        return warning_list(raw)

    @classmethod
    def _is_light_cim_hard_denial(cls, cim_result: Dict[str, Any]) -> bool:
        return is_light_cim_hard_denial(cim_result)

    def _has_cron_context(
        self,
        verification: Dict[str, Any],
        thinking_plan: Dict[str, Any],
    ) -> bool:
        route = (thinking_plan or {}).get("_domain_route", {}) if isinstance(thinking_plan, dict) else {}
        domain_tag = str((route or {}).get("domain_tag") or "").strip().upper()
        if domain_tag == "CRONJOB":
            return True

        suggested_plan = self._tool_names((thinking_plan or {}).get("suggested_tools", []), limit=12)
        suggested_verify = self._tool_names((verification or {}).get("suggested_tools", []), limit=12)
        combined = suggested_plan + [name for name in suggested_verify if name not in suggested_plan]
        if any(self._is_cron_tool_name(name) for name in combined):
            return True

        intent = str((thinking_plan or {}).get("intent") or "").strip().lower()
        return any(token in intent for token in ("cron", "cronjob", "schedule", "zeitplan"))

    def _should_lift_cron_false_block(
        self,
        verification: Dict[str, Any],
        thinking_plan: Dict[str, Any],
    ) -> bool:
        if self._has_hard_safety_markers(verification):
            return False
        if not self._has_cron_context(verification, thinking_plan):
            return False

        route = (thinking_plan or {}).get("_domain_route", {}) if isinstance(thinking_plan, dict) else {}
        domain_tag = str((route or {}).get("domain_tag") or "").strip().upper()
        domain_locked = bool((route or {}).get("domain_locked"))
        if domain_locked and domain_tag == "CRONJOB":
            return True

        return self._looks_like_capability_mismatch(verification) or self._looks_like_spurious_policy_block(verification)

    def _has_container_context(
        self,
        verification: Dict[str, Any],
        thinking_plan: Dict[str, Any],
    ) -> bool:
        route = (thinking_plan or {}).get("_domain_route", {}) if isinstance(thinking_plan, dict) else {}
        domain_tag = str((route or {}).get("domain_tag") or "").strip().upper()
        if domain_tag == "CONTAINER":
            return True

        suggested_plan = self._tool_names((thinking_plan or {}).get("suggested_tools", []), limit=12)
        suggested_verify = self._tool_names((verification or {}).get("suggested_tools", []), limit=12)
        combined = suggested_plan + [name for name in suggested_verify if name not in suggested_plan]
        container_tools = {
            "request_container",
            "stop_container",
            "exec_in_container",
            "container_logs",
            "container_stats",
            "container_list",
            "container_inspect",
            "blueprint_list",
            "blueprint_get",
            "blueprint_create",
        }
        if any(str(name or "").strip().lower() in container_tools for name in combined):
            return True

        intent = str((thinking_plan or {}).get("intent") or "").strip().lower()
        return any(token in intent for token in ("container", "docker", "blueprint", "host server", "ip"))

    def _should_lift_container_false_block(
        self,
        verification: Dict[str, Any],
        thinking_plan: Dict[str, Any],
    ) -> bool:
        if self._has_hard_safety_markers(verification):
            return False
        if not self._has_container_context(verification, thinking_plan):
            return False

        route = (thinking_plan or {}).get("_domain_route", {}) if isinstance(thinking_plan, dict) else {}
        domain_tag = str((route or {}).get("domain_tag") or "").strip().upper()
        domain_locked = bool((route or {}).get("domain_locked"))
        if domain_locked and domain_tag == "CONTAINER":
            return True

        text = self._verification_text(verification)
        if "needs memory but no keys specified" in text:
            return True
        return self._looks_like_capability_mismatch(verification) or self._looks_like_spurious_policy_block(verification)

    def _combined_suggested_tools(
        self,
        verification: Dict[str, Any],
        thinking_plan: Dict[str, Any],
        *,
        limit: int = 16,
    ) -> List[str]:
        from_plan = self._tool_names((thinking_plan or {}).get("suggested_tools", []), limit=limit)
        from_verify = self._tool_names((verification or {}).get("suggested_tools", []), limit=limit)
        combined: List[str] = list(from_plan)
        for name in from_verify:
            if name not in combined:
                combined.append(name)
            if len(combined) >= limit:
                break
        return combined

    @staticmethod
    def _is_runtime_operation_tool(tool_name: str) -> bool:
        return is_runtime_operation_tool(tool_name)

    def _has_solution_oriented_action_signal(
        self,
        verification: Dict[str, Any],
        thinking_plan: Dict[str, Any],
        *,
        user_text: str = "",
    ) -> bool:
        route = (thinking_plan or {}).get("_domain_route", {}) if isinstance(thinking_plan, dict) else {}
        domain_tag = str((route or {}).get("domain_tag") or "").strip().upper()
        domain_locked = bool((route or {}).get("domain_locked"))
        if domain_locked and domain_tag in {"CONTAINER", "CRONJOB", "SKILL"}:
            return True

        combined_tools = self._combined_suggested_tools(verification, thinking_plan)
        if any(self._is_runtime_operation_tool(name) for name in combined_tools):
            return True

        merged_text = " ".join(
            part
            for part in (
                str((thinking_plan or {}).get("intent") or "").strip(),
                str(user_text or "").strip(),
            )
            if part
        ).lower()
        if not merged_text:
            return False
        has_domain = bool(
            re.search(
                r"\b(container|docker|blueprint|cron|cronjob|schedule|zeitplan|skill|server|host|ip|runtime|tool|mcp)\b",
                merged_text,
            )
        )
        has_action = bool(
            re.search(
                r"\b(create|erstell\w*|start\w*|run\b|führe?\w*|fuehr\w*|execute|deploy|stop\w*|delete\w*|lösch\w*|loesch\w*|check\w*|prüf\w*|pruef\w*|find\w*|ermittel\w*|list\w*|status|logs?|inspect|update|pause|resume)\b",
                merged_text,
            )
        )
        return has_domain and has_action

    def _should_lift_solution_oriented_false_block(
        self,
        verification: Dict[str, Any],
        thinking_plan: Dict[str, Any],
        *,
        user_text: str = "",
    ) -> bool:
        if self._has_hard_safety_markers(verification):
            return False
        if self._user_text_has_hard_safety_keywords(user_text):
            return False
        if self._user_text_has_malicious_intent(user_text):
            return False

        text = self._verification_text(verification)
        has_spurious_signal = (
            self._looks_like_capability_mismatch(verification)
            or self._looks_like_spurious_policy_block(verification)
            or "needs memory but no keys specified" in text
        )
        if not has_spurious_signal:
            return False
        if not self._has_solution_oriented_action_signal(
            verification,
            thinking_plan,
            user_text=user_text,
        ):
            return False

        route = (thinking_plan or {}).get("_domain_route", {}) if isinstance(thinking_plan, dict) else {}
        domain_tag = str((route or {}).get("domain_tag") or "").strip().upper()
        domain_locked = bool((route or {}).get("domain_locked"))
        if domain_locked and domain_tag in {"CONTAINER", "CRONJOB", "SKILL"}:
            return True

        combined_tools = self._combined_suggested_tools(verification, thinking_plan)
        if not combined_tools:
            return False
        available = [name for name in combined_tools if self._is_tool_available(name)]
        return bool(available)

    def _user_text_has_hard_safety_keywords(self, user_text: str) -> bool:
        text = str(user_text or "").strip().lower()
        if not text:
            return False
        destructive_shell_patterns = (
            r"\brm\s+-rf\s+/\b",
            r"\bsudo\s+rm\s+-rf\b",
            r"\bmkfs\.[a-z0-9]+\b",
            r"\b(?:del|erase)\s+[/\-][a-z]+\b",
            r"\bformat\s+[a-z]:\b",
        )
        for pattern in destructive_shell_patterns:
            try:
                if re.search(pattern, text):
                    return True
            except re.error:
                continue
        high_risk_markers = (
            "virus",
            "malware",
            "trojan",
            "ransomware",
            "keylogger",
            "botnet",
            "credential theft",
            "passwort ausliest",
            "passwörter ausliest",
            "passwoerter ausliest",
            "passwords ausliest",
            "delete all files",
            "alle dateien loesch",
            "alle dateien lösch",
        )
        if any(marker in text for marker in high_risk_markers):
            return True
        try:
            keywords = list(getattr(self.light_cim, "danger_keywords", []) or []) + list(
                getattr(self.light_cim, "sensitive_keywords", []) or []
            )
            for kw in keywords:
                if self.light_cim._contains_keyword(text, str(kw or "")):
                    return True
        except Exception:
            # Fail-closed for this override path.
            return True
        return False

    def _user_text_has_malicious_intent(self, user_text: str) -> bool:
        text = str(user_text or "").strip().lower()
        if not text:
            return False
        direct_patterns = (
            r"rm\s+-rf\s+/",
            r"\bsudo\s+rm\s+-rf\b",
            r"\b(?:hacke|hacken|hack|exploit|crack)\b",
            r"\b(?:virus|malware|trojan|ransomware|keylogger|botnet)\b",
            r"\b(?:alle\s+dateien\s+(?:lösch\w*|loesch\w*|delete\w*)|delete\s+all\s+files)\b",
        )
        for pattern in direct_patterns:
            try:
                if re.search(pattern, text):
                    return True
            except re.error:
                continue
        if re.search(r"\b(?:passw(?:ort|oerter|örter)|passwords?)\b", text) and re.search(
            r"\b(?:ausles\w*|auslies\w*|stehl\w*|exfiltrat\w*|klau\w*)\b",
            text,
        ):
            return True
        return False

    @staticmethod
    def _user_text_has_explicit_skill_intent(user_text: str) -> bool:
        return user_text_has_explicit_skill_intent(user_text)

    def _should_lift_query_budget_fast_path_false_block(
        self,
        verification: Dict[str, Any],
        thinking_plan: Dict[str, Any],
        user_text: str = "",
    ) -> bool:
        if self._has_hard_safety_markers(verification):
            return False
        if self._user_text_has_hard_safety_keywords(user_text):
            return False
        text = self._verification_text(verification)
        benign_false_block_markers = (
            "keine notwendigkeit für tool",
            "keine notwendigkeit fuer tool",
            "direkte berechnung möglich",
            "direkte berechnung moeglich",
            "irrelevant für",
            "irrelevant fuer",
            "falsche intent-klassifizierung",
            "rechnerische_operation",
            "container-hinweis irrelevant",
            "container hinweis irrelevant",
            "no tool required",
            "direct calculation",
        )
        looks_like_spurious_block = self._looks_like_spurious_policy_block(verification) or any(
            marker in text for marker in benign_false_block_markers
        )

        intent = str((thinking_plan or {}).get("intent") or "").strip().lower()
        query_budget_signal = (
            (thinking_plan or {}).get("_query_budget", {})
            if isinstance(thinking_plan, dict)
            else {}
        )
        query_budget_skip_candidate = bool(
            isinstance(query_budget_signal, dict)
            and query_budget_signal.get("skip_thinking_candidate")
        )
        if intent != "query_budget_fast_path" and not query_budget_skip_candidate:
            return False

        if self._has_cron_context(verification, thinking_plan):
            return False
        user_low = str(user_text or "").strip().lower()
        has_domain_or_tool_markers = bool(
            re.search(
                r"\b(cron|cronjob|schedule|zeitplan|container|blueprint|docker|skill|run_skill|create_skill|autonomous_skill_task|mcp)\b",
                user_low,
            )
        )
        has_execution_markers = bool(
            re.search(
                r"\b(erstell\w*|create|starte?\b|start\b|fuehr\w*|führe?\w*|execute|deploy|run\b|lösch\w*|loesch\w*|delete)\b",
                user_low,
            )
        )
        if has_domain_or_tool_markers or has_execution_markers:
            return False
        if self._user_text_has_malicious_intent(user_text):
            return False
        if len(user_low) < 3:
            return False
        if not looks_like_spurious_block:
            return True
        if re.search(r"\b\d+\s*(?:[\+\-\*/]|x|×)\s*\d+\b", str(user_text or "").lower()):
            return True
        return True

    @staticmethod
    def _sanitize_warning_messages(warnings: Any) -> List[str]:
        return sanitize_warning_messages(warnings)

    @classmethod
    def _infer_block_reason_code(
        cls,
        verification: Dict[str, Any],
        *,
        user_text: str = "",
        thinking_plan: Dict[str, Any],
    ) -> str:
        text = cls._verification_text(verification)
        if re.search(r"(dangerous keyword|malicious|policy guard|virus|malware|trojan|ransomware|keylogger|botnet)", text):
            return "malicious_intent"
        if re.search(r"(sensitive content|email address detected|phone number detected|pii|password|api key|token|credentials)", text):
            return "pii"
        if re.search(r"(critical|deny_autonomy|policy_check)", text):
            return "critical_cim"
        if bool((thinking_plan or {}).get("_hardware_gate_triggered")):
            return "hardware_self_protection"
        _ = user_text  # keep signature explicit for future guard extensions
        return ""

    def _enforce_block_authority(
        self,
        verification: Dict[str, Any],
        thinking_plan: Dict[str, Any],
        *,
        user_text: str = "",
    ) -> Dict[str, Any]:
        if not isinstance(verification, dict):
            return verification

        warnings = self._warning_list(verification.get("warnings", []))
        approved = verification.get("approved") is not False
        code = normalize_block_reason_code(verification.get("block_reason_code"))

        if approved:
            verification["approved"] = True
            verification["hard_block"] = False
            verification["block_reason_code"] = ""
            if str(verification.get("decision_class") or "").strip().lower() in {"", "hard_block"}:
                verification["decision_class"] = "warn" if warnings else "allow"
            return verification

        if not code:
            code = self._infer_block_reason_code(
                verification,
                user_text=user_text,
                thinking_plan=thinking_plan,
            )

        hard_block_allowed = (
            is_allowed_hard_block_reason_code(
                code,
                allowed_codes=DEFAULT_HARD_BLOCK_REASON_CODES,
            )
            or self._has_hard_safety_markers(verification)
            or self._user_text_has_hard_safety_keywords(user_text)
            or self._user_text_has_malicious_intent(user_text)
        )

        if not hard_block_allowed:
            warnings.append(
                "Deterministic override: non-authoritative soft block converted to warning (Control-only hard-block policy)."
            )
            verification["approved"] = True
            verification["hard_block"] = False
            verification["decision_class"] = "warn"
            verification["block_reason_code"] = ""
            verification["reason"] = "soft_block_auto_corrected"
            verification["warnings"] = warnings
            return verification

        verification["approved"] = False
        verification["hard_block"] = True
        verification["decision_class"] = "hard_block"
        verification["block_reason_code"] = code or "critical_cim"
        if not str(verification.get("reason") or "").strip():
            verification["reason"] = verification["block_reason_code"]
        verification["warnings"] = warnings
        return verification

    def _stabilize_verification_result(
        self,
        verification: Dict[str, Any],
        thinking_plan: Dict[str, Any],
        user_text: str = "",
    ) -> Dict[str, Any]:
        if not isinstance(verification, dict):
            return self._default_verification(thinking_plan)

        # Keep explicit LightCIM denials untouched except normalized authority fields.
        if verification.get("_light_cim"):
            verification["warnings"] = self._sanitize_warning_messages(verification.get("warnings", []))
            return self._enforce_block_authority(
                verification,
                thinking_plan,
                user_text=user_text,
            )

        if verification.get("approved") is False:
            if (
                (
                    bool((thinking_plan or {}).get("_skill_gate_blocked"))
                    or bool((thinking_plan or {}).get("_blueprint_gate_blocked"))
                )
                and not self._has_hard_safety_markers(verification)
                and not self._user_text_has_hard_safety_keywords(user_text)
                and not self._user_text_has_malicious_intent(user_text)
            ):
                warnings = verification.get("warnings")
                if not isinstance(warnings, list):
                    warnings = [str(warnings)] if warnings else []
                warnings.append(
                    "Deterministic override: tool gate denial is treated as tool-level soft deny, not chat-level block."
                )
                verification["warnings"] = warnings
                verification["approved"] = True
                verification["reason"] = "tool_gate_soft_deny_auto_corrected"

            suggested = self._tool_names((thinking_plan or {}).get("suggested_tools", []), limit=8)
            if suggested:
                unavailable = [name for name in suggested if not self._is_tool_available(name)]
                if not unavailable and self._looks_like_capability_mismatch(verification):
                    warnings = verification.get("warnings")
                    if not isinstance(warnings, list):
                        warnings = [str(warnings)] if warnings else []
                    warnings.append(
                        "Deterministic override: suggested tools are runtime-available; "
                        "control capability mismatch block was lifted."
                    )
                    verification["warnings"] = warnings
                    verification["approved"] = True
                    verification["reason"] = "tool_availability_mismatch_auto_corrected"
                    log_warning(
                        "[ControlLayer] Auto-corrected false unavailable-tool block "
                        f"for suggested_tools={suggested}"
                    )
            if verification.get("approved") is False and self._should_lift_cron_false_block(verification, thinking_plan):
                warnings = verification.get("warnings")
                if not isinstance(warnings, list):
                    warnings = [str(warnings)] if warnings else []
                warnings.append(
                    "Deterministic override: cron-domain request with runtime-available cron tools "
                    "was blocked by a spurious policy response and has been unblocked."
                )
                verification["warnings"] = warnings
                verification["approved"] = True
                verification["reason"] = "cron_domain_false_block_auto_corrected"
                log_warning(
                    "[ControlLayer] Auto-corrected false cron-domain block "
                    f"for intent={str((thinking_plan or {}).get('intent') or '')[:120]}"
                )
            if (
                verification.get("approved") is False
                and self._should_lift_container_false_block(verification, thinking_plan)
            ):
                warnings = verification.get("warnings")
                if not isinstance(warnings, list):
                    warnings = [str(warnings)] if warnings else []
                warnings.append(
                    "Deterministic override: container-domain request was blocked by a spurious "
                    "policy/memory mismatch response and has been unblocked."
                )
                verification["warnings"] = warnings
                verification["approved"] = True
                verification["reason"] = "container_domain_false_block_auto_corrected"
                log_warning(
                    "[ControlLayer] Auto-corrected false container-domain block "
                    f"for intent={str((thinking_plan or {}).get('intent') or '')[:120]}"
                )
            if (
                verification.get("approved") is False
                and self._should_lift_query_budget_fast_path_false_block(
                    verification,
                    thinking_plan,
                    user_text=user_text,
                )
            ):
                warnings = verification.get("warnings")
                if not isinstance(warnings, list):
                    warnings = [str(warnings)] if warnings else []
                warnings.append(
                    "Deterministic override: benign query_budget_fast_path prompt "
                    "was blocked by a spurious policy response and has been unblocked."
                )
                verification["warnings"] = warnings
                verification["approved"] = True
                verification["reason"] = "query_budget_fast_path_false_block_auto_corrected"
                log_warning(
                    "[ControlLayer] Auto-corrected false query_budget_fast_path block "
                    f"for user_text={str(user_text or '')[:120]}"
                )
            if (
                verification.get("approved") is False
                and self._should_lift_solution_oriented_false_block(
                    verification,
                    thinking_plan,
                    user_text=user_text,
                )
            ):
                warnings = verification.get("warnings")
                if not isinstance(warnings, list):
                    warnings = [str(warnings)] if warnings else []
                warnings.append(
                    "Deterministic override: solution-oriented runtime/tool execution path exists; "
                    "spurious policy block was lifted."
                )
                verification["warnings"] = warnings
                verification["approved"] = True
                verification["reason"] = "solution_oriented_false_block_auto_corrected"
                log_warning(
                    "[ControlLayer] Auto-corrected spurious policy block via solution-oriented path "
                    f"for intent={str((thinking_plan or {}).get('intent') or '')[:120]}"
                )
        verification["warnings"] = self._sanitize_warning_messages(verification.get("warnings", []))
        return self._enforce_block_authority(
            verification,
            thinking_plan,
            user_text=user_text,
        )
    
    def set_mcp_hub(self, hub):
        self.mcp_hub = hub
        log_info("[ControlLayer] MCP Hub connected")

    @staticmethod
    def _extract_skill_names(result: Any) -> List[str]:
        payload = result
        if isinstance(payload, dict) and isinstance(payload.get("structuredContent"), dict):
            payload = payload.get("structuredContent", {})

        names: List[str] = []
        if isinstance(payload, dict):
            skill_rows: List[Any] = []
            for key in ("skills", "installed", "active"):
                value = payload.get(key, [])
                if isinstance(value, list):
                    skill_rows.extend(value)
            for item in skill_rows:
                if isinstance(item, dict):
                    name = str(item.get("name", "")).strip()
                else:
                    name = str(item or "").strip()
                if name:
                    names.append(name)
        elif isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    name = str(item.get("name", "")).strip()
                else:
                    name = str(item or "").strip()
                if name:
                    names.append(name)

        # Deduplicate while preserving first-seen order.
        seen = set()
        deduped: List[str] = []
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            deduped.append(name)
        return deduped

    def _get_available_skills(self) -> list:
        """Holt Liste aller installierten Skills vom MCPHub (sync path)."""
        if not self.mcp_hub:
            return []
        try:
            result = self.mcp_hub.call_tool("list_skills", {})
            return self._extract_skill_names(result)
        except Exception as e:
            log_debug(f"[ControlLayer] Could not fetch skills: {e}")
            return []

    async def _get_available_skills_async(self) -> list:
        """Holt Liste aller installierten Skills vom MCPHub (async-safe path)."""
        if not self.mcp_hub:
            return []
        try:
            call_tool_async = getattr(self.mcp_hub, "call_tool_async", None)
            if asyncio.iscoroutinefunction(call_tool_async):
                result = await call_tool_async("list_skills", {})
            else:
                result = await asyncio.to_thread(self.mcp_hub.call_tool, "list_skills", {})
            return self._extract_skill_names(result)
        except Exception as e:
            log_debug(f"[ControlLayer] Could not fetch skills (async): {e}")
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
            "blueprint_list", "container_list", "container_inspect", "container_stats", "container_logs",
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

        # Installed skills are available — ThinkingLayer sometimes suggests the skill
        # name directly instead of "run_skill". Treat any installed skill as available
        # so it doesn't end up in tool_availability.unavailable and cause a false block.
        try:
            installed_skills = self._get_available_skills()
            if tool_name in installed_skills:
                log_info(
                    f"[ControlLayer] '{tool_name}' resolved as installed skill → available"
                )
                return True
        except Exception:
            pass

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
            if (
                name in {"autonomous_skill_task", "create_skill", "run_skill", "list_skills", "get_skill_info"}
                and not self._user_text_has_explicit_skill_intent(user_text)
            ):
                log_info(
                    "[ControlLayer] decide_tools filtered skill tool without explicit skill intent: "
                    f"{name}"
                )
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
    
    async def verify(
        self,
        user_text: str,
        thinking_plan: Dict[str, Any],
        retrieved_memory: str = "",
        response_mode: str = "interactive",
    ) -> Dict[str, Any]:
        sequential_result = thinking_plan.get("_sequential_result")
        # FIX: Removed - Bridge handles Sequential Thinking
        # if not sequential_result:
        # sequential_result = await self._check_sequential_thinking(user_text, thinking_plan)
        if sequential_result:
            log_info(f"[ControlLayer] Sequential completed with {len(sequential_result.get('steps', []))} steps")
            thinking_plan["_sequential_result"] = sequential_result

        if self._user_text_has_malicious_intent(user_text):
            return make_hard_block_verification(
                reason_code="malicious_intent",
                warnings=["Dangerous keyword detected: blocked by deterministic policy guard"],
            )

        if bool((thinking_plan or {}).get("_hardware_gate_triggered")):
            _hardware_msg = str((thinking_plan or {}).get("_hardware_gate_warning") or "").strip()
            return make_hard_block_verification(
                reason_code="hardware_self_protection",
                warnings=[_hardware_msg or "Hardware self-protection gate triggered."],
                reason="hardware_self_protection",
            )
        
        # ═══════════════════════════════════════════════════════════
        # CIM POLICY ENGINE - Skill Creation Detection
        # ═══════════════════════════════════════════════════════════
        log_info(f"[ControlLayer-DEBUG] CIM_POLICY_AVAILABLE={CIM_POLICY_AVAILABLE}")
        domain_route = thinking_plan.get("_domain_route", {}) if isinstance(thinking_plan, dict) else {}
        domain_tag = str((domain_route or {}).get("domain_tag") or "").strip().upper()
        domain_locked = bool((domain_route or {}).get("domain_locked"))
        domain_blocks_skill_confirmation = bool(
            domain_locked and domain_tag == "CRONJOB"
        ) or bool((thinking_plan or {}).get("_domain_skill_confirmation_disabled"))
        keyword_match = False
        cim_decision = None
        if CIM_POLICY_AVAILABLE and not domain_blocks_skill_confirmation:
            intent = thinking_plan.get("intent", "").lower()
            # Check für skill-creation Intents
            skill_keywords = ["skill", "erstelle", "create", "programmier", "bau", "neu"]
            keyword_match = any(kw in intent or kw in user_text.lower() for kw in skill_keywords)
            log_info(f"[ControlLayer-DEBUG] intent='{intent}', keyword_match={keyword_match}")
            if keyword_match:
                try:
                    available_skills = await self._get_available_skills_async()
                    log_info(f"[ControlLayer-DEBUG] available_skills={available_skills[:5] if available_skills else []}")
                    cim_decision = process_cim_policy(user_text, available_skills)
                    log_info(f"[ControlLayer-DEBUG] cim_decision.matched={cim_decision.matched}, requires_confirmation={cim_decision.requires_confirmation}")

                    if cim_decision.matched:
                        log_info(f"[ControlLayer-CIM] Decision: {cim_decision.action.value} for '{cim_decision.skill_name}'")
                        cim_action = str(getattr(cim_decision.action, "value", cim_decision.action) or "").strip().lower()
                        cim_pattern_id = (
                            str(getattr(getattr(cim_decision, "policy_match", None), "pattern_id", "") or "").strip().lower()
                        )
                        cim_safety_raw = getattr(getattr(cim_decision, "policy_match", None), "safety_level", "")
                        cim_safety_level = str(
                            getattr(cim_safety_raw, "value", cim_safety_raw) or ""
                        ).strip().lower()
                        if (
                            self._user_text_has_malicious_intent(user_text)
                            or cim_action in {"deny_autonomy", "policy_check"}
                            or cim_pattern_id == "policy_guard"
                            or cim_safety_level == "critical"
                        ):
                            return make_hard_block_verification(
                                reason_code="critical_cim",
                                warnings=[
                                    "Dangerous keyword detected: blocked by deterministic policy guard"
                                ],
                                reason="critical_cim",
                            )
                        
                        # Read-only Aktionen direkt durchlassen
                        safe_actions = ["list_skills", "get_skill_info", "list_draft_skills"]
                        if cim_decision.action.value in safe_actions:
                            log_info(f"[ControlLayer-CIM] Safe read-only action: {cim_decision.action.value}")
                            return {
                                "approved": True,
                                "hard_block": False,
                                "decision_class": "allow",
                                "block_reason_code": "",
                                "reason": "cim_safe_action",
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
                                "hard_block": False,
                                "decision_class": "allow",
                                "block_reason_code": "",
                                "reason": "skill_confirmation_required",
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
        if (
            keyword_match
            and not domain_blocks_skill_confirmation
            and self._is_skill_creation_sensitive(thinking_plan)
        ):
            if self._user_text_has_malicious_intent(user_text):
                return make_hard_block_verification(
                    reason_code="malicious_intent",
                    warnings=["Dangerous keyword detected: blocked by deterministic policy guard"],
                )
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
                    "hard_block": False,
                    "decision_class": "allow",
                    "block_reason_code": "",
                    "reason": "skill_confirmation_required_fallback",
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

        soft_light_cim_warnings: List[str] = []
        try:
            cim_result = self.light_cim.validate_basic(
                intent=thinking_plan.get("intent", ""),
                hallucination_risk=thinking_plan.get("hallucination_risk", "low"),
                user_text=user_text,
                thinking_plan=thinking_plan
            )
            log_info(f"[LightCIM] safe={cim_result['safe']}, confidence={cim_result['confidence']:.2f}")
            if not cim_result["safe"]:
                if self._is_light_cim_hard_denial(cim_result):
                    out = make_hard_block_verification(
                        reason_code="pii",
                        warnings=cim_result["warnings"],
                        reason="pii",
                    )
                    out["_light_cim"] = cim_result
                    return out
                soft_light_cim_warnings = self._warning_list(cim_result.get("warnings", []))
                if soft_light_cim_warnings:
                    log_warning(
                        "[ControlLayer] LightCIM soft warning pass-through: "
                        f"{soft_light_cim_warnings}"
                    )
        except Exception as e:
            log_error(f"[LightCIM] Error: {e}")
        response_mode_norm = self._normalize_response_mode(response_mode)
        verify_timeout_s = self._resolve_verify_timeout_s(response_mode_norm)
        control_model = self._resolve_model(response_mode_norm)
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

        provider = resolve_role_provider("control", default=get_control_provider())
        try:
            endpoint_source = "cloud"
            endpoint = self.ollama_base
            if provider == "ollama":
                route = resolve_role_endpoint("control", default_endpoint=self.ollama_base)
                endpoint_source = "routing"
                log_info(
                    f"[Routing] role=control provider=ollama requested_target={route['requested_target']} "
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
                endpoint_override = self._resolve_control_endpoint_override(response_mode_norm)
                if endpoint_override:
                    endpoint = endpoint_override
                    endpoint_source = "control_override"
            else:
                log_info(f"[Routing] role=control provider={provider} endpoint=cloud")

            log_info(
                "[ControlLayer] verify_runtime "
                f"mode={response_mode_norm} provider={provider} model={control_model} "
                f"timeout_s={verify_timeout_s:.1f} endpoint={endpoint} "
                f"endpoint_source={endpoint_source}"
            )

            content = await complete_prompt(
                provider=provider,
                model=control_model,
                prompt=prompt,
                timeout_s=verify_timeout_s,
                ollama_endpoint=endpoint,
                json_mode=True,
            )
            if not content:
                fallback = self._default_verification(thinking_plan)
                if soft_light_cim_warnings:
                    warnings = self._warning_list(fallback.get("warnings", []))
                    warnings.extend(soft_light_cim_warnings)
                    fallback["warnings"] = warnings
                return fallback
            parsed = safe_parse_json(
                content,
                default=self._default_verification(thinking_plan),
                context="ControlLayer",
            )
            if soft_light_cim_warnings:
                warnings = self._warning_list(parsed.get("warnings", []))
                warnings.extend(soft_light_cim_warnings)
                parsed["warnings"] = warnings
            return self._stabilize_verification_result(parsed, thinking_plan, user_text=user_text)
        except (httpx.TimeoutException, asyncio.TimeoutError) as e:
            msg = (
                "Control verification timeout (504): "
                f"provider={provider if 'provider' in locals() else 'unknown'} "
                f"model={control_model if 'control_model' in locals() else self._resolve_model(response_mode_norm)} "
                f"endpoint={endpoint if 'endpoint' in locals() else self.ollama_base} "
                f"timeout_s={verify_timeout_s if 'verify_timeout_s' in locals() else 30.0}"
            )
            log_error(f"[ControlLayer] {msg} err={type(e).__name__}")
            fallback = self._default_verification(thinking_plan)
            warnings = list(fallback.get("warnings", []))
            warnings.append(msg)
            warnings.extend(soft_light_cim_warnings)
            fallback["warnings"] = warnings
            fallback["_error"] = {"code": 504, "type": "control_timeout", "message": msg}
            return fallback
        except Exception as e:
            msg = f"Control verification error: {type(e).__name__}: {e}"
            log_error(f"[ControlLayer] {msg}")
            fallback = self._default_verification(thinking_plan)
            warnings = list(fallback.get("warnings", []))
            warnings.append(msg)
            warnings.extend(soft_light_cim_warnings)
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
                    if hasattr(self.mcp_hub, "call_tool_async"):
                        cim_result = await self.mcp_hub.call_tool_async("analyze", {"query": user_text})
                    else:
                        cim_result = await asyncio.to_thread(
                            self.mcp_hub.call_tool, "analyze", {"query": user_text}
                        )
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
            seq_provider = resolve_role_provider("thinking", default="ollama")
            log_info(f"[ControlLayer] Starting TRUE STREAMING provider={seq_provider}...")
            content_buffer = ""
            thinking_buffer = ""
            last_thinking_yield = ""
            seq_model = self._resolve_sequential_model()
            seq_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            if seq_provider == "ollama":
                route = resolve_role_endpoint("thinking", default_endpoint=self.ollama_base)
                log_info(
                    f"[Routing] role=thinking provider=ollama requested_target={route['requested_target']} "
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
                async with httpx.AsyncClient(timeout=180.0) as client:
                    async with client.stream(
                        "POST",
                        f"{endpoint}/api/chat",
                        json={
                            "model": seq_model,
                            "messages": seq_messages,
                            "stream": True,
                        },
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

                            if thinking and thinking != last_thinking_yield:
                                thinking_buffer += thinking
                                last_thinking_yield = thinking
                                yield {
                                    "type": "seq_thinking_stream",
                                    "task_id": task_id,
                                    "chunk": thinking,
                                    "total_length": len(thinking_buffer),
                                }

                            if content:
                                content_buffer += content
                            if done:
                                log_info(
                                    f"[ControlLayer] Stream complete. Thinking: {len(thinking_buffer)} chars, "
                                    f"Content: {len(content_buffer)} chars"
                                )
                                break
            else:
                log_info(
                    f"[Routing] role=thinking provider={seq_provider} endpoint=cloud"
                )
                async for content in stream_chat(
                    provider=seq_provider,
                    model=seq_model,
                    messages=seq_messages,
                    timeout_s=180.0,
                    ollama_endpoint="",
                ):
                    if not content:
                        continue
                    content_buffer += content
                    yield {
                        "type": "seq_thinking_stream",
                        "task_id": task_id,
                        "chunk": content,
                        "total_length": len(content_buffer),
                    }
            
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
        return {
            "approved": False,
            "hard_block": True,
            "decision_class": "hard_block",
            "block_reason_code": "control_decision_missing",
            "reason": "control_layer_fallback_fail_closed",
            "corrections": {
                "needs_memory": None,
                "memory_keys": None,
                "hallucination_risk": None,
                "new_fact_key": None,
                "new_fact_value": None,
                "suggested_response_style": None,
                "dialogue_act": None,
                "response_tone": None,
                "response_length_hint": None,
                "tone_confidence": None,
            },
            "warnings": ["Control-Layer Fallback (fail-closed)"],
            "final_instruction": "Request blocked: control decision unavailable.",
        }
    
    def apply_corrections(self, thinking_plan: Dict[str, Any], verification: Dict[str, Any]) -> Dict[str, Any]:
        corrected = thinking_plan.copy()
        for k, v in verification.get("corrections", {}).items():
            if v is not None:
                corrected[k] = v
        corrected["_verified"] = True
        corrected["_final_instruction"] = verification.get("final_instruction", "")
        corrected["_warnings"] = self._sanitize_warning_messages(verification.get("warnings", []))
        # Merge suggested_tools from CIM decision
        if verification.get("suggested_tools"):
            existing = corrected.get("suggested_tools", [])
            corrected["suggested_tools"] = list(set(existing + verification["suggested_tools"]))
        # Merge CIM decision metadata
        if verification.get("_cim_decision"):
            corrected["_cim_decision"] = verification["_cim_decision"]
        return corrected
