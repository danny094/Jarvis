import asyncio
import httpx
import json
import uuid
import os
import time

# Configuration
MEMORY_URL = os.environ.get("TEST_MEMORY_URL", "http://localhost:8081/mcp") 
SEQUENTIAL_URL = os.environ.get("TEST_SEQUENTIAL_URL", "http://localhost:8085")
# Note: SEQUENTIAL_URL base for CIMClient logic usually implies it has /mcp endpoint.

async def mcp_rpc_call(client, base_url, method, params=None, session_id=None):
    """
    Helper to perform JSON-RPC call to MCP endpoint.
    Handles session initialization if needed.
    Returns (result, headers_dict)
    """
    url = f"{base_url}" 
    
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": params or {}
    }
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"
    }
    if session_id:
        headers["mcp-session-id"] = session_id
    
    print(f"   RPC POST {url} - {method}")
    resp = await client.post(url, json=payload, headers=headers)
    
    if resp.status_code != 200:
        print(f"   ❌ HTTP {resp.status_code}: {resp.text[:200]}")
        return None, resp.headers
        
    # Parse SSE or JSON
    text = resp.text
    # Helper to parse SSE
    def parse_sse(text):
        for line in text.split("\n"):
            if line.startswith("data: "):
                try:
                    return json.loads(line[6:])
                except: pass
        try:
             return json.loads(text)
        except: return None
        
    data = parse_sse(text)
    if not data:
        print(f"   ❌ Failed to parse response (valid JSON or SSE data required). Raw: {text[:100]}")
        return None, resp.headers

    if "error" in data:
        print(f"   ❌ RPC Error: {data['error']}")
        return None, resp.headers
    return data.get("result"), resp.headers

async def test_rag_flow():
    print("🚀 Starting E2E RAG Flow Test (JSON-RPC)")
    print(f"Memory URL: {MEMORY_URL}")
    print(f"Sequential URL: {SEQUENTIAL_URL}")
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        # ---------------------------------------------------------
        # 1. INJECT SECRET FACT
        # ---------------------------------------------------------
        conversation_id = "test_rag_bluebook"
        secret_fact = "Der Projektname lautet Project-Bluebook"
        
        print(f"\n[Step 1] Injecting fact into Memory: '{secret_fact}'")
        
        params = {
            "name": "memory_save",
            "arguments": {
                "conversation_id": conversation_id,
                "role": "system",
                "content": secret_fact,
                "layer": "ltm"
            }
        }
        
        # Memory interaction
        start_t = time.time()
        result, _ = await mcp_rpc_call(client, MEMORY_URL, "tools/call", params)
        dur = time.time() - start_t
        
        if result:
            print(f"✅ Injection success ({dur:.2f}s)")
        else:
            print("❌ Injection failed, attempting initialize first...")
            _, headers = await mcp_rpc_call(client, MEMORY_URL, "initialize", {
                "protocolVersion": "2024-11-05", 
                "capabilities": {}, 
                "clientInfo": {"name": "test", "version": "1.0"}
            })
            # Check if session ID needed for Memory (unlikely if stateless, but good to check)
            mem_session = headers.get("mcp-session-id")
            
            start_t = time.time()
            result, _ = await mcp_rpc_call(client, MEMORY_URL, "tools/call", params, session_id=mem_session)
            dur = time.time() - start_t
            
            if not result:
                print("❌ Injection failed even after init.")
                return
            print(f"✅ Injection success (after init) ({dur:.2f}s)")

        # ---------------------------------------------------------
        # 1.5 DEBUG: TEST MEMORY SEARCH DIRECTLY
        # ---------------------------------------------------------
        print("\n[Step 1.5] Debug: Testing memory_graph_search tool...")
        params_search = {
            "name": "memory_graph_search",
            "arguments": {
                "query": "Projekt-Bluebook",
                "depth": 2,
                "limit": 5
            }
        }
        
        start_t = time.time()
        search_res, _ = await mcp_rpc_call(client, MEMORY_URL, "tools/call", params_search, session_id=mem_session if 'mem_session' in locals() else None)
        dur = time.time() - start_t
        
        if search_res:
            print(f"✅ memory_graph_search success! ({dur:.2f}s) Result keys: {search_res.keys()}")
            print(json.dumps(search_res, indent=2))
        else:
            print("❌ memory_graph_search FAILED. Tool might be missing or erroring.")
            # Try semantic search fallback
            print("   Trying memory_semantic_search fallback...")
            params_sem = {
                "name": "memory_semantic_search",
                "arguments": {"query": "Projekt-Bluebook", "limit": 5}
            }
            sem_res, _ = await mcp_rpc_call(client, MEMORY_URL, "tools/call", params_sem, session_id=mem_session if 'mem_session' in locals() else None)
            if sem_res:
                 print(f"✅ memory_semantic_search success! Result keys: {sem_res.keys()}")
            else:
                 print("❌ memory_semantic_search FAILED too.")


        # ---------------------------------------------------------
        # 2. ASK THINKING MODEL
        # ---------------------------------------------------------
        query = "Wie lautet der geheime Projektname?"
        print(f"\n[Step 2] Asking Sequential Thinking: '{query}'")
        
        seq_url = f"{SEQUENTIAL_URL}/mcp"
        
        params_think = {
            "name": "think",
            "arguments": {
                "message": query,
                "use_memory": True,
                "validate_steps": False
            }
        }
        
        # Init Sequential
        print("   Initializing Sequential Session...")
        _, headers = await mcp_rpc_call(client, seq_url, "initialize", {
             "protocolVersion": "2024-11-05", 
             "capabilities": {}, 
             "clientInfo": {"name": "test", "version": "1.0"}
        })
        
        session_id = headers.get("mcp-session-id")
        if session_id:
             print(f"   Session ID: {session_id}")
        else:
             print("   ⚠️ No Session ID returned")
        
        print("   Calling think tool...")
        start_t = time.time()
        result_think, _ = await mcp_rpc_call(client, seq_url, "tools/call", params_think, session_id=session_id)
        dur = time.time() - start_t
        
        if not result_think:
            print(f"❌ Think call failed ({dur:.2f}s)")
            return

        print(f"✅ Think call completed in {dur:.2f}s")

        # ---------------------------------------------------------
        # 3. VERIFY
        # ---------------------------------------------------------
        print("\n[Step 3] Verifying Response...")
        
        # Parse content
        content_items = result_think.get("content", [])
        full_text = ""
        for item in content_items:
            if item.get("type") == "text":
                full_text += item.get("text", "")
        
        if not full_text:
             full_text = json.dumps(result_think)
             
        print(f"\n--- Model Response Preview ---\n{full_text[:500]}...\n------------------------------")
        
        if "Project-Bluebook" in full_text or "Project Bluebook" in full_text or "Project-Bluebook" in str(result_think):
            print("\n✅ SUCCESS: Model recalled 'Project-Bluebook'!")
        else:
            print("\n❌ FAILURE: 'Project-Bluebook' not found in response.")

if __name__ == "__main__":
    asyncio.run(test_rag_flow())
