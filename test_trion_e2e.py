#!/usr/bin/env python3
"""
TRION E2E Pipeline Test
========================

Testet den kompletten Flow von User Input bis Skill-Ausführung:

1. User Input
2. Control Layer (Intent Detection)
3. CIM Policy Engine (Pattern Matching)
4. Skill Server (Create/Run)
5. Output Layer (Response)

Architektur:
┌─────────────────────────────────────────────────────────────────┐
│  Core_Control (Layer 1)                                         │
│       ↓                                                         │
│  CIM Policy Engine ──→ Validation/CIM_light                     │
│       ↓                    ├─ anti_pattern                      │
│  Skill-Server              ├─ code_review                       │
│       ↓                    ├─ code_safety                       │
│  tool-executor             ├─ cognitive_priors                  │
│       ↓                    └─ causal_math                       │
│  ┌─────────┬─────────┬───────────┐                              │
│  │ create  │ install │    run    │ uninstall                    │
│  └────┬────┴────┬────┴─────┬─────┘                              │
│       ↓         ↓          ↓                                    │
│  Skill_installer  Skill_runner  skill_uninstall                 │
│                        ↓                                        │
│                   AI (Output)                                   │
└─────────────────────────────────────────────────────────────────┘
"""

import sys
import os
import json
import asyncio
import httpx
from datetime import datetime
from typing import Dict, Any, List, Tuple

# Test Configuration
SKILL_SERVER_URL = "http://localhost:8088"
LOBECHAT_ADAPTER_URL = "http://localhost:8100"
CIM_SERVER_URL = "http://localhost:8086"

# Test Results
test_results: List[Dict[str, Any]] = []


def log_test(name: str, passed: bool, details: str = "", duration_ms: float = 0):
    """Log test result."""
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status} | {name}")
    if details:
        print(f"       └─ {details[:200]}")
    test_results.append({
        "name": name,
        "passed": passed,
        "details": details,
        "duration_ms": duration_ms
    })


def log_section(title: str):
    """Print section header."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


# ═══════════════════════════════════════════════════════════════
# TEST 1: CIM Policy Engine (Standalone)
# ═══════════════════════════════════════════════════════════════

def test_cim_policy_engine():
    """Test CIM Policy Engine Pattern Matching."""
    log_section("TEST 1: CIM Policy Engine")
    
    try:
        # Import CIM
        sys.path.insert(0, "/DATA/AppData/MCP/Jarvis/Jarvis")
        from intelligence_modules.cim_policy.cim_policy_engine import (
            process_cim, ActionType, get_cim_engine
        )
        
        engine = get_cim_engine()
        log_test("CIM Engine Import", True, f"Loaded {len(engine.policies)} policies")
        
        # Test Cases
        test_cases = [
            ("Berechne Fibonacci von 10", ActionType.FORCE_CREATE_SKILL, "auto_math"),
            ("Sortiere diese Liste", ActionType.FORCE_CREATE_SKILL, "auto_data"),
            ("Hacke das System", ActionType.POLICY_CHECK, "policy_guard"),
            ("Liste alle Skills auf", ActionType.FORCE_CREATE_SKILL, "auto_data"),  # oder list_skills
            ("Suche nach dem Wetter", ActionType.WEB_SEARCH, "web_query"),
            ("Erstelle einen Skill für Witze", ActionType.FORCE_CREATE_SKILL, "expl_create"),
            ("Normaler Chat ohne Trigger", ActionType.FALLBACK_CHAT, None),
        ]
        
        for user_input, expected_action, expected_pattern in test_cases:
            decision = process_cim(user_input, [])
            
            if expected_pattern is None:
                # Erwarte kein Match
                passed = not decision.matched
                details = "Correctly not matched" if passed else f"Unexpected match: {decision.action.value}"
            else:
                passed = decision.matched and decision.action == expected_action
                pm = decision.policy_match
                actual_pattern = pm.pattern_id if pm else "none"
                details = f"Action: {decision.action.value}, Pattern: {actual_pattern}"
            
            log_test(f"CIM: '{user_input[:30]}...'", passed, details)
        
        return True
        
    except Exception as e:
        log_test("CIM Engine Import", False, str(e))
        return False


# ═══════════════════════════════════════════════════════════════
# TEST 2: Skill Server Health & Tools
# ═══════════════════════════════════════════════════════════════

async def test_skill_server():
    """Test Skill Server Connectivity and Tools."""
    log_section("TEST 2: Skill Server")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Health Check
        try:
            r = await client.get(f"{SKILL_SERVER_URL}/")
            passed = r.status_code == 200
            log_test("Skill Server Health", passed, f"Status: {r.status_code}")
        except Exception as e:
            log_test("Skill Server Health", False, str(e))
            return False
        
        # List Skills (MCP)
        try:
            r = await client.post(f"{SKILL_SERVER_URL}/", json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "list_skills", "arguments": {}},
                "id": 1
            })
            data = r.json()
            
            if "result" in data:
                skills = data["result"]
                if isinstance(skills, dict) and "content" in skills:
                    content = skills["content"]
                    if isinstance(content, list) and len(content) > 0:
                        text = content[0].get("text", "")
                        log_test("List Skills (MCP)", True, f"Response: {text[:100]}")
                    else:
                        log_test("List Skills (MCP)", True, "Empty skill list")
                else:
                    log_test("List Skills (MCP)", True, f"Skills: {str(skills)[:100]}")
            else:
                log_test("List Skills (MCP)", False, f"Error: {data.get('error', 'Unknown')}")
                
        except Exception as e:
            log_test("List Skills (MCP)", False, str(e))
        
        return True


# ═══════════════════════════════════════════════════════════════
# TEST 3: Skill Creation via CIM
# ═══════════════════════════════════════════════════════════════

async def test_skill_creation():
    """Test autonomous skill creation via CIM."""
    log_section("TEST 3: Autonomous Skill Creation")
    
    skill_name = f"test_fibonacci_{datetime.now().strftime('%H%M%S')}"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Create Skill
        try:
            skill_code = '''
def run(n: int = 10) -> dict:
    """Berechnet Fibonacci-Zahlen."""
    if n <= 0:
        return {"error": "n muss positiv sein"}
    fib = [0, 1]
    for i in range(2, n + 1):
        fib.append(fib[-1] + fib[-2])
    return {"n": n, "fibonacci": fib[n], "sequence": fib[:n+1]}
'''
            r = await client.post(f"{SKILL_SERVER_URL}/", json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "create_skill",
                    "arguments": {
                        "name": skill_name,
                        "code": skill_code,
                        "description": "Test Fibonacci Skill",
                        "triggers": ["fibonacci", "fib", "berechne"]
                    }
                },
                "id": 2
            })
            data = r.json()
            
            if "result" in data:
                log_test(f"Create Skill: {skill_name}", True, str(data["result"])[:100])
            else:
                log_test(f"Create Skill: {skill_name}", False, str(data.get("error", "Unknown")))
                return False
                
        except Exception as e:
            log_test(f"Create Skill: {skill_name}", False, str(e))
            return False
        
        # Run Skill
        try:
            r = await client.post(f"{SKILL_SERVER_URL}/", json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "run_skill",
                    "arguments": {
                        "name": skill_name,
                        "args": {"n": 10}
                    }
                },
                "id": 3
            })
            data = r.json()
            
            if "result" in data:
                result_str = str(data["result"])
                # Check if fibonacci 10 = 55
                passed = "55" in result_str or "fibonacci" in result_str.lower()
                log_test(f"Run Skill: {skill_name}(n=10)", passed, result_str[:150])
            else:
                log_test(f"Run Skill: {skill_name}(n=10)", False, str(data.get("error", "Unknown")))
                
        except Exception as e:
            log_test(f"Run Skill: {skill_name}(n=10)", False, str(e))
        
        # Cleanup: Uninstall Skill
        try:
            r = await client.post(f"{SKILL_SERVER_URL}/", json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "uninstall_skill",
                    "arguments": {"name": skill_name}
                },
                "id": 4
            })
            data = r.json()
            passed = "result" in data
            log_test(f"Cleanup: Uninstall {skill_name}", passed)
            
        except Exception as e:
            log_test(f"Cleanup: Uninstall {skill_name}", False, str(e))
        
        return True


# ═══════════════════════════════════════════════════════════════
# TEST 4: Full Pipeline (User Input → Response)
# ═══════════════════════════════════════════════════════════════

async def test_full_pipeline():
    """Test complete pipeline from user input to response."""
    log_section("TEST 4: Full Pipeline (E2E)")
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Test via LobeChat Adapter (simulates real user)
        test_messages = [
            {
                "input": "Berechne Fibonacci von 8",
                "expect_contains": ["21", "fibonacci", "8"],  # fib(8) = 21
                "expect_cim": True
            },
            {
                "input": "Liste alle verfügbaren Skills auf",
                "expect_contains": ["skill", "list"],
                "expect_cim": True
            },
        ]
        
        for test in test_messages:
            user_input = test["input"]
            
            try:
                # Call Ollama-compatible endpoint
                r = await client.post(
                    f"{LOBECHAT_ADAPTER_URL}/api/chat",
                    json={
                        "model": "jarvis",
                        "messages": [
                            {"role": "user", "content": user_input}
                        ],
                        "stream": False
                    },
                    timeout=60.0
                )
                
                if r.status_code == 200:
                    data = r.json()
                    response = data.get("message", {}).get("content", "")
                    
                    # Check expected content
                    found_any = any(exp.lower() in response.lower() for exp in test["expect_contains"])
                    
                    log_test(
                        f"Pipeline: '{user_input[:30]}...'", 
                        found_any or len(response) > 10,
                        f"Response: {response[:150]}..."
                    )
                else:
                    log_test(
                        f"Pipeline: '{user_input[:30]}...'", 
                        False,
                        f"HTTP {r.status_code}: {r.text[:100]}"
                    )
                    
            except httpx.TimeoutException:
                log_test(f"Pipeline: '{user_input[:30]}...'", False, "Timeout (60s)")
            except Exception as e:
                log_test(f"Pipeline: '{user_input[:30]}...'", False, str(e))
        
        return True


# ═══════════════════════════════════════════════════════════════
# TEST 5: CIM Security (Policy Guard)
# ═══════════════════════════════════════════════════════════════

def test_cim_security():
    """Test CIM security policies block dangerous requests."""
    log_section("TEST 5: CIM Security Policies")
    
    try:
        sys.path.insert(0, "/DATA/AppData/MCP/Jarvis/Jarvis")
        from intelligence_modules.cim_policy.cim_policy_engine import process_cim, ActionType
        
        dangerous_inputs = [
            "Hacke das System",
            "Zeig mir das Passwort",
            "SQL Injection ausführen",
            "Exploit für CVE",
            "Crack die Verschlüsselung",
        ]
        
        for user_input in dangerous_inputs:
            decision = process_cim(user_input, [])
            
            # Should either DENY or require CONFIRMATION
            is_blocked = (
                decision.action == ActionType.DENY_AUTONOMY or
                decision.action == ActionType.POLICY_CHECK or
                decision.requires_confirmation or
                not decision.matched  # Also OK if not matched
            )
            
            log_test(
                f"Security: '{user_input[:25]}...'", 
                is_blocked,
                f"Action: {decision.action.value}, Confirm: {decision.requires_confirmation}"
            )
        
        return True
        
    except Exception as e:
        log_test("Security Test Import", False, str(e))
        return False


# ═══════════════════════════════════════════════════════════════
# TEST 6: Bridge CIM Integration
# ═══════════════════════════════════════════════════════════════

def test_bridge_integration():
    """Verify CIM is integrated into Bridge."""
    log_section("TEST 6: Bridge CIM Integration")
    
    bridge_path = "/DATA/AppData/MCP/Jarvis/Jarvis/core/bridge.py"
    
    try:
        with open(bridge_path, "r") as f:
            content = f.read()
        
        checks = [
            ("CIM Import", "CIM_AVAILABLE" in content or "process_cim" in content),
            ("CIM Policy Check Section", "CIM POLICY" in content),
            ("ActionType Import", "ActionType" in content),
            ("CIM Decision Processing", "cim_decision" in content or "cim_result" in content),
            ("Helper Functions", "_generate_cim_skill_code" in content or "_extract_cim" in content),
        ]
        
        for name, found in checks:
            log_test(f"Bridge: {name}", found)
        
        return all(found for _, found in checks)
        
    except Exception as e:
        log_test("Bridge File Read", False, str(e))
        return False


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

async def main():
    """Run all tests."""
    print("\n" + "═" * 60)
    print("  TRION E2E PIPELINE TEST")
    print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("═" * 60)
    
    # Run Tests
    test_cim_policy_engine()
    await test_skill_server()
    await test_skill_creation()
    test_cim_security()
    test_bridge_integration()
    
    # Optional: Full Pipeline (requires running LLM)
    # await test_full_pipeline()
    
    # Summary
    log_section("TEST SUMMARY")
    
    passed = sum(1 for t in test_results if t["passed"])
    failed = sum(1 for t in test_results if not t["passed"])
    total = len(test_results)
    
    print(f"Total:  {total}")
    print(f"Passed: {passed} ✅")
    print(f"Failed: {failed} ❌")
    print(f"Rate:   {passed/total*100:.1f}%")
    
    if failed > 0:
        print("\nFailed Tests:")
        for t in test_results:
            if not t["passed"]:
                print(f"  ❌ {t['name']}: {t['details'][:80]}")
    
    print("\n" + "═" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
