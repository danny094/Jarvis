#!/usr/bin/env python3
"""
Integration Test: CIM + Sequential Thinking + Full Pipeline
============================================================

Testet die gesamte Kette:
1. CIM Server erreichbar & Session funktioniert
2. Sequential Thinking erreichbar & Session funktioniert  
3. Sequential → CIM Integration
4. End-to-End API Call

Usage:
  python test_cim_sequential_integration.py [--internal]
  
  --internal: Nutzt Docker-interne URLs (cim-server:8086)
  Default: Nutzt localhost URLs (localhost:8086)

Exit Codes:
  0 = Alle Tests bestanden
  1 = Mindestens ein Test fehlgeschlagen
"""

import httpx
import json
import sys
from datetime import datetime
from typing import Dict, Any, Tuple, Optional

# ============================================================
# CONFIGURATION
# ============================================================

class Config:
    # External URLs (from host)
    EXTERNAL = {
        "cim": "http://localhost:8086",
        "sequential": "http://localhost:8085",
        "api": "http://localhost:8200"
    }
    # Internal URLs (from within Docker network)
    INTERNAL = {
        "cim": "http://cim-server:8086",
        "sequential": "http://sequential-thinking:8085",
        "api": "http://jarvis-admin-api:8200"
    }

# ============================================================
# TEST UTILITIES
# ============================================================

class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.results = []
    
    def add(self, name: str, success: bool, details: str = ""):
        self.results.append({
            "name": name,
            "success": success,
            "details": details
        })
        if success:
            self.passed += 1
        else:
            self.failed += 1
    
    def print_summary(self):
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        
        for r in self.results:
            icon = "✅" if r["success"] else "❌"
            print(f"  {icon} {r['name']}")
            if r["details"] and not r["success"]:
                print(f"      → {r['details'][:100]}")
        
        print("-" * 60)
        total = self.passed + self.failed
        print(f"  TOTAL: {self.passed}/{total} passed")
        
        if self.failed == 0:
            print("\n  🎉 ALL TESTS PASSED!")
        else:
            print(f"\n  ⚠️  {self.failed} TEST(S) FAILED")
        
        return self.failed == 0


def log(msg: str, level: str = "INFO"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [{level}] {msg}")


class MCPClient:
    """Helper class for MCP protocol communication."""
    
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.session_id: Optional[str] = None
        self.timeout = 30.0
    
    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        return headers
    
    def _parse_sse(self, text: str) -> Dict[str, Any]:
        """Parse SSE response."""
        for line in text.split("\n"):
            if line.startswith("data: "):
                try:
                    return json.loads(line[6:])
                except:
                    pass
        try:
            return json.loads(text)
        except:
            return {"error": f"Parse failed: {text[:100]}"}
    
    def initialize(self) -> Tuple[bool, str]:
        """Initialize MCP session."""
        try:
            r = httpx.post(
                f"{self.base_url}/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 0,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "integration-test", "version": "1.0"}
                    }
                },
                headers=self._headers(),
                timeout=self.timeout
            )
            
            self.session_id = r.headers.get("mcp-session-id")
            
            if r.status_code == 200 and self.session_id:
                return True, f"Session: {self.session_id[:8]}..."
            else:
                return False, f"Status {r.status_code}, no session"
                
        except Exception as e:
            return False, str(e)
    
    def list_tools(self) -> Tuple[bool, Any]:
        """List available tools."""
        try:
            r = httpx.post(
                f"{self.base_url}/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list"
                },
                headers=self._headers(),
                timeout=self.timeout
            )
            
            if r.status_code != 200:
                return False, f"Status {r.status_code}"
            
            data = self._parse_sse(r.text)
            if "result" in data:
                tools = data["result"].get("tools", [])
                return True, [t["name"] for t in tools]
            
            return False, data.get("error", "Unknown error")
            
        except Exception as e:
            return False, str(e)
    
    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Tuple[bool, Any]:
        """Call a tool."""
        try:
            r = httpx.post(
                f"{self.base_url}/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments}
                },
                headers=self._headers(),
                timeout=60.0  # Longer timeout for tool calls
            )
            
            if r.status_code != 200:
                return False, f"Status {r.status_code}: {r.text[:200]}"
            
            data = self._parse_sse(r.text)
            
            if "result" in data:
                content = data["result"]
                if isinstance(content, dict) and "content" in content:
                    items = content["content"]
                    if isinstance(items, list) and len(items) > 0:
                        text = items[0].get("text", "{}")
                        try:
                            return True, json.loads(text)
                        except:
                            return True, {"raw": text}
                return True, content
            
            if "error" in data:
                return False, data["error"]
            
            return False, "Unknown response format"
            
        except Exception as e:
            return False, str(e)


# ============================================================
# TEST FUNCTIONS
# ============================================================

def test_cim_server(urls: Dict[str, str], results: TestResult):
    """Test CIM Server."""
    log("Testing CIM Server...")
    
    client = MCPClient(urls["cim"])
    
    # Test 1: Session
    success, details = client.initialize()
    results.add("CIM: Session Init", success, details)
    
    if not success:
        results.add("CIM: List Tools", False, "Skipped - no session")
        results.add("CIM: Health Check", False, "Skipped - no session")
        return
    
    # Test 2: List Tools
    success, tools = client.list_tools()
    if success:
        expected = ["analyze", "validate_before", "validate_after", "correct_course", "health"]
        missing = [t for t in expected if t not in tools]
        if missing:
            results.add("CIM: List Tools", False, f"Missing: {missing}")
        else:
            results.add("CIM: List Tools", True, f"{len(tools)} tools found")
    else:
        results.add("CIM: List Tools", False, str(tools))
    
    # Test 3: Health Check
    success, response = client.call_tool("health", {})
    if success and response.get("status") == "healthy":
        results.add("CIM: Health Check", True, f"v{response.get('version', '?')}")
    else:
        results.add("CIM: Health Check", False, str(response))


def test_sequential_server(urls: Dict[str, str], results: TestResult):
    """Test Sequential Thinking Server."""
    log("Testing Sequential Thinking Server...")
    
    client = MCPClient(urls["sequential"])
    
    # Test 1: Session
    success, details = client.initialize()
    results.add("Sequential: Session Init", success, details)
    
    if not success:
        results.add("Sequential: List Tools", False, "Skipped - no session")
        results.add("Sequential: Health Check", False, "Skipped - no session")
        return
    
    # Test 2: List Tools
    success, tools = client.list_tools()
    if success:
        expected = ["think", "think_simple", "health"]
        missing = [t for t in expected if t not in tools]
        if missing:
            results.add("Sequential: List Tools", False, f"Missing: {missing}")
        else:
            results.add("Sequential: List Tools", True, f"{len(tools)} tools found")
    else:
        results.add("Sequential: List Tools", False, str(tools))
    
    # Test 3: Health Check (includes CIM status)
    success, response = client.call_tool("health", {})
    if success and response.get("status") == "healthy":
        cim_status = response.get("cim_status", "unknown")
        version = response.get("version", "?")
        results.add("Sequential: Health Check", True, f"v{version}, CIM: {cim_status}")
    else:
        results.add("Sequential: Health Check", False, str(response))


def test_sequential_cim_integration(urls: Dict[str, str], results: TestResult):
    """Test Sequential → CIM Integration."""
    log("Testing Sequential → CIM Integration...")
    
    client = MCPClient(urls["sequential"])
    
    # Initialize
    success, _ = client.initialize()
    if not success:
        results.add("Integration: Sequential→CIM", False, "Could not init session")
        return
    
    # Call think with CIM enabled
    success, response = client.call_tool("think", {
        "message": "What is 2+2?",
        "steps": 2,
        "use_cim": True
    })
    
    if not success:
        results.add("Integration: Sequential→CIM", False, str(response))
        return
    
    # Check response
    cim_enabled = response.get("cim_enabled", False)
    cim_errors = response.get("cim_errors")
    steps = response.get("total_steps", 0)
    
    if not cim_enabled:
        results.add("Integration: Sequential→CIM", False, "CIM not enabled in response")
    elif cim_errors:
        results.add("Integration: Sequential→CIM", False, f"CIM errors: {cim_errors[0]}")
    elif steps < 1:
        results.add("Integration: Sequential→CIM", False, "No steps completed")
    else:
        # Check if CIM validation data is present
        step1 = response.get("steps", [{}])[0]
        cim_before = step1.get("cim_before", {})
        cim_after = step1.get("cim_after", {})
        
        if "error" in cim_before:
            results.add("Integration: Sequential→CIM", False, f"CIM before error: {cim_before['error']}")
        elif "error" in cim_after:
            results.add("Integration: Sequential→CIM", False, f"CIM after error: {cim_after['error']}")
        else:
            mode = response.get("cim_mode", "unknown")
            results.add("Integration: Sequential→CIM", True, f"{steps} steps, CIM mode: {mode}")


def test_api_endpoint(urls: Dict[str, str], results: TestResult):
    """Test the main API endpoint."""
    log("Testing API Endpoint...")
    
    try:
        r = httpx.post(
            f"{urls['api']}/api/chat",
            json={
                "message": "Hello",
                "persona": "default"
            },
            timeout=60.0
        )
        
        if r.status_code != 200:
            results.add("API: Chat Endpoint", False, f"Status {r.status_code}")
            return
        
        data = r.json()
        content = data.get("message", {}).get("content", "")
        
        if "Server-Fehler" in content or "Error" in content:
            results.add("API: Chat Endpoint", False, content[:100])
        elif len(content) > 0:
            results.add("API: Chat Endpoint", True, f"Response: {len(content)} chars")
        else:
            results.add("API: Chat Endpoint", False, "Empty response")
            
    except Exception as e:
        results.add("API: Chat Endpoint", False, str(e))


# ============================================================
# MAIN
# ============================================================

def main():
    # Parse args
    use_internal = "--internal" in sys.argv
    urls = Config.INTERNAL if use_internal else Config.EXTERNAL
    
    print("=" * 60)
    print("CIM + SEQUENTIAL THINKING INTEGRATION TEST")
    print("=" * 60)
    print(f"Mode: {'Internal (Docker)' if use_internal else 'External (localhost)'}")
    print(f"CIM URL: {urls['cim']}")
    print(f"Sequential URL: {urls['sequential']}")
    print(f"API URL: {urls['api']}")
    print("=" * 60)
    
    results = TestResult()
    
    # Run tests
    test_cim_server(urls, results)
    print()
    test_sequential_server(urls, results)
    print()
    test_sequential_cim_integration(urls, results)
    print()
    test_api_endpoint(urls, results)
    
    # Summary
    all_passed = results.print_summary()
    
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
