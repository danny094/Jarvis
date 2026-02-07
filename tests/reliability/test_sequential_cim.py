#!/usr/bin/env python3
"""Direct test: Sequential Thinking -> CIM"""
import httpx
import json

SEQ_URL = "http://localhost:8085"

def test_sequential_with_cim():
    print("=== DIRECT TEST: Sequential -> CIM ===")
    
    # 1. Initialize session
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"
    }
    
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0"}
        }
    }
    
    r = httpx.post(f"{SEQ_URL}/mcp", json=init, headers=headers, timeout=30)
    session_id = r.headers.get("mcp-session-id")
    print(f"Session: {session_id[:8]}...")
    
    headers["mcp-session-id"] = session_id
    
    # 2. Call think with use_cim=True
    call = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "think",
            "arguments": {
                "message": "What are the pros and cons of electric cars?",
                "steps": 2,
                "use_cim": True
            }
        }
    }
    
    print("Calling think with CIM enabled...")
    r = httpx.post(f"{SEQ_URL}/mcp", json=call, headers=headers, timeout=120)
    print(f"Status: {r.status_code}")
    
    # Parse SSE response
    for line in r.text.split("\n"):
        if line.startswith("data: "):
            data = json.loads(line[6:])
            if "result" in data:
                result = data["result"]
                if "content" in result:
                    text = result["content"][0].get("text", "{}")
                    parsed = json.loads(text)
                    print(f"\nSuccess: {parsed.get('success')}")
                    print(f"CIM Enabled: {parsed.get('cim_enabled')}")
                    print(f"CIM Mode: {parsed.get('cim_mode')}")
                    print(f"CIM Errors: {parsed.get('cim_errors')}")
                    print(f"Steps: {parsed.get('total_steps')}")
                    print(f"Summary: {parsed.get('summary')}")
                    
                    # Check first step for CIM data
                    if parsed.get("steps"):
                        step1 = parsed["steps"][0]
                        print(f"\nStep 1 CIM Before: {step1.get('cim_before')}")
                        print(f"Step 1 CIM After: {step1.get('cim_after')}")

if __name__ == "__main__":
    test_sequential_with_cim()
