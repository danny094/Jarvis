# 🧪 COMPREHENSIVE TESTING PLAN - Task 1.3

**Date:** 2026-01-16  
**Duration:** 1 hour  
**Status:** Ready to Execute

---

## ✅ PRE-TEST CHECKLIST

```
✅ Sequential MCP Server: Running (Port 8001)
✅ Frank's Intelligence Modules: Loaded (40 priors, 25 patterns, 20 procedures)
✅ Light CIM: Integrated in ControlLayer
✅ Phase 1 Engine: Operational
✅ Tools Registered: 2 (sequential_thinking, sequential_workflow)
```

---

## 📋 TEST SUITE

### **TEST 1: MCP Hub Discovery (15 min)**

**Objective:** Verify Hub can discover and register our server

**Steps:**
```python
# 1. Check if Hub exists
from mcp.hub import get_hub

# 2. Initialize Hub
hub = get_hub()
hub.initialize()

# 3. List all tools
tools = hub.list_tools()

# 4. Verify our tools are present
assert "sequential_thinking" in [t['name'] for t in tools]
assert "sequential_workflow" in [t['name'] for t in tools]
```

**Expected Results:**
- ✅ Hub initializes successfully
- ✅ Discovers sequential-thinking server
- ✅ Both tools appear in tool list
- ✅ Tool schemas are correct

**Failure Scenarios:**
- ❌ Hub can't connect → Check mcp_registry.py
- ❌ Tools not found → Check server registration
- ❌ Wrong schemas → Check tools.py definitions

---

### **TEST 2: Tool Routing (15 min)**

**Objective:** Verify Hub can route tool calls to our server

**Steps:**
```python
# 1. Simple tool call via Hub
result = hub.call_tool("sequential_thinking", {
    "task_description": "Calculate 5+7"
})

# 2. Multi-step task
result = hub.call_tool("sequential_thinking", {
    "task_description": "Multi-step test",
    "steps": [
        {"id": "step1", "description": "First step"},
        {"id": "step2", "description": "Second step", "dependencies": ["step1"]}
    ]
})

# 3. Workflow tool
result = hub.call_tool("sequential_workflow", {
    "template_id": "data_analysis"
})
```

**Expected Results:**
- ✅ Hub routes calls correctly
- ✅ Server receives requests
- ✅ Results are returned
- ✅ Error handling works

**Performance Targets:**
- Simple task: < 2 seconds
- Multi-step task: < 5 seconds
- Workflow call: < 1 second

---

### **TEST 3: CIM Validation Pipeline (15 min)**

**Objective:** Verify Frank's CIM validates steps correctly

**Steps:**
```python
# 1. Task that should pass validation
safe_task = hub.call_tool("sequential_thinking", {
    "task_description": "Analyze quarterly sales data"
})

# Expected: CIM validates, step executes, result returned

# 2. Task with potential issues (test corrections)
risky_task = hub.call_tool("sequential_thinking", {
    "task_description": "Make decision based on incomplete data"
})

# Expected: CIM flags issues, applies corrections

# 3. Check logs for CIM activity
# Should see:
# - Prior lookups
# - Pattern matching
# - Validation scores
# - Corrections applied (if any)
```

**Expected Results:**
- ✅ Priors are consulted (40 available)
- ✅ Patterns are checked (25 anti-patterns)
- ✅ Procedures are applied (20 available)
- ✅ Validation scores calculated
- ✅ Corrections applied when needed

**CIM Metrics to Check:**
```python
# From logs:
- "Loaded CIM: 40 priors, 25 patterns, 20 procedures" ✅
- "Intelligence Loader: 25 anti-patterns, 40 priors" ✅
- Safety checks performed: Yes/No
- Corrections applied: Count
- Validation confidence: 0.0-1.0
```

---

### **TEST 4: End-to-End Complex Task (15 min)**

**Objective:** Real-world scenario with all components

**Scenario:**
```python
complex_task = {
    "task_description": "Analyze Q4 sales trends and recommend actions",
    "steps": [
        {
            "id": "data_review",
            "description": "Review Q4 sales data for patterns"
        },
        {
            "id": "trend_analysis", 
            "description": "Identify key trends and anomalies",
            "dependencies": ["data_review"]
        },
        {
            "id": "causal_factors",
            "description": "Determine causal factors for trends",
            "dependencies": ["trend_analysis"]
        },
        {
            "id": "recommendations",
            "description": "Generate actionable recommendations",
            "dependencies": ["causal_factors"]
        }
    ]
}

result = hub.call_tool("sequential_thinking", complex_task)
```

**Expected Flow:**
```
1. Hub receives request
2. Routes to sequential-thinking server
3. Server creates Task with 4 Steps
4. Engine executes steps sequentially:
   
   For each step:
   a. Light CIM (ControlLayer) - Quick safety check
   b. Safety Layer (Phase 1) - Full validation with Frank's modules
      - Consult priors
      - Check anti-patterns
      - Apply procedures
   c. Execute step
   d. Validate result
   e. Store in memory
   
5. Return complete results
```

**Expected Results:**
- ✅ All 4 steps execute
- ✅ Dependencies respected
- ✅ CIM validates each step
- ✅ Results contain step details
- ✅ Progress = 1.0 (100%)
- ✅ failed_steps = 0

**Validation Points:**
```json
{
  "success": true,
  "task_id": "seq_...",
  "progress": 1.0,
  "completed_steps": 4,
  "failed_steps": 0,
  "steps": [
    {
      "id": "data_review",
      "status": "verified",
      "result": {...},
      "safety_passed": true,
      "corrections_applied": [...]
    },
    // ... 3 more steps
  ]
}
```

---

### **TEST 5: Performance & Logging (10 min)**

**Objective:** Measure performance and verify logging

**Metrics to Collect:**
```python
import time

# 1. Response times
tests = [
    ("simple", {"task_description": "Simple task"}),
    ("medium", {"task_description": "Task with 3 steps", "steps": [...]}),
    ("complex", {"task_description": "Task with 5 steps", "steps": [...]})
]

for name, task in tests:
    start = time.time()
    result = hub.call_tool("sequential_thinking", task)
    duration = time.time() - start
    print(f"{name}: {duration:.2f}s")

# 2. CIM overhead
# Compare with/without CIM validation

# 3. Memory usage
# Check engine.memory.get_size_mb()
```

**Performance Targets:**
- Simple task: < 2s
- Medium task (3 steps): < 5s
- Complex task (5 steps): < 10s
- CIM overhead per step: < 200ms

**Log Verification:**
```bash
# Check logs contain:
grep "Loaded CIM" /tmp/sequential_mcp.log
grep "Intelligence Loader" /tmp/sequential_mcp.log
grep "Safety Layer" /tmp/sequential_mcp.log
grep "verified" /tmp/sequential_mcp.log
```

---

### **TEST 6: Edge Cases & Error Handling (5 min)**

**Objective:** Verify system handles errors gracefully

**Test Cases:**
```python
# 1. Invalid task
try:
    hub.call_tool("sequential_thinking", {})
    # Should fail: missing task_description
except Exception as e:
    print(f"✅ Caught error: {e}")

# 2. Circular dependencies
try:
    hub.call_tool("sequential_thinking", {
        "task_description": "Circular deps test",
        "steps": [
            {"id": "a", "dependencies": ["b"]},
            {"id": "b", "dependencies": ["a"]}
        ]
    })
    # Should fail or handle gracefully
except Exception as e:
    print(f"✅ Caught error: {e}")

# 3. Non-existent tool
try:
    hub.call_tool("non_existent_tool", {})
    # Should fail
except Exception as e:
    print(f"✅ Caught error: {e}")

# 4. Malformed request
try:
    hub.call_tool("sequential_thinking", "not a dict")
    # Should fail
except Exception as e:
    print(f"✅ Caught error: {e}")
```

**Expected Results:**
- ✅ All errors caught gracefully
- ✅ Meaningful error messages
- ✅ Server stays running
- ✅ No crashes

---

## 📊 SUCCESS CRITERIA

### **Must Pass:**
- ✅ Hub discovers server
- ✅ Tools are callable via Hub
- ✅ CIM modules load (40 priors, 25 patterns, 20 procedures)
- ✅ End-to-end task completes
- ✅ No crashes or hangs

### **Should Pass:**
- ✅ Performance within targets
- ✅ Proper error handling
- ✅ Logging is comprehensive
- ✅ Dependencies respected

### **Nice to Have:**
- ✅ CIM validations visible in logs
- ✅ Memory usage reasonable
- ✅ Auto-recovery from errors

---

## 🚀 EXECUTION PLAN

### **Phase 1: Setup (5 min)**
```bash
# 1. Ensure server is running
ps aux | grep "uvicorn sequential"

# 2. Clear old logs
> /tmp/sequential_mcp.log

# 3. Prepare test script
cd /DATA/AppData/MCP/Jarvis/Jarvis
```

### **Phase 2: Run Tests (50 min)**
```bash
# Run each test in sequence
# Document results
# Collect metrics
```

### **Phase 3: Analysis (5 min)**
```bash
# Review logs
# Compile results
# Identify issues
```

---

## 📝 TEST RESULTS TEMPLATE

```markdown
# Test Results - Task 1.3

Date: 2026-01-16
Duration: XX minutes

## Summary
- Tests Passed: X/6
- Tests Failed: X/6
- Performance: Within/Outside targets

## Detailed Results

### TEST 1: Hub Discovery
Status: ✅/❌
Notes: ...

### TEST 2: Tool Routing
Status: ✅/❌
Performance: X.XXs
Notes: ...

### TEST 3: CIM Validation
Status: ✅/❌
Priors Used: X/40
Patterns Checked: X/25
Notes: ...

### TEST 4: End-to-End
Status: ✅/❌
Duration: X.XXs
Steps Completed: X/X
Notes: ...

### TEST 5: Performance
Status: ✅/❌
Simple: X.XXs (target: <2s)
Medium: X.XXs (target: <5s)
Complex: X.XXs (target: <10s)
Notes: ...

### TEST 6: Edge Cases
Status: ✅/❌
Errors Handled: X/4
Notes: ...

## Issues Found
1. Issue description
2. ...

## Recommendations
1. ...
2. ...

## Conclusion
Task 1.3: PASS/FAIL
Ready for Task 2: YES/NO
```

---

## 🎯 NEXT STEPS AFTER TESTING

### **If All Pass:**
```
✅ Mark Task 1.3 as COMPLETE
✅ Update Phase 2 Roadmap
✅ Move to Task 2 (JarvisWebUI Integration)
```

### **If Some Fail:**
```
🔧 Fix critical issues
⏸️ Re-test failed tests
✅ Document workarounds
→ Decide: Continue or fix first?
```

### **If Major Issues:**
```
🛑 Stop and analyze
📋 Create issue list
💬 Discuss with Danny & Frank
🔄 Re-plan if needed
```

---

**STATUS: READY TO EXECUTE**

Waiting for Frank's confirmation on Intelligence Modules, then we proceed with testing! 🚀
