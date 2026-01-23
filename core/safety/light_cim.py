"""
Light CIM - Quick Safety Checks

Designed for ALL requests (not just Sequential).
Fast checks (<50ms) with escalation to Full CIM when needed.
"""

from typing import Dict, Any, List
import re


class LightCIM:
    """
    Light Causal Intelligence Module
    
    Quick safety checks for every request:
    - Intent validation
    - Basic logic consistency
    - Safety guards (PII, sensitive topics)
    """
    
    def __init__(self):
        self.danger_keywords = [
            "harm", "hurt", "kill", "attack", "weapon",
            "illegal", "hack", "exploit", "steal"
        ]
        self.sensitive_keywords = [
            "password", "credit card", "ssn", "social security",
            "bank account", "api key", "secret"
        ]

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
        logic_check = self.check_logic_basic(thinking_plan)
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
            if keyword in intent_lower:
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

    def check_logic_basic(self, thinking_plan: Dict[str, Any]) -> Dict[str, Any]:
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
        if thinking_plan.get("needs_memory") and not thinking_plan.get("memory_keys"):
            issues.append("Needs memory but no keys specified")
        
        # Check 2: High hallucination without memory
        # DISABLED: Sequential Thinking handles hallucination risk now
        #         if (thinking_plan.get("hallucination_risk") == "high" and 
        # DISABLED: Sequential Thinking handles hallucination risk now
        #             not thinking_plan.get("needs_memory")):
        # DISABLED: Sequential Thinking handles hallucination risk now
        #             issues.append("High hallucination risk without memory usage")
        
        # Check 3: New fact completeness
        if thinking_plan.get("is_new_fact"):
            if not thinking_plan.get("new_fact_key"):
                issues.append("New fact without key")
            if not thinking_plan.get("new_fact_value"):
                issues.append("New fact without value")
        
        return {
            "consistent": len(issues) == 0,
            "issues": issues
        }

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
            if keyword in text_lower:
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
