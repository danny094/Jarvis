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
import time
from concurrent.futures import ALL_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Tuple, Dict, List, Optional
from utils.logger import log_info, log_warn, log_error
from config import (
    get_context_retrieval_budget_s,
    get_memory_lookup_timeout_s,
    get_memory_keys_max_per_request,
)
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
        self._retrieval_executor: Optional[ThreadPoolExecutor] = None
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
        request_cache: Optional[Dict[str, Any]] = None,
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
            request_cache: Optional request-scoped cache for memory lookup results.
                           Reused across multiple retrieval rounds in one request.

        Returns:
            ContextResult with memory_data, memory_used, system_tools
        """
        result = ContextResult()
        request_cache = request_cache if isinstance(request_cache, dict) else {}
        retrieval_budget_s = get_context_retrieval_budget_s()
        per_call_timeout_s = get_memory_lookup_timeout_s()
        deadline = time.monotonic() + retrieval_budget_s

        def _budget_remaining() -> float:
            return max(0.0, deadline - time.monotonic())

        def _budget_ok(stage: str) -> bool:
            if _budget_remaining() > 0:
                return True
            log_warn(
                f"[ContextManager] Retrieval budget exhausted at stage={stage} "
                f"budget_s={retrieval_budget_s:.2f} — degrading context"
            )
            return False

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
                memory_keys = self._normalize_memory_keys(thinking_plan.get("memory_keys", []))
                if memory_keys and _budget_ok("small_mode_memory_keys"):
                    key_results = self._search_memory_keys_parallel(
                        keys=memory_keys,
                        conversation_id=conversation_id,
                        include_system=False,
                        deadline=deadline,
                        call_timeout_s=per_call_timeout_s,
                        request_cache=request_cache,
                    )
                    for key in memory_keys:
                        content, found = key_results.get(key, ("", False))
                        if found:
                            log_info(f"[ContextManager] small_model_mode memory key='{key}'")
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
                        f"gespräch {time_ref}",
                        conversation_id,
                        include_system=False,
                        deadline=deadline,
                        call_timeout_s=per_call_timeout_s,
                        request_cache=request_cache,
                    )
                    if graph_results[1]:  # found = True
                        result.memory_data += f"\n[GRAPH-FALLBACK für {time_ref}]\n{graph_results[0]}\n"
                        result.sources.append(f"graph_fallback:{time_ref}")

        # 0.3. TRION Gesetze (unumstößliche Hardware-Constraints, immer geladen)
        laws_ctx = self._load_trion_laws() if _budget_ok("trion_laws") else ""
        if laws_ctx:
            result.memory_data += laws_ctx + "\n"
            result.memory_used = True
            result.sources.append("trion_laws")

        # 0.5. Active Container context (Workspace Event-Log)
        container_ctx = self._load_active_containers() if _budget_ok("active_containers") else ""
        if container_ctx:
            result.memory_data += container_ctx + "\n"
            result.memory_used = True
            result.sources.append("active_containers")

        # 1. System Tools if relevant
        system_tools = self._search_system_tools(query) if _budget_ok("system_tools") else ""
        if system_tools:
            result.system_tools = system_tools
            result.memory_used = True
            result.sources.append("system_tools")
            log_info("[ContextManager] Found system tool info")

        # 1.5. Skill Graph: semantische Skill-Discovery (renderer-gesteuert, C6)
        # typedstate: skills injected by ThinkingLayer prefetch (_maybe_prefetch_skills) — skip here
        # legacy:     inject via _search_skill_graph (original behaviour)
        from config import get_skill_context_renderer as _gcr
        if _gcr() == "legacy" and _budget_ok("skill_graph"):
            skill_ctx = self._get_skill_context(query)
            if skill_ctx:
                result.system_tools = (result.system_tools + "\n" + skill_ctx).strip()
                result.memory_used = True
                result.sources.append("skill_graph")
                log_info("[ContextManager] Found skills in graph (legacy renderer)")

        # 1.55. Blueprint Graph: semantische Blueprint-Discovery (immer aktiv)
        blueprint_ctx = self._search_blueprint_graph(query) if _budget_ok("blueprint_graph") else ""
        if blueprint_ctx:
            result.system_tools = (result.system_tools + "\n\n" + blueprint_ctx).strip()
            result.memory_used = True
            result.sources.append("blueprint_graph")

        # 1.6. SkillKnowledgeBase Hint (winziger Kontext-Footprint, immer da)
        kb_hint = self._load_skill_knowledge_hint() if _budget_ok("skill_knowledge_hint") else ""
        if kb_hint:
            result.system_tools = (result.system_tools + "\n\n" + kb_hint).strip()
            result.sources.append("skill_knowledge_base")

        # 2. User Memory if needed
        # Temporal guard: Protokoll ist die Quelle — kein Graph/Fact-Lookup nötig
        if time_ref:
            log_info(f"[ContextManager] Skipping memory search — time_reference={time_ref}, protocol is source")
        elif thinking_plan.get("needs_memory") or thinking_plan.get("is_fact_query"):
            memory_keys = self._normalize_memory_keys(thinking_plan.get("memory_keys", []))
            if memory_keys and _budget_ok("memory_keys_loop"):
                key_results = self._search_memory_keys_parallel(
                    keys=memory_keys,
                    conversation_id=conversation_id,
                    include_system=True,
                    deadline=deadline,
                    call_timeout_s=per_call_timeout_s,
                    request_cache=request_cache,
                )

                for key in memory_keys:
                    content, found = key_results.get(key, ("", False))
                    if found:
                        result.memory_data += content
                        result.memory_used = True
                        result.sources.append(f"memory:{key}")
        
        return result
    
    # ═══════════════════════════════════════════════════════════
    # PRIVATE HELPERS (Copied from bridge.py)
    # ═══════════════════════════════════════════════════════════
    
    def _ensure_retrieval_executor(self) -> ThreadPoolExecutor:
        """Lazy init for retrieval executor (needed for __new__ test instances)."""
        executor = getattr(self, "_retrieval_executor", None)
        if executor is not None:
            return executor
        try:
            raw_workers = int(os.getenv("CONTEXT_RETRIEVAL_MAX_WORKERS", "16"))
        except Exception:
            raw_workers = 16
        max_workers = max(4, min(64, raw_workers))
        executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ctx-retrieval")
        self._retrieval_executor = executor
        return executor

    @staticmethod
    def _normalize_memory_keys(keys: List[str], max_keys: Optional[int] = None) -> List[str]:
        limit = (
            max(1, int(max_keys))
            if max_keys is not None
            else get_memory_keys_max_per_request()
        )
        normalized: List[str] = []
        seen = set()
        total_nonempty = 0
        for key in keys or []:
            k = str(key or "").strip()
            if not k or k in seen:
                continue
            total_nonempty += 1
            normalized.append(k)
            seen.add(k)
            if len(normalized) >= limit:
                break
        if total_nonempty > limit:
            log_info(
                f"[ContextManager] memory_keys capped: kept={len(normalized)} "
                f"dropped={total_nonempty - len(normalized)} limit={limit}"
            )
        return normalized

    def _search_memory_keys_parallel(
        self,
        keys: List[str],
        conversation_id: str,
        include_system: bool = True,
        deadline: Optional[float] = None,
        call_timeout_s: Optional[float] = None,
        request_cache: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Tuple[str, bool]]:
        """
        Request phase retrieval:
        1) collect keys
        2) execute key lookups concurrently
        3) merge in original key order
        """
        normalized_keys = self._normalize_memory_keys(keys)
        if not normalized_keys:
            return {}
        call_timeout_s = call_timeout_s if call_timeout_s is not None else get_memory_lookup_timeout_s()
        request_cache = request_cache if isinstance(request_cache, dict) else {}

        def _remaining_timeout() -> float:
            if deadline is None:
                # Whole key phase budget when no global deadline exists.
                return max(0.2, call_timeout_s * len(normalized_keys))
            return max(0.0, deadline - time.monotonic())

        max_workers = max(1, min(6, len(normalized_keys)))
        degraded_fanout = len(normalized_keys) >= 3
        if degraded_fanout:
            log_info(
                f"[ContextManager-Memory] degraded fanout active: keys={len(normalized_keys)} "
                f"workers={max_workers}"
            )
        results: Dict[str, Tuple[str, bool]] = {}
        future_map = {}

        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ctx-keys") as key_executor:
            for key in normalized_keys:
                if _remaining_timeout() <= 0:
                    log_warn(f"[ContextManager-Memory] Key phase budget exhausted before key='{key}'")
                    results[key] = ("", False)
                    continue
                future = key_executor.submit(
                    self._search_memory_multi_context,
                    key,
                    conversation_id,
                    include_system,
                    deadline,
                    call_timeout_s,
                    request_cache,
                    "degraded" if degraded_fanout else "full",
                )
                future_map[future] = key

            if future_map:
                phase_wait_timeout = self._compute_key_phase_wait_timeout(
                    remaining_s=_remaining_timeout(),
                    call_timeout_s=call_timeout_s,
                    num_keys=len(normalized_keys),
                    max_workers=max_workers,
                )
                done, not_done = wait(
                    set(future_map.keys()),
                    timeout=phase_wait_timeout,
                    return_when=ALL_COMPLETED,
                )
                for fut in done:
                    key = future_map[fut]
                    try:
                        results[key] = fut.result()
                    except Exception as e:
                        log_warn(f"[ContextManager-Memory] Key lookup failed key='{key}': {e}")
                        results[key] = ("", False)
                for fut in not_done:
                    key = future_map[fut]
                    fut.cancel()
                    log_warn(f"[ContextManager-Memory] Key lookup timed out key='{key}'")
                    results[key] = ("", False)

        return results

    @staticmethod
    def _compute_key_phase_wait_timeout(
        remaining_s: float,
        call_timeout_s: float,
        num_keys: int,
        max_workers: int,
    ) -> float:
        """
        Bound key-phase wait time to avoid long tail stalls under high fanout.
        """
        remaining = max(0.0, float(remaining_s))
        timeout = max(0.2, float(call_timeout_s))
        keys = max(1, int(num_keys))
        workers = max(1, int(max_workers))
        queue_factor = max(1.0, keys / workers)
        capped = max(0.3, timeout * queue_factor + 0.25)
        return max(0.0, min(remaining, capped))

    def _search_memory_multi_context(
        self, 
        key: str, 
        conversation_id: str,
        include_system: bool = True,
        deadline: Optional[float] = None,
        call_timeout_s: Optional[float] = None,
        request_cache: Optional[Dict[str, Any]] = None,
        fanout_mode: str = "full",
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
        call_timeout_s = call_timeout_s if call_timeout_s is not None else get_memory_lookup_timeout_s()
        request_cache = request_cache if isinstance(request_cache, dict) else {}
        fanout_mode = (fanout_mode or "full").strip().lower()
        degraded_fanout = fanout_mode == "degraded"
        executor = self._ensure_retrieval_executor()

        def _remaining_timeout() -> float:
            if deadline is None:
                return max(0.2, call_timeout_s)
            remaining = max(0.0, deadline - time.monotonic())
            return max(0.2, min(call_timeout_s, remaining))

        def _budget_ok(stage: str) -> bool:
            if deadline is None:
                return True
            if (deadline - time.monotonic()) > 0:
                return True
            log_warn(f"[ContextManager-Memory] Budget exhausted at stage={stage} key='{key}'")
            return False
        
        # Kontexte die durchsucht werden
        contexts = [conversation_id]
        if include_system and conversation_id != SYSTEM_CONV_ID:
            contexts.append(SYSTEM_CONV_ID)

        def _cache_key(ctx: str, backend: str) -> str:
            return f"{ctx}|{backend}|{key}"

        backend_values: Dict[str, Dict[str, Any]] = {ctx: {} for ctx in contexts}
        future_map = {}
        cache_hits = 0

        for ctx in contexts:
            if not _budget_ok("context_submit"):
                break
            stage_timeout = _remaining_timeout()
            if stage_timeout <= 0:
                break

            if ctx == SYSTEM_CONV_ID:
                # System context is useful but expensive under pressure:
                # keep FACT always, GRAPH only in full fanout with sufficient budget.
                specs = [("fact", get_fact_for_query, None)]
                if not degraded_fanout and stage_timeout >= 1.0:
                    specs.append(("graph", graph_search, []))
            else:
                # User context: keep high-signal backends first.
                specs = [
                    ("fact", get_fact_for_query, None),
                    ("graph", graph_search, []),
                ]
                if stage_timeout >= 0.45:
                    specs.append(("semantic", semantic_search, []))
                if not degraded_fanout and stage_timeout >= 0.9:
                    specs.append(("fallback", search_memory_fallback, ""))

            for backend_name, fn, default_value in specs:
                ck = _cache_key(ctx, backend_name)
                if ck in request_cache:
                    backend_values[ctx][backend_name] = request_cache[ck]
                    cache_hits += 1
                    continue
                future = executor.submit(fn, ctx, key, timeout_s=stage_timeout)
                future_map[future] = (ctx, backend_name, ck, default_value)

        if future_map:
            wait_timeout = max(0.0, _remaining_timeout())
            done, not_done = wait(set(future_map.keys()), timeout=wait_timeout, return_when=ALL_COMPLETED)
            for fut in done:
                ctx, backend_name, ck, default_value = future_map[fut]
                try:
                    value = fut.result()
                except Exception as e:
                    value = default_value
                    log_warn(
                        f"[ContextManager-Memory] backend failed key='{key}' "
                        f"ctx='{ctx}' backend='{backend_name}' err={e}"
                    )
                backend_values[ctx][backend_name] = value
                request_cache[ck] = value

            for fut in not_done:
                ctx, backend_name, ck, default_value = future_map[fut]
                fut.cancel()
                backend_values[ctx][backend_name] = default_value
                request_cache[ck] = default_value
                log_warn(
                    f"[ContextManager-Memory] backend timeout key='{key}' "
                    f"ctx='{ctx}' backend='{backend_name}'"
                )

        for ctx in contexts:
            if not _budget_ok("context_compose"):
                break
            ctx_label = "system" if ctx == SYSTEM_CONV_ID else "user"
            values = backend_values.get(ctx, {})
            ctx_added_content = False

            # 1) Fact priority
            fact_value = values.get("fact")
            if fact_value:
                found_content += f"{key}: {fact_value}\n"
                found = True
                ctx_added_content = True
                log_info(f"[ContextManager-Memory] Found fact ({ctx_label}): {key}={str(fact_value)[:50]}...")
                continue

            # 2) Graph
            graph_results = values.get("graph") or []
            if isinstance(graph_results, list) and graph_results:
                for res in graph_results[:3]:
                    if not isinstance(res, dict):
                        continue
                    content = res.get("content", "")
                    if content:
                        log_info(f"[ContextManager-Memory] Graph match ({ctx_label}): {content[:50]}")
                        found_content += f"{content}\n"
                        ctx_added_content = True
                if ctx_added_content:
                    found = True
                    continue

            # 3) Semantic (user ctx only)
            if ctx != SYSTEM_CONV_ID:
                semantic_results = values.get("semantic") or []
                if isinstance(semantic_results, list) and semantic_results:
                    for res in semantic_results[:3]:
                        if not isinstance(res, dict):
                            continue
                        content = res.get("content", "")
                        if content:
                            found_content += f"{content}\n"
                            ctx_added_content = True
                    if ctx_added_content:
                        found = True
                        continue

                # 4) Fallback
                fallback = values.get("fallback")
                if fallback:
                    found_content += f"{key}: {fallback}\n"
                    found = True

        if future_map or cache_hits:
            log_info(
                f"[ContextManager-Memory] key='{key}' contexts={len(contexts)} "
                f"backend_calls={len(future_map)} cache_hits={cache_hits}"
            )

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

    def _build_typedstate_skill_context(self, query: str) -> str:
        """
        C6 TypedState skill context using the C5 pipeline.

        C10 selection mode:
          - budgeted (default): top-k + char-cap preselection first, then lazy
            detail fetch only for selected active skills.
          - legacy: eager detail fetch for all active skills (rollback behavior).

        Runs the C5 deterministic pipeline for final rendering:
            normalize → dedupe → top_k → budget → render

        Returns "SKILLS:\n  - ..." format, empty string on error or no skills.
        Never raises — fail-closed: returns "" on any exception.
        """
        import urllib.request as _ur
        import json as _json
        import importlib
        from urllib.parse import quote as _quote

        try:
            _ts = importlib.import_module("core.typedstate_skills")
        except ImportError:
            log_warn("[ContextManager] typedstate_skills import failed — returning empty skill context")
            return ""
        build_skills_context = getattr(_ts, "build_skills_context", None)
        if not callable(build_skills_context):
            log_warn("[ContextManager] build_skills_context missing — returning empty skill context")
            return ""
        _ts_normalize = getattr(_ts, "normalize", None)
        _ts_dedupe = getattr(_ts, "dedupe", None)
        _ts_top_k = getattr(_ts, "top_k", None)
        _ts_budget = getattr(_ts, "budget", None)
        can_preselect = all(callable(fn) for fn in (_ts_normalize, _ts_dedupe, _ts_top_k, _ts_budget))

        from config import (
            get_skill_selection_char_cap,
            get_skill_selection_mode,
            get_skill_selection_top_k,
        )

        skill_server_url = os.getenv("SKILL_SERVER_URL", "http://trion-skill-server:8088")
        selection_mode = get_skill_selection_mode()
        top_k_count = get_skill_selection_top_k()
        char_cap = get_skill_selection_char_cap()

        def _detail_url(name: str) -> str:
            # channel=active makes endpoint contract explicit and avoids draft fallback.
            return f"{skill_server_url}/v1/skills/{_quote(name, safe='')}?channel=active"

        def _fetch_active_detail(name: str) -> dict:
            try:
                req_detail = _ur.Request(_detail_url(name))
                with _ur.urlopen(req_detail, timeout=2) as mr:
                    return _json.loads(mr.read())
            except Exception:
                return {}

        def _to_raw_active(name: str, meta: dict) -> dict:
            return {
                "name": name,
                "channel": "active",
                "description": meta.get("description", ""),
                "triggers": meta.get("triggers", []),
                "validation_score": meta.get("validation_score", 1.0),
                "gap_question": meta.get("gap_question"),
                "required_packages": meta.get("required_packages", []),
                "status": "installed",
                "signature_status": meta.get("signature_status", "unsigned"),
            }

        try:
            req = _ur.Request(f"{skill_server_url}/v1/skills")
            with _ur.urlopen(req, timeout=3) as r:
                data = _json.loads(r.read())

            active_names = data.get("active", [])
            draft_names = data.get("drafts", [])
        except Exception as e:
            log_warn(f"[ContextManager] TypedState skill fetch failed: {e}")
            return ""

        if not active_names and not draft_names:
            return ""

        raw_skills = []
        if selection_mode == "legacy" or not can_preselect:
            for name in active_names:
                meta = _fetch_active_detail(name)
                raw_skills.append(_to_raw_active(name, meta))
            for name in draft_names:
                raw_skills.append({"name": name, "channel": "draft", "status": "draft"})
        else:
            # C10 budgeted preselection on minimal records (no detail I/O).
            preselect_raw = (
                [{"name": name, "channel": "active", "status": "installed"} for name in active_names]
                + [{"name": name, "channel": "draft", "status": "draft"} for name in draft_names]
            )
            try:
                selected_entities = [_ts_normalize(s) for s in preselect_raw]
                selected_entities = _ts_dedupe(selected_entities)
                selected_entities = _ts_top_k(selected_entities, top_k_count)
                selected_entities = _ts_budget(selected_entities, char_cap)
            except Exception as exc:
                log_warn(f"[ContextManager] TypedState preselection failed: {exc}")
                return ""

            for entity in selected_entities:
                if entity.channel == "active":
                    meta = _fetch_active_detail(entity.name)
                    raw_skills.append(_to_raw_active(entity.name, meta))
                else:
                    raw_skills.append({"name": entity.name, "channel": "draft", "status": "draft"})

        if not raw_skills:
            return ""

        result = build_skills_context(
            raw_skills,
            mode="active",
            top_k_count=top_k_count,
            char_cap=char_cap,
        )
        if result:
            selected_active = sum(1 for s in raw_skills if s.get("channel") == "active")
            log_info(
                f"[ContextManager] TypedState skill context ({selection_mode}): "
                f"selected={len(raw_skills)} active_detail={selected_active}/{len(active_names)} "
                f"top_k={top_k_count} char_cap={char_cap}"
            )
        return result

    def _get_skill_context(self, query: str) -> str:
        """
        Single authority for skill context injection (C6).

        Routes between TypedState C5 pipeline and legacy _search_skill_graph
        based on SKILL_CONTEXT_RENDERER environment flag.

        'typedstate' (default): uses C5 pipeline → 'SKILLS:' header format
        'legacy':               uses _search_skill_graph → 'VERFÜGBARE SKILLS:' format

        Rollback: SKILL_CONTEXT_RENDERER=legacy
        """
        from config import get_skill_context_renderer
        if get_skill_context_renderer() == "typedstate":
            return self._build_typedstate_skill_context(query)
        return self._search_skill_graph(query)

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
