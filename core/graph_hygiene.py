"""
Graph Hygiene — Phase 5
=======================

SQLite = Truth, Graph = Index.

Central hygiene pipeline for all blueprint graph queries:
  parse → extra_filter → dedupe_latest_by_blueprint_id → filter_against_sqlite_active_set

Policy:
  - fail-closed by default: if SQLite is unavailable, return NO results (safe).
  - Explicit opt-in required to override to fail-open (legacy, only via flag).

Used by:
  - core/blueprint_router.py  (BlueprintSemanticRouter)
  - core/context_manager.py   (_search_blueprint_graph)

Logging markers (all calls emit these via log_info):
  graph_candidates_raw                  — after parse
  graph_candidates_after_extra          — after caller-supplied extra_filter
  graph_candidates_deduped              — after dedupe_latest_by_blueprint_id
  graph_candidates_after_sqlite_filter  — final count after SQLite cross-check
  graph_crosscheck_mode                 — "strict" | "fail_closed_no_sqlite" | "fail_open_no_sqlite"
"""

import json
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

from utils.logger import log_info, log_warn


# ─────────────────────────────────────────────────────────────────────────────
# Data type
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GraphCandidate:
    """
    A single blueprint candidate from the graph, ready for hygiene processing.

    Fields:
        blueprint_id  — unique blueprint identifier (from metadata or content)
        score         — similarity score from graph search (higher = better match)
        meta          — parsed metadata dict (may be empty if metadata was missing)
        content       — raw content string from the graph node (for rendering)
        updated_at    — ISO 8601 timestamp from metadata.updated_at;
                        "" if absent (older graph nodes synced before Phase 5)
        node_id       — integer graph node id; 0 if absent.
                        Used as tie-breaker when updated_at strings are equal.
                        Higher node_id = later insertion = "newer" in tie-breaking.
    """
    blueprint_id: str
    score: float
    meta: dict
    content: str = ""
    updated_at: str = ""
    node_id: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Internal parser
# ─────────────────────────────────────────────────────────────────────────────

def _parse_candidate(raw: dict) -> Optional[GraphCandidate]:
    """
    Parse one raw graph-search result dict into a GraphCandidate.

    Returns None if:
      - metadata is broken JSON (non-parseable)
      - blueprint_id cannot be determined from metadata or content
    """
    try:
        meta_raw = raw.get("metadata") or "{}"
        meta = json.loads(meta_raw) if isinstance(meta_raw, str) else (meta_raw or {})
        if not isinstance(meta, dict):
            meta = {}
    except Exception:
        return None

    blueprint_id = meta.get("blueprint_id", "")
    if not blueprint_id:
        # Fallback: parse from content "blueprint_id: description ..."
        content = raw.get("content", "")
        if ":" in content:
            blueprint_id = content.split(":", 1)[0].strip()
    if not blueprint_id:
        return None

    try:
        score = float(raw.get("similarity") or raw.get("score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    try:
        node_id = int(raw.get("id") or raw.get("node_id") or 0)
    except (TypeError, ValueError):
        node_id = 0

    return GraphCandidate(
        blueprint_id=blueprint_id,
        score=score,
        meta=meta,
        content=raw.get("content") or "",
        updated_at=meta.get("updated_at") or "",
        node_id=node_id,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Deduplicate
# ─────────────────────────────────────────────────────────────────────────────

def dedupe_latest_by_blueprint_id(
    candidates: List[GraphCandidate],
) -> List[GraphCandidate]:
    """
    Deduplicate: keep exactly one candidate per blueprint_id — the "latest" one.

    "Latest" is determined by (updated_at, node_id) tuple comparison:
      1. updated_at — ISO 8601 lexicographic order (YYYY-MM-DD[Thh:mm:ss] — works correctly).
                      "" sorts before any real timestamp → nodes with updated_at always win.
      2. node_id    — higher integer means later graph insertion (tie-breaker).

    The returned list is sorted descending by score (highest score first),
    preserving the caller's original ranking intent for unique blueprint_ids.

    Args:
        candidates: list of GraphCandidate (may contain duplicates per blueprint_id)

    Returns:
        list of GraphCandidate, one per blueprint_id, score-sorted descending.
    """
    best: Dict[str, GraphCandidate] = {}
    for c in candidates:
        existing = best.get(c.blueprint_id)
        if existing is None:
            best[c.blueprint_id] = c
        else:
            # Compare (updated_at, node_id): higher = more recent
            if (c.updated_at, c.node_id) > (existing.updated_at, existing.node_id):
                best[c.blueprint_id] = c
    return sorted(best.values(), key=lambda x: x.score, reverse=True)


# ─────────────────────────────────────────────────────────────────────────────
# SQLite cross-check
# ─────────────────────────────────────────────────────────────────────────────

def filter_against_sqlite_active_set(
    candidates: List[GraphCandidate],
    active_ids: Set[str],
    *,
    fail_closed: bool = True,
) -> List[GraphCandidate]:
    """
    Filter candidates to only those present in the SQLite active set.

    Args:
        candidates:  list of GraphCandidate after dedupe
        active_ids:  set of blueprint_ids from get_active_blueprint_ids()
        fail_closed: default True. When True, blueprints absent from active_ids
                     are rejected (soft-deleted or stale graph nodes).
                     When False, all candidates pass (legacy fail-open — explicit opt-in only).

    Returns:
        Filtered list of GraphCandidate.
    """
    if not fail_closed:
        log_warn("[GraphHygiene] filter_against_sqlite_active_set: fail_closed=False — fail-open mode")
        return candidates

    accepted = []
    for c in candidates:
        if c.blueprint_id in active_ids:
            accepted.append(c)
        else:
            log_info(
                f"[GraphHygiene] Rejected '{c.blueprint_id}' "
                f"— not in SQLite active set (soft-deleted or stale graph node)"
            )
    return accepted


# ─────────────────────────────────────────────────────────────────────────────
# Full pipeline
# ─────────────────────────────────────────────────────────────────────────────

def apply_graph_hygiene(
    raw_results: list,
    *,
    fail_closed: bool = True,
    crosscheck_mode: str = "strict",
    extra_filter: Optional[Callable[["GraphCandidate"], bool]] = None,
) -> Tuple[List[GraphCandidate], Dict]:
    """
    Full blueprint hygiene pipeline:
      parse → extra_filter → dedupe_latest_by_blueprint_id → sqlite_crosscheck

    Args:
        raw_results:      Raw list from blueprint_semantic_search() or graph_search().
        fail_closed:      If True (default), return [] when SQLite is unavailable.
                          If False, return deduped candidates without SQLite filter
                          (legacy fail-open, requires explicit opt-in).
        crosscheck_mode:  Label for logging; currently only "strict" is used.
        extra_filter:     Optional predicate(GraphCandidate) -> bool applied BEFORE
                          SQLite cross-check (e.g. trust_level=="verified" in router).
                          Rejected candidates are excluded from all subsequent steps.

    Returns:
        Tuple (candidates, log_meta) where:
          candidates — List[GraphCandidate], hygiene-clean, score-sorted descending.
          log_meta   — dict with logging markers:
            "graph_candidates_raw"                  — count after parse
            "graph_candidates_after_extra"          — count after extra_filter
            "graph_candidates_deduped"              — count after dedupe
            "graph_candidates_after_sqlite_filter"  — final count
            "graph_crosscheck_mode"                 — effective mode string

    Policy:
        SQLite unavailable + fail_closed=True  → return []  (safe default)
        SQLite unavailable + fail_closed=False → return deduped (legacy explicit)
        SQLite ok                              → filter via active set
    """
    log_meta: Dict = {
        "graph_candidates_raw": 0,
        "graph_candidates_after_extra": 0,
        "graph_candidates_deduped": 0,
        "graph_candidates_after_sqlite_filter": 0,
        "graph_crosscheck_mode": crosscheck_mode,
    }

    # Step 1: Parse raw results into typed GraphCandidate objects
    parsed: List[GraphCandidate] = [
        c for raw in (raw_results or [])
        if (c := _parse_candidate(raw)) is not None
    ]
    log_meta["graph_candidates_raw"] = len(parsed)

    # Step 2: Extra filter (caller-supplied predicate — e.g. trust_level check)
    if extra_filter is not None:
        parsed = [c for c in parsed if extra_filter(c)]
    log_meta["graph_candidates_after_extra"] = len(parsed)

    # Step 3: Dedupe — keep latest revision per blueprint_id
    deduped = dedupe_latest_by_blueprint_id(parsed)
    log_meta["graph_candidates_deduped"] = len(deduped)

    # Step 4: SQLite cross-check
    try:
        from container_commander.blueprint_store import get_active_blueprint_ids
        active_ids: Set[str] = get_active_blueprint_ids()
        final = filter_against_sqlite_active_set(deduped, active_ids, fail_closed=fail_closed)
        log_meta["graph_crosscheck_mode"] = crosscheck_mode
    except Exception as e:
        log_warn(f"[GraphHygiene] SQLite cross-check failed: {e}")
        if fail_closed:
            log_warn(
                "[GraphHygiene] fail_closed=True — returning empty candidates "
                "(SQLite unavailable, safety default)"
            )
            log_meta["graph_crosscheck_mode"] = "fail_closed_no_sqlite"
            final = []
        else:
            log_warn(
                "[GraphHygiene] fail_closed=False — returning deduped candidates "
                "without SQLite filter (explicit fail-open override)"
            )
            log_meta["graph_crosscheck_mode"] = "fail_open_no_sqlite"
            final = deduped

    log_meta["graph_candidates_after_sqlite_filter"] = len(final)
    log_info(
        f"[GraphHygiene] Pipeline complete: "
        f"raw={log_meta['graph_candidates_raw']} "
        f"→ after_extra={log_meta['graph_candidates_after_extra']} "
        f"→ deduped={log_meta['graph_candidates_deduped']} "
        f"→ final={log_meta['graph_candidates_after_sqlite_filter']} "
        f"(mode={log_meta['graph_crosscheck_mode']})"
    )
    return final, log_meta
