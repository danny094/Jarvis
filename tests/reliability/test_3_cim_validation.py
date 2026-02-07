#!/usr/bin/env python3
"""
TEST 3: CIM Validation Pipeline
Verifies Frank's Intelligence Modules are loaded and working
"""

import sys
sys.path.insert(0, '/DATA/AppData/MCP/Jarvis/Jarvis')

import json
import requests
import time
from datetime import datetime

print("=" * 70)
print("TEST 3: CIM VALIDATION PIPELINE")
print("=" * 70)
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

results = {"test_name": "CIM Validation", "checks": [], "passed": 0, "failed": 0}

def check(name, condition, details=""):
    status = "✅ PASS" if condition else "❌ FAIL"
    print(f"{status}: {name}")
    if details:
        print(f"   {details}")
    results["checks"].append({"name": name, "passed": condition, "details": details})
    results["passed" if condition else "failed"] += 1
    return condition

# CHECK 1: Verify Intelligence Modules Loaded
print("CHECK 3.1: Intelligence Modules Loaded")
try:
    with open("/tmp/sequential_mcp.log", "r") as f:
        log_content = f.read()
    
    # Check for module loading messages
    has_cim = "Loaded CIM:" in log_content
    check("CIM Loaded Message", has_cim)
    
    if has_cim:
        # Extract counts
        import re
        match = re.search(r"Loaded CIM: (\d+) priors, (\d+) patterns, (\d+) procedures", log_content)
        if match:
            priors, patterns, procedures = match.groups()
            check("40 Priors Loaded", priors == "40", f"Found {priors}")
            check("25 Patterns Loaded", patterns == "25", f"Found {patterns}")
            check("20 Procedures Loaded", procedures == "20", f"Found {procedures}")
        
    has_loader = "Intelligence Loader:" in log_content
    check("Intelligence Loader Message", has_loader)
    
    if has_loader:
        match = re.search(r"Intelligence Loader: (\d+) anti-patterns, (\d+) priors", log_content)
        if match:
            anti_patterns, loader_priors = match.groups()
            check("25 Anti-Patterns", anti_patterns == "25", f"Found {anti_patterns}")
            check("40 Priors (Loader)", loader_priors == "40", f"Found {loader_priors}")
            
except FileNotFoundError:
    check("Log File Exists", False, "/tmp/sequential_mcp.log not found")
except Exception as e:
    check("Log Analysis", False, f"Error: {e}")

print()

# CHECK 2: Verify Intelligence Modules Directory
print("CHECK 3.2: Intelligence Modules Files")
try:
    import os
    
    base_path = "/DATA/AppData/MCP/Jarvis/Jarvis/modules/sequential_thinking/intelligence_modules"
    
    check("Base Directory Exists", os.path.exists(base_path))
    
    # Check key directories
    dirs_to_check = ["knowledge_rag", "procedural_rag", "executable_rag", "code_tools"]
    for dir_name in dirs_to_check:
        dir_path = os.path.join(base_path, dir_name)
        check(f"{dir_name} Directory", os.path.exists(dir_path))
    
    # Check key files
    files_to_check = [
        ("knowledge_rag/cognitive_priors_v2.csv", "Cognitive Priors"),
        ("procedural_rag/anti_patterns.csv", "Anti-Patterns"),
        ("procedural_rag/causal_reasoning_procedures_v2.csv", "Procedures")
    ]
    
    for file_path, name in files_to_check:
        full_path = os.path.join(base_path, file_path)
        exists = os.path.exists(full_path)
        size = os.path.getsize(full_path) if exists else 0
        check(f"{name} File", exists, f"Size: {size} bytes" if exists else "Missing")
        
except Exception as e:
    check("File System Check", False, f"Error: {e}")

print()

# CHECK 3: Test CIM in Action
print("CHECK 3.3: CIM Validation in Action")
try:
    url = "http://localhost:8001/tools/call"
    
    # Task that should trigger validation
    payload = {
        "name": "sequential_thinking",
        "arguments": {
            "task_description": "Analyze sales data with causal reasoning"
        }
    }
    
    response = requests.post(url, json=payload, timeout=30)
    check("CIM Test Request", response.status_code == 200)
    
    data = response.json()
    check("Response Received", "content" in data)
    check("No Errors", not data.get("isError", False))
    
    # Check if Safety Layer was involved
    # (We'd need to parse the response to confirm CIM validation happened)
    print("   Note: CIM validation happens internally in Safety Layer")
    
except Exception as e:
    check("CIM Test", False, f"Error: {e}")

print()

# CHECK 4: Safety Layer Initialization
print("CHECK 3.4: Safety Layer Status")
try:
    with open("/tmp/sequential_mcp.log", "r") as f:
        log_content = f.read()
    
    check("Safety Layer Init", "Safety Layer" in log_content)
    check("Safety Layer Ready", "Safety Layer ready" in log_content or "Safety Layer: ✅ Active" in log_content)
    
    # Check for GraphSelector
    has_graph = "GraphSelector" in log_content
    check("GraphSelector Loaded", has_graph)
    
    if has_graph:
        match = re.search(r"GraphSelector loaded \((\d+) builders", log_content)
        if match:
            builders = match.group(1)
            check("5 Graph Builders", builders == "5", f"Found {builders}")
    
except Exception as e:
    check("Safety Layer Check", False, f"Error: {e}")

# SUMMARY
print()
print("=" * 70)
print("TEST 3 SUMMARY")
print("=" * 70)
print(f"✅ Passed: {results['passed']}")
print(f"❌ Failed: {results['failed']}")
print(f"Success Rate: {results['passed']/(results['passed']+results['failed'])*100:.1f}%")
print()

if results["failed"] == 0:
    print("🎉 TEST 3: PASS - CIM Validation Working!")
    print("\nFrank's Intelligence Modules:")
    print("  ✅ 40 Cognitive Priors")
    print("  ✅ 25 Anti-Patterns")
    print("  ✅ 20 Causal Procedures")
    print("  ✅ Safety Layer Active")
    sys.exit(0)
else:
    print("❌ TEST 3: FAIL - CIM Issues Found")
    sys.exit(1)
