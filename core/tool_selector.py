"""
Layer 0: Tool Selector (Candidate Finder)

Nur noch Semantic Search — kein LLM-Call mehr.
ControlLayer übernimmt die finale Entscheidung via Function Calling.
"""

import logging
from typing import List, Dict, Optional, Any

from config import (
    ENABLE_TOOL_SELECTOR,
    get_tool_selector_candidate_limit,
    get_tool_selector_min_similarity,
)
from mcp.hub import get_hub

logger = logging.getLogger(__name__)


class ToolSelector:
    def __init__(self):
        self.hub = get_hub()
        self._semantic_unavailable_logged = False

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
        if not self.hub.get_mcp_for_tool("memory_semantic_search"):
            # Startup race recovery: refresh once if sql-memory came up late.
            try:
                self.hub.refresh()
            except Exception:
                pass
        if not self.hub.get_mcp_for_tool("memory_semantic_search"):
            if not self._semantic_unavailable_logged:
                logger.warning(
                    "[ToolSelector] memory_semantic_search unavailable - semantic prefilter disabled"
                )
                self._semantic_unavailable_logged = True
            return []

        try:
            limit = get_tool_selector_candidate_limit()
            min_similarity = get_tool_selector_min_similarity()
            result = self.hub.call_tool("memory_semantic_search", {
                "query": query,
                "limit": limit,
                "min_similarity": min_similarity,
            })
            if isinstance(result, dict) and result.get("error"):
                logger.warning(f"[ToolSelector] Semantic search error: {result.get('error')}")
                return []
            rows = result.get("results", []) if isinstance(result, dict) else []
            seen = set()
            candidates = []
            dropped_low_similarity = 0
            for row in rows:
                score = self._extract_similarity(row)
                if score is not None and score < min_similarity:
                    dropped_low_similarity += 1
                    continue
                meta = row.get("metadata", {})
                key = meta.get("key", "")
                if key.startswith("tool_"):
                    tool_name = key[5:]
                    if tool_name and tool_name not in seen:
                        seen.add(tool_name)
                        candidates.append({"name": tool_name, "description": meta.get("description", "")})
                        if len(candidates) >= limit:
                            break
            if dropped_low_similarity:
                logger.info(
                    "[ToolSelector] Dropped %d low-similarity rows (< %.2f)",
                    dropped_low_similarity,
                    min_similarity,
                )
            return candidates
        except Exception as e:
            logger.error(f"[ToolSelector] Semantic search failed: {e}")
            return []

    @staticmethod
    def _extract_similarity(row: Any) -> Optional[float]:
        """Best-effort similarity extraction from semantic rows."""
        if not isinstance(row, dict):
            return None
        meta = row.get("metadata", {}) if isinstance(row.get("metadata"), dict) else {}
        for key in ("similarity", "score"):
            val = row.get(key, None)
            if val is None:
                val = meta.get(key, None)
            if val is None:
                continue
            try:
                return float(val)
            except Exception:
                continue
        return None
