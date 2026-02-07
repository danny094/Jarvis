#!/usr/bin/env python3
"""
Test: CIM Server Verbindung
===========================
Testet verschiedene Wege, den CIM Server aufzurufen.
Ziel: Herausfinden warum 406 Not Acceptable kommt.

Usage:
  python test_cim_connection.py

Läuft INNERHALB des Docker-Netzwerks (z.B. von jarvis-admin-api Container)
oder von außen mit localhost:8086
"""

import httpx
import json
import sys
from datetime import datetime

# Config - Anpassen je nach wo der Test läuft
CIM_URL_INTERNAL = "http://cim-server:8086"  # Innerhalb Docker
CIM_URL_EXTERNAL = "http://localhost:8086"   # Von außen

def log(msg: str, level: str = "INFO"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [{level}] {msg}")

def test_health_simple(base_url: str) -> dict:
    """Test 1: Einfacher GET auf Root"""
    log(f"TEST 1: GET {base_url}/")
    try:
        r = httpx.get(f"{base_url}/", timeout=5)
        return {"status": r.status_code, "body": r.text[:200]}
    except Exception as e:
        return {"error": str(e)}

def test_mcp_no_headers(base_url: str) -> dict:
    """Test 2: POST /mcp ohne spezielle Headers (wie Sequential es macht)"""
    log(f"TEST 2: POST {base_url}/mcp - OHNE spezielle Headers")
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list"
    }
    try:
        r = httpx.post(
            f"{base_url}/mcp",
            json=payload,
            timeout=10
        )
        return {"status": r.status_code, "body": r.text[:500]}
    except Exception as e:
        return {"error": str(e)}

def test_mcp_with_accept_headers(base_url: str) -> dict:
    """Test 3: POST /mcp MIT Accept Headers"""
    log(f"TEST 3: POST {base_url}/mcp - MIT Accept Headers")
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list"
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"
    }
    try:
        r = httpx.post(
            f"{base_url}/mcp",
            json=payload,
            headers=headers,
            timeout=10
        )
        return {"status": r.status_code, "body": r.text[:500]}
    except Exception as e:
        return {"error": str(e)}

def test_mcp_with_session(base_url: str) -> dict:
    """Test 4: POST /mcp mit Session initialisierung"""
    log(f"TEST 4: POST {base_url}/mcp - Session Init Flow")
    
    # Step 1: Initialize request
    init_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"}
        }
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"
    }
    try:
        r = httpx.post(
            f"{base_url}/mcp",
            json=init_payload,
            headers=headers,
            timeout=10
        )
        
        result = {"init_status": r.status_code}
        
        # Check for session ID in response headers
        session_id = r.headers.get("mcp-session-id")
        result["session_id"] = session_id
        result["init_body"] = r.text[:300]
        
        if session_id and r.status_code == 200:
            # Step 2: Use session for tools/list
            log(f"  → Session ID: {session_id}")
            headers["mcp-session-id"] = session_id
            
            list_payload = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list"
            }
            r2 = httpx.post(
                f"{base_url}/mcp",
                json=list_payload,
                headers=headers,
                timeout=10
            )
            result["list_status"] = r2.status_code
            result["list_body"] = r2.text[:500]
        
        return result
    except Exception as e:
        return {"error": str(e)}

def test_direct_tool_call(base_url: str) -> dict:
    """Test 5: Direkter Tool Call (wie Sequential._call_cim macht)"""
    log(f"TEST 5: Direkter health Tool Call")
    
    # Erst Session holen
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"
    }
    
    init_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0"}
        }
    }
    
    try:
        r = httpx.post(f"{base_url}/mcp", json=init_payload, headers=headers, timeout=10)
        session_id = r.headers.get("mcp-session-id")
        
        if not session_id:
            return {"error": "No session ID received", "status": r.status_code, "body": r.text[:300]}
        
        # Tool call
        headers["mcp-session-id"] = session_id
        tool_payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "health",
                "arguments": {}
            }
        }
        
        r2 = httpx.post(f"{base_url}/mcp", json=tool_payload, headers=headers, timeout=10)
        return {
            "session_id": session_id,
            "status": r2.status_code,
            "body": r2.text[:500]
        }
    except Exception as e:
        return {"error": str(e)}

def run_all_tests(base_url: str):
    """Führt alle Tests aus"""
    print("=" * 60)
    print(f"CIM CONNECTION TESTS - {base_url}")
    print("=" * 60)
    print()
    
    tests = [
        ("Health Simple", test_health_simple),
        ("MCP ohne Headers", test_mcp_no_headers),
        ("MCP mit Accept Headers", test_mcp_with_accept_headers),
        ("MCP mit Session", test_mcp_with_session),
        ("Direct Tool Call", test_direct_tool_call),
    ]
    
    results = {}
    for name, test_fn in tests:
        print(f"\n{'─' * 50}")
        result = test_fn(base_url)
        results[name] = result
        
        # Status ausgeben
        status = result.get("status") or result.get("init_status") or "ERROR"
        if "error" in result:
            log(f"RESULT: ❌ ERROR - {result['error']}", "ERROR")
        elif status == 200:
            log(f"RESULT: ✅ {status} OK", "OK")
        elif status == 406:
            log(f"RESULT: ❌ {status} Not Acceptable", "FAIL")
        elif status == 400:
            log(f"RESULT: ⚠️  {status} Bad Request", "WARN")
        else:
            log(f"RESULT: ⚠️  {status}", "WARN")
        
        # Body preview
        body = result.get("body") or result.get("init_body") or ""
        if body:
            print(f"  Body: {body[:150]}...")
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    for name, result in results.items():
        status = result.get("status") or result.get("init_status") or "ERR"
        icon = "✅" if status == 200 else "❌" if status in [406, 400] else "⚠️"
        print(f"  {icon} {name}: {status}")
    
    return results

if __name__ == "__main__":
    # Bestimme welche URL
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        # Default: externe URL (localhost)
        url = CIM_URL_EXTERNAL
    
    run_all_tests(url)
