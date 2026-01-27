# 🚀 TONIGHT: Light CIM Implementation

**Date:** 2025-01-14 Evening  
**Duration:** ~2 hours  
**Goal:** Implement Light CIM in ControlLayer

---

## 🎯 WHAT WE'RE BUILDING TONIGHT:

```
Light CIM im ControlLayer = Quick safety checks für ALLE Anfragen
├─ < 50ms overhead
├─ 3 einfache Checks
└─ Kein Blocking, nur Warnings
```

---

## 📋 TONIGHT'S CHECKLIST:

### **STEP 1: Create Light CIM Module (45 min)**

#### 1.1: Create Directory
```bash
cd /DATA/AppData/MCP/Jarvis/Jarvis/
sudo mkdir -p core/safety
```

#### 1.2: Create `core/safety/__init__.py`
```python
"""
Safety Module - Light CIM Integration
"""

from .light_cim import LightCIM

__all__ = ['LightCIM']
```

#### 1.3: Create `core/safety/light_cim.py`
```python
"""
Light CIM - Quick Safety Checks

Designed for ALL requests (not just Sequential).
Fast checks (<50ms) with escalation to Full CIM when needed.
"""

from typing import Dict, Any, List


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
        if (thinking_plan.get("hallucination_risk") == "high" and 
            not thinking_plan.get("needs_memory")):
            issues.append("High hallucination risk without memory usage")
        
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
        import re
        
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
```

---

### **STEP 2: Integrate into ControlLayer (45 min)**

#### 2.1: Modify `core/layers/control.py`

**Add import at top:**
```python
from core.safety.light_cim import LightCIM
```

**Modify `__init__` method:**
```python
def __init__(self, model: str = CONTROL_MODEL):
    self.model = model
    self.ollama_base = OLLAMA_BASE
    self.light_cim = LightCIM()  # NEW!
```

**Modify `verify` method - ADD THIS BEFORE QWEN CALL:**
```python
async def verify(
    self, 
    user_text: str, 
    thinking_plan: Dict[str, Any],
    retrieved_memory: str = ""
) -> Dict[str, Any]:
    """
    Verifiziert den Plan vom ThinkingLayer.
    NOW WITH LIGHT CIM INTEGRATION!
    """
    
    # NEW: Light CIM validation FIRST
    cim_result = self.light_cim.validate_basic(
        intent=thinking_plan.get("intent", ""),
        hallucination_risk=thinking_plan.get("hallucination_risk", "low"),
        user_text=user_text,
        thinking_plan=thinking_plan
    )
    
    log_info(f"[LightCIM] safe={cim_result['safe']}, confidence={cim_result['confidence']:.2f}, escalate={cim_result['should_escalate']}")
    
    # If unsafe, return early
    if not cim_result["safe"]:
        return {
            "approved": False,
            "corrections": {},
            "warnings": cim_result["warnings"],
            "final_instruction": "Request blocked by safety checks",
            "_light_cim": cim_result
        }
    
    # Continue with existing Qwen validation...
    prompt = f"""{CONTROL_PROMPT}
    
    # ... rest of existing code ...
```

**Add merge method at end of class:**
```python
def _merge_validations(
    self,
    qwen_result: Dict[str, Any],
    cim_result: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Merge Qwen and Light CIM results.
    """
    # Start with Qwen result
    merged = qwen_result.copy()
    
    # Add CIM warnings
    merged["warnings"] = merged.get("warnings", []) + cim_result.get("warnings", [])
    
    # Add escalation flag
    merged["_should_escalate"] = cim_result.get("should_escalate", False)
    
    # Add CIM details
    merged["_light_cim"] = cim_result
    
    # If CIM says not safe, override approval
    if not cim_result.get("safe"):
        merged["approved"] = False
    
    return merged
```

---

### **STEP 3: Basic Testing (30 min)**

#### 3.1: Create test file
```bash
sudo nano /DATA/AppData/MCP/Jarvis/Jarvis/tests/test_light_cim.py
```

#### 3.2: Test code
```python
"""
Light CIM Tests
"""

import sys
sys.path.insert(0, '/DATA/AppData/MCP/Jarvis/Jarvis')

from core.safety.light_cim import LightCIM


def test_basic_intent():
    """Test basic intent validation"""
    cim = LightCIM()
    
    # Safe intent
    result = cim.validate_intent("Analyze sales data for Q4")
    assert result["safe"] == True
    print("✅ Safe intent test passed")
    
    # Dangerous intent
    result = cim.validate_intent("How to hack a system")
    assert result["safe"] == False
    print("✅ Dangerous intent test passed")


def test_logic_consistency():
    """Test logic checks"""
    cim = LightCIM()
    
    # Inconsistent: needs memory but no keys
    plan = {
        "needs_memory": True,
        "memory_keys": [],
        "hallucination_risk": "low"
    }
    result = cim.check_logic_basic(plan)
    assert result["consistent"] == False
    print("✅ Logic inconsistency detected")
    
    # Consistent plan
    plan = {
        "needs_memory": True,
        "memory_keys": ["age"],
        "hallucination_risk": "low"
    }
    result = cim.check_logic_basic(plan)
    assert result["consistent"] == True
    print("✅ Consistent plan validated")


def test_safety_guard():
    """Test safety checks"""
    cim = LightCIM()
    
    # PII detection
    result = cim.safety_guard_lite(
        "My email is danny@example.com",
        {}
    )
    assert result["safe"] == False
    print("✅ PII detected")
    
    # Clean text
    result = cim.safety_guard_lite(
        "What is the weather today?",
        {}
    )
    assert result["safe"] == True
    print("✅ Clean text validated")


def test_escalation():
    """Test escalation logic"""
    cim = LightCIM()
    
    # Should escalate: high hallucination
    result = cim.validate_basic(
        intent="Analyze complex data patterns",
        hallucination_risk="high",
        user_text="Analyze this dataset",
        thinking_plan={
            "intent": "analyze complex data patterns",
            "hallucination_risk": "high",
            "needs_memory": False,
            "memory_keys": []
        }
    )
    assert result["should_escalate"] == True
    print("✅ Escalation triggered correctly")


if __name__ == "__main__":
    print("🧪 Running Light CIM Tests...\n")
    
    test_basic_intent()
    test_logic_consistency()
    test_safety_guard()
    test_escalation()
    
    print("\n✅ ALL TESTS PASSED!")
```

#### 3.3: Run tests
```bash
cd /DATA/AppData/MCP/Jarvis/Jarvis
python3 tests/test_light_cim.py
```

---

## ✅ TONIGHT'S SUCCESS CRITERIA:

```
[ ] core/safety/ directory created
[ ] light_cim.py created (~200 lines)
[ ] ControlLayer modified (import + integration)
[ ] Tests created
[ ] Tests passing ✅
[ ] Light CIM validates ALL requests
[ ] Overhead < 100ms
```

---

## 🎯 WHAT THIS GIVES US:

```
BEFORE:
User → ThinkingLayer → ControlLayer (Qwen only) → Output

AFTER (TONIGHT):
User → ThinkingLayer → ControlLayer (Qwen + Light CIM) → Output
                                          ↓
                            If complex → Sequential Engine (Full CIM)
```

---

## 📊 EXPECTED RESULTS:

```python
# Example output after integration:
{
    "approved": True,
    "corrections": {...},
    "warnings": ["Intent unclear (too short)"],  # From Light CIM
    "_light_cim": {
        "safe": True,
        "confidence": 0.8,
        "should_escalate": False,
        "checks": {...}
    },
    "_should_escalate": False
}
```

---

**READY TO START?** 

Just follow these 3 steps:
1. Create Light CIM module
2. Integrate into ControlLayer  
3. Run tests

**Estimated:** ~2 hours  
**Difficulty:** Medium (mostly copy-paste + small mods)

Let's go! 🚀
