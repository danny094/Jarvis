#!/usr/bin/env python3
"""
Comprehensive Light CIM Integration Tests
Tests all aspects of Light CIM in production environment
"""
import sys
import time
sys.path.insert(0, "/DATA/AppData/MCP/Jarvis/Jarvis")

from core.layers.control import ControlLayer
from core.safety import LightCIM

print("="*60)
print("🧪 LIGHT CIM COMPREHENSIVE TEST SUITE")
print("="*60)

# Initialize
control = ControlLayer()
cim = LightCIM()

passed = 0
failed = 0
total = 0

def test(name, func):
    """Run a test and track results"""
    global passed, failed, total
    total += 1
    try:
        result = func()
        if result:
            print(f"✅ {name}")
            passed += 1
        else:
            print(f"❌ {name}")
            failed += 1
        return result
    except Exception as e:
        print(f"❌ {name} - Exception: {e}")
        failed += 1
        return False

print("\n📋 TEST GROUP 1: Intent Validation")
print("-" * 60)

def test_safe_intent():
    """Test safe intent passes"""
    result = cim.validate_intent("Analyze sales data for Q4")
    return result["safe"] == True and result["confidence"] == 1.0

def test_dangerous_intent():
    """Test dangerous intent is blocked"""
    result = cim.validate_intent("How to hack a system")
    return result["safe"] == False

def test_unclear_intent():
    """Test unclear intent gets warning"""
    result = cim.validate_intent("Do it")
    return result["safe"] == True and result["confidence"] < 1.0

test("Safe intent passes", test_safe_intent)
test("Dangerous intent blocked", test_dangerous_intent)
test("Unclear intent warning", test_unclear_intent)

print("\n📋 TEST GROUP 2: Logic Consistency")
print("-" * 60)

def test_logic_consistent():
    """Test consistent plan"""
    plan = {
        "needs_memory": True,
        "memory_keys": ["age"],
        "hallucination_risk": "low"
    }
    result = cim.check_logic_basic(plan)
    return result["consistent"] == True

def test_logic_inconsistent_no_keys():
    """Test inconsistent: needs memory but no keys"""
    plan = {
        "needs_memory": True,
        "memory_keys": [],
        "hallucination_risk": "low"
    }
    result = cim.check_logic_basic(plan)
    return result["consistent"] == False and len(result["issues"]) > 0

def test_logic_inconsistent_high_risk():
    """Test inconsistent: high risk without memory"""
    plan = {
        "needs_memory": False,
        "memory_keys": [],
        "hallucination_risk": "high"
    }
    result = cim.check_logic_basic(plan)
    return result["consistent"] == False

test("Consistent plan passes", test_logic_consistent)
test("Inconsistent plan (no keys) detected", test_logic_inconsistent_no_keys)
test("Inconsistent plan (high risk) detected", test_logic_inconsistent_high_risk)

print("\n📋 TEST GROUP 3: Safety Guards")
print("-" * 60)

def test_clean_text():
    """Test clean text passes"""
    result = cim.safety_guard_lite("What is the weather today?", {})
    return result["safe"] == True

def test_pii_email():
    """Test email detection"""
    result = cim.safety_guard_lite("My email is danny@example.com", {})
    return result["safe"] == False and "email" in result["warning"].lower()

def test_pii_phone():
    """Test phone number detection"""
    result = cim.safety_guard_lite("Call me at 555-123-4567", {})
    return result["safe"] == False and "phone" in result["warning"].lower()

def test_sensitive_keyword():
    """Test sensitive keyword detection"""
    result = cim.safety_guard_lite("Here is my password: secret123", {})
    return result["safe"] == False

test("Clean text passes", test_clean_text)
test("PII email detected", test_pii_email)
test("PII phone detected", test_pii_phone)
test("Sensitive keyword detected", test_sensitive_keyword)

print("\n📋 TEST GROUP 4: Escalation Logic")
print("-" * 60)

def test_escalate_high_risk():
    """Test escalation on high hallucination risk"""
    result = cim.validate_basic(
        intent="Answer question",
        hallucination_risk="high",
        user_text="What is X?",
        thinking_plan={
            "intent": "answer question",
            "hallucination_risk": "high",
            "needs_memory": False,
            "memory_keys": []
        }
    )
    return result["should_escalate"] == True

def test_escalate_complex():
    """Test escalation on complex keywords"""
    result = cim.validate_basic(
        intent="Analyze complex data patterns",
        hallucination_risk="low",
        user_text="Analyze this dataset",
        thinking_plan={
            "intent": "analyze complex data patterns",
            "hallucination_risk": "low",
            "needs_memory": False,
            "memory_keys": []
        }
    )
    return result["should_escalate"] == True

def test_no_escalate_simple():
    """Test no escalation on simple query"""
    result = cim.validate_basic(
        intent="Get weather info",
        hallucination_risk="low",
        user_text="What's the weather?",
        thinking_plan={
            "intent": "get weather info",
            "hallucination_risk": "low",
            "needs_memory": False,
            "memory_keys": []
        }
    )
    return result["should_escalate"] == False

test("Escalate on high risk", test_escalate_high_risk)
test("Escalate on complex keywords", test_escalate_complex)
test("No escalation on simple query", test_no_escalate_simple)

print("\n📋 TEST GROUP 5: Full Integration")
print("-" * 60)

def test_control_layer_has_cim():
    """Test ControlLayer has light_cim"""
    return hasattr(control, 'light_cim')

def test_control_layer_cim_type():
    """Test ControlLayer light_cim is correct type"""
    return isinstance(control.light_cim, LightCIM)

def test_full_validate_basic():
    """Test full validate_basic integration"""
    plan = {
        "intent": "analyze data",
        "hallucination_risk": "low",
        "needs_memory": False,
        "memory_keys": []
    }
    result = control.light_cim.validate_basic(
        intent="analyze data",
        hallucination_risk="low",
        user_text="Can you analyze this?",
        thinking_plan=plan
    )
    return "safe" in result and "confidence" in result and "should_escalate" in result

test("ControlLayer has light_cim", test_control_layer_has_cim)
test("ControlLayer light_cim correct type", test_control_layer_cim_type)
test("Full validate_basic works", test_full_validate_basic)

print("\n📋 TEST GROUP 6: Performance")
print("-" * 60)

def test_performance():
    """Test Light CIM performance (<100ms)"""
    plan = {
        "intent": "analyze sales data",
        "hallucination_risk": "low",
        "needs_memory": True,
        "memory_keys": ["sales"],
        "is_new_fact": False
    }
    
    start = time.time()
    for i in range(10):
        result = cim.validate_basic(
            intent="analyze sales data",
            hallucination_risk="low",
            user_text="Analyze Q4 sales",
            thinking_plan=plan
        )
    end = time.time()
    
    avg_time = (end - start) / 10 * 1000  # Convert to ms
    print(f"   Average time: {avg_time:.2f}ms")
    
    return avg_time < 100  # Should be under 100ms

test("Performance under 100ms", test_performance)

print("\n" + "="*60)
print("📊 TEST RESULTS")
print("="*60)
print(f"Total Tests: {total}")
print(f"Passed: {passed} ✅")
print(f"Failed: {failed} ❌")
print(f"Success Rate: {(passed/total*100):.1f}%")

if failed == 0:
    print("\n🎉 ALL TESTS PASSED! Light CIM is production ready!")
    exit(0)
else:
    print(f"\n⚠️  {failed} test(s) failed. Review needed.")
    exit(1)
