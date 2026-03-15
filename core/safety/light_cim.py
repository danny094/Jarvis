"""
Light CIM - Quick Safety Checks

Designed for ALL requests (not just Sequential).
Fast checks (<50ms) with escalation to Full CIM when needed.
"""

from typing import Dict, Any, List
import re

from core.light_cim_policy import load_light_cim_policy


class LightCIM:
    """
    Light Causal Intelligence Module
    
    Quick safety checks for every request:
    - Intent validation
    - Basic logic consistency
    - Safety guards (PII, sensitive topics)
    """
    
    def __init__(self):
        self.policy = load_light_cim_policy()
        self.danger_keywords = [
            "harm", "hurt", "attack", "weapon",
            "illegal", "hack", "exploit", "steal", 
            "murder", "assault", "abuse", "torture",
            "bomb", "gun", "knife", "firearm",
            "terror", "terrorism", "hostage",
            "poison", "overdose", "suicide",
            "threat", "blackmail", "extort",
            "fraud", "scam", "impersonate",
            "virus", "malware", "trojan", "ransomware",
            "keylogger", "botnet"
        ]
        self.sensitive_keywords = [
            "password", "passcode", "pin",
            "credit card", "debit card", "cvv", "cvc",
            "ssn", "social security",
            "bank account", "iban", "swift",
            "api key", "apikey", "token",
            "secret", "private key", "seed phrase",
            "oauth", "bearer token",
            "login", "credentials", "auth"
        ]

    @staticmethod
    def _contains_keyword(text: str, keyword: str) -> bool:
        raw = str(text or "").lower()
        token = str(keyword or "").strip().lower()
        if not raw or not token:
            return False
        # Multi-token / phrase keywords should still match exactly as phrase.
        if " " in token or "-" in token or "/" in token:
            pattern = rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])"
            return re.search(pattern, raw) is not None
        return re.search(rf"\b{re.escape(token)}\b", raw) is not None

    def validate_basic(
        self, 
        intent: str, 
        hallucination_risk: str,
        user_text: str,
        thinking_plan: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Main validation entry point.
        
        Returns:
            {
                "safe": True/False,
                "confidence": 0.0-1.0,
                "warnings": [],
                "should_escalate": True/False,
                "checks": {...}
            }
        """
        # Run all checks
        intent_check = self.validate_intent(intent)
        logic_check = self.check_logic_basic(thinking_plan, user_text=user_text)
        safety_check = self.safety_guard_lite(user_text, thinking_plan)
        
        # Decide if escalation needed
        should_escalate = self._should_escalate(
            hallucination_risk,
            intent_check,
            logic_check,
            thinking_plan
        )
        
        # Collect all warnings
        warnings = []
        warnings.extend(intent_check.get("warnings", []))
        warnings.extend(logic_check.get("issues", []))
        if safety_check.get("warning"):
            warnings.append(safety_check["warning"])
        
        # Overall safety
        safe = (
            intent_check["safe"] and 
            logic_check["consistent"] and 
            safety_check["safe"]
        )
        
        # Calculate confidence
        confidence = min(
            intent_check.get("confidence", 1.0),
            1.0 if logic_check["consistent"] else 0.5
        )
        
        return {
            "safe": safe,
            "confidence": confidence,
            "warnings": warnings,
            "should_escalate": should_escalate,
            "checks": {
                "intent": intent_check,
                "logic": logic_check,
                "safety": safety_check
            }
        }

    def validate_intent(self, intent: str) -> Dict[str, Any]:
        """
        Quick intent safety check.
        
        Checks:
        - Dangerous keywords
        - Intent clarity
        
        Returns:
            {
                "safe": True/False,
                "confidence": 0.0-1.0,
                "warnings": []
            }
        """
        warnings = []
        
        # Check for danger keywords
        intent_lower = intent.lower()
        for keyword in self.danger_keywords:
            if self._contains_keyword(intent_lower, keyword):
                warnings.append(f"Dangerous keyword detected: {keyword}")
                return {
                    "safe": False,
                    "confidence": 0.0,
                    "warnings": warnings
                }
        
        # Check clarity
        if len(intent.split()) < 3:
            warnings.append("Intent unclear (too short)")
            return {
                "safe": True,
                "confidence": 0.6,
                "warnings": warnings
            }
        
        return {
            "safe": True,
            "confidence": 1.0,
            "warnings": warnings
        }

    def check_logic_basic(
        self,
        thinking_plan: Dict[str, Any],
        user_text: str = "",
    ) -> Dict[str, Any]:
        """
        Quick logic consistency checks.
        
        Checks:
        - If needs_memory=True, are memory_keys provided?
        - If hallucination_risk=high, is memory being used?
        - If is_new_fact=True, are key/value provided?
        
        Returns:
            {
                "consistent": True/False,
                "issues": []
            }
        """
        issues = []
        
        # Check 1: Memory keys consistency
        if (
            thinking_plan.get("needs_memory")
            and not thinking_plan.get("memory_keys")
            and not self._is_cron_context_turn(thinking_plan, user_text)
            and not self._is_runtime_action_context_turn(thinking_plan, user_text)
            and not self._has_explicit_tool_domain_tag(user_text)
        ):
            issues.append("Needs memory but no keys specified")
        
        # Check 2: High hallucination without memory
        # DISABLED: Sequential Thinking handles hallucination risk now
        #         if (thinking_plan.get("hallucination_risk") == "high" and 
        # DISABLED: Sequential Thinking handles hallucination risk now
        #             not thinking_plan.get("needs_memory")):
        # DISABLED: Sequential Thinking handles hallucination risk now
        #             issues.append("High hallucination risk without memory usage")
        
        # Check 3: New fact completeness (policy-driven with meta-turn relaxation)
        logic_cfg = (
            (self.policy or {}).get("logic", {})
            if isinstance(self.policy, dict)
            else {}
        )
        enforce_new_fact = bool(logic_cfg.get("enforce_new_fact_completeness", True))
        if thinking_plan.get("is_new_fact") and enforce_new_fact:
            if not self._should_relax_new_fact_completeness(thinking_plan, user_text):
                if not thinking_plan.get("new_fact_key"):
                    issues.append("New fact without key")
                if not thinking_plan.get("new_fact_value"):
                    issues.append("New fact without value")
        
        return {
            "consistent": len(issues) == 0,
            "issues": issues
        }

    @staticmethod
    def _is_cron_context_turn(thinking_plan: Dict[str, Any], user_text: str = "") -> bool:
        route = (thinking_plan or {}).get("_domain_route", {}) if isinstance(thinking_plan, dict) else {}
        if str((route or {}).get("domain_tag") or "").strip().upper() == "CRONJOB":
            return True

        suggested = (thinking_plan or {}).get("suggested_tools", []) if isinstance(thinking_plan, dict) else []
        for tool in suggested if isinstance(suggested, list) else []:
            if isinstance(tool, dict):
                name = str(tool.get("tool") or tool.get("name") or "").strip().lower()
            else:
                name = str(tool or "").strip().lower()
            if name.startswith("autonomy_cron_") or name == "cron_reference_links_list":
                return True

        intent = str((thinking_plan or {}).get("intent") or "").strip().lower()
        if any(tok in intent for tok in ("cron", "cronjob", "schedule", "zeitplan")):
            return True

        text = str(user_text or "").strip().lower()
        return any(tok in text for tok in ("cron", "cronjob", "zeitplan", "schedule"))

    @staticmethod
    def _has_explicit_tool_domain_tag(user_text: str) -> bool:
        text = str(user_text or "")
        if not text:
            return False
        if re.search(r"\{(?:tool|domain)\s*[:=]\s*(cronjob|skill|container|mcp_call)\s*\}", text, re.IGNORECASE):
            return True
        if re.search(r"\{(cronjob|skill|container|mcp_call)\}", text, re.IGNORECASE):
            return True
        return False

    @classmethod
    def _is_runtime_action_context_turn(
        cls,
        thinking_plan: Dict[str, Any],
        user_text: str = "",
    ) -> bool:
        route = (thinking_plan or {}).get("_domain_route", {}) if isinstance(thinking_plan, dict) else {}
        domain_tag = str((route or {}).get("domain_tag") or "").strip().upper()
        domain_locked = bool((route or {}).get("domain_locked"))
        if domain_locked and domain_tag in {"CRONJOB", "SKILL", "CONTAINER"}:
            return True

        suggested = (thinking_plan or {}).get("suggested_tools", []) if isinstance(thinking_plan, dict) else []
        runtime_tools = {
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
            "run_skill",
            "create_skill",
            "autonomous_skill_task",
            "list_skills",
            "get_skill_info",
            "validate_skill_code",
            "cron_reference_links_list",
        }
        for tool in suggested if isinstance(suggested, list) else []:
            if isinstance(tool, dict):
                name = str(tool.get("tool") or tool.get("name") or "").strip().lower()
            else:
                name = str(tool or "").strip().lower()
            if not name:
                continue
            if name in runtime_tools:
                return True
            if name.startswith("autonomy_cron_"):
                return True

        text = str(user_text or "").strip().lower()
        if not text:
            return False
        has_runtime_context = any(
            token in text
            for token in (
                "container",
                "docker",
                "blueprint",
                "host server",
                "host-server",
                "ip adresse",
                "ip-adresse",
                "ip address",
                "cron",
                "cronjob",
                "schedule",
                "zeitplan",
                "skill",
                "tools",
                "tool",
            )
        )
        if not has_runtime_context:
            return False
        return any(
            token in text
            for token in (
                "starte",
                "start",
                "deploy",
                "run",
                "ausführen",
                "ausfuehren",
                "execute",
                "stop",
                "status",
                "logs",
                "list",
                "liste",
                "find",
                "finden",
                "ermittel",
                "heraus",
                "zeige",
                "gib",
                "nutze",
                "benutze",
                "use",
            )
        )

    def safety_guard_lite(
        self, 
        user_text: str, 
        plan: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Quick safety checks.
        
        Checks:
        - PII detection (basic)
        - Sensitive topics
        
        Returns:
            {
                "safe": True/False,
                "warning": str or None
            }
        """
        text_lower = user_text.lower()
        
        # Check for sensitive keywords
        for keyword in self.sensitive_keywords:
            if self._contains_keyword(text_lower, keyword):
                return {
                    "safe": False,
                    "warning": f"Sensitive content detected: {keyword}"
                }
        
        # Basic PII patterns (very simple for now)
        # Email pattern
        if re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', user_text):
            return {
                "safe": False,
                "warning": "Email address detected (PII)"
            }
        
        # Phone number pattern (very basic)
        if re.search(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', user_text):
            return {
                "safe": False,
                "warning": "Phone number detected (PII)"
            }
        
        return {
            "safe": True,
            "warning": None
        }

    def _should_relax_new_fact_completeness(
        self,
        thinking_plan: Dict[str, Any],
        user_text: str,
    ) -> bool:
        logic_cfg = (
            (self.policy or {}).get("logic", {})
            if isinstance(self.policy, dict)
            else {}
        )
        relax_cfg = logic_cfg.get("relax_new_fact_completeness", {})
        if not isinstance(relax_cfg, dict):
            return False
        if not bool(relax_cfg.get("enabled", True)):
            return False

        dialogue_act = str(thinking_plan.get("dialogue_act") or "").strip().lower()
        allowed_acts = {
            str(act).strip().lower()
            for act in relax_cfg.get("dialogue_acts", [])
            if str(act).strip()
        }
        if dialogue_act and dialogue_act in allowed_acts:
            return True

        intent = str(thinking_plan.get("intent") or "")
        intent_patterns = [
            str(pattern)
            for pattern in relax_cfg.get("intent_regex", [])
            if str(pattern).strip()
        ]
        if self._matches_any_regex(intent, intent_patterns):
            return True

        user_patterns = [
            str(pattern)
            for pattern in relax_cfg.get("user_text_regex", [])
            if str(pattern).strip()
        ]
        if self._matches_any_regex(str(user_text or ""), user_patterns):
            return True

        return False

    @staticmethod
    def _matches_any_regex(text: str, patterns: List[str]) -> bool:
        if not text:
            return False
        for pattern in patterns:
            try:
                if re.search(pattern, text, flags=re.IGNORECASE):
                    return True
            except re.error:
                continue
        return False
    
    def _should_escalate(
        self,
        hallucination_risk: str,
        intent_check: Dict,
        logic_check: Dict,
        thinking_plan: Dict
    ) -> bool:
        """
        Decide if Full CIM (Sequential Engine) is needed.
        
        Escalation triggers:
        - High hallucination risk
        - Low confidence in intent
        - Logic inconsistencies
        - Multi-step tasks mentioned
        - Complex analysis required
        """
        # Trigger 1: High hallucination risk
        if hallucination_risk == "high":
            return True
        
        # Trigger 2: Low confidence
        if intent_check.get("confidence", 1.0) < 0.7:
            return True
        
        # Trigger 3: Logic issues
        if not logic_check.get("consistent"):
            return True
        
        # Trigger 4: Multi-step or complex keywords
        intent = thinking_plan.get("intent", "").lower()
        complex_keywords = [
            "analyze", "research", "compare", "evaluate",
            "step-by-step", "multi-step", "workflow"
        ]
        if any(keyword in intent for keyword in complex_keywords):
            return True
        
        # Trigger 5: Many memory keys (complex context)
        if len(thinking_plan.get("memory_keys", [])) > 3:
            return True
        
        return False
