#!/usr/bin/env python3
"""
TEST 1: MCP Hub Discovery
Verifies that MCP Hub can discover and register our Sequential Thinking server
"""

import sys
sys.path.insert(0, '/DATA/AppData/MCP/Jarvis/Jarvis')

import json
from datetime import datetime

print("=" * 70)
print("TEST 1: MCP HUB DISCOVERY")
print("=" * 70)
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

results = {"test_name": "Hub Discovery", "checks": [], "passed": 0, "failed": 0}

def check(name, condition, details=""):
    status = "✅ PASS" if condition else "❌ FAIL"
    print(f"{status}: {name}")
    if details:
        print(f"   {details}")
    results["checks"].append({"name": name, "passed": condition, "details": details})
    results["passed" if condition else "failed"] += 1
    return condition

# CHECK 1: Import MCP Registry
print("CHECK 1: Import MCP Registry")
try:
    from mcp_registry import MCPS as MCP_SERVERS
    check("Import MCP Registry", True, f"Found {len(MCP_SERVERS)} servers")
except Exception as e:
    check("Import MCP Registry", False, f"Error: {e}")
    sys.exit(1)

print()

# CHECK 2: Sequential Server Registered
print("CHECK 2: Sequential Server Registered")
seq_server = MCP_SERVERS.get("sequential-thinking")
if check("Server in Registry", seq_server is not None):
    check("Server Enabled", seq_server.get("enabled", False))
    check("Server URL", seq_server.get("url") == "http://localhost:8001")
    print(f"   URL: {seq_server.get('url')}")
    print(f"   Description: {seq_server.get('description')}")

print()

# CHECK 3: Server is Reachable
print("CHECK 3: Server Health Check")
try:
    import requests
    response = requests.get("http://localhost:8001/", timeout=5)
    check("Server Reachable", response.status_code == 200)
    
    data = response.json()
    check("Server Name", data.get("name") == "sequential-thinking")
    check("Server Status", data.get("status") == "healthy")
    print(f"   Version: {data.get('version')}")
except Exception as e:
    check("Server Reachable", False, f"Error: {e}")

print()

# CHECK 4: Tools Endpoint
print("CHECK 4: Tools Discovery")
try:
    response = requests.get("http://localhost:8001/tools", timeout=5)
    check("Tools Endpoint", response.status_code == 200)
    
    tools_data = response.json()
    tools = tools_data.get("tools", [])
    tool_names = [t["name"] for t in tools]
    
    check("Tools Found", len(tools) > 0, f"Found {len(tools)} tools")
    check("sequential_thinking tool", "sequential_thinking" in tool_names)
    check("sequential_workflow tool", "sequential_workflow" in tool_names)
    
    print("\n   Available Tools:")
    for tool in tools:
        print(f"   - {tool['name']}: {tool.get('description', 'No description')}")
except Exception as e:
    check("Tools Endpoint", False, f"Error: {e}")

# SUMMARY
print()
print("=" * 70)
print("TEST 1 SUMMARY")
print("=" * 70)
print(f"✅ Passed: {results['passed']}")
print(f"❌ Failed: {results['failed']}")
print(f"Success Rate: {results['passed']/(results['passed']+results['failed'])*100:.1f}%")
print()

if results["failed"] == 0:
    print("🎉 TEST 1: PASS - Hub Discovery Working!")
    sys.exit(0)
else:
    print("❌ TEST 1: FAIL - Issues Found")
    sys.exit(1)
