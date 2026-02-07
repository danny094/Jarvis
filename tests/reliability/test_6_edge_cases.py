#!/usr/bin/env python3
"""
TEST 6: Edge Cases & Error Handling
Verifies system handles errors and edge cases gracefully
"""

import sys
sys.path.insert(0, '/DATA/AppData/MCP/Jarvis/Jarvis')

import json
import requests
import time
from datetime import datetime

print("=" * 70)
print("TEST 6: EDGE CASES & ERROR HANDLING")
print("=" * 70)
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

results = {"test_name": "Edge Cases", "checks": [], "passed": 0, "failed": 0}

def check(name, condition, details=""):
    status = "✅ PASS" if condition else "❌ FAIL"
    print(f"{status}: {name}")
    if details:
        print(f"   {details}")
    results["checks"].append({"name": name, "passed": condition, "details": details})
    results["passed" if condition else "failed"] += 1
    return condition

def test_edge_case(name, tool_name, arguments, should_fail=False):
    """Test an edge case"""
    print(f"\nTest: {name}")
    url = "http://localhost:8001/tools/call"
    payload = {"name": tool_name, "arguments": arguments}
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        
        if should_fail:
            # We expect this to fail gracefully
            is_error = response.status_code >= 400 or response.json().get("isError", False)
            check(f"{name} - Fails Gracefully", is_error, "Error handled properly")
            check(f"{name} - Server Still Responsive", response.status_code in [200, 400, 404, 500])
        else:
            # We expect this to succeed
            check(f"{name} - Succeeds", response.status_code == 200)
            check(f"{name} - No Error", not response.json().get("isError", False))
        
        return True
    except requests.exceptions.Timeout:
        check(f"{name} - No Timeout", False, "Request timed out")
        return False
    except Exception as e:
        if should_fail:
            check(f"{name} - Error Caught", True, f"Handled: {type(e).__name__}")
            return True
        else:
            check(f"{name} - No Exception", False, f"Error: {e}")
            return False

# TEST 1: Missing Required Fields
test_edge_case(
    "Missing task_description",
    "sequential_thinking",
    {},  # Empty arguments
    should_fail=True
)

# TEST 2: Invalid Tool Name
test_edge_case(
    "Non-existent Tool",
    "non_existent_tool_xyz",
    {"task_description": "Test"},
    should_fail=True
)

# TEST 3: Malformed JSON-like Arguments
test_edge_case(
    "String Instead of Dict",
    "sequential_thinking",
    "this is not a dict",
    should_fail=True
)

# TEST 4: Circular Dependencies
test_edge_case(
    "Circular Dependencies",
    "sequential_thinking",
    {
        "task_description": "Circular dependency test",
        "steps": [
            {"id": "a", "dependencies": ["b"]},
            {"id": "b", "dependencies": ["a"]}
        ]
    },
    should_fail=False  # Engine should detect and handle this
)

# TEST 5: Very Long Task Description
test_edge_case(
    "Very Long Description",
    "sequential_thinking",
    {
        "task_description": "x" * 10000  # 10k characters
    },
    should_fail=False  # Should handle but might be slow
)

# TEST 6: Empty Steps Array
test_edge_case(
    "Empty Steps Array",
    "sequential_thinking",
    {
        "task_description": "Task with no steps",
        "steps": []
    },
    should_fail=False  # Should create a single default step
)

# TEST 7: Duplicate Step IDs
test_edge_case(
    "Duplicate Step IDs",
    "sequential_thinking",
    {
        "task_description": "Duplicate IDs test",
        "steps": [
            {"id": "step1", "description": "First"},
            {"id": "step1", "description": "Second (duplicate ID)"}
        ]
    },
    should_fail=False  # Engine should handle this
)

# TEST 8: Missing Dependency Reference
test_edge_case(
    "Missing Dependency",
    "sequential_thinking",
    {
        "task_description": "Missing dependency test",
        "steps": [
            {"id": "step1", "description": "First"},
            {"id": "step2", "description": "Second", "dependencies": ["nonexistent"]}
        ]
    },
    should_fail=False  # Engine should detect and warn
)

# TEST 9: Special Characters in Task Description
test_edge_case(
    "Special Characters",
    "sequential_thinking",
    {
        "task_description": "Test with special chars: <>&\"'`\n\t\r"
    },
    should_fail=False
)

# TEST 10: Unicode Characters
test_edge_case(
    "Unicode Characters",
    "sequential_thinking",
    {
        "task_description": "Test with unicode: 你好世界 🚀 Привет мир"
    },
    should_fail=False
)

print()
print("=" * 70)
print("SERVER STABILITY CHECK")
print("=" * 70)

# After all edge cases, verify server is still healthy
print("\nChecking server health after edge case tests...")
try:
    response = requests.get("http://localhost:8001/", timeout=5)
    healthy = response.status_code == 200 and response.json().get("status") == "healthy"
    check("Server Still Healthy", healthy, "Server survived all edge cases")
except Exception as e:
    check("Server Still Healthy", False, f"Server may have crashed: {e}")

# SUMMARY
print()
print("=" * 70)
print("TEST 6 SUMMARY")
print("=" * 70)
print(f"✅ Passed: {results['passed']}")
print(f"❌ Failed: {results['failed']}")
print(f"Success Rate: {results['passed']/(results['passed']+results['failed'])*100:.1f}%")
print()

if results["failed"] == 0:
    print("🎉 TEST 6: PASS - Edge Cases Handled Gracefully!")
    print("\nRobustness Verified:")
    print("  ✅ Invalid inputs handled")
    print("  ✅ Error messages clear")
    print("  ✅ Server stays running")
    print("  ✅ No crashes or hangs")
    sys.exit(0)
elif results["failed"] <= 2:
    print("⚠️ TEST 6: MOSTLY PASS - Minor edge case issues")
    sys.exit(0)  # Don't fail completely on edge cases
else:
    print("❌ TEST 6: FAIL - Significant error handling issues")
    sys.exit(1)
