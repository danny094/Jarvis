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
        conversation_id: str,
        small_model_mode: bool = False,
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
            small_model_mode: If True, skip daily protocol, skills, blueprints.
                              Only TRION laws + active containers are loaded.
                              Compact NOW/RULES/NEXT context is injected by the
                              orchestrator via _get_compact_context() instead.

        Returns:
            ContextResult with memory_data, memory_used, system_tools
        """
        result = ContextResult()

        if small_model_mode:
            # ── SMALL-MODEL fast path ──────────────────────────────────────
            # Skips: daily_protocol, skills, blueprints (injected as compact NOW/RULES/NEXT).
            # Keeps: TRION laws (safety, non-negotiable) + active containers + memory keys.
            laws_ctx = self._load_trion_laws()
            if laws_ctx:
                result.memory_data = laws_ctx + "\n"
                result.memory_used = True
                result.sources.append("trion_laws")

            container_ctx = self._load_active_containers()
            if container_ctx:
                result.memory_data += container_ctx + "\n"
                result.memory_used = True
                result.sources.append("active_containers")

            # Memory-Key lookups: still run for personal facts / fact queries.
            # time_ref guard applies here too (temporal queries use protocol, not graph).
            _smm_time_ref = thinking_plan.get("time_reference") if thinking_plan else None
            if not _smm_time_ref and thinking_plan and (
                thinking_plan.get("needs_memory") or thinking_plan.get("is_fact_query")
            ):
                for key in thinking_plan.get("memory_keys", []):
                    log_info(f"[ContextManager] small_model_mode memory key='{key}'")
                    content, found = self._search_memory_multi_context(
                        key, conversation_id, include_system=False
                    )
                    if found:
                        result.memory_data += content + "\n"
                        result.memory_used = True
                        result.sources.append(f"memory:{key}")

            log_info(
                f"[ContextManager] small_model_mode=True — skipped daily_protocol/skills/blueprints, "
                f"memory_keys={'kept' if thinking_plan and thinking_plan.get('needs_memory') else 'skipped'}"
            )
            return result

        # ── NORMAL full-context path ───────────────────────────────────────

        # 0. Daily Protocol context — Commit 3: only loaded for explicit time_reference queries.
        # Avoids automatic full-protocol dumps on every non-temporal request.
        # Protocol files remain unchanged as truth store; JIT index handles other lookups.
        time_ref = thinking_plan.get("time_reference") if thinking_plan else None
        if time_ref:
            protocol_ctx = self._load_daily_protocol(time_reference=time_ref)
            if protocol_ctx:
                result.memory_data = protocol_ctx + "\n"
                result.memory_used = True
                result.sources.append("daily_protocol")

            # Graph-Fallback: Protokoll fehlt für spezifisches Datum → graph_search
            if time_ref and time_ref not in ("today", "yesterday", "day_before_yesterday"):
                if "NICHT VORHANDEN" in protocol_ctx:
                    log_info(f"[ContextManager] Protocol missing for {time_ref} — activating graph fallback")
                    graph_results = self._search_memory_multi_context(
                        f"gespräch {time_ref}", conversation_id, include_system=False
                    )
                    if graph_results[1]:  # found = True
                        result.memory_data += f"\n[GRAPH-FALLBACK für {time_ref}]\n{graph_results[0]}\n"
                        result.sources.append(f"graph_fallback:{time_ref}")

        # 0.3. TRION Gesetze (unumstößliche Hardware-Constraints, immer geladen)
        laws_ctx = self._load_trion_laws()
        if laws_ctx:
            result.memory_data += laws_ctx + "\n"
            result.memory_used = True
            result.sources.append("trion_laws")

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

        # 1.5. Skill Graph: semantische Skill-Discovery (immer aktiv)
        skill_ctx = self._search_skill_graph(query)
        if skill_ctx:
            result.system_tools = (result.system_tools + "\n" + skill_ctx).strip()
            result.memory_used = True
            result.sources.append("skill_graph")
            log_info("[ContextManager] Found skills in graph")

        # 1.55. Blueprint Graph: semantische Blueprint-Discovery (immer aktiv)
        blueprint_ctx = self._search_blueprint_graph(query)
        if blueprint_ctx:
            result.system_tools = (result.system_tools + "\n\n" + blueprint_ctx).strip()
            result.memory_used = True
            result.sources.append("blueprint_graph")

        # 1.6. SkillKnowledgeBase Hint (winziger Kontext-Footprint, immer da)
        kb_hint = self._load_skill_knowledge_hint()
        if kb_hint:
            result.system_tools = (result.system_tools + "\n\n" + kb_hint).strip()
            result.sources.append("skill_knowledge_base")

        # 2. User Memory if needed
        # Temporal guard: Protokoll ist die Quelle — kein Graph/Fact-Lookup nötig
        if time_ref:
            log_info(f"[ContextManager] Skipping memory search — time_reference={time_ref}, protocol is source")
        elif thinking_plan.get("needs_memory") or thinking_plan.get("is_fact_query"):
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
    
    def _search_skill_graph(self, query: str) -> str:
        """
        Liefert ALLE installierten Skills an ThinkingLayer.
        Strategie: REST-API (vollständig + zuverlässig) als primäre Quelle,
        semantische Graph-Suche als Bonus für tiefere Metadaten.
        """
        import urllib.request as _ur
        import json as _json

        skill_server_url = os.getenv("SKILL_SERVER_URL", "http://trion-skill-server:8088")
        skill_lines = []

        # Primär: REST-API → immer alle installierten Skills
        try:
            req = _ur.Request(f"{skill_server_url}/v1/skills")
            with _ur.urlopen(req, timeout=3) as r:
                data = _json.loads(r.read())
            active_names = data.get("active", [])
            if active_names:
                for name in active_names:
                    # Metadaten holen
                    try:
                        meta_req = _ur.Request(f"{skill_server_url}/v1/skills/{name}")
                        with _ur.urlopen(meta_req, timeout=2) as mr:
                            meta = _json.loads(mr.read())
                        desc = meta.get("description", "")
                        triggers = meta.get("triggers", [])
                        line = f"- {name}"
                        if desc:
                            line += f": {desc}"
                        if triggers:
                            line += f" (Triggers: {', '.join(triggers[:5])})"
                        skill_lines.append(line)
                    except Exception:
                        skill_lines.append(f"- {name}")
        except Exception as e:
            log_warn(f"[ContextManager] Skill REST fetch failed: {e}")

        # Fallback: Graph-Suche (falls REST nicht erreichbar)
        if not skill_lines:
            try:
                results = graph_search("_skills", query, depth=0, limit=10)
                for r in results:
                    content = r.get("content", "").strip()
                    if content:
                        skill_lines.append(f"- {content}")
            except Exception as ge:
                log_warn(f"[ContextManager] Skill graph fallback failed: {ge}")

        if skill_lines:
            log_info(f"[ContextManager] Skill context: {len(skill_lines)} Skills für ThinkingLayer")
            return "VERFÜGBARE SKILLS (installiert):\n" + "\n".join(skill_lines)
        return ""

    # ═══════════════════════════════════════════════════════════
    # BLUEPRINT GRAPH
    # ═══════════════════════════════════════════════════════════

    def _search_blueprint_graph(self, query: str) -> str:
        """
        Sucht Blueprints semantisch im Graph (conv_id="_blueprints").
        Liefert "VERFÜGBARE BLUEPRINTS" Block für ThinkingLayer.
        Nur Graph-Suche (kein REST) — Blueprints werden beim Startup gesynct.

        Phase 5 — Graph Hygiene:
          Alle Kandidaten laufen durch apply_graph_hygiene() (fail-closed):
            parse → dedupe_latest_by_blueprint_id → sqlite_crosscheck
          Kein Fail-Open bei SQLite-Fehler.
        """
        try:
            from core.graph_hygiene import apply_graph_hygiene

            results = graph_search("_blueprints", query, depth=0, limit=5)
            if not results:
                return ""

            candidates, log_meta = apply_graph_hygiene(
                results,
                fail_closed=True,
                crosscheck_mode="strict",
            )
            log_info(
                f"[ContextManager] Blueprint hygiene: "
                f"raw={log_meta['graph_candidates_raw']} "
                f"→ deduped={log_meta['graph_candidates_deduped']} "
                f"→ final={log_meta['graph_candidates_after_sqlite_filter']} "
                f"(mode={log_meta['graph_crosscheck_mode']})"
            )

            if not candidates:
                return ""

            lines = ["VERFÜGBARE BLUEPRINTS (installiert):"]
            for c in candidates:
                caps = c.meta.get("capabilities", [])
                # Extract description from raw content: "id: description (Capabilities: ...)"
                desc_raw = c.content
                if ":" in desc_raw:
                    desc = desc_raw.split(":", 1)[1].split("(")[0].strip()
                else:
                    desc = desc_raw[:80] if desc_raw else (c.meta.get("name", "") or c.blueprint_id)
                line = f"- {c.blueprint_id}: {desc}"
                if caps:
                    line += f" (Capabilities: {', '.join(caps)})"
                lines.append(line)

            log_info(f"[ContextManager] Blueprint context: {len(lines) - 1} Blueprints für ThinkingLayer")
            return "\n".join(lines)
        except Exception as e:
            log_warn(f"[ContextManager] Blueprint graph search failed: {e}")
            return ""

    # ═══════════════════════════════════════════════════════════
    # SKILL KNOWLEDGE BASE HINT
    # ═══════════════════════════════════════════════════════════

    def _load_skill_knowledge_hint(self) -> str:
        """
        Lädt nur den Hinweis dass die SkillKnowledgeBase existiert.
        Winziger Kontext-Footprint — kein Inhalt, nur Kategorien + Tool-Name.
        TRION fragt aktiv ab (query_skill_knowledge) wenn er Inspiration braucht.
        """
        import urllib.request as _ur
        import json as _json

        skill_server_url = os.getenv("SKILL_SERVER_URL", "http://trion-skill-server:8088")
        try:
            req = _ur.Request(f"{skill_server_url}/v1/skill-knowledge/categories")
            with _ur.urlopen(req, timeout=2) as r:
                data = _json.loads(r.read())
            categories = data.get("categories", [])
            if not categories:
                return ""
            cats_str = " · ".join(categories)
            return (
                f"SKILL_KNOWLEDGE_BASE (Inspiration für neue Skills):\n"
                f"Kategorien: {cats_str}\n"
                f"→ Tool: query_skill_knowledge(query, category) — Templates + Pakete abrufen"
            )
        except Exception:
            return ""

    # ═══════════════════════════════════════════════════════════
    # TRION GESETZE
    # ═══════════════════════════════════════════════════════════

    def _load_trion_laws(self) -> str:
        """
        Lädt unumstößliche TRION-Gesetze aus dem Graph (_trion_laws).
        Immer im ThinkingLayer-Kontext — kein Caching nötig (selten geändert).
        """
        try:
            results = graph_search("_trion_laws", "hardware limits laws constraints", depth=0, limit=20)
            if not results:
                return ""
            lines = []
            for r in results:
                content = r.get("content", "").strip()
                if content:
                    lines.append(f"⚖️ {content}")
            if lines:
                return "TRION-GESETZE (unumstößlich):\n" + "\n".join(lines)
        except Exception as e:
            pass
        return ""

    # ═══════════════════════════════════════════════════════════
    # DAILY PROTOCOL
    # ═══════════════════════════════════════════════════════════

    def _load_daily_protocol(self, time_reference: str = None) -> str:
        """
        Lädt Protokoll-Dateien mit intelligentem time_reference-Routing.

        time_reference:
          None / "today"             → heute + gestern (Standard)
          "yesterday"                → gestern
          "day_before_yesterday"     → vorgestern
          "YYYY-MM-DD"               → genau dieses Datum
                                       Fallback → graph_search wenn Datei fehlt

        Jede Datei bekommt einen Datum-Header damit TRION weiß was "heute" ist.
        Rolling Summary wird immer vorangestellt.
        """
        today = datetime.now()
        today_str = today.strftime("%Y-%m-%d")

        # Ziel-Datum(en) bestimmen
        if time_reference in (None, "today"):
            yesterday_str = (today - timedelta(days=1)).strftime("%Y-%m-%d")
            date_strs = [today_str, yesterday_str]
            is_specific = False
        elif time_reference == "yesterday":
            date_strs = [(today - timedelta(days=1)).strftime("%Y-%m-%d")]
            is_specific = True
        elif time_reference == "day_before_yesterday":
            date_strs = [(today - timedelta(days=2)).strftime("%Y-%m-%d")]
            is_specific = True
        else:
            # Konkretes ISO-Datum "YYYY-MM-DD"
            date_strs = [time_reference]
            is_specific = True

        combined = ""
        found_any = False

        for date_str in date_strs:
            filepath = self.PROTOCOL_DIR / f"{date_str}.md"
            if not filepath.exists():
                continue
            try:
                mtime = filepath.stat().st_mtime
                cached = self._protocol_cache.get(str(filepath))
                if cached and cached[0] == mtime:
                    content = cached[1]
                else:
                    content = filepath.read_text(encoding="utf-8")
                    self._protocol_cache[str(filepath)] = (mtime, content)

                if content.strip():
                    # Datum-Header voranstellen (TRION weiß so was "heute" ist)
                    label = f"DATUM: {date_str}" + (" (HEUTE)" if date_str == today_str else "")
                    combined += f"[{label}]\n{content}\n"
                    found_any = True
            except Exception as e:
                log_warn(f"[ContextManager] Protocol read error for {date_str}: {e}")

        # Fallback: spezifisches Datum nicht gefunden → graph_search Hinweis
        if is_specific and not found_any and date_strs:
            log_info(f"[ContextManager] Protocol missing for {date_strs[0]} — graph fallback active")
            combined = f"[PROTOKOLL FÜR {date_strs[0]} NICHT VORHANDEN — Graph-Suche empfohlen]\n"

        # Rolling Summary voranstellen (komprimierte ältere Sessions)
        rolling_file = self.PROTOCOL_DIR / "rolling_summary.md"
        if rolling_file.exists():
            try:
                rs_content = rolling_file.read_text(encoding="utf-8").strip()
                if rs_content:
                    combined = f"[ZUSAMMENFASSUNG ÄLTERER GESPRÄCHE]\n{rs_content}\n\n[AKTUELLE GESPRÄCHE]\n" + combined
            except Exception:
                pass

        return combined.strip()

    # ═══════════════════════════════════════════════════════════
    # ACTIVE CONTAINERS (Docker-Truth — Phase 4)
    # ═══════════════════════════════════════════════════════════

    def _load_active_containers(self) -> str:
        """
        Load active containers from Docker Engine truth (via container_commander).

        Phase 4: Uses list_containers() → Docker SDK instead of workspace event-log.
        Survives restarts, TTL drift, and today-only filter issues.

        Returns formatted text for ThinkingLayer injection.
        Falls back to empty string on any error (Docker unavailable etc.).
        """
        try:
            from container_commander.engine import list_containers
            from container_commander.models import ContainerStatus

            instances = list_containers()
            active = [i for i in instances if i.status == ContainerStatus.RUNNING]

            if not active:
                return ""

            lines = ["AKTIVE CONTAINER (Docker-Sicht):"]
            for inst in active:
                short_id = inst.container_id[:12]
                ttl_str = f", TTL={inst.ttl_remaining}s" if inst.ttl_remaining > 0 else ""
                lines.append(
                    f"- {inst.blueprint_id} → {short_id}"
                    f" (gestartet {inst.started_at or '?'}{ttl_str})"
                )
            lines.append(
                "HINWEIS: Nutze exec_in_container mit der container_id "
                "statt einen neuen Container zu starten."
            )

            ctx = "\n".join(lines)
            log_info(f"[ContextManager] Active containers (Docker): {len(active)} found")
            return ctx

        except Exception as e:
            log_warn(f"[ContextManager] Active container load failed: {e}")
            return ""

    def _extract_workspace_events(self, result) -> list:
        """
        Extract event list from workspace_event_list result.
        Handles:
          - ToolResult (Fast-Lane): result.content is a list of dicts
          - dict with structuredContent.entries
          - plain list
        """
        # Fast-Lane ToolResult: .content holds the list directly
        if hasattr(result, "content"):
            content = result.content
            if isinstance(content, list):
                return content
            # Rare: content is a JSON string
            if isinstance(content, str):
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, list):
                        return parsed
                except (json.JSONDecodeError, TypeError):
                    pass
            return []
        # Dict wrapper (sql-memory fallback)
        if isinstance(result, dict):
            sc = result.get("structuredContent", result)
            entries = sc.get("entries", sc.get("events", []))
            return entries if isinstance(entries, list) else []
        # Already a list
        if isinstance(result, list):
            return result
        return []

    def _get_event_data(self, entry: dict) -> dict:
        """
        Extract event payload from a workspace_events row.
        event_data is stored as a dict directly (after Commit 2 migration).
        """
        event_data = entry.get("event_data", {})
        if isinstance(event_data, dict):
            return event_data
        # Legacy: JSON string (pre-migration rows)
        if isinstance(event_data, str):
            try:
                parsed = json.loads(event_data)
                return parsed if isinstance(parsed, dict) else {}
            except (json.JSONDecodeError, TypeError):
                pass
        return {}

    def _extract_workspace_entries(self, result) -> list:
        """Extract entries list from MCP workspace_list result (workspace_entries table)."""
        if isinstance(result, dict):
            sc = result.get("structuredContent", result)
            return sc.get("entries", [])
        return []

    # ═══════════════════════════════════════════════════════════
    # SMALL-MODEL CONTEXT CLEANUP
    # ═══════════════════════════════════════════════════════════

    def build_small_model_context(
        self,
        conversation_id: Optional[str] = None,
        limits: Optional[dict] = None,
        include_entries: bool = False,
        exclude_event_types: Optional[set] = None,
        trigger: Optional[str] = None,
    ) -> str:
        """
        Build a compact NOW/RULES/NEXT context for small/constrained models.

        Fetches workspace_events (last 48h), applies mapping rules via
        core.context_cleanup, and returns formatted text.

        Args:
            conversation_id:     Filter events to this conversation (None = all).
            trigger:             (Commit B) JIT trigger type for CSV loading gate.
                                 "time_reference" | "remember" | "fact_recall" | None.
                                 When TYPEDSTATE_CSV_JIT_ONLY=true: None → 0 CSV rows.
            limits:              Optional override for now_max, rules_max, next_max.
            include_entries:     If True, also load editable workspace_entries.
            exclude_event_types: Optional set of event_type strings to skip.
                                 Used by SINGLE_TRUTH_GUARD to prevent tool_result
                                 events from appearing in both compact context and
                                 tool_context (double injection).

        Returns:
            Formatted string, empty if no events found.
        """
        try:
            from core.context_cleanup import build_compact_context, format_compact_context
            from mcp.hub import get_hub

            hub = get_hub()
            hub.initialize()

            # Load events from Fast-Lane event store
            args: dict = {"limit": 100}
            if conversation_id:
                args["conversation_id"] = conversation_id
            ev_result = hub.call_tool("workspace_event_list", args)
            events = self._extract_workspace_events(ev_result)
            # SINGLE_TRUTH_GUARD: filter event types already claimed by another channel.
            # Prevents tool_result events (in tool_ctx) from also appearing in compact context.
            if exclude_event_types:
                _before = len(events)
                events = [e for e in events if e.get("event_type") not in exclude_event_types]
                if len(events) < _before:
                    log_info(
                        f"[ContextManager] Single-Truth filter: "
                        f"{_before - len(events)} events excluded (types={exclude_event_types})"
                    )

            entries = None
            if include_entries:
                # Load editable entries from sql-memory
                ent_result = hub.call_tool("workspace_list", {"limit": 20})
                entries = self._extract_workspace_entries(ent_result)

            # TypedState CSV: load supplementary events if enabled via config flags.
            # maybe_load_csv_events() respects TYPEDSTATE_CSV_ENABLE, TYPEDSTATE_MODE,
            # and TYPEDSTATE_ENABLE_SMALL_ONLY — returns [] when any flag is off.
            from core.typedstate_csv_loader import maybe_load_csv_events
            # Commit B: pass trigger for JIT gating (trigger from limits or explicit param)
            # Finding #2: pass conversation_id to prevent cross-conversation event leak
            _csv_trigger = trigger or (limits or {}).get("csv_trigger")
            csv_events = maybe_load_csv_events(
                small_model_mode=True,
                trigger=_csv_trigger,
                conversation_id=conversation_id or None,
            )

            ctx = build_compact_context(events, entries=entries, limits=limits,
                                        extra_events=csv_events or None)

            # TypedState V1 wiring (Commit 4: shadow=log-diff, active=use-v1-render)
            # off (default) → legacy path (format_compact_context), behavior unchanged.
            # shadow         → log diff between V1 and legacy NOW bullets, return legacy.
            # active         → return V1 render (includes V1 extra NOW bullets).
            from config import get_typedstate_mode as _get_ts_mode
            _ts_mode = _get_ts_mode()

            if _ts_mode == "shadow":
                from core.context_cleanup import format_typedstate_v1, _log_typedstate_diff
                _v1_now = list(ctx.now) + ctx.meta.get("v1_extra_now", [])
                _log_typedstate_diff(ctx.now, _v1_now)
                text = format_compact_context(ctx)  # kein Wiring im Output
                log_info(
                    f"[ContextManager] TypedState-shadow: legacy output, diff logged "
                    f"v1_extras={len(ctx.meta.get('v1_extra_now', []))}"
                )
            elif _ts_mode == "active":
                from core.context_cleanup import format_typedstate_v1
                text = format_typedstate_v1(ctx)
                log_info(
                    f"[ContextManager] TypedState-active: v1 render "
                    f"v1_extras={len(ctx.meta.get('v1_extra_now', []))}"
                )
            else:  # "off" or unknown → legacy (current behavior, TYPEDSTATE_MODE default)
                text = format_compact_context(ctx)

            log_info(
                f"[ContextManager] Small-model context built: "
                f"{len(ctx.now)}NOW/{len(ctx.rules)}RULES/{len(ctx.next)}NEXT"
            )
            return text
        except Exception as e:
            log_warn(f"[ContextManager] build_small_model_context failed: {e}")
            # Fail-closed: return canonical minimal context instead of silent empty string.
            # The model sees CONTEXT ERROR + Rückfrage and can ask the user for clarification.
            try:
                from core.context_cleanup import _minimal_fail_context, format_compact_context
                return format_compact_context(_minimal_fail_context())
            except Exception:
                return "NOW:\n  - CONTEXT ERROR: Zustand unvollständig\nNEXT:\n  - Bitte Anfrage kurz präzisieren oder letzten Schritt wiederholen"

    # ═══════════════════════════════════════════════════════════
    # ADDITIONAL HELPERS
    # ═══════════════════════════════════════════════════════════

    def get_tool_context(self, query: str) -> str:
        """
        Specialized method for tool RAG.
        Alias for _search_system_tools (public API).
        """
        return self._search_system_tools(query)
