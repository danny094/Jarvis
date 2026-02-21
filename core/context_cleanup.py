"""
core/context_cleanup.py — Small-Model-Context-Cleanup

Converts raw workspace_events into a CompactContext (NOW / RULES / NEXT)
suitable for context-limited models.

Pipeline (Phase 3):
    merge → normalize → dedupe → sort(ASC) → correlate → apply_to_state
    → select_top → render

Usage:
    from core.context_cleanup import build_compact_context, format_compact_context
    ctx = build_compact_context(events, entries=None, limits=None)
    text = format_compact_context(ctx)
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from dataclasses import field as _dc_field
from datetime import datetime
from typing import Dict, List, Optional

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

from utils.logger import log_info, log_warn

# ---------------------------------------------------------------------------
# TypedState V1 — Source reliability weights (active from Commit 2).
# Override via mapping_rules.yaml source_reliability.sources section.
# ---------------------------------------------------------------------------
_SOURCE_RELIABILITY_DEFAULTS: Dict[str, float] = {
    "workspace_event": 1.0,    # direct workspace event (highest trust)
    "tool_result":     0.85,   # tool result card
    "protocol":        0.75,   # daily protocol (time-gated)
    "memory":          0.70,   # retrieved memory entry
    "inference":       0.50,   # derived / inferred fact
}


# ---------------------------------------------------------------------------
# Inline data models (mirrors memory_speicher_draft/trion_small_model_models.py)
# ---------------------------------------------------------------------------

class _EntityState:
    def __init__(self, entity_type: str, entity_id: str):
        self.type = entity_type
        self.id = entity_id
        self.state = "unknown"
        self.last_action = ""
        self.last_exit_code: Optional[int] = None
        self.last_error: Optional[str] = None
        self.stability_score = "medium"
        self.blueprint_id: Optional[str] = None
        self.runtime: Optional[str] = None
        self.image: Optional[str] = None
        self.purpose: Optional[str] = None
        self.session_id: Optional[str] = None
        self.last_change_ts: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


# ---------------------------------------------------------------------------
# Phase 2 typed models
# ---------------------------------------------------------------------------

@dataclass
class TypedFact:
    """A typed, normalized fact extracted from a workspace event."""
    fact_type: str                          # e.g. "TOOL_ERROR", "CONTAINER_STARTED"
    value: str                              # human-readable fact value (capped at 200 chars)
    confidence: float = 1.0                 # 0.0–1.0
    observed_at: str = ""                   # ISO timestamp
    source: str = ""                        # event_type that produced this fact
    source_event_ids: List[str] = _dc_field(default_factory=list)


@dataclass
class ContainerEntity:
    """Typed entity for container lifecycle tracking (Phase 2 / V1 schema)."""
    id: str
    blueprint_id: Optional[str] = None
    status: str = "unknown"                 # running | stopped | expired | failed
    ttl_remaining: Optional[int] = None     # seconds; None = unknown/not set
    last_error: Optional[str] = None
    updated_at: str = ""                    # ISO timestamp of last state change
    last_exit_code: Optional[int] = None
    stability_score: str = "medium"
    # ── V1 fields (Commit 1: schema-only, no active wiring) ──────────────
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    source_event_ids: List[str] = _dc_field(default_factory=list)

    @property
    def container_id(self) -> str:
        """Backward-compat alias for id (V1)."""
        return self.id

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


class TypedState:
    """Mutable state built by applying mapping rules to event list."""

    def __init__(self):
        self.entities: Dict[str, _EntityState] = {}   # generic entities (backward compat)
        self.containers: Dict[str, ContainerEntity] = {}  # typed container entities (Phase 2)
        self.facts: Dict[str, List[TypedFact]] = {}    # typed facts by fact_type (Phase 2)
        self.focus_entity: Optional[str] = None
        self.active_gates: List[str] = []
        self.open_issues: List[str] = []
        self.user_constraints: List[str] = []
        self.last_error: Optional[str] = None
        self.pending_blueprint: Optional[str] = None
        self.updated_at: str = datetime.utcnow().isoformat() + "Z"
        # ── TypedState V1 fields ──────────────────────────────────────────
        self.version: str = "1"
        self.session_id: Optional[str] = None
        self.conversation_id: Optional[str] = None
        self.last_errors: List[str] = []           # ordered error log (max 10)
        self.pending_approvals: List[str] = []     # items awaiting approval (max 20)
        self.last_tool_results: List[str] = []     # ref_ids of recent tool result cards (max 10)
        self.source_event_ids: List[str] = []      # all contributing workspace event IDs (max 100)

    def upsert_entity(self, entity_type: str, entity_id: str, updates: dict) -> _EntityState:
        """Upsert a generic entity (backward compat). Also updates focus_entity."""
        if entity_id not in self.entities:
            self.entities[entity_id] = _EntityState(entity_type, entity_id)
        ent = self.entities[entity_id]
        for k, v in updates.items():
            if v is not None:
                setattr(ent, k, v)
        self.focus_entity = entity_id
        return ent

    def upsert_container(self, container_id: str, updates: dict) -> ContainerEntity:
        """Upsert a typed ContainerEntity (Phase 2)."""
        if container_id not in self.containers:
            self.containers[container_id] = ContainerEntity(id=container_id)
        c = self.containers[container_id]
        for k, v in updates.items():
            if v is not None and hasattr(c, k):
                setattr(c, k, v)
        return c

    def add_fact(self, fact: TypedFact) -> None:
        """Register a typed fact (Phase 2)."""
        self.facts.setdefault(fact.fact_type, []).append(fact)


class CompactContext:
    """Trimmed context output for small models."""

    def __init__(
        self,
        now: List[str],
        rules: List[str],
        next_steps: List[str],
        meta: Optional[dict] = None,
    ):
        self.now = now
        self.rules = rules
        self.next = next_steps
        self.meta = meta or {}


# ---------------------------------------------------------------------------
# Phase 3: Candidate model for global select_top
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    """Single renderable bullet with priority metadata for global select_top.

    Sort order (applied by select_top):
        1. confidence DESC  — higher confidence preferred
        2. severity DESC    — more urgent preferred  (0=fallback … 3=critical)
        3. recency_ts DESC  — more recent preferred
        4. tie_breaker ASC  — stable alphabetical, deterministic last resort
    """
    section: str        # "now" | "rules" | "next"
    text: str           # rendered bullet text (≤ _ITEM_CHAR_CAP chars)
    confidence: float   # 0.0–1.0
    severity: int       # 0–3
    recency_ts: float   # unix timestamp (0.0 = no timestamp)
    tie_breaker: str    # stable sort key (section + ordinal/text)


def _ts_to_float(ts_str: str) -> float:
    """Parse ISO timestamp string to float seconds. Returns 0.0 on any error."""
    if not ts_str:
        return 0.0
    try:
        return datetime.fromisoformat(ts_str.rstrip("Z")).timestamp()
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Dedupe helpers (Phase 2) — unchanged
# ---------------------------------------------------------------------------

_DEDUPE_WINDOW_SECS = 2.0
_DEDUPE_SKIP_FIELDS = frozenset({"timestamp", "created_at", "updated_at", "ts"})


def _event_core_hash(event: dict) -> str:
    """Stable 12-char hash for deduplication (ignores timestamp fields)."""
    event_type = event.get("event_type", "")
    event_data = event.get("event_data", {})
    if not isinstance(event_data, dict):
        try:
            event_data = json.loads(event_data)
        except (TypeError, ValueError):
            event_data = {}
    key_fields = {k: v for k, v in sorted(event_data.items()) if k not in _DEDUPE_SKIP_FIELDS}
    raw = f"{event_type}:{json.dumps(key_fields, sort_keys=True, default=str)}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def _dedupe_events(events: List[dict]) -> List[dict]:
    """
    Remove duplicate events within DEDUPE_WINDOW_SECS.
    Duplicate = same event_type AND same core hash within the time window.
    Input order is preserved; first occurrence is kept.

    Commit D: when DIGEST_DEDUPE_INCLUDE_CONV=true, the dedupe key is scoped per
    conversation_id so that identical events in different conversations are not
    conflated (cross-conversation safe).
    Rollback: DIGEST_DEDUPE_INCLUDE_CONV=false restores original behaviour.
    """
    try:
        from config import get_digest_dedupe_include_conv as _include_conv
        _scope_by_conv = _include_conv()
    except Exception:
        _scope_by_conv = False

    seen: Dict[str, float] = {}   # dedupe_key -> first seen timestamp
    result: List[dict] = []
    for ev in events:
        ev_type = ev.get("event_type", "")
        ev_hash = _event_core_hash(ev)
        if _scope_by_conv:
            conv_id = ev.get("conversation_id", "")
            key = f"{conv_id}:{ev_type}:{ev_hash}"
        else:
            key = f"{ev_type}:{ev_hash}"
        created_at = ev.get("created_at", "")
        try:
            ts = datetime.fromisoformat(created_at.rstrip("Z")).timestamp()
        except Exception:
            ts = 0.0
        if key in seen and abs(ts - seen[key]) < _DEDUPE_WINDOW_SECS:
            continue  # duplicate within window
        seen[key] = ts
        result.append(ev)
    if len(result) < len(events):
        log_info(
            f"[ContextCleanup] Dedupe: {len(events)} → {len(result)} events "
            f"({len(events) - len(result)} removed; conv_scoped={_scope_by_conv})"
        )
    return result


# ---------------------------------------------------------------------------
# Limits (overridable from config or mapping_rules.yaml) — unchanged
# ---------------------------------------------------------------------------

_DEFAULT_LIMITS = {
    "now_max": 5,
    "rules_max": 3,
    "next_max": 2,
    "snippets_max": 2,
    "retrieval_default_max": 1,
    "retrieval_on_failure_max": 2,
}

_DEFAULT_RULES = [
    "No freestyle container execution",
    "Verified/trust-gated actions only",
    "If confidence is low, ask clarification",
]


def _load_limits() -> dict:
    """Load limits from mapping_rules.yaml (if available), else use defaults."""
    rules_path = os.path.join(os.path.dirname(__file__), "mapping_rules.yaml")
    if _YAML_AVAILABLE and os.path.exists(rules_path):
        try:
            with open(rules_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return {**_DEFAULT_LIMITS, **(data.get("limits", {}))}
        except Exception as e:
            log_warn(f"[ContextCleanup] Could not load mapping_rules.yaml: {e}")
    return dict(_DEFAULT_LIMITS)


# ---------------------------------------------------------------------------
# Commit 2: Confidence config loader + fact confidence computation
# ---------------------------------------------------------------------------

def _load_confidence_config() -> dict:
    """
    Load confidence and source-reliability config from mapping_rules.yaml.

    Returns a dict with keys:
        source_reliability: {sources: {key: float}, default_confidence: float}
        entity_match:       {exact: float, same_name: float, ...}
        label_thresholds:   {high: float, medium: float}

    Falls back to empty dict (callers use _SOURCE_RELIABILITY_DEFAULTS).
    """
    rules_path = os.path.join(os.path.dirname(__file__), "mapping_rules.yaml")
    if _YAML_AVAILABLE and os.path.exists(rules_path):
        try:
            with open(rules_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return {
                "source_reliability": data.get("source_reliability", {}),
                "entity_match":       data.get("confidence", {}).get("entity_match", {}),
                "label_thresholds":   data.get("confidence", {}).get("label_thresholds", {}),
            }
        except Exception as exc:
            log_warn(f"[ContextCleanup] Could not load confidence config: {exc}")
    return {}


def _compute_fact_confidence(
    source_key: str = "workspace_event",
    entity_match_type: str = "exact",
    consistency_factor: float = 1.0,
    temporal_factor: float = 1.0,
    conf_cfg: Optional[dict] = None,
) -> float:
    """
    Compute TypedFact.confidence from YAML-loaded config and event signals.

    Formula:
        confidence = source_reliability × entity_match × consistency_factor × temporal_factor

    Result is clamped to [0.0, 1.0].
    All lookups fall back safely on missing keys — no exceptions raised.

    Args:
        source_key:          Key into source_reliability.sources (e.g. "workspace_event").
        entity_match_type:   Key into confidence.entity_match (e.g. "exact").
        consistency_factor:  Additional multiplier for consistency signals (default 1.0).
        temporal_factor:     Additional multiplier for temporal freshness (default 1.0).
        conf_cfg:            Dict from _load_confidence_config(); None uses defaults only.
    """
    cfg = conf_cfg or {}

    # Source reliability from YAML, fall back to module-level defaults
    src_rels = cfg.get("source_reliability", {}).get("sources", {})
    src_rel = float(src_rels.get(source_key,
                                  _SOURCE_RELIABILITY_DEFAULTS.get(source_key, 1.0)))

    # Entity match factor from YAML (default 1.0 = exact match)
    entity_matches = cfg.get("entity_match", {})
    ent_match = float(entity_matches.get(entity_match_type, 1.0))

    result = src_rel * ent_match * float(consistency_factor) * float(temporal_factor)
    return max(0.0, min(1.0, result))


# ---------------------------------------------------------------------------
# Commit 2: Pipeline step 1 — Normalize
# ---------------------------------------------------------------------------

def _normalize_events(
    events: List[dict],
    entries: Optional[List[dict]] = None,
) -> List[dict]:
    """
    Normalize raw event dicts into canonical form for pipeline processing.

    Steps per event:
    - Shallow-copy (never mutates caller's data)
    - Ensure event_data is always a dict (parse JSON string if needed)
    - Ensure id is a non-empty string (generate stable content-hash if missing)
    - Ensure created_at key is present (empty string if missing)

    entries: informational for now; future commits may incorporate them.
    """
    normalized: List[dict] = []
    for raw_ev in events:
        ev = dict(raw_ev)  # shallow copy

        # Normalize event_data → always dict
        ev_data = ev.get("event_data", {})
        if not isinstance(ev_data, dict):
            try:
                ev_data = json.loads(ev_data)
            except (TypeError, ValueError):
                ev_data = {}
        ev["event_data"] = ev_data

        # Normalize id → always non-empty string
        ev_id = str(ev.get("id", "")).strip()
        if not ev_id:
            # Generate stable id from content (deterministic)
            ev_type = ev.get("event_type", "")
            created_at = ev.get("created_at", "")
            raw_content = (
                f"{ev_type}:{created_at}:"
                f"{json.dumps(ev_data, sort_keys=True, default=str)}"
            )
            ev_id = "gen-" + hashlib.md5(raw_content.encode("utf-8")).hexdigest()[:10]
        ev["id"] = ev_id

        # Ensure created_at is present
        ev.setdefault("created_at", "")

        normalized.append(ev)
    return normalized


# ---------------------------------------------------------------------------
# Commit 2: Pipeline step 2 (sort) — deterministic ordering for state-mutation
# ---------------------------------------------------------------------------

def _sort_events_asc(events: List[dict]) -> List[dict]:
    """
    Sort events for deterministic state-mutation.

    Primary:    created_at ASC (oldest-first so newer events overwrite stale state)
    Tie-breaker: id ASC (stable string sort on normalized id)

    Input order does NOT affect the result — any permutation of the same events
    yields the same sorted list.
    """
    def _sort_key(ev: dict):
        ts_str = ev.get("created_at", "")
        try:
            ts = datetime.fromisoformat(ts_str.rstrip("Z")).timestamp()
        except Exception:
            ts = 0.0
        return (ts, ev.get("id", ""))

    return sorted(events, key=_sort_key)


# ---------------------------------------------------------------------------
# Commit 2: Pipeline step 3 — Correlate
# ---------------------------------------------------------------------------

def _correlate_events(events: List[dict]) -> dict:
    """
    Build correlation maps from a sorted (ASC) event list.

    Currently computes:
    - container_last_status: final known status per container_id (from full lifecycle)
    - tool_result_refs:      tool_result events indexed by ref_id

    Events must be pre-sorted ASC so last-write wins for container_last_status.

    Returns:
        {
          "container_last_status": Dict[str, str],   # cid -> "running"|"stopped"|...
          "tool_result_refs":      Dict[str, dict],  # ref_id -> event dict
        }
    """
    container_last_status: Dict[str, str] = {}
    tool_result_refs: Dict[str, dict] = {}

    _lifecycle_status = {
        "container_started":     "running",
        "container_stopped":     "stopped",
        "container_ttl_expired": "expired",
        "container_failed":      "failed",
    }

    for ev in events:
        ev_type = ev.get("event_type", "")
        ev_data = ev.get("event_data", {}) or {}

        if ev_type in _lifecycle_status:
            cid = ev_data.get("container_id", "")
            if cid:
                container_last_status[cid] = _lifecycle_status[ev_type]

        elif ev_type == "tool_result":
            ref_id = ev_data.get("ref_id", "")
            if ref_id:
                tool_result_refs[ref_id] = ev

    return {
        "container_last_status": container_last_status,
        "tool_result_refs":      tool_result_refs,
    }


# ---------------------------------------------------------------------------
# Rule engine — extended for Commit 2
# ---------------------------------------------------------------------------

def _apply_event(
    state: TypedState,
    event: dict,
    conf_cfg: Optional[dict] = None,
) -> None:
    """
    Apply a single workspace_event dict to the TypedState.

    conf_cfg: confidence config from _load_confidence_config(); None uses defaults.
    Existing event types are fully backward-compatible.
    New in Commit 2: tool_result, pending_skill/approval_requested/skill_pending.
    """
    event_type = event.get("event_type", "")
    event_data = event.get("event_data", {})
    if not isinstance(event_data, dict):
        try:
            event_data = json.loads(event_data)
        except (TypeError, ValueError):
            event_data = {}

    created_at = event.get("created_at", datetime.utcnow().isoformat())
    event_id = str(event.get("id", ""))

    # V1 Wiring: Propagate session_id/conversation_id from any event to TypedState.
    # Events are sorted ASC → last event with these fields wins (newest state).
    _ev_session = event_data.get("session_id")
    _ev_conv    = event_data.get("conversation_id")
    if _ev_session:
        state.session_id = str(_ev_session)
    if _ev_conv:
        state.conversation_id = str(_ev_conv)

    # ── container_started ────────────────────────────────────────────────
    if event_type == "container_started":
        cid = event_data.get("container_id", "")
        if cid:
            state.upsert_entity("container", cid, {
                "state": "running",
                "last_action": "container_started",
                "blueprint_id": event_data.get("blueprint_id"),
                "purpose": event_data.get("purpose"),
                "session_id": event_data.get("session_id"),
                "last_change_ts": created_at,
            })
            state.upsert_container(cid, {
                "blueprint_id": event_data.get("blueprint_id"),
                "status": "running",
                "updated_at": created_at,
                "session_id": event_data.get("session_id"),           # V1 Wiring
                "conversation_id": event_data.get("conversation_id"), # V1 Wiring
            })
            # V1: track source_event_ids at ContainerEntity level
            if event_id and cid in state.containers:
                _c = state.containers[cid]
                if event_id not in _c.source_event_ids:
                    _c.source_event_ids.append(event_id)
            state.add_fact(TypedFact(
                fact_type="CONTAINER_STARTED",
                value=f"{cid[:12]} blueprint={event_data.get('blueprint_id', '?')}",
                confidence=_compute_fact_confidence(
                    "workspace_event", conf_cfg=conf_cfg),
                observed_at=created_at,
                source=event_type,
                source_event_ids=[event_id] if event_id else [],
            ))

    # ── container_stopped ────────────────────────────────────────────────
    elif event_type == "container_stopped":
        cid = event_data.get("container_id", "")
        if cid and cid in state.entities:
            state.upsert_entity("container", cid, {
                "state": "stopped",
                "last_action": "container_stopped",
                "last_change_ts": created_at,
            })
            if state.focus_entity == cid:
                state.focus_entity = None
        if cid:
            state.upsert_container(cid, {"status": "stopped", "updated_at": created_at})
            # V1: track source_event_ids at ContainerEntity level
            if event_id and cid in state.containers:
                _c = state.containers[cid]
                if event_id not in _c.source_event_ids:
                    _c.source_event_ids.append(event_id)

    # ── container_ttl_expired ────────────────────────────────────────────
    elif event_type == "container_ttl_expired":
        cid = event_data.get("container_id", "")
        if cid and cid in state.entities:
            state.upsert_entity("container", cid, {
                "state": "expired",
                "last_action": "container_ttl_expired",
                "last_change_ts": created_at,
            })
        if cid:
            state.upsert_container(cid, {"status": "expired", "updated_at": created_at})
            # V1: track source_event_ids at ContainerEntity level
            if event_id and cid in state.containers:
                _c = state.containers[cid]
                if event_id not in _c.source_event_ids:
                    _c.source_event_ids.append(event_id)

    # ── container_exec ───────────────────────────────────────────────────
    elif event_type == "container_exec":
        cid = event_data.get("container_id", "")
        exit_code = event_data.get("exit_code")
        if cid:
            success = exit_code == 0 if exit_code is not None else True
            state.upsert_entity("container", cid, {
                "last_action": "container_exec_ok" if success else "container_exec_fail",
                "last_exit_code": exit_code,
                "last_error": None if success else event_data.get("stderr", "non-zero exit"),
                "stability_score": "high" if success else "low",
                "last_change_ts": created_at,
            })
            state.upsert_container(cid, {
                "last_exit_code": exit_code,
                "stability_score": "high" if success else "low",
                "updated_at": created_at,
            })
            # V1: track source_event_ids at ContainerEntity level
            if event_id and cid in state.containers:
                _c = state.containers[cid]
                if event_id not in _c.source_event_ids:
                    _c.source_event_ids.append(event_id)
            if not success:
                err = event_data.get("stderr", f"exit_code={exit_code}")
                issue = f"container_exec_fail: {str(err)[:120]}"
                if issue not in state.open_issues:
                    state.open_issues.append(issue)
                state.last_error = issue
                # V1: also update last_errors list
                if issue not in state.last_errors:
                    state.last_errors.append(issue)
                if len(state.last_errors) > 10:
                    state.last_errors = state.last_errors[-10:]
                state.upsert_container(cid, {"last_error": str(err)[:200]})
                state.add_fact(TypedFact(
                    fact_type="TOOL_ERROR",
                    value=str(err)[:200],
                    confidence=_compute_fact_confidence(
                        "workspace_event", conf_cfg=conf_cfg),
                    observed_at=created_at,
                    source=event_type,
                    source_event_ids=[event_id] if event_id else [],
                ))

    # ── trust_blocked ────────────────────────────────────────────────────
    elif event_type == "trust_blocked":
        reason = event_data.get("reason", "trust_blocked")
        gate_entry = f"trust:{reason[:80]}"
        if gate_entry not in state.active_gates:
            state.active_gates.append(gate_entry)
        state.last_error = reason
        # V1: also update last_errors list
        err_entry = str(reason)[:120]
        if err_entry not in state.last_errors:
            state.last_errors.append(err_entry)
        if len(state.last_errors) > 10:
            state.last_errors = state.last_errors[-10:]
        state.add_fact(TypedFact(
            fact_type="GATE_BLOCKED",
            value=reason[:200],
            confidence=_compute_fact_confidence(
                "workspace_event", conf_cfg=conf_cfg),
            observed_at=created_at,
            source=event_type,
            source_event_ids=[event_id] if event_id else [],
        ))

    # ── tool_result (Commit 2) ───────────────────────────────────────────
    elif event_type == "tool_result":
        ref_id   = event_data.get("ref_id", "") or event_id
        status   = event_data.get("status", "success")
        tool_name = event_data.get("tool_name", "")

        # Update last_tool_results (bounded at 10, dedupe by insertion order)
        result_ref = ref_id or tool_name or event_id
        if result_ref and result_ref not in state.last_tool_results:
            state.last_tool_results.append(result_ref)
        if len(state.last_tool_results) > 10:
            state.last_tool_results = state.last_tool_results[-10:]

        # Error / partial → also record in error state
        if status in ("error", "partial"):
            err_raw = event_data.get(
                "error", event_data.get("message", f"tool:{status}"))
            err_msg = str(err_raw)[:120]
            issue = f"tool_result:{status}: {err_msg}"
            if issue not in state.open_issues:
                state.open_issues.append(issue)
            state.last_error = issue
            if issue not in state.last_errors:
                state.last_errors.append(issue)
            if len(state.last_errors) > 10:
                state.last_errors = state.last_errors[-10:]

        # TypedFact — confidence from YAML tool_result source reliability
        fact_conf = _compute_fact_confidence("tool_result", conf_cfg=conf_cfg)
        state.add_fact(TypedFact(
            fact_type="TOOL_RESULT",
            value=f"{tool_name or ref_id} status={status}"[:200],
            confidence=fact_conf,
            observed_at=created_at,
            source=event_type,
            source_event_ids=[event_id] if event_id else [],
        ))

    # ── pending_skill / approval events (Commit 2) ───────────────────────
    elif event_type in ("pending_skill", "approval_requested", "skill_pending"):
        skill_ref = (
            event_data.get("skill_id")
            or event_data.get("skill_name")
            or event_data.get("ref_id")
            or event_id
        )
        if skill_ref:
            skill_ref = str(skill_ref)[:100]
            if skill_ref not in state.pending_approvals:
                state.pending_approvals.append(skill_ref)
        if len(state.pending_approvals) > 20:
            state.pending_approvals = state.pending_approvals[-20:]

    # ── observation / task / note ────────────────────────────────────────
    elif event_type in ("observation", "task", "note"):
        # Soft observations — record last_error if it looks like a failure note
        content = event_data.get("content", "")
        if "error" in content.lower() or "fail" in content.lower():
            state.last_error = content[:120]

    # ── Commit E: Digest event types ─────────────────────────────────────
    # Digest events (daily_digest / weekly_digest / archive_digest) are treated
    # as informational facts. Fail-closed: any malformed payload is silently ignored.
    elif event_type == "daily_digest":
        try:
            digest_date = str(event_data.get("digest_date", ""))[:20]
            event_count = int(event_data.get("event_count", 0))
            digest_key  = str(event_data.get("digest_key", ""))[:64]
            fact_val = f"daily_digest date={digest_date} events={event_count}"[:200]
            state.add_fact(TypedFact(
                fact_type="DAILY_DIGEST",
                value=fact_val,
                confidence=_compute_fact_confidence("memory", conf_cfg=conf_cfg),
                observed_at=created_at,
                source=event_type,
                source_event_ids=[event_id] if event_id else [],
            ))
        except Exception:
            pass  # fail-closed: malformed digest payload → no state change

    elif event_type == "weekly_digest":
        try:
            iso_week   = str(event_data.get("iso_week", ""))[:20]
            daily_count = int(event_data.get("daily_digest_count", 0))
            fact_val   = f"weekly_digest week={iso_week} daily_digests={daily_count}"[:200]
            state.add_fact(TypedFact(
                fact_type="WEEKLY_DIGEST",
                value=fact_val,
                confidence=_compute_fact_confidence("memory", conf_cfg=conf_cfg),
                observed_at=created_at,
                source=event_type,
                source_event_ids=[event_id] if event_id else [],
            ))
        except Exception:
            pass  # fail-closed

    elif event_type == "archive_digest":
        try:
            archived_at    = str(event_data.get("archived_at", ""))[:30]
            graph_node_id  = str(event_data.get("archive_graph_node_id", ""))[:100]
            fact_val       = f"archive_digest archived={archived_at} node={graph_node_id[:40]}"[:200]
            state.add_fact(TypedFact(
                fact_type="ARCHIVE_DIGEST",
                value=fact_val,
                confidence=_compute_fact_confidence("memory", conf_cfg=conf_cfg),
                observed_at=created_at,
                source=event_type,
                source_event_ids=[event_id] if event_id else [],
            ))
        except Exception:
            pass  # fail-closed


# ---------------------------------------------------------------------------
# Commit 2: Pipeline step 4 — Apply events to state
# ---------------------------------------------------------------------------

def _apply_events_to_state(
    state: TypedState,
    events: List[dict],
    correlations: dict,
    conf_cfg: dict,
) -> None:
    """
    Apply all pre-sorted events to TypedState deterministically.

    Events must be pre-sorted (created_at ASC, id ASC) — produced by
    _sort_events_asc(). This guarantees that newer events overwrite stale state
    and that the result is independent of the original input order.

    Also tracks state.source_event_ids for every processed event
    (bounded at 100, dedupe by insertion order).

    correlations: informational dict from _correlate_events(); reserved for
    future use by richer rendering/rendering decisions.
    """
    _MAX_SOURCE_IDS = 100
    for ev in events:
        try:
            _apply_event(state, ev, conf_cfg=conf_cfg)
        except Exception as exc:
            log_warn(f"[ContextCleanup] Event apply error: {exc}")

        # Track source_event_ids for ALL event types (bounded, dedupe)
        ev_id = ev.get("id", "")
        if ev_id and ev_id not in state.source_event_ids:
            state.source_event_ids.append(ev_id)

    if len(state.source_event_ids) > _MAX_SOURCE_IDS:
        state.source_event_ids = state.source_event_ids[-_MAX_SOURCE_IDS:]


# ---------------------------------------------------------------------------
# Commit 3: Output config loader + deterministic NOW/RULES/NEXT builders
# ---------------------------------------------------------------------------

_NOW_ORDER_DEFAULT: List[str] = [
    "active_container",
    "focus_entity",
    "active_gates",
    "open_issues",
    "last_error",
]

# Per-item character cap inside builders (prevents one huge bullet eating the cap)
_ITEM_CHAR_CAP = 200


def _load_output_config() -> dict:
    """
    Load output.compact_context section from mapping_rules.yaml.

    Returns dict with optional keys:
        now_order:     List[str] — priority order for NOW bullet categories
        rules_default: List[str] — base rules (overrides _DEFAULT_RULES when present)
        next_strategy: List[str] — strategy hints (informational)

    Falls back to empty dict; callers use module-level defaults.
    """
    rules_path = os.path.join(os.path.dirname(__file__), "mapping_rules.yaml")
    if _YAML_AVAILABLE and os.path.exists(rules_path):
        try:
            with open(rules_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return data.get("output", {}).get("compact_context", {})
        except Exception as exc:
            log_warn(f"[ContextCleanup] Could not load output config: {exc}")
    return {}


def _build_now_bullets(state: TypedState, cfg: dict, output_cfg: dict) -> List[str]:
    """
    Build NOW bullets in YAML-configured priority order.

    Deterministic within each category:
    - active_container: sorted by container_id ASC
    - active_gates:     sorted alphabetically
    - open_issues:      sorted alphabetically
    - focus_entity:     single entry (no sort needed)
    - last_error:       single entry

    Items are capped at _ITEM_CHAR_CAP chars each (prevents unbounded truncation
    in the renderer).

    Fail-closed: any exception yields an empty list for that category.
    """
    order: List[str] = output_cfg.get("now_order", _NOW_ORDER_DEFAULT)
    buckets: Dict[str, List[str]] = {k: [] for k in _NOW_ORDER_DEFAULT}

    try:
        # ── active_container: sorted by container_id for determinism ──────
        _seen_cids: set = set()
        for c_id in sorted(state.containers.keys()):
            c = state.containers[c_id]
            if c.status == "running":
                _seen_cids.add(c_id)
                bp    = (c.blueprint_id or "?")[:40]
                score = c.stability_score or "medium"
                err_sfx = (
                    f" err={c.last_error[:40]}" if c.last_error else ""
                )
                bullet = f"ACTIVE_CONTAINER {bp}/{c_id[:12]} stability={score}{err_sfx}"
                buckets["active_container"].append(bullet[:_ITEM_CHAR_CAP])

        # Fallback: legacy entity containers not yet in typed dict
        for ent_id in sorted(state.entities.keys()):
            ent = state.entities[ent_id]
            if (
                ent.type == "container"
                and ent.state == "running"
                and ent.id not in _seen_cids
            ):
                short_id = ent.id[:12]
                bp       = (ent.blueprint_id or "?")[:40]
                purpose  = (ent.purpose or "")[:40]
                score    = ent.stability_score or "medium"
                bullet   = (
                    f"ACTIVE_CONTAINER {bp}/{short_id} stability={score}"
                    f" purpose={purpose}"
                )
                buckets["active_container"].append(bullet[:_ITEM_CHAR_CAP])
    except Exception as exc:
        log_warn(f"[ContextCleanup] NOW active_container builder error: {exc}")

    try:
        # ── focus_entity ──────────────────────────────────────────────────
        if state.focus_entity and state.focus_entity in state.entities:
            ent = state.entities[state.focus_entity]
            if ent.state != "running":  # avoid duplicate with active_container
                bullet = f"FOCUS_ENTITY {ent.type}/{ent.id[:12]} state={ent.state}"
                buckets["focus_entity"].append(bullet[:_ITEM_CHAR_CAP])
    except Exception as exc:
        log_warn(f"[ContextCleanup] NOW focus_entity builder error: {exc}")

    try:
        # ── active_gates: sorted for determinism ──────────────────────────
        for gate in sorted(state.active_gates):
            buckets["active_gates"].append(
                f"GATE_ACTIVE {gate}"[:_ITEM_CHAR_CAP]
            )
    except Exception as exc:
        log_warn(f"[ContextCleanup] NOW active_gates builder error: {exc}")

    try:
        # ── open_issues: sorted for determinism ───────────────────────────
        for issue in sorted(state.open_issues):
            buckets["open_issues"].append(
                f"OPEN_ISSUE {issue}"[:_ITEM_CHAR_CAP]
            )
    except Exception as exc:
        log_warn(f"[ContextCleanup] NOW open_issues builder error: {exc}")

    try:
        # ── last_error ────────────────────────────────────────────────────
        if state.last_error:
            buckets["last_error"].append(
                f"LAST_ERROR {state.last_error[:100]}"[:_ITEM_CHAR_CAP]
            )
    except Exception as exc:
        log_warn(f"[ContextCleanup] NOW last_error builder error: {exc}")

    # Assemble in YAML-configured order, apply now_max cap
    now: List[str] = []
    for key in order:
        now.extend(buckets.get(key, []))
    return now[: cfg.get("now_max", _DEFAULT_LIMITS["now_max"])]


def _build_rules_bullets(state: TypedState, cfg: dict, output_cfg: dict) -> List[str]:
    """
    Build RULES bullets.

    Base rules loaded from YAML rules_default (falls back to _DEFAULT_RULES).
    User constraints appended: sorted alphabetically, deduped against base rules.
    Fail-closed: any exception returns base rules only.
    """
    yaml_rules: List[str] = output_cfg.get("rules_default", [])
    base_rules: List[str] = list(yaml_rules) if yaml_rules else list(_DEFAULT_RULES)

    try:
        seen: set = set(base_rules)
        for constraint in sorted(state.user_constraints):
            entry = f"USER: {constraint}"[:_ITEM_CHAR_CAP]
            if entry not in seen:
                base_rules.append(entry)
                seen.add(entry)
    except Exception as exc:
        log_warn(f"[ContextCleanup] RULES builder error: {exc}")

    return base_rules[: cfg.get("rules_max", _DEFAULT_LIMITS["rules_max"])]


def _build_next_bullets(state: TypedState, cfg: dict) -> List[str]:
    """
    Build NEXT bullets with explicit priority strategy:

    1. pending_approvals present → handle approval first (most urgent)
    2. last_error present        → diagnose before continuing
    3. focus_entity running      → continue work on it
    4. fallback                  → await user instruction

    Fail-closed: any exception returns ["Await user instruction"].
    """
    try:
        next_steps: List[str] = []

        # Priority 1: pending approvals need human decision first
        if state.pending_approvals:
            ref = state.pending_approvals[-1]  # most recently added
            next_steps.append(f"Handle pending approval: {ref[:60]}"[:_ITEM_CHAR_CAP])

        # Priority 2: last error must be diagnosed
        if state.last_error:
            next_steps.append("Diagnose last error before proceeding")
        elif state.focus_entity and state.focus_entity in state.entities:
            # Priority 3: continue active work
            ent = state.entities[state.focus_entity]
            if ent.state == "running":
                next_steps.append(
                    f"Continue work on {ent.blueprint_id or ent.id[:12]}"
                    [:_ITEM_CHAR_CAP]
                )

        if not next_steps:
            next_steps.append("Await user instruction")

        return next_steps[: cfg.get("next_max", _DEFAULT_LIMITS["next_max"])]
    except Exception as exc:
        log_warn(f"[ContextCleanup] NEXT builder error: {exc}")
        return ["Await user instruction"]


# ---------------------------------------------------------------------------
# Phase 3: Candidate builder, select_top, section materializer, fail-closed
# ---------------------------------------------------------------------------

def _build_candidates_from_state(
    state: "TypedState",
    limits: dict,
    output_cfg: dict,
) -> "List[Candidate]":
    """
    Enumerate ALL potential bullets from TypedState as a flat Candidate list.

    Does NOT apply section caps — that is the job of _candidates_to_sections.
    Fail-closed per category: any exception is logged; remaining categories continue.

    Severity scale:
        3 = critical/blocking  (GATE_ACTIVE, pending_approval)
        2 = error/warning      (LAST_ERROR, failed/expired container, error_diagnosis)
        1 = informational      (active container running, focus_entity, open_issues,
                                continue_work, base_rules, user_constraints)
        0 = fallback           (await)
    """
    candidates: List[Candidate] = []

    # ── NOW candidates ────────────────────────────────────────────────────────
    try:
        _seen_cids: set = set()
        for c_id in sorted(state.containers.keys()):
            c = state.containers[c_id]
            bp = (c.blueprint_id or "?")[:40]
            if c.status == "running":
                _seen_cids.add(c_id)
                score = c.stability_score or "medium"
                err_sfx = f" err={c.last_error[:40]}" if c.last_error else ""
                text = f"ACTIVE_CONTAINER {bp}/{c_id[:12]} stability={score}{err_sfx}"[:_ITEM_CHAR_CAP]
                candidates.append(Candidate(
                    section="now", text=text, confidence=1.0, severity=1,
                    recency_ts=_ts_to_float(c.updated_at),
                    tie_breaker=f"now:{text[:50]}",
                ))
            elif c.status in ("failed", "expired"):
                _seen_cids.add(c_id)
                err_sfx = f" err={c.last_error[:40]}" if c.last_error else ""
                text = f"ACTIVE_CONTAINER {bp}/{c_id[:12]} status={c.status}{err_sfx}"[:_ITEM_CHAR_CAP]
                candidates.append(Candidate(
                    section="now", text=text, confidence=1.0, severity=2,
                    recency_ts=_ts_to_float(c.updated_at),
                    tie_breaker=f"now:{text[:50]}",
                ))
        # Fallback: legacy entity containers not yet in typed dict
        for ent_id in sorted(state.entities.keys()):
            ent = state.entities[ent_id]
            if ent.type == "container" and ent.state == "running" and ent.id not in _seen_cids:
                short_id = ent.id[:12]
                bp = (ent.blueprint_id or "?")[:40]
                purpose = (ent.purpose or "")[:40]
                score = ent.stability_score or "medium"
                text = (
                    f"ACTIVE_CONTAINER {bp}/{short_id} stability={score} purpose={purpose}"
                )[:_ITEM_CHAR_CAP]
                candidates.append(Candidate(
                    section="now", text=text, confidence=1.0, severity=1,
                    recency_ts=_ts_to_float(ent.last_change_ts or ""),
                    tie_breaker=f"now:{text[:50]}",
                ))
    except Exception as exc:
        log_warn(f"[ContextCleanup] Candidate active_container error: {exc}")

    try:
        # active_gates — severity 3 (critical blockers)
        for gate in sorted(state.active_gates):
            text = f"GATE_ACTIVE {gate}"[:_ITEM_CHAR_CAP]
            candidates.append(Candidate(
                section="now", text=text, confidence=1.0, severity=3,
                recency_ts=0.0, tie_breaker=f"now:{text[:50]}",
            ))
    except Exception as exc:
        log_warn(f"[ContextCleanup] Candidate active_gates error: {exc}")

    try:
        # focus_entity — skip if running (already covered by active_container)
        if state.focus_entity and state.focus_entity in state.entities:
            ent = state.entities[state.focus_entity]
            if ent.state != "running":
                text = f"FOCUS_ENTITY {ent.type}/{ent.id[:12]} state={ent.state}"[:_ITEM_CHAR_CAP]
                candidates.append(Candidate(
                    section="now", text=text, confidence=1.0, severity=1,
                    recency_ts=_ts_to_float(ent.last_change_ts or ""),
                    tie_breaker=f"now:{text[:50]}",
                ))
    except Exception as exc:
        log_warn(f"[ContextCleanup] Candidate focus_entity error: {exc}")

    try:
        for issue in sorted(state.open_issues):
            text = f"OPEN_ISSUE {issue}"[:_ITEM_CHAR_CAP]
            candidates.append(Candidate(
                section="now", text=text, confidence=0.9, severity=1,
                recency_ts=0.0, tie_breaker=f"now:{text[:50]}",
            ))
    except Exception as exc:
        log_warn(f"[ContextCleanup] Candidate open_issues error: {exc}")

    try:
        if state.last_error:
            text = f"LAST_ERROR {state.last_error[:100]}"[:_ITEM_CHAR_CAP]
            candidates.append(Candidate(
                section="now", text=text, confidence=0.85, severity=2,
                recency_ts=0.0, tie_breaker=f"now:{text[:50]}",
            ))
    except Exception as exc:
        log_warn(f"[ContextCleanup] Candidate last_error error: {exc}")

    # ── RULES candidates ──────────────────────────────────────────────────────
    try:
        yaml_rules: List[str] = output_cfg.get("rules_default", [])
        base_rules: List[str] = list(yaml_rules) if yaml_rules else list(_DEFAULT_RULES)
        # Index-based tie_breaker preserves definition order (all base rules have
        # identical confidence/severity/recency, so tie_breaker is the deciding factor).
        for i, rule in enumerate(base_rules):
            text = rule[:_ITEM_CHAR_CAP]
            candidates.append(Candidate(
                section="rules", text=text, confidence=0.9, severity=1,
                recency_ts=0.0, tie_breaker=f"rules:{i:04d}:{text[:30]}",
            ))
        seen_rules: set = set(base_rules)
        for constraint in sorted(state.user_constraints):
            entry = f"USER: {constraint}"[:_ITEM_CHAR_CAP]
            if entry not in seen_rules:
                candidates.append(Candidate(
                    section="rules", text=entry, confidence=0.95, severity=1,
                    recency_ts=0.0, tie_breaker=f"rules:zzzz:{entry[:30]}",
                ))
                seen_rules.add(entry)
    except Exception as exc:
        log_warn(f"[ContextCleanup] Candidate rules error: {exc}")

    # Guarantee at least the default rules are candidates even after an error.
    if not any(c.section == "rules" for c in candidates):
        for i, rule in enumerate(_DEFAULT_RULES):
            candidates.append(Candidate(
                section="rules", text=rule[:_ITEM_CHAR_CAP], confidence=0.9, severity=1,
                recency_ts=0.0, tie_breaker=f"rules:{i:04d}:{rule[:30]}",
            ))

    # ── NEXT candidates ───────────────────────────────────────────────────────
    try:
        if state.pending_approvals:
            ref = state.pending_approvals[-1]
            text = f"Handle pending approval: {ref[:60]}"[:_ITEM_CHAR_CAP]
            candidates.append(Candidate(
                section="next", text=text, confidence=1.0, severity=3,
                recency_ts=0.0, tie_breaker=f"next:{text[:50]}",
            ))
        if state.last_error:
            text = "Diagnose last error before proceeding"
            candidates.append(Candidate(
                section="next", text=text, confidence=0.9, severity=2,
                recency_ts=0.0, tie_breaker=f"next:{text[:50]}",
            ))
        elif state.focus_entity and state.focus_entity in state.entities:
            # continue_work only when no last_error (mirrors _build_next_bullets)
            ent = state.entities[state.focus_entity]
            if ent.state == "running":
                text = f"Continue work on {ent.blueprint_id or ent.id[:12]}"[:_ITEM_CHAR_CAP]
                candidates.append(Candidate(
                    section="next", text=text, confidence=1.0, severity=1,
                    recency_ts=0.0, tie_breaker=f"next:{text[:50]}",
                ))
        if not any(c.section == "next" for c in candidates):
            candidates.append(Candidate(
                section="next", text="Await user instruction", confidence=1.0, severity=0,
                recency_ts=0.0, tie_breaker="next:await_user",
            ))
    except Exception as exc:
        log_warn(f"[ContextCleanup] Candidate next error: {exc}")
        if not any(c.section == "next" for c in candidates):
            candidates.append(Candidate(
                section="next", text="Await user instruction", confidence=1.0, severity=0,
                recency_ts=0.0, tie_breaker="next:await_user",
            ))

    return candidates


def select_top(candidates: "List[Candidate]", budget: int) -> "List[Candidate]":
    """
    Select the top `budget` candidates by global priority.

    Sort order (deterministic):
        1. confidence DESC  — higher confidence preferred
        2. severity DESC    — more urgent preferred
        3. recency_ts DESC  — more recent preferred
        4. tie_breaker ASC  — stable alphabetical last resort

    Any permutation of identical inputs yields identical output.
    Returns at most `budget` candidates.
    """
    if budget <= 0:
        return []
    return sorted(
        candidates,
        key=lambda c: (-c.confidence, -c.severity, -c.recency_ts, c.tie_breaker),
    )[:budget]


def _candidates_to_sections(
    selected: "List[Candidate]",
    limits: dict,
) -> tuple:
    """
    Materialize selected candidates into (now_bullets, rules_bullets, next_bullets).

    Preserves select_top order within each section.
    Section caps (now_max / rules_max / next_max) are hard limits applied here.
    """
    now_max = limits.get("now_max", _DEFAULT_LIMITS["now_max"])
    rules_max = limits.get("rules_max", _DEFAULT_LIMITS["rules_max"])
    next_max = limits.get("next_max", _DEFAULT_LIMITS["next_max"])
    now: List[str] = []
    rules: List[str] = []
    next_steps: List[str] = []
    for cand in selected:
        if cand.section == "now" and len(now) < now_max:
            now.append(cand.text)
        elif cand.section == "rules" and len(rules) < rules_max:
            rules.append(cand.text)
        elif cand.section == "next" and len(next_steps) < next_max:
            next_steps.append(cand.text)
    return now, rules, next_steps


def _minimal_fail_context(meta: Optional[dict] = None) -> "CompactContext":
    """
    Canonical fail-closed CompactContext: Minimal-NOW + Rückfrage.

    Returned when a fatal error prevents normal pipeline completion.
    Always stable and renderable; never raises.

    Output when formatted:
        NOW:
          - CONTEXT ERROR: Zustand unvollständig
        NEXT:
          - Bitte Anfrage kurz präzisieren oder letzten Schritt wiederholen
    """
    _meta: dict = {
        "small_model_mode": True,
        "cleanup_used": True,
        "focus_entity": "",
        "retrieval_count": 0,
        "context_chars": 0,
        "events_processed": 0,
        "entities_tracked": 0,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "fail_closed": True,
    }
    if meta:
        _meta.update(meta)
    now = ["CONTEXT ERROR: Zustand unvollständig"]
    next_steps = ["Bitte Anfrage kurz präzisieren oder letzten Schritt wiederholen"]
    _meta["context_chars"] = sum(len(s) for s in now + next_steps)
    return CompactContext(now=now, rules=[], next_steps=next_steps, meta=_meta)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_compact_context(
    events: List[dict],
    entries: Optional[List[dict]] = None,
    limits: Optional[dict] = None,
    extra_events: Optional[List[dict]] = None,
) -> CompactContext:
    """
    Convert workspace_events (and optional workspace_entries) into a CompactContext.

    Pipeline (Phase 3):
        merge → normalize → dedupe → sort(ASC) → correlate → apply_to_state
        → select_top → render

    Args:
        events:       List of event dicts from workspace_event_list (any order).
        entries:      Optional list of editable entry dicts from workspace_list.
        limits:       Override dict for now_max, rules_max, next_max, top_budget, etc.
        extra_events: Optional supplementary events (e.g. from CSV loader).
                      Merged before normalize; same pipeline applies.

    Determinism guarantee:
        The same set of events in any input order produces identical
        TypedState and therefore identical NOW / RULES / NEXT output.

    Returns:
        CompactContext with now/rules/next populated within hard limits.
        On fatal error: _minimal_fail_context (Minimal-NOW + Rückfrage).
    """
    cfg = {**_load_limits(), **(limits or {})}
    conf_cfg = _load_confidence_config()

    try:
        # ── Step 1: Merge all event sources ──────────────────────────────────
        all_events: List[dict] = list(events)
        if extra_events:
            all_events.extend(extra_events)

        # ── Step 2: Normalize ─────────────────────────────────────────────────
        all_events = _normalize_events(all_events, entries)

        # ── Step 3: Dedupe (2-second window, first-occurrence kept) ───────────
        all_events = _dedupe_events(all_events)

        # ── Step 4: Sort deterministically (created_at ASC, id ASC) ──────────
        all_events = _sort_events_asc(all_events)

        # ── Step 5: Correlate ─────────────────────────────────────────────────
        correlations = _correlate_events(all_events)

        # ── Step 6: Apply to TypedState ───────────────────────────────────────
        state = TypedState()
        _apply_events_to_state(state, all_events, correlations, conf_cfg)

        # ── Step 7: select_top — global priority selection ────────────────────
        output_cfg = _load_output_config()
        candidates = _build_candidates_from_state(state, cfg, output_cfg)
        # Global budget: configurable via limits["top_budget"].
        # Default = sum of section caps so normal operation is unchanged.
        top_budget = cfg.get(
            "top_budget",
            cfg.get("now_max", _DEFAULT_LIMITS["now_max"])
            + cfg.get("rules_max", _DEFAULT_LIMITS["rules_max"])
            + cfg.get("next_max", _DEFAULT_LIMITS["next_max"]),
        )
        selected = select_top(candidates, top_budget)

        # ── Step 8: Render — materialize into NOW / RULES / NEXT sections ─────
        now, rules, next_steps = _candidates_to_sections(selected, cfg)

        # Fail-closed: NEXT fallback if select_top yielded nothing for that section
        # (RULES is guaranteed by _build_candidates_from_state's own fallback).
        if not next_steps:
            next_steps = ["Await user instruction"]

    except Exception as exc:
        log_warn(f"[ContextCleanup] Fatal pipeline error: {exc} — fail-closed")
        return _minimal_fail_context()

    focus_entity = state.focus_entity or ""
    context_chars = sum(len(s) for s in now + rules + next_steps)
    retrieval_count = (limits or {}).get("retrieval_count", 1)

    # ── Commit 4: V1 extra NOW bullets (from V1 state fields not used by legacy pipeline) ──
    # These are stored in meta so format_typedstate_v1() can extend NOW without re-running
    # the full pipeline. Computed fail-open (extras are informational only).
    _v1_extra_now: List[str] = []
    try:
        _legacy_now_set = set(now)
        # last_errors history: entries beyond the most-recent (singular last_error covers last one).
        # Only adds entries not already rendered as LAST_ERROR bullets.
        for _err in state.last_errors[:-1]:
            _b = f"V1_ERR_HIST: {_err[:100]}"[:_ITEM_CHAR_CAP]
            if _b not in _legacy_now_set:
                _v1_extra_now.append(_b)
        # last_tool_results: recent tool operation refs (not shown in legacy NOW).
        for _ref in state.last_tool_results[-2:]:
            _b = f"V1_TOOL: {_ref[:80]}"[:_ITEM_CHAR_CAP]
            if _b not in _legacy_now_set:
                _v1_extra_now.append(_b)
    except Exception:
        pass  # fail-open: V1 extras are informational, never block rendering

    meta = {
        "small_model_mode": True,
        "cleanup_used": True,
        "focus_entity": focus_entity,
        "retrieval_count": retrieval_count,
        "context_chars": context_chars,
        "events_processed": len(all_events),
        "entities_tracked": len(state.entities),
        "generated_at": datetime.utcnow().isoformat() + "Z",
        # Commit C: Observability fields
        "typedstate_version": state.version,
        "source_event_ids_count": len(state.source_event_ids),
        "fail_closed": False,
        # Commit 4: V1 wiring fields (used by format_typedstate_v1 + _log_typedstate_diff)
        "v1_extra_now": _v1_extra_now,
        "v1_last_errors": list(state.last_errors),
        "v1_last_tool_results": list(state.last_tool_results),
    }

    log_info(
        f"[ContextCleanup] cleanup_used=True focus_entity={focus_entity!r} "
        f"retrieval_count={retrieval_count} context_chars={context_chars} "
        f"now={len(now)} rules={len(rules)} next={len(next_steps)} "
        f"events={len(all_events)} entities={len(state.entities)} "
        f"typedstate_version={state.version} source_event_ids={len(state.source_event_ids)}"
    )
    return CompactContext(now=now, rules=rules, next_steps=next_steps, meta=meta)


# ---------------------------------------------------------------------------
# Commit 4: TypedState V1 diff-log helper + V1 renderer
# ---------------------------------------------------------------------------

def _log_typedstate_diff(legacy_now: List[str], v1_now: List[str]) -> None:
    """
    Log diff between legacy NOW bullets and TypedState V1 NOW bullets.

    Format: [TypedState-DIFF] +NOW-bullets: [...] -NOW-bullets: [...]
      + = bullets present in V1 but not in legacy (additions)
      - = bullets present in legacy but not in V1 (removals)

    Called by TYPEDSTATE_MODE=shadow path in ContextManager.build_small_model_context.
    Never raises; any error is silently swallowed.
    """
    try:
        legacy_set = set(legacy_now)
        v1_set = set(v1_now)
        added = [b for b in v1_now if b not in legacy_set]
        removed = [b for b in legacy_now if b not in v1_set]
        log_info(f"[TypedState-DIFF] +NOW-bullets: {added} -NOW-bullets: {removed}")
    except Exception as exc:
        log_warn(f"[ContextCleanup] _log_typedstate_diff error: {exc}")


def format_typedstate_v1(ctx: CompactContext, char_cap: Optional[int] = None) -> str:
    """
    Format CompactContext as TypedState V1 render.

    Identical base to format_compact_context but extends NOW section with
    V1-specific bullets from ctx.meta["v1_extra_now"]:
      - V1_ERR_HIST: entries from last_errors beyond the last (singular) error
      - V1_TOOL: recent tool result refs from last_tool_results

    Respects now_max (from _DEFAULT_LIMITS) and char_cap.
    Falls back to format_compact_context on any error (fail-open for V1 extras).

    Used by TYPEDSTATE_MODE=active in ContextManager.build_small_model_context.
    """
    _cap = char_cap if char_cap is not None else _get_renderer_char_cap()
    try:
        now_max = _DEFAULT_LIMITS["now_max"]
        # V1 NOW: legacy bullets + V1 extras (bounded by now_max total)
        now_v1 = list(ctx.now)
        v1_extras = ctx.meta.get("v1_extra_now", [])
        for item in v1_extras:
            if len(now_v1) >= now_max:
                break
            now_v1.append(item)

        lines: List[str] = []
        if now_v1:
            lines.append("NOW:")
            for item in now_v1:
                lines.append(f"  - {item}")
        if ctx.rules:
            lines.append("RULES:")
            for item in ctx.rules:
                lines.append(f"  - {item}")
        if ctx.next:
            lines.append("NEXT:")
            for item in ctx.next:
                lines.append(f"  - {item}")
        text = "\n".join(lines)
        if len(text) > _cap:
            log_warn(f"[ContextCleanup] V1 renderer char_cap enforced: {len(text)} → {_cap} chars")
            text = text[:_cap]
        return text
    except Exception as exc:
        log_warn(f"[ContextCleanup] V1 renderer error: {exc} — fallback to legacy")
        return format_compact_context(ctx, char_cap=char_cap)


_RENDERER_CHAR_CAP_DEFAULT = 2200


def _get_renderer_char_cap() -> int:
    """Load renderer char_cap from mapping_rules.yaml limits.char_cap, else default 2200."""
    rules_path = os.path.join(os.path.dirname(__file__), "mapping_rules.yaml")
    if _YAML_AVAILABLE and os.path.exists(rules_path):
        try:
            with open(rules_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            val = data.get("limits", {}).get("char_cap")
            if val is not None:
                return int(val)
        except Exception:
            pass
    return _RENDERER_CHAR_CAP_DEFAULT


def format_compact_context(ctx: CompactContext, char_cap: Optional[int] = None) -> str:
    """
    Format a CompactContext as a short text block for injection into prompts.

    Deterministic rendering with hard char_cap enforcement and fail-closed fallback.

    char_cap: override char budget (default from mapping_rules.yaml limits.char_cap or 2200).

    Example output:
        NOW:
        - ACTIVE_CONTAINER py39/abc123def456 stability=high
        RULES:
        - No freestyle container execution
        NEXT:
        - Continue work on py39
    """
    _cap = char_cap if char_cap is not None else _get_renderer_char_cap()
    try:
        lines: List[str] = []
        if ctx.now:
            lines.append("NOW:")
            for item in ctx.now:
                lines.append(f"  - {item}")
        if ctx.rules:
            lines.append("RULES:")
            for item in ctx.rules:
                lines.append(f"  - {item}")
        if ctx.next:
            lines.append("NEXT:")
            for item in ctx.next:
                lines.append(f"  - {item}")
        text = "\n".join(lines)
        if len(text) > _cap:
            log_warn(f"[ContextCleanup] Renderer char_cap enforced: {len(text)} → {_cap} chars")
            text = text[:_cap]
        return text
    except Exception as exc:
        log_warn(f"[ContextCleanup] Renderer error: {exc} — fail-closed minimal response")
        return (
            "NOW:\n  - CONTEXT ERROR: Zustand unvollständig\n"
            "NEXT:\n  - Bitte Anfrage kurz präzisieren oder letzten Schritt wiederholen"
        )
