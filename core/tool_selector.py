"""
Layer 0: Tool Selector
Verwendet Semantic Search und ein kleines LLM (Qwen 1.5B), um relevante Tools VOR dem Reasoning auszuwählen.
"""

import logging
import json
import httpx
from typing import List, Dict, Optional, Any

from config import TOOL_SELECTOR_MODEL, OLLAMA_BASE, ENABLE_TOOL_SELECTOR
from mcp.hub import get_hub
from utils.json_parser import safe_parse_json

logger = logging.getLogger(__name__)

# System Prompt für den Selector
SELECTOR_PROMPT = """You are the Tool Selector.
Your task is to identify the relevant tools for a user query from a list of candidates.

CONTEXT:
{context}

QUERY: "{query}"

CANDIDATES:
{candidates}

INSTRUCTIONS:
1. Select ONLY tools that are strictly capable of solving the query.
2. If the user mentions a specific container or task, check the Context to choose between 'request_container' (new) and 'exec_in_container' (existing).
3. Be tolerant: If unsure, select the tool. Better too many than too few.
4. Return a JSON list of tool names strings.

Example Output:
["tool_a", "tool_b"]
"""

class ToolSelector:
    def __init__(self):
        self.model = TOOL_SELECTOR_MODEL
        self.ollama_url = f"{OLLAMA_BASE}/api/generate"
        self.hub = get_hub()
        
    async def select_tools(self, user_text: str, context_summary: str = "") -> Optional[List[str]]:
        """
        Wählt relevante Tools basierend auf Query und Context aus.
        Returns:
            List[str]: Liste der Tool-Namen.
            None: Fallback (Fehler oder Feature deaktiviert) -> Nutze alle Tools.
        """
        if not ENABLE_TOOL_SELECTOR:
            return None

        try:
            # 1. Semantic Search nach Kandidaten
            candidates = await self._get_candidates(user_text)
            if not candidates:
                logger.warning("[ToolSelector] No candidates found via semantic search. Falling back.")
                return None
            
            # 2. LLM Selection
            selected = await self._query_llm(user_text, context_summary, candidates)
            
            # 3. Validation / Fallback
            if not selected:
                logger.warning("[ToolSelector] LLM returned empty list. Falling back.")
                return None
                
            logger.info(f"[ToolSelector] Selected {len(selected)} tools: {selected}")
            return selected

        except Exception as e:
            logger.error(f"[ToolSelector] Error: {e}")
            return None # Fail-Open

    async def _get_candidates(self, query: str) -> List[Dict[str, Any]]:
        """Ruft memory_semantic_search auf, um Tool-Definitionen zu finden."""
        try:
            # Wir nutzen das MCP Tool direkt
            result = self.hub.call_tool("memory_semantic_search", {
                "query": query,
                "limit": 15,    # Hole genuegend Kandidaten
                "content_type": "tool_def",
                "min_similarity": 0.3 # Tolerant sein
            })
            
            # Result Format: {"results": [...], "count": N}
            rows = result.get("results", [])
            
            candidates = []
            for row in rows:
                meta = row.get("metadata", {})
                tool_name = meta.get("tool_name")
                desc = meta.get("description", "")
                # Fallback falls metadata leer
                if not tool_name and "Tool:" in row.get("content", ""):
                    # Parse content string "Tool: name\nDesc..."
                    lines = row["content"].split("\n")
                    for line in lines:
                        if line.startswith("Tool:"):
                            tool_name = line.replace("Tool:", "").strip()
                        if line.startswith("Description:"):
                            desc = line.replace("Description:", "").strip()
                            
                if tool_name:
                    candidates.append({"name": tool_name, "description": desc})
            
            # Add strict defaults? (e.g. memory_save is always good)
            # For now rely on search.
            
            return candidates

        except Exception as e:
            logger.error(f"[ToolSelector] Semantic search failed: {e}")
            return []

    async def _query_llm(self, query: str, context: str, candidates: List[Dict]) -> List[str]:
        """Fragt das kleine LLM."""
        
        # Format candidates list
        cand_str = json.dumps(candidates, indent=1)
        
        prompt = SELECTOR_PROMPT.format(
            query=query,
            context=context,
            candidates=cand_str
        )
        
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(self.ollama_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            response_text = data.get("response", "")
            
        # Parse JSON
        parsed = safe_parse_json(response_text)
        
        # Expect list of strings
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
        # Handle {"tools": [...]} wrapper if model does that
        if isinstance(parsed, dict) and "tools" in parsed:
            return parsed["tools"]
            
        return []
