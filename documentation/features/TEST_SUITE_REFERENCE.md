# 🧪 TEST SUITE QUICK REFERENCE

**Date:** 2026-01-16  
**Location:** /tmp/ on Ubuntu server  
**Status:** ✅ READY TO RUN

---

## 📋 AVAILABLE TESTS

### **Individual Tests**
```bash
# TEST 1: Hub Discovery (2 min)
python3 /tmp/test_1_hub_discovery.py

# TEST 2: Tool Routing (3 min)
python3 /tmp/test_2_tool_routing.py

# TEST 3: CIM Validation (2 min)
python3 /tmp/test_3_cim_validation.py

# TEST 4: End-to-End Complex Task (3 min)
python3 /tmp/test_4_end_to_end.py

# TEST 5: Performance & Logging (5 min)
python3 /tmp/test_5_performance.py

# TEST 6: Edge Cases (3 min)
python3 /tmp/test_6_edge_cases.py
```

### **Master Test Runner (All Tests)**
```bash
# Run ALL tests sequentially (~18 min)
python3 /tmp/run_all_tests.py
```

---

## 🎯 WHAT EACH TEST DOES

### **TEST 1: Hub Discovery**
✅ Imports MCP Registry  
✅ Verifies sequential-thinking server registered  
✅ Checks server is reachable (port 8001)  
✅ Verifies tools endpoint  
✅ Confirms both tools present  

**Expected:** All checks pass, 2 tools found

---

### **TEST 2: Tool Routing**
✅ Simple task call  
✅ Multi-step task with dependencies  
✅ Workflow tool call  
✅ Error handling (invalid tool)  

**Expected:** All calls work, performance <10s

---

### **TEST 3: CIM Validation**
✅ 40 priors loaded  
✅ 25 anti-patterns loaded  
✅ 20 procedures loaded  
✅ Intelligence files present  
✅ Safety Layer initialized  

**Expected:** Frank's modules fully loaded

---

### **TEST 4: End-to-End**
✅ 4-step complex task  
✅ Dependencies respected  
✅ All steps verified  
✅ CIM validation per step  
✅ Complete pipeline working  

**Expected:** 100% progress, 0 failed steps

---

### **TEST 5: Performance**
✅ Simple task < 2s  
✅ Medium task (3 steps) < 5s  
✅ Complex task (5 steps) < 10s  
✅ Log file verification  
✅ CIM overhead analysis  

**Expected:** Performance targets met

---

### **TEST 6: Edge Cases**
✅ Missing fields handled  
✅ Invalid tools rejected  
✅ Circular dependencies detected  
✅ Special characters handled  
✅ Server stays healthy  

**Expected:** Graceful error handling

---

## 🚀 RUNNING THE TESTS

### **Before Running:**
```bash
# 1. Ensure server is running
ps aux | grep "uvicorn sequential"

# 2. If not running, start it:
/tmp/start_sequential_server.sh

# 3. Verify health
curl http://localhost:8001/
```

### **Run Single Test:**
```bash
ssh -i ~/.ssh/claude_ubuntu claude@192.168.0.226
cd /tmp
python3 test_1_hub_discovery.py
```

### **Run All Tests:**
```bash
ssh -i ~/.ssh/claude_ubuntu claude@192.168.0.226
cd /tmp
python3 run_all_tests.py
```

### **Save Results:**
```bash
python3 run_all_tests.py 2>&1 | tee test_results_$(date +%Y%m%d_%H%M%S).log
```

---

## 📊 INTERPRETING RESULTS

### **Exit Codes:**
- `0` = All tests passed ✅
- `1` = Critical tests failed ❌

### **Success Criteria:**
```
MUST PASS (Critical):
- TEST 1: Hub Discovery
- TEST 2: Tool Routing
- TEST 3: CIM Validation
- TEST 4: End-to-End

SHOULD PASS (Important):
- TEST 5: Performance
- TEST 6: Edge Cases
```

### **Acceptable Results:**
✅ **100% Pass:** Task 1.3 COMPLETE, proceed to Task 2  
✅ **4/6 Pass (all critical):** Acceptable, can proceed  
⚠️ **Performance issues only:** Acceptable, note for optimization  
❌ **Any critical fail:** Must fix before Task 2

---

## 🔧 TROUBLESHOOTING

### **Server Not Running:**
```bash
/tmp/start_sequential_server.sh
sleep 5
curl http://localhost:8001/
```

### **Import Errors:**
```bash
# Verify PYTHONPATH
export PYTHONPATH=/DATA/AppData/MCP/Jarvis/Jarvis
```

### **Tests Timeout:**
```bash
# Check server logs
tail -50 /tmp/sequential_mcp.log

# Restart server
pkill -f "uvicorn sequential"
/tmp/start_sequential_server.sh
```

### **CIM Modules Not Loaded:**
```bash
# Check symlink
ls -la /DATA/AppData/MCP/Jarvis/Jarvis/modules/sequential_thinking/intelligence_modules

# Check safety_layer.py path
grep "intelligence_modules_path" /DATA/AppData/MCP/Jarvis/Jarvis/modules/sequential_thinking/safety_layer.py
```

---

## 📈 EXPECTED TIMELINE

```
TEST 1: Hub Discovery          ~2 min  ████░░░░░░
TEST 2: Tool Routing           ~3 min  ██████░░░░
TEST 3: CIM Validation         ~2 min  ████░░░░░░
TEST 4: End-to-End            ~3 min  ██████░░░░
TEST 5: Performance           ~5 min  ██████████
TEST 6: Edge Cases            ~3 min  ██████░░░░

Total: ~18 minutes
```

---

## ✅ NEXT STEPS AFTER TESTS

### **If All Pass:**
1. Save test results
2. Update PHASE2_ROADMAP.md
3. Mark Task 1.3 as COMPLETE
4. Move to Task 2: JarvisWebUI Integration

### **If Some Fail:**
1. Review failed test output
2. Fix critical issues first
3. Re-run failed tests
4. Document workarounds
5. Decide: Proceed or fix?

---

## 📝 FILES CREATED

```
/tmp/test_1_hub_discovery.py          104 lines
/tmp/test_2_tool_routing.py           162 lines
/tmp/test_3_cim_validation.py         174 lines
/tmp/test_4_end_to_end.py             192 lines
/tmp/test_5_performance.py            188 lines
/tmp/test_6_edge_cases.py             208 lines
/tmp/run_all_tests.py                 241 lines

Total: 1,269 lines of test code
```

---

**STATUS: ✅ READY TO EXECUTE**

Danny & Frank: Run `python3 /tmp/run_all_tests.py` whenever ready! 🚀
