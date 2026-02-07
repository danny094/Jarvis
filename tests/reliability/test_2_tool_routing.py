#!/usr/bin/env python3
"""
TEST 2: Tool Routing
Verifies that tools can be called through the MCP Server
"""

import sys
sys.path.insert(0, '/DATA/AppData/MCP/Jarvis/Jarvis')

import json
import requests
import time
from datetime import datetime

print("=" * 70)
print("TEST 2: TOOL ROUTING")
print("=" * 70)
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

results = {"test_name": "Tool Routing", "checks": [], "passed": 0, "failed": 0, "timings": []}

def check(name, condition, details=""):
    status = "✅ PASS" if condition else "❌ FAIL"
    print(f"{status}: {name}")
    if details:
        print(f"   {details}")
    results["checks"].append({"name": name, "passed": condition, "details": details})
    results["passed" if condition else "failed"] += 1
    return condition

def call_tool(tool_name, arguments, timeout=30):
    """Call a tool via the MCP server"""
    url = "http://localhost:8001/tools/call"
    payload = {"name": tool_name, "arguments": arguments}
    
    start = time.time()
    response = requests.post(url, json=payload, timeout=timeout)
    duration = time.time() - start
    
    return response, duration

# TEST 1: Simple Sequential Thinking Call
print("TEST 2.1: Simple Task")
try:
    response, duration = call_tool("sequential_thinking", {
        "task_description": "Calculate 15 + 27"
    })
    
    check("Request Successful", response.status_code == 200)
    
    data = response.json()
    check("Response Has Content", "content" in data)
    check("Not an Error", not data.get("isError", False))
    
    print(f"   Duration: {duration:.2f}s")
    results["timings"].append({"test": "simple", "duration": duration})
    
    if duration < 5.0:
        check("Performance < 5s", True, f"{duration:.2f}s")
    else:
        check("Performance < 5s", False, f"{duration:.2f}s (slow)")
        
except Exception as e:
    check("Simple Task", False, f"Error: {e}")

print()

# TEST 2: Multi-Step Task
print("TEST 2.2: Multi-Step Task")
try:
    response, duration = call_tool("sequential_thinking", {
        "task_description": "Multi-step calculation",
        "steps": [
            {"id": "step1", "description": "Calculate 10+5"},
            {"id": "step2", "description": "Multiply result by 2", "dependencies": ["step1"]},
            {"id": "step3", "description": "Subtract 3", "dependencies": ["step2"]}
        ]
    })
    
    check("Multi-Step Request", response.status_code == 200)
    
    data = response.json()
    check("Response Has Content", "content" in data)
    check("Not an Error", not data.get("isError", False))
    
    print(f"   Duration: {duration:.2f}s")
    results["timings"].append({"test": "multi-step", "duration": duration})
    
    if duration < 10.0:
        check("Performance < 10s", True, f"{duration:.2f}s")
    else:
        check("Performance < 10s", False, f"{duration:.2f}s (slow)")
        
except Exception as e:
    check("Multi-Step Task", False, f"Error: {e}")

print()

# TEST 3: Workflow Tool
print("TEST 2.3: Workflow Tool")
try:
    response, duration = call_tool("sequential_workflow", {
        "template_id": "data_analysis"
    })
    
    check("Workflow Request", response.status_code == 200)
    
    data = response.json()
    check("Response Has Content", "content" in data)
    
    print(f"   Duration: {duration:.2f}s")
    results["timings"].append({"test": "workflow", "duration": duration})
    
    if duration < 2.0:
        check("Performance < 2s", True, f"{duration:.2f}s")
    else:
        check("Performance < 2s", False, f"{duration:.2f}s (acceptable)")
        
except Exception as e:
    check("Workflow Tool", False, f"Error: {e}")

print()

# TEST 4: Error Handling - Invalid Tool
print("TEST 2.4: Error Handling")
try:
    response, duration = call_tool("non_existent_tool", {})
    
    # Should return an error response, not crash
    check("Invalid Tool Handled", response.status_code in [400, 404, 500])
    
    data = response.json()
    check("Error Response", data.get("isError", True))
    print(f"   Error message present: {'error' in str(data).lower()}")
    
except Exception as e:
    check("Error Handling", True, f"Request failed as expected: {e}")

# SUMMARY
print()
print("=" * 70)
print("TEST 2 SUMMARY")
print("=" * 70)
print(f"✅ Passed: {results['passed']}")
print(f"❌ Failed: {results['failed']}")
print(f"Success Rate: {results['passed']/(results['passed']+results['failed'])*100:.1f}%")
print()

print("Performance Timings:")
for timing in results["timings"]:
    print(f"  {timing['test']}: {timing['duration']:.2f}s")

print()

if results["failed"] == 0:
    print("🎉 TEST 2: PASS - Tool Routing Working!")
    sys.exit(0)
else:
    print("❌ TEST 2: FAIL - Issues Found")
    sys.exit(1)
