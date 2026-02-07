"""
ContextManager: Handles all context retrieval (Memory + System Knowledge)

Responsibilities:
- User Memory Retrieval (Facts, Graph, Semantic Search)
- System Tool RAG (Tool Documentation & Capabilities)
- Multi-Context Search (User + System)

Created by: Claude 1 (Parallel Development)
Date: 2026-02-05
Part of: CoreBridge Refactoring Phase 1
"""

import os
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Tuple, Dict, List, Optional
from utils.logger import log_info, log_warn, log_error
from mcp.client import (
    get_fact_for_query,
    graph_search,
    semantic_search,
    search_memory_fallback,
)
# Constants
SYSTEM_CONV_ID = "system"


class ContextResult:
    """Result of context retrieval operations"""
    
    def __init__(
        self,
        memory_data: str = "",
        memory_used: bool = False,
        system_tools: str = "",
        sources: List[str] = None
    ):
        self.memory_data = memory_data
        self.memory_used = memory_used
        self.system_tools = system_tools
        self.sources = sources or []
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization"""
        return {
            "memory_data": self.memory_data,
            "memory_used": self.memory_used,
            "system_tools": self.system_tools,
            "sources": self.sources
        }


class ContextManager:
    """
    Manages all context retrieval:
    - User memory (facts, graph, semantic search)
    - System knowledge (tool docs, capabilities)
    - Daily protocol context
    """

    PROTOCOL_DIR = Path(os.environ.get("PROTOCOL_DIR", "/app/memory"))

    def __init__(self):
        self._protocol_cache = {}  # {filepath: (mtime, content)}
        log_info("[ContextManager] Initialized")
    
    # ═══════════════════════════════════════════════════════════
    # MAIN PUBLIC INTERFACE
    # ═══════════════════════════════════════════════════════════
    
    def get_context(
        self,
        query: str,
        thinking_plan: Dict,
        conversation_id: str
    ) -> ContextResult:
        """
        Main entry point: Get all relevant context for a query.
        
        Args:
            query: User's query text
            thinking_plan: Output from ThinkingLayer
                Expected keys:
                - needs_memory: bool
                - is_fact_query: bool
                - memory_keys: List[str]
            conversation_id: Current conversation ID
        
        Returns:
            ContextResult with memory_data, memory_used, system_tools
        """
        result = ContextResult()

        # 0. Daily Protocol context (today + yesterday)
        protocol_ctx = self._load_daily_protocol()
        if protocol_ctx:
            result.memory_data = protocol_ctx + "\n"
            result.memory_used = True
            result.sources.append("daily_protocol")

        # 0.5. Active Container context (Workspace Event-Log)
        container_ctx = self._load_active_containers()
        if container_ctx:
            result.memory_data += container_ctx + "\n"
            result.memory_used = True
            result.sources.append("active_containers")

        # 1. System Tools if relevant
        system_tools = self._search_system_tools(query)
        if system_tools:
            result.system_tools = system_tools
            result.memory_used = True
            result.sources.append("system_tools")
            log_info("[ContextManager] Found system tool info")
        
        # 2. User Memory if needed
        if thinking_plan.get("needs_memory") or thinking_plan.get("is_fact_query"):
            memory_keys = thinking_plan.get("memory_keys", [])
            
            for key in memory_keys:
                log_info(f"[ContextManager] Searching key='{key}'")
                
                content, found = self._search_memory_multi_context(
                    key,
                    conversation_id,
                    include_system=True
                )
                
                if found:
                    result.memory_data += content
                    result.memory_used = True
                    result.sources.append(f"memory:{key}")
        
        return result
    
    # ═══════════════════════════════════════════════════════════
    # PRIVATE HELPERS (Copied from bridge.py)
    # ═══════════════════════════════════════════════════════════
    
    def _search_memory_multi_context(
        self, 
        key: str, 
        conversation_id: str,
        include_system: bool = True
    ) -> Tuple[str, bool]:
        """
        Sucht Memory in mehreren Kontexten:
        1. User's conversation_id
        2. System-Wissen (Tool-Infos, Anleitungen)
        
        Returns:
            Tuple[str, bool]: (gefundener Content, wurde etwas gefunden)
        """
        found_content = ""
        found = False
        
        # Kontexte die durchsucht werden
        contexts = [conversation_id]
        if include_system and conversation_id != SYSTEM_CONV_ID:
            contexts.append(SYSTEM_CONV_ID)
        
        for ctx in contexts:
            ctx_label = "system" if ctx == SYSTEM_CONV_ID else "user"
            
            # 1. Facts suchen
            fact_value = get_fact_for_query(ctx, key)
            if fact_value:
                found_content += f"{key}: {fact_value}\n"
                found = True
                log_info(f"[ContextManager-Memory] Found fact ({ctx_label}): {key}={fact_value[:50]}...")
                continue  # Nächster Kontext
            
            # 2. Graph search
            graph_results = graph_search(ctx, key)
            if graph_results:
                for res in graph_results[:3]:
                    content = res.get("content", "")
                    log_info(f"[ContextManager-Memory] Graph match ({ctx_label}): {content[:50]}")
                    found_content += f"{content}\n"
                found = True
                continue
            
            # 3. Semantic search (nur für User-Kontext, System ist meist Fakten)
            if ctx != SYSTEM_CONV_ID:
                semantic_results = semantic_search(ctx, key)
                if semantic_results:
                    for res in semantic_results[:3]:
                        content = res.get("content", "")
                        found_content += f"{content}\n"
                    found = True
                    continue
            
            # 4. Text-Fallback (nur User)
            if ctx != SYSTEM_CONV_ID:
                fallback = search_memory_fallback(ctx, key)
                if fallback:
                    found_content += f"{key}: {fallback}\n"
                    found = True
        
        return found_content, found
    
    def _search_system_tools(self, query: str) -> str:
        """
        Sucht speziell nach Tool-Wissen im System-Kontext.
        
        Nützlich wenn die Anfrage nach Tools/Funktionen fragt.
        """
        # Suche nach allgemeinen Tool-Infos
        tool_keywords = ["tool", "function", "mcp", "think", "sequential", "hilfe", "können"]
        
        query_lower = query.lower()
        if any(kw in query_lower for kw in tool_keywords):
            log_info(f"[ContextManager-Memory] Searching system tools for: {query}")
            
            # Lade Tool-Übersicht
            tools_info = get_fact_for_query(SYSTEM_CONV_ID, "available_mcp_tools")
            if tools_info:
                return f"Verfügbare Tools: {tools_info}\n"
            
            # Fallback: Graph-Suche im System
            graph_results = graph_search(SYSTEM_CONV_ID, query)
            if graph_results:
                return "\n".join([r.get("content", "") for r in graph_results[:2]])
        
        return ""
    
    # ═══════════════════════════════════════════════════════════
    # DAILY PROTOCOL
    # ═══════════════════════════════════════════════════════════

    def _load_daily_protocol(self) -> str:
        """
        Load today's and yesterday's protocol files with mtime caching.
        Returns combined content or empty string.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        combined = ""

        for date_str in [today, yesterday]:
            filepath = self.PROTOCOL_DIR / f"{date_str}.md"
            if not filepath.exists():
                continue

            try:
                mtime = filepath.stat().st_mtime
                cached = self._protocol_cache.get(str(filepath))

                if cached and cached[0] == mtime:
                    content = cached[1]
                else:
                    content = filepath.read_text()
                    self._protocol_cache[str(filepath)] = (mtime, content)

                if content.strip():
                    combined += content + "\n"
            except Exception as e:
                log_warn(f"[ContextManager] Protocol read error for {date_str}: {e}")

        return combined.strip()

    # ═══════════════════════════════════════════════════════════
    # ACTIVE CONTAINERS (Workspace Event-Log)
    # ═══════════════════════════════════════════════════════════

    def _load_active_containers(self) -> str:
        """
        Load active containers from workspace event-log.

        Logic: container_started entries WITHOUT a matching container_stopped entry.
        Returns formatted text for ThinkingLayer injection.
        """
        try:
            from mcp.hub import get_hub
            hub = get_hub()
            hub.initialize()

            # Fetch all container_started entries (dedicated conversation)
            started_result = hub.call_tool("workspace_list", {
                "conversation_id": "_container_events",
                "entry_type": "container_started",
                "limit": 50,
            })
            started_entries = self._extract_workspace_entries(started_result)

            if not started_entries:
                return ""

            # Fetch all container_stopped entries (dedicated conversation)
            stopped_result = hub.call_tool("workspace_list", {
                "conversation_id": "_container_events",
                "entry_type": "container_stopped",
                "limit": 50,
            })
            stopped_entries = self._extract_workspace_entries(stopped_result)

            # Build set of stopped container_ids
            stopped_ids = set()
            for entry in stopped_entries:
                try:
                    data = json.loads(entry.get("content", "{}"))
                    cid = data.get("container_id", "")
                    if cid:
                        stopped_ids.add(cid)
                except (json.JSONDecodeError, TypeError):
                    continue

            # Filter: started but not stopped, today only
            today = datetime.now().strftime("%Y-%m-%d")
            active = []
            for entry in started_entries:
                try:
                    data = json.loads(entry.get("content", "{}"))
                    cid = data.get("container_id", "")
                    created = entry.get("created_at", "")

                    if not cid or cid in stopped_ids:
                        continue
                    if not created.startswith(today):
                        continue

                    active.append({
                        "container_id": cid,
                        "blueprint": data.get("blueprint", "unknown"),
                        "purpose": data.get("purpose", ""),
                        "started_at": data.get("started_at", created),
                    })
                except (json.JSONDecodeError, TypeError):
                    continue

            if not active:
                return ""

            # Format for ThinkingLayer
            lines = ["AKTIVE CONTAINER (Workspace-Sicht):"]
            for c in active:
                short_id = c["container_id"][:12]
                lines.append(
                    f"- {c['blueprint']} → {short_id} "
                    f"(gestartet {c['started_at']}, Zweck: {c['purpose'][:80]})"
                )
            lines.append("HINWEIS: Nutze exec_in_container mit der container_id statt einen neuen Container zu starten.")

            ctx = "\n".join(lines)
            log_info(f"[ContextManager] Active containers: {len(active)} found")
            return ctx

        except Exception as e:
            log_warn(f"[ContextManager] Active container load failed: {e}")
            return ""

    def _extract_workspace_entries(self, result) -> list:
        """Extract entries list from MCP workspace_list result."""
        if isinstance(result, dict):
            sc = result.get("structuredContent", result)
            return sc.get("entries", [])
        return []

    # ═══════════════════════════════════════════════════════════
    # ADDITIONAL HELPERS
    # ═══════════════════════════════════════════════════════════
    
    def get_tool_context(self, query: str) -> str:
        """
        Specialized method for tool RAG.
        Alias for _search_system_tools (public API).
        """
        return self._search_system_tools(query)
