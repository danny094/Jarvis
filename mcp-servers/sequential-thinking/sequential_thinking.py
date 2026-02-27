"""
Sequential Thinking MCP Server v3.0

Correct architecture using Frank's CIM design:
- CIM.analyze() provides REASONING ROADMAP from RAG
- Single Ollama call follows the ROADMAP
- Optional lightweight validation per step

Port: 8085
Calls: CIM Server on port 8086

v3.0 Changes:
- REMOVED: Loop with multiple Ollama calls
- NEW: Single Ollama call following CIM's ROADMAP
- NEW: Step parser for structured output
- FIXED: Now uses CIM as context-scaler, not just validator
"""

import os
import json
import httpx
import re
from typing import Optional, Dict, Any, List
from fastmcp import FastMCP

# Configuration
CIM_URL = os.environ.get("CIM_URL", "http://cim-server:8086")
OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://ollama:11434")
MEMORY_URL = os.environ.get("MEMORY_URL", "http://mcp-sql-memory:8081/mcp")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "ministral-3:8b")

# Initialize MCP Server
mcp = FastMCP("sequential_thinking")


# ============================================================
# CIM CLIENT - Calls to CIM MCP Server
# ============================================================

class CIMClient:
    """
    HTTP client for CIM MCP Server.
    v2.1: Proper FastMCP Streamable HTTP support with Session Management.
    """
    
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.timeout = 30.0
        self._session_id: Optional[str] = None
        self._initialized = False
    
    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }
        if self._session_id:
            headers["mcp-session-id"] = self._session_id
        return headers
    
    def _parse_sse_response(self, text: str) -> Dict[str, Any]:
        for line in text.split("\n"):
            if line.startswith("data: "):
                json_str = line[6:]
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    pass
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"error": f"Could not parse response: {text[:200]}"}
    
    async def _ensure_session(self, client: httpx.AsyncClient) -> bool:
        if self._initialized and self._session_id:
            return True
        
        try:
            init_payload = {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "sequential-thinking", "version": "3.0.0"}
                }
            }
            
            response = await client.post(
                f"{self.base_url}/mcp",
                json=init_payload,
                headers=self._get_headers()
            )
            
            self._session_id = response.headers.get("mcp-session-id")
            
            if response.status_code == 200:
                self._initialized = True
                if self._session_id:
                    print(f"[CIMClient] Session initialized: {self._session_id[:8]}...")
                else:
                    print(f"[CIMClient] Session initialized (Stateless/No ID)")
                return True
            else:
                print(f"[CIMClient] Session init failed: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"[CIMClient] Session init error: {e}")
            return False
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                if not await self._ensure_session(client):
                    return {"error": "Failed to establish CIM session"}
                
                response = await client.post(
                    f"{self.base_url}/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": tool_name, "arguments": arguments}
                    },
                    headers=self._get_headers()
                )
                
                if response.status_code != 200:
                    return {"error": f"CIM returned {response.status_code}: {response.text[:200]}"}
                
                result = self._parse_sse_response(response.text)
                
                if "result" in result:
                    content = result["result"]
                    if isinstance(content, dict) and "content" in content:
                        items = content["content"]
                        if isinstance(items, list) and len(items) > 0:
                            text = items[0].get("text", "{}")
                            try:
                                return json.loads(text) if isinstance(text, str) else text
                            except json.JSONDecodeError:
                                return {"raw_text": text}
                    return content
                elif "error" in result:
                    return {"error": result["error"]}
                
                return result
                
        except httpx.ConnectError:
            self._initialized = False
            self._session_id = None
            return {"error": f"Cannot connect to CIM server at {self.base_url}"}
        except Exception as e:
            return {"error": str(e)}
    
    async def analyze(self, query: str, mode: Optional[str] = None) -> Dict[str, Any]:
        """Build causal graph for query - returns causal_prompt with REASONING ROADMAP."""
        return await self.call_tool("analyze", {
            "query": query,
            "mode": mode,
            "include_visual": False,
            "include_prompt": True  # KEY: This gets us the REASONING ROADMAP!
        })
    
    async def validate_after(self, step_id: str, step_result: str, expected: str = None) -> Dict[str, Any]:
        """Lightweight validation of a step result."""
        return await self.call_tool("validate_after", {
            "step_id": step_id,
            "step_result": step_result[:500],  # Truncate for speed
            "expected_outcome": expected
        })
    
    async def health_check(self) -> Dict[str, Any]:
        return await self.call_tool("health", {})


# Initialize CIM Client
cim = CIMClient(CIM_URL)


# ============================================================
# MEMORY CLIENT - Calls to SQL Memory MCP Server
# ============================================================

class MemoryClient(CIMClient):
    """
    Client for interacting with Memory MCP (similar protocol to CIM).
    """
    def __init__(self, base_url: str):
        super().__init__(base_url)
        self.name = "memory-client"

    async def search(self, query: str) -> Dict[str, Any]:
        """
        Search memory using graph search (semantic + graph walk).
        """
        # Try graph search first (most comprehensive)
        try:
            return await self.call_tool("memory_graph_search", {
                "query": query,
                "depth": 2,
                "limit": 10
            })
        except Exception as e:
            # Fallback to simple semantic search
            print(f"[Memory] Graph search failed, fallback: {e}")
            return await self.call_tool("memory_semantic_search", {
                "query": query,
                "limit": 5
            })
            
    async def health_check(self) -> Dict[str, Any]:
        # Try memory_healthcheck if available, else heuristic
        try:
            return await self.call_tool("memory_healthcheck", {})
        except:
             return {"status": "unknown"}

# Initialize Memory Client
memory = MemoryClient(MEMORY_URL)


# ============================================================
# OLLAMA CLIENT - Single Call for All Steps
# ============================================================

async def call_ollama(prompt: str, system: str = None, timeout: float = 120.0) -> str:
    """
    Call Ollama for LLM reasoning.
    v3.0: Increased timeout for single comprehensive response.
    """
    try:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{OLLAMA_BASE}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": messages,
                    "stream": False
                }
            )
            response.raise_for_status()
            result = response.json()
            
            # --- Performance Metrics ---
            eval_count = result.get("eval_count", 0)
            eval_duration_ns = result.get("eval_duration", 0)
            eval_duration_s = eval_duration_ns / 1_000_000_000
            
            if eval_duration_s > 0:
                tps = eval_count / eval_duration_s
                print(f"[Ollama] Performance: {eval_count} tokens in {eval_duration_s:.2f}s = {tps:.2f} tokens/sec")
            else:
                print(f"[Ollama] Stats: {eval_count} tokens (duration unknown)")
            # ---------------------------
            
            return result.get("message", {}).get("content", "")
            
    except Exception as e:
        return f"[Ollama Error: {e}]"


# ============================================================
# STEP PARSER - Extract Steps from Ollama Response
# ============================================================

def parse_steps(response: str, expected_steps: int = 0) -> List[Dict[str, Any]]:
    """
    Parse Ollama response into individual steps.
    
    Looks for patterns like:
    - ## Step 1: Title
    - ### Step 1: Title
    - **Step 1:** Title
    - Step 1: Title
    - 1. Title
    """
    steps = []
    
    # Try multiple patterns
    patterns = [
        r'(?:#{1,3}\s*)?(?:\*\*)?Step\s+(\d+)[:\s]*(?:\*\*)?\s*(.+?)(?=(?:#{1,3}\s*)?(?:\*\*)?Step\s+\d+|$)',
        r'^(\d+)\.\s*(.+?)(?=^\d+\.|$)',
    ]
    
    # First try: Step N: format
    step_pattern = r'(?:#{1,3}\s*)?(?:\*\*)?Step\s+(\d+)[:\s]*(?:\*\*)?(.+?)(?=(?:#{1,3}\s*)?(?:\*\*)?Step\s+\d+|$)'
    matches = re.findall(step_pattern, response, re.IGNORECASE | re.DOTALL)
    
    if matches:
        for num, content in matches:
            # Extract title (first line) and thought (rest)
            lines = content.strip().split('\n', 1)
            title = lines[0].strip().strip(':').strip()
            thought = lines[1].strip() if len(lines) > 1 else content.strip()
            
            steps.append({
                "step": int(num),
                "step_id": f"step_{num}",
                "title": title[:100],  # Truncate title
                "thought": thought,
                "status": "complete"
            })
    
    # Fallback: Split by numbered list
    if not steps:
        numbered_pattern = r'^(\d+)[\.\)]\s*(.+?)(?=^\d+[\.\)]|$)'
        matches = re.findall(numbered_pattern, response, re.MULTILINE | re.DOTALL)
        
        for num, content in matches:
            steps.append({
                "step": int(num),
                "step_id": f"step_{num}",
                "title": f"Step {num}",
                "thought": content.strip(),
                "status": "complete"
            })
    
    # Last fallback: Split by double newlines
    if not steps and expected_steps > 0:
        chunks = response.split('\n\n')
        for i, chunk in enumerate(chunks[:expected_steps], 1):
            if chunk.strip():
                steps.append({
                    "step": i,
                    "step_id": f"step_{i}",
                    "title": f"Step {i}",
                    "thought": chunk.strip(),
                    "status": "complete"
                })
    
    return steps


# ============================================================
# MCP TOOLS
# ============================================================

@mcp.tool()
async def think(
    message: str,
    steps: int = 5,
    mode: Optional[str] = None,
    use_cim: bool = True,
    use_memory: bool = True,
    validate_steps: bool = False
) -> Dict[str, Any]:
    """
    Sequential thinking with CIM-guided reasoning and Memory context.
    
    v3.0 Architecture (Frank's Design):
    1. CIM.analyze() retrieves procedures from RAG and builds REASONING ROADMAP
    2. Memory.search() retrieves factual context (Dynamic RAG)
    3. Single Ollama call follows the ROADMAP with MEMORY CONTEXT
    4. Optional: lightweight validation per step
    
    Args:
        message: The query/task to think through
        steps: Suggested number of steps (CIM may override based on RAG procedure)
        mode: Force CIM mode (light, heavy, strategic, temporal, simulation)
        use_cim: Enable CIM for context building (default: True)
        use_memory: Enable Memory retrieval (default: True)
        validate_steps: Enable post-step validation (default: False, adds latency)
    
    Returns:
        Chain of reasoning steps with CIM context and Memory facts
    """
    cim_errors = []
    causal_prompt = ""
    cim_mode = None
    cim_graph = None
    memory_context = ""
    memory_results = []
    
    # ============================================================
    # PHASE 0: Memory Retrieval (Dynamic RAG)
    # ============================================================
    if use_memory:
        print(f"[Sequential] Calling Memory.search for: {message[:50]}...")
        mem_response = await memory.search(message)
        
        if mem_response and "results" in mem_response:
            results = mem_response["results"]
            memory_results = results
            print(f"[Sequential] Memory found {len(results)} items")
            
            if results:
                memory_context = "=== MEMORY CONTEXT (FACTS) ===\n"
                for idx, item in enumerate(results, 1):
                    content = item.get("content", "")
                    m_type = item.get("type", "fact")
                    memory_context += f"{idx}. [{m_type.upper()}] {content}\n"
                memory_context += "=== END MEMORY CONTEXT ===\n\n"
        else:
            print("[Sequential] Memory retrieval returned no results or error")

    
    # ============================================================
    # PHASE 1: CIM Analysis - Get REASONING ROADMAP from RAG
    # ============================================================
    if use_cim:
        print(f"[Sequential] Calling CIM.analyze for: {message[:50]}...")
        analysis = await cim.analyze(message, mode)
        
        if analysis.get("error"):
            cim_errors.append(f"analyze: {analysis['error']}")
            print(f"[Sequential] CIM analyze error: {analysis['error']}")
        elif analysis.get("success"):
            causal_prompt = analysis.get("causal_prompt", "")
            cim_mode = analysis.get("mode_selected")
            cim_graph = {
                "node_count": analysis.get("node_count", 0),
                "edge_count": analysis.get("edge_count", 0)
            }
            print(f"[Sequential] CIM mode: {cim_mode}")
            print(f"[Sequential] Graph: {cim_graph['node_count']} nodes, {cim_graph['edge_count']} edges")
            if causal_prompt:
                print(f"[Sequential] ROADMAP received: {len(causal_prompt)} chars")
    
    # ============================================================
    # PHASE 2: Single Ollama Call - Follow the ROADMAP
    # ============================================================
    print(f"[Sequential] Calling Ollama (1x) for comprehensive analysis...")
    
    # Build system prompt with CIM context
    system_prompt = """You are a rigorous step-by-step reasoner using causal inference principles.

Your task is to analyze the given query by following the REASONING ROADMAP provided.
For each step in the roadmap, provide thorough but concise analysis.

Format your response with clear step markers:
## Step 1: [Step Title from Roadmap]
[Your detailed analysis for this step]

## Step 2: [Step Title from Roadmap]
[Your detailed analysis for this step]

Continue for all steps in the roadmap."""

    if causal_prompt:
        system_prompt += f"""

=== CIM CAUSAL CONTEXT ===
{causal_prompt}
=== END CAUSAL CONTEXT ===
"""
    if memory_context:
        system_prompt += f"""

{memory_context}
Use the facts from MEMORY CONTEXT to answer the query accurately. 
Checking memory is CRITICAL for specific questions about projects, names, or stored data.
"""
    system_prompt += f"""

Follow the REASONING ROADMAP above strictly. Address each step systematically."""
    
    # Build user prompt
    user_prompt = f"""Analyze the following query using {steps} reasoning steps:

QUERY: {message}

Provide your complete analysis following the reasoning roadmap. Be thorough and methodical."""

    # SINGLE Ollama call
    full_response = await call_ollama(user_prompt, system_prompt, timeout=180.0)
    
    if full_response.startswith("[Ollama Error:"):
        print(f"[Sequential] Ollama error: {full_response}")
        return {
            "success": False,
            "error": full_response,
            "input": message,
            "cim_enabled": use_cim,
            "cim_mode": cim_mode
        }
    
    print(f"[Sequential] Ollama response: {len(full_response)} chars")
    
    # ============================================================
    # PHASE 3: Parse Response into Steps
    # ============================================================
    parsed_steps = parse_steps(full_response, steps)
    print(f"[Sequential] Parsed {len(parsed_steps)} steps")
    
    # If parsing failed, create single step with full response
    if not parsed_steps:
        parsed_steps = [{
            "step": 1,
            "step_id": "step_1",
            "title": "Complete Analysis",
            "thought": full_response,
            "status": "complete"
        }]
    
    # ============================================================
    # PHASE 4: Optional Lightweight Validation
    # ============================================================
    if use_cim and validate_steps:
        print(f"[Sequential] Validating {len(parsed_steps)} steps...")
        for step in parsed_steps:
            validation = await cim.validate_after(
                step_id=step["step_id"],
                step_result=step["thought"][:500]
            )
            
            if validation.get("error"):
                cim_errors.append(f"validate[{step['step_id']}]: {validation['error']}")
                step["validation"] = {"error": validation["error"]}
            else:
                step["validation"] = {
                    "valid": validation.get("valid", True),
                    "consistency_score": validation.get("consistency_score", 1.0)
                }
    
    # ============================================================
    # BUILD RESPONSE
    # ============================================================
    return {
        "success": True,
        "input": message,
        "steps": parsed_steps,
        "total_steps": len(parsed_steps),
        "full_response": full_response,  # Include for debugging
        "cim_enabled": use_cim,
        "cim_enabled": use_cim,
        "cim_mode": cim_mode,
        "cim_graph": cim_graph,
        "memory_enabled": use_memory,
        "memory_results_count": len(memory_results),
        "cim_errors": cim_errors if cim_errors else None,
        "ollama_calls": 1,  # v3.0: Always 1!
        "summary": f"{len(parsed_steps)} steps completed with {'CIM-guided reasoning' if use_cim else 'basic reasoning'}"
    }


@mcp.tool()
async def think_simple(message: str, steps: int = 3) -> Dict[str, Any]:
    """
    Simple sequential thinking WITHOUT CIM (for comparison/fallback).
    Still uses single Ollama call architecture.
    """
    return await think(message=message, steps=steps, use_cim=False)


@mcp.tool()
async def health() -> Dict[str, Any]:
    """Health check for Sequential Thinking server."""
    cim_status = "unknown"
    cim_session = None
    
    try:
        cim_health = await cim.health_check()
        if cim_health.get("error"):
            cim_status = f"error: {cim_health['error']}"
        elif cim_health.get("status") == "healthy":
            cim_status = "connected"
            cim_session = cim._session_id[:8] + "..." if cim._session_id else None
        else:
            cim_status = "unknown"
    except Exception as e:
        cim_status = f"error: {e}"

    # Check Memory
    memory_status = "unknown"
    try:
        mem_health = await memory.health_check()
        if mem_health.get("status") == "ok":
            memory_status = "connected"
        else:
            memory_status = f"error: {mem_health}"
    except Exception as e:
        memory_status = f"error: {e}"
    
    return {
        "status": "healthy",
        "service": "sequential-thinking",
        "version": "3.1.0",
        "architecture": "single-ollama-call-with-memory",
        "cim_url": CIM_URL,
        "cim_status": cim_status,
        "cim_session": cim_session,
        "memory_url": MEMORY_URL,
        "memory_status": memory_status,
        "ollama_url": OLLAMA_BASE,
        "ollama_model": OLLAMA_MODEL
    }


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print("🧠 Starting Sequential Thinking MCP Server v3.0 on port 8085...")
    print(f"   CIM_URL: {CIM_URL}")
    print(f"   OLLAMA_BASE: {OLLAMA_BASE}")
    print(f"   OLLAMA_MODEL: {OLLAMA_MODEL}")
    print("   Architecture: Single Ollama call with CIM ROADMAP")
    print("   Tools available:")
    print("   - think: CIM-guided sequential reasoning (1 Ollama call)")
    print("   - think_simple: Basic reasoning without CIM")
    print("   - health: Health check")
    print("   v3.0: Fixed architecture - CIM provides ROADMAP, Ollama follows")
    
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8085
    )
