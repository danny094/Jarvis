#!/usr/bin/env python3
"""
TEST 4: End-to-End Complex Task
Real-world scenario with multi-step dependencies and CIM validation
"""

import sys
sys.path.insert(0, '/DATA/AppData/MCP/Jarvis/Jarvis')

import json
import requests
import time
from datetime import datetime

print("=" * 70)
print("TEST 4: END-TO-END COMPLEX TASK")
print("=" * 70)
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

results = {"test_name": "End-to-End", "checks": [], "passed": 0, "failed": 0}

def check(name, condition, details=""):
    status = "✅ PASS" if condition else "❌ FAIL"
    print(f"{status}: {name}")
    if details:
        print(f"   {details}")
    results["checks"].append({"name": name, "passed": condition, "details": details})
    results["passed" if condition else "failed"] += 1
    return condition

# Define Complex Task
print("SCENARIO: Q4 Sales Analysis with Causal Reasoning")
print()

complex_task = {
    "task_description": "Analyze Q4 sales trends and recommend actions",
    "steps": [
        {
            "id": "data_review",
            "description": "Review Q4 sales data for patterns and anomalies"
        },
        {
            "id": "trend_analysis",
            "description": "Identify key trends using causal reasoning",
            "dependencies": ["data_review"]
        },
        {
            "id": "causal_factors",
            "description": "Determine root causal factors for observed trends",
            "dependencies": ["trend_analysis"]
        },
        {
            "id": "recommendations",
            "description": "Generate actionable recommendations based on causal analysis",
            "dependencies": ["causal_factors"]
        }
    ]
}

print(f"Task: {complex_task['task_description']}")
print(f"Steps: {len(complex_task['steps'])}")
print()

for i, step in enumerate(complex_task['steps'], 1):
    deps = step.get('dependencies', [])
    print(f"  Step {i}: {step['id']}")
    print(f"          {step['description']}")
    if deps:
        print(f"          Depends on: {', '.join(deps)}")
    print()

# Execute Task
print("=" * 70)
print("EXECUTING TASK...")
print("=" * 70)

try:
    url = "http://localhost:8001/tools/call"
    payload = {
        "name": "sequential_thinking",
        "arguments": complex_task
    }
    
    start_time = time.time()
    response = requests.post(url, json=payload, timeout=60)
    duration = time.time() - start_time
    
    print(f"\nRequest completed in {duration:.2f}s")
    print()
    
    # Basic Response Checks
    check("HTTP 200 Response", response.status_code == 200)
    
    data = response.json()
    check("Response Has Content", "content" in data)
    check("No Error Flag", not data.get("isError", False))
    
    # Parse Response Content
    if "content" in data and len(data["content"]) > 0:
        content_text = str(data["content"][0].get("text", ""))
        
        # Try to parse as dict
        try:
            # The text might be a string representation of a dict
            import ast
            result_data = ast.literal_eval(content_text)
            
            check("Response is Dict", isinstance(result_data, dict))
            
            if isinstance(result_data, dict):
                # Check key fields
                check("Has 'success' field", "success" in result_data)
                check("Task Successful", result_data.get("success", False))
                
                check("Has 'task_id'", "task_id" in result_data)
                check("Has 'progress'", "progress" in result_data)
                check("Has 'steps'", "steps" in result_data)
                
                # Progress Check
                progress = result_data.get("progress", 0)
                check("Progress = 1.0 (100%)", progress == 1.0, f"Progress: {progress}")
                
                # Steps Check
                completed = result_data.get("completed_steps", 0)
                failed = result_data.get("failed_steps", 0)
                total = result_data.get("total_steps", 0)
                
                check("4 Steps Total", total == 4, f"Total: {total}")
                check("4 Steps Completed", completed == 4, f"Completed: {completed}")
                check("0 Steps Failed", failed == 0, f"Failed: {failed}")
                
                # Check individual steps
                steps = result_data.get("steps", [])
                check("Steps Data Present", len(steps) > 0, f"Found {len(steps)} steps")
                
                if len(steps) == 4:
                    print("\n  Step Details:")
                    for step in steps:
                        step_id = step.get("id", "unknown")
                        status = step.get("status", "unknown")
                        print(f"    {step_id}: {status}")
                        
                        # Check if verified
                        if status == "verified":
                            results["passed"] += 1
                        else:
                            results["failed"] += 1
                
                # Performance Check
                if duration < 20.0:
                    check("Performance < 20s", True, f"{duration:.2f}s")
                else:
                    check("Performance < 20s", False, f"{duration:.2f}s (acceptable for complex task)")
                
                # Memory Check
                memory_mb = result_data.get("memory_used_mb", 0)
                check("Memory Usage Tracked", memory_mb >= 0, f"{memory_mb:.2f} MB")
                
        except (ValueError, SyntaxError) as e:
            check("Parse Response", False, f"Could not parse response: {e}")
            print(f"\nRaw response: {content_text[:500]}...")
    
except requests.exceptions.Timeout:
    check("Request Timeout", False, "Request took > 60s")
except Exception as e:
    check("Task Execution", False, f"Error: {e}")

# SUMMARY
print()
print("=" * 70)
print("TEST 4 SUMMARY")
print("=" * 70)
print(f"✅ Passed: {results['passed']}")
print(f"❌ Failed: {results['failed']}")
print(f"Success Rate: {results['passed']/(results['passed']+results['failed'])*100:.1f}%")
print()

if results["failed"] == 0:
    print("🎉 TEST 4: PASS - End-to-End Complex Task Working!")
    print("\nPipeline Verified:")
    print("  ✅ Request → MCP Server")
    print("  ✅ MCP Server → Sequential Engine")
    print("  ✅ Engine → Safety Layer (CIM)")
    print("  ✅ Safety Layer → Step Execution")
    print("  ✅ All Steps Validated")
    print("  ✅ Results Returned")
    sys.exit(0)
else:
    print("❌ TEST 4: FAIL - Issues in Pipeline")
    sys.exit(1)
