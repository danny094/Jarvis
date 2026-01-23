# 🧠 FRANK'S CIM INTEGRATION - HYBRID ARCHITECTURE

**Version:** 1.0  
**Date:** 2025-01-14  
**Status:** Designed for Phase 2

---

## 📋 OVERVIEW

Frank's Causal Intelligence Module (CIM) wird in zwei Ebenen integriert:

```
┌─────────────────────────────────────────────────────────────┐
│                    ALLE ANFRAGEN                             │
│  ┌────────────────────────────────────────────────────┐     │
│  │  ControlLayer (Qwen) + Light CIM                   │     │
│  │  ├─ Basic Safety Checks     (~50ms)                │     │
│  │  ├─ Intent Validation                              │     │
│  │  └─ Quick Logic Consistency                        │     │
│  └────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
                           │
                           ├─ Simple Queries → Direct to Output
                           │
                           └─ Complex Tasks → Sequential Engine
                                      │
                    ┌─────────────────▼────────────────┐
                    │  Sequential Engine + Full CIM    │
                    │  ├─ Deep Causal Analysis         │
                    │  ├─ Comprehensive Validation     │
                    │  └─ Step-by-Step Verification    │
                    └──────────────────────────────────┘
```

---

## 🎯 DESIGN PRINCIPLES

### **Principle 1: Defense in Depth**
- **Layer 1:** Quick safety checks for ALL requests
- **Layer 2:** Deep analysis for COMPLEX tasks
- No request bypasses validation

### **Principle 2: Performance First**
- Light checks must be fast (<100ms)
- Full checks only when complexity justifies it
- Automatic escalation when needed

### **Principle 3: Graceful Degradation**
- If Light CIM fails → Continue with warning
- If Full CIM fails → Fallback to manual review
- System never blocks without reason

---

## 🔧 LEVEL 1: LIGHT CIM (ControlLayer)

### **Location:** `core/layers/control.py`

### **Integration Point:**
```python
class ControlLayer:
    def __init__(self):
        self.model = CONTROL_MODEL
        self.light_cim = LightCIM()  # NEW!
    
    async def verify(self, user_text, thinking_plan, retrieved_memory):
        # Existing: Qwen validation
        qwen_result = await self._qwen_verify(...)
        
        # NEW: Light CIM validation
        cim_result = self.light_cim.validate_basic(
            intent=thinking_plan["intent"],
            hallucination_risk=thinking_plan["hallucination_risk"],
            user_text=user_text
        )
        
        # Merge results
        return self._merge_validations(qwen_result, cim_result)
```

### **Light CIM Checks:**

#### **1. Intent Safety Check**
```python
def validate_intent(intent: str) -> Dict[str, Any]:
    """
    Quick check if intent is safe and clear.
    
    Returns:
        {
            "safe": True/False,
            "warning": "..." if unsafe,
            "confidence": 0.0-1.0
        }
    """
    # Check for dangerous intents
    danger_keywords = ["harm", "illegal", "exploit", ...]
    
    # Check for unclear intents
    if len(intent.split()) < 3:
        return {"safe": True, "warning": "Intent unclear", "confidence": 0.6}
    
    return {"safe": True, "confidence": 1.0}
```

#### **2. Basic Logic Consistency**
```python
def check_logic_basic(thinking_plan: Dict) -> Dict[str, Any]:
    """
    Quick sanity checks on the plan.
    
    Checks:
    - If needs_memory=True, are memory_keys provided?
    - If hallucination_risk=high, is memory being used?
    - If is_new_fact=True, are key/value provided?
    """
    issues = []
    
    if thinking_plan["needs_memory"] and not thinking_plan["memory_keys"]:
        issues.append("Needs memory but no keys specified")
    
    if thinking_plan["hallucination_risk"] == "high" and not thinking_plan["needs_memory"]:
        issues.append("High hallucination risk without memory")
    
    return {
        "consistent": len(issues) == 0,
        "issues": issues
    }
```

#### **3. Safety Guard Lite**
```python
def safety_guard_lite(user_text: str, plan: Dict) -> Dict[str, Any]:
    """
    Quick safety checks before execution.
    
    Returns:
        {
            "safe": True/False,
            "block": True if should block,
            "warning": "..." if concerns
        }
    """
    # PII detection
    has_pii = detect_pii_quick(user_text)
    
    # Sensitive topics
    is_sensitive = check_sensitive_topics(user_text)
    
    return {
        "safe": not (has_pii or is_sensitive),
        "block": False,  # Light CIM doesn't block, just warns
        "warning": "Contains PII or sensitive content" if (has_pii or is_sensitive) else None
    }
```

### **Performance Target:**
- Total Light CIM overhead: <50ms
- Non-blocking (async)
- Fails gracefully

---

## 🚀 LEVEL 2: FULL CIM (Sequential Engine)

### **Location:** `modules/sequential_thinking/safety.py` ✅ (Already implemented!)

### **Integration Point:**
```python
class SequentialThinkingEngine:
    def __init__(self):
        self.safety = FrankSafetyLayer()  # Full CIM
    
    def execute_task(self, task: Task):
        # BEFORE each step
        validation = self.safety.validate_before(step)
        if not validation["safe"]:
            step.status = StepStatus.FAILED
            continue
        
        # Execute step
        result = self._execute_step(step)
        
        # AFTER each step
        verification = self.safety.validate_after(step, result)
        if not verification["valid"]:
            step.status = StepStatus.FAILED
```

### **Full CIM Features:** (from Phase 1)
- ✅ Deep Causal Analysis
- ✅ Comprehensive Logic Validation
- ✅ Step-by-Step Verification
- ✅ Relationship Mapping
- ✅ Confidence Scoring

### **Performance:**
- Total overhead: ~200-500ms per step
- Only for complex tasks
- Can block execution if unsafe

---

## 🔄 ESCALATION LOGIC

### **When to escalate from Light → Full CIM:**

```python
def should_escalate(thinking_plan: Dict, light_cim_result: Dict) -> bool:
    """
    Decide if task needs Full CIM validation.
    """
    # Automatic escalation triggers:
    triggers = [
        thinking_plan.get("hallucination_risk") == "high",
        len(thinking_plan.get("memory_keys", [])) > 3,
        light_cim_result.get("confidence", 1.0) < 0.7,
        thinking_plan.get("is_new_fact") == True,
        "multi-step" in thinking_plan.get("intent", "").lower(),
    ]
    
    return any(triggers)
```

### **Escalation Flow:**

```
User Query → ThinkingLayer → ControlLayer (Light CIM)
                                    │
                                    ├─ Low Complexity → OutputLayer
                                    │
                                    └─ High Complexity → Sequential Engine (Full CIM)
                                                              │
                                                              └─ Validated Result → OutputLayer
```

---

## 📊 COMPARISON TABLE

| Feature | Light CIM (L1) | Full CIM (L2) |
|---------|---------------|---------------|
| **Scope** | All requests | Complex tasks only |
| **Speed** | ~50ms | ~200-500ms per step |
| **Depth** | Basic checks | Comprehensive analysis |
| **Blocking** | No (warns only) | Yes (can block) |
| **Location** | `core/layers/control.py` | `modules/sequential_thinking/` |
| **Integration** | Phase 2 Task 1 | Phase 1 ✅ Complete |

---

## 🛠️ IMPLEMENTATION PLAN

### **Phase 2 - Task 1: Light CIM in ControlLayer**

**Duration:** 2 hours (part of MCP Server task)

**Steps:**

1. **Create Light CIM Module** (45 min)
   ```
   core/safety/
   ├─ __init__.py
   ├─ light_cim.py        ← NEW!
   │  ├─ class LightCIM
   │  ├─ validate_intent()
   │  ├─ check_logic_basic()
   │  └─ safety_guard_lite()
   └─ README.md
   ```

2. **Integrate into ControlLayer** (45 min)
   - Modify `core/layers/control.py`
   - Add Light CIM validation
   - Merge with Qwen results
   - Add escalation logic

3. **Testing** (30 min)
   - Unit tests for Light CIM
   - Integration test with ControlLayer
   - Performance benchmarks

**Acceptance Criteria:**
- ✅ All requests pass through Light CIM
- ✅ Overhead < 100ms
- ✅ High-risk queries escalate to Full CIM
- ✅ No false positives blocking simple queries

---

## 🎯 SUCCESS METRICS

### **Light CIM (L1):**
- **Speed:** < 100ms per request
- **Coverage:** 100% of requests
- **False Positive Rate:** < 5%
- **Escalation Accuracy:** > 90%

### **Full CIM (L2):**
- **Validation Accuracy:** > 95%
- **Step Failure Detection:** > 98%
- **Causal Consistency:** > 90%

### **Overall System:**
- **No request bypasses validation**
- **Performance degradation:** < 10%
- **User satisfaction:** Increased clarity and trust

---

## 📝 CODE STRUCTURE

### **Files to Create:**

```
core/
├─ safety/                      ← NEW DIRECTORY!
│  ├─ __init__.py
│  ├─ light_cim.py             ← Light CIM implementation
│  ├─ escalation.py            ← Escalation logic
│  └─ README.md
│
└─ layers/
   └─ control.py               ← MODIFY: Add Light CIM

modules/
└─ sequential_thinking/
   └─ safety.py                ← EXISTS: Full CIM ✅
```

---

## 🔐 SECURITY CONSIDERATIONS

### **Light CIM:**
- Fast checks only - no deep inspection
- Cannot block by itself (only warns)
- Designed to escalate suspicious requests

### **Full CIM:**
- Comprehensive validation
- Can block unsafe operations
- Detailed logging for audit

### **Data Privacy:**
- PII detection in Light CIM
- No data storage in validation layer
- Audit logs are anonymized

---

## 🚦 ROLLOUT STRATEGY

### **Phase 2.1: Light CIM (Week 1)**
1. Implement `core/safety/light_cim.py`
2. Integrate into ControlLayer
3. Test with existing traffic
4. Monitor performance

### **Phase 2.2: Integration Testing (Week 1)**
1. Test Light → Full escalation
2. Verify no regressions
3. Performance benchmarks
4. Adjust thresholds if needed

### **Phase 2.3: Production (Week 2)**
1. Enable Light CIM for all requests
2. Monitor escalation rates
3. Fine-tune escalation logic
4. Document learnings

---

## 📚 REFERENCES

### **Frank's Research:**
- Causal Intelligence Module (CIM)
- Intent-Based Capability Framework
- Hallucination Prevention Strategies

### **Related Docs:**
- `documentation/features/PHASE1_COMPLETE.md` - Full CIM implementation
- `documentation/features/PHASE2_ROADMAP.md` - Phase 2 plan
- `modules/sequential_thinking/safety.py` - Current Full CIM

---

## ✅ DECISION LOG

**Date:** 2025-01-14  
**Decision:** Hybrid CIM Architecture (A)  
**Rationale:**
- Light CIM provides baseline safety for ALL requests
- Full CIM provides deep validation for complex tasks
- Best balance of performance and safety
- Follows defense-in-depth principle

**Alternatives Considered:**
- B) Full CIM everywhere → Too slow
- C) Full CIM only in Sequential → No baseline protection

**Decision Makers:**
- Danny (Lead Architect)
- Frank (CIM Designer)
- Claude (Implementation Support)

---

## 🎯 NEXT STEPS

1. **Immediate:** Add to Phase 2 Task 1 documentation
2. **This Week:** Implement Light CIM during Phase 2
3. **Next Week:** Test and refine escalation logic
4. **Ongoing:** Monitor and optimize thresholds

---

**Status:** Design Complete ✅  
**Ready for:** Implementation in Phase 2 Task 1  
**Estimated Effort:** 2 hours (integrated into existing task)
