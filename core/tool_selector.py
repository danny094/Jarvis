"""
Layer 0: Tool Selector (Candidate Finder)

Nur noch Semantic Search — kein LLM-Call mehr.
ControlLayer übernimmt die finale Entscheidung via Function Calling.
"""

import logging
from typing import List, Dict, Optional, Any

from config import ENABLE_TOOL_SELECTOR
from mcp.hub import get_hub

logger = logging.getLogger(__name__)


class ToolSelector:
    def __init__(self):
        self.hub = get_hub()

    async def select_tools(self, user_text: str, context_summary: str = "") -> Optional[List[str]]:
        """
        Gibt Tool-Kandidaten zurück (Semantic Search, kein LLM).
        ControlLayer entscheidet final welche davon genutzt werden.

        Returns:
            List[str]: Kandidaten-Namen.
            None: Fehler oder Feature deaktiviert.
        """
        if not ENABLE_TOOL_SELECTOR:
            return None

        try:
            candidates = self._get_candidates(user_text)
            if not candidates:
                return None
            names = [c["name"] for c in candidates]
            logger.info(f"[ToolSelector] Candidates ({len(names)}): {names}")
            return names
        except Exception as e:
            logger.error(f"[ToolSelector] Error: {e}")
            return None

    def _get_candidates(self, query: str) -> List[Dict[str, Any]]:
        """Semantic Search → Tool-Kandidaten. Kein LLM-Call."""
        try:
            result = self.hub.call_tool("memory_semantic_search", {
                "query": query,
                "limit": 15,
                "min_similarity": 0.3,
            })
            rows = result.get("results", []) if isinstance(result, dict) else []
            seen = set()
            candidates = []
            for row in rows:
                meta = row.get("metadata", {})
                key = meta.get("key", "")
                if key.startswith("tool_"):
                    tool_name = key[5:]
                    if tool_name and tool_name not in seen:
                        seen.add(tool_name)
                        candidates.append({"name": tool_name, "description": meta.get("description", "")})
            return candidates
        except Exception as e:
            logger.error(f"[ToolSelector] Semantic search failed: {e}")
            return []
