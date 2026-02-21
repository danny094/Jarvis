"""
core/typedstate_csv_loader.py — CSV Event Loader for TypedState V1

Loads memory_speicher/memory_150_rows.csv (or any configured path) as a
supplementary event source for the TypedState pipeline:

    CSV -> workspace_event-compatible dicts -> TypedState -> CompactContext

CSV column mapping (columns are NEVER renamed in source):
    event_id          -> id
    conversation_id   -> conversation_id
    timestamp         -> created_at   (ISO string preserved as-is)
    action            -> event_type
    event_data        <- merge(fact_attributes, parameters) + extra fields

Ranking (for Fact-Selektion / Compact-Kontext):
    rank_score = 0.5 * confidence_score + 0.3 * recency_score + 0.2 * fact_priority_score

Deterministic sort:
    rank_score DESC, created_at DESC, id ASC

State-mutation ordering (lifecycle correctness):
    Callers use sorted events via created_at ASC for _apply_event; no regression.
"""
from __future__ import annotations

import ast
import csv
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils.logger import log_info, log_warn


# ---------------------------------------------------------------------------
# JSON / literal field parsing
# ---------------------------------------------------------------------------

def _parse_json_field(value: str, fallback_eval: bool = False) -> Any:
    """
    Parse a JSON string field.

    Returns parsed object (dict/list/…) on success, {} on failure.
    When fallback_eval=True, tries ast.literal_eval after JSON failure
    (needed for Python-literal list strings like "['uuid-1', 'uuid-2']").
    """
    if not value or not value.strip():
        return {}
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        if fallback_eval:
            try:
                return ast.literal_eval(value)
            except Exception:
                pass
        return {}


# ---------------------------------------------------------------------------
# Confidence / reliability helpers
# ---------------------------------------------------------------------------

_CONFIDENCE_LABEL_MAP: Dict[str, float] = {
    "high":   1.0,
    "medium": 0.65,
    "low":    0.30,
}

_SOURCE_TYPE_RELIABILITY: Dict[str, float] = {
    "system":    1.0,
    "user":      0.85,
    "memory":    0.70,
    "inference": 0.50,
}

_CATEGORY_PRIORITY: Dict[str, float] = {
    "knowledge": 1.0,
    "decision":  0.8,
    "user":      0.6,
}

_DEFAULT_CATEGORY_PRIORITY = 0.4


def _confidence_label_to_float(label: str) -> float:
    """Convert 'high'/'medium'/'low' label to float. Unknown labels → 0.65."""
    return _CONFIDENCE_LABEL_MAP.get(str(label).lower().strip(), 0.65)


def _source_reliability_to_float(source_type: str, raw_value: str) -> float:
    """
    Parse source_reliability from a CSV cell.

    Accepts:
    - A float string ("0.85", "1.0")
    - Falls back to _SOURCE_TYPE_RELIABILITY lookup by source_type label
    """
    try:
        return max(0.0, min(1.0, float(raw_value)))
    except (ValueError, TypeError):
        return _SOURCE_TYPE_RELIABILITY.get(str(source_type).lower().strip(), 0.70)


def _category_to_priority(category: str) -> float:
    """Map category string to priority float."""
    return _CATEGORY_PRIORITY.get(str(category).lower().strip(), _DEFAULT_CATEGORY_PRIORITY)


# ---------------------------------------------------------------------------
# Ranking functions (public — usable by TypedState-Builder callers)
# ---------------------------------------------------------------------------

def confidence_score(row: Dict[str, str]) -> float:
    """
    Combined confidence score in [0, 1].

    = mean(source_reliability, confidence_label_float)
    """
    src_rel = _source_reliability_to_float(
        row.get("source_type", ""),
        row.get("source_reliability", ""),
    )
    label_val = _confidence_label_to_float(row.get("confidence_overall", "medium"))
    return (src_rel + label_val) / 2.0


def recency_score(row: Dict[str, str], now_ts: Optional[datetime] = None) -> float:
    """
    Time-decay recency score in [0, 1].

    score = 1 / (1 + days_elapsed)

    Rows with unparseable timestamps return 0.0.
    """
    if now_ts is None:
        now_ts = datetime.now(tz=timezone.utc)
    ts_str = row.get("timestamp", "")
    if not ts_str:
        return 0.0
    try:
        parsed = datetime.fromisoformat(ts_str.rstrip("Z"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        delta_days = (now_ts - parsed).total_seconds() / 86400.0
        return 1.0 / (1.0 + max(0.0, delta_days))
    except Exception:
        return 0.0


def fact_priority_score(row: Dict[str, str]) -> float:
    """Priority score in [0, 1] derived from row category."""
    return _category_to_priority(row.get("category", ""))


def rank_score(row: Dict[str, str], now_ts: Optional[datetime] = None) -> float:
    """
    Composite ranking score for Fact-Selektion:

        0.5 * confidence_score + 0.3 * recency_score + 0.2 * fact_priority_score
    """
    c = confidence_score(row)
    r = recency_score(row, now_ts)
    p = fact_priority_score(row)
    return 0.5 * c + 0.3 * r + 0.2 * p


# ---------------------------------------------------------------------------
# Row → workspace_event mapping
# ---------------------------------------------------------------------------

def _map_row_to_event(row: Dict[str, str]) -> Dict[str, Any]:
    """
    Map a single CSV row dict to a workspace_event-compatible dict.

    Column mapping (CSV columns are NOT renamed in source):
        id              <- event_id
        conversation_id <- conversation_id
        event_type      <- action
        created_at      <- timestamp    (ISO string, preserved as-is)
        event_data      <- merge(fact_attributes, parameters) + extras

    Returns a dict compatible with _apply_event() in context_cleanup.py.
    """
    parameters        = _parse_json_field(row.get("parameters", ""))
    fact_attributes   = _parse_json_field(row.get("fact_attributes", ""))
    confidence_breakdown = _parse_json_field(row.get("confidence_breakdown", ""))
    # derived_from uses Python list literals → needs ast.literal_eval fallback
    derived_from      = _parse_json_field(row.get("derived_from", ""), fallback_eval=True)

    # Build merged event_data: fact_attributes base, parameters override
    event_data: Dict[str, Any] = {}
    if isinstance(fact_attributes, dict):
        event_data.update(fact_attributes)
    if isinstance(parameters, dict):
        event_data.update(parameters)

    # Include useful context fields from row
    for extra_key in ("fact_type", "category", "scenario_type", "entity_ids", "raw_text"):
        val = row.get(extra_key, "")
        if val:
            event_data[extra_key] = val

    if derived_from:
        event_data["derived_from"] = derived_from
    if confidence_breakdown:
        event_data["confidence_breakdown"] = confidence_breakdown

    stale_at = row.get("stale_at", "")
    if stale_at:
        event_data["stale_at"] = stale_at

    expires_at = row.get("expires_at", "")
    if expires_at:
        event_data["expires_at"] = expires_at

    return {
        "id":              row.get("event_id", ""),
        "conversation_id": row.get("conversation_id", ""),
        "event_type":      row.get("action", ""),
        "created_at":      row.get("timestamp", ""),   # timestamp -> created_at
        "event_data":      event_data,
        # Internal CSV provenance metadata (prefixed, not used by _apply_event)
        "_csv_source":          True,
        "_source_type":         row.get("source_type", ""),
        "_source_reliability":  row.get("source_reliability", ""),
        "_confidence_overall":  row.get("confidence_overall", ""),
    }


# ---------------------------------------------------------------------------
# Timestamp helper (for sort key)
# ---------------------------------------------------------------------------

def _ts_to_float(ts_str: str) -> float:
    """Convert ISO timestamp string to unix float; returns 0.0 on error."""
    if not ts_str:
        return 0.0
    try:
        dt = datetime.fromisoformat(ts_str.rstrip("Z"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------

def load_csv_events(
    path: str,
    sorted_by_rank: bool = True,
    now_ts: Optional[datetime] = None,
    start_ts: Optional[datetime] = None,
    end_ts: Optional[datetime] = None,
    conversation_id: Optional[str] = None,
    actions: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Load CSV from path and return workspace_event-compatible event dicts.

    Args:
        path:            Absolute or relative path to the CSV file.
        sorted_by_rank:  If True, deterministic sort:
                           rank_score DESC, created_at DESC, id ASC.
                         If False, preserves CSV row order.
        now_ts:          Reference timestamp for recency_score (default: UTC now).
        start_ts:        (Commit C) Filter: include only rows with timestamp >= start_ts.
        end_ts:          (Commit C) Filter: include only rows with timestamp <= end_ts.
        conversation_id: (Commit C) Filter: include only rows matching this conversation.
                         None = no conversation filter (all conversations).
        actions:         (Commit C) Filter: include only rows whose action is in this list.
                         None = no action filter (all actions).

    Returns:
        List of event dicts ready for build_compact_context(extra_events=…).
        CSV columns are NOT renamed; timestamp -> created_at mapping is applied here.

    Raises:
        FileNotFoundError: if path does not exist.
        csv.Error: on malformed CSV.

    Rollback: DIGEST_FILTERS_ENABLE=false keeps default (no filtering) behaviour.
    """
    if now_ts is None:
        now_ts = datetime.now(tz=timezone.utc)

    raw_rows: List[Dict[str, str]] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_rows.append(dict(row))

    log_info(f"[CSVLoader] Loaded {len(raw_rows)} rows from {path}")

    # Commit C: optional time-window, conversation and action filters
    if start_ts is not None or end_ts is not None or conversation_id is not None or actions is not None:
        _start_f = start_ts.timestamp() if start_ts is not None else None
        _end_f   = end_ts.timestamp()   if end_ts is not None   else None
        _actions_set = set(actions) if actions is not None else None
        filtered: List[Dict[str, str]] = []
        _removed = 0
        for row in raw_rows:
            ts_f = _ts_to_float(row.get("timestamp", ""))
            if _start_f is not None and ts_f < _start_f:
                _removed += 1
                continue
            if _end_f is not None and ts_f > _end_f:
                _removed += 1
                continue
            if conversation_id is not None and row.get("conversation_id", "") != conversation_id:
                _removed += 1
                continue
            if _actions_set is not None and row.get("action", "") not in _actions_set:
                _removed += 1
                continue
            filtered.append(row)
        if _removed:
            log_info(
                f"[CSVLoader] Filter: {len(raw_rows)} → {len(filtered)} rows "
                f"({_removed} removed; start_ts={start_ts} end_ts={end_ts} "
                f"conv={conversation_id} actions={actions})"
            )
        raw_rows = filtered

    if sorted_by_rank:
        # Precompute scores once for each row (stable sort key)
        def _sort_key(row: Dict[str, str]):
            rs = rank_score(row, now_ts)
            ts_float = _ts_to_float(row.get("timestamp", ""))
            eid = row.get("event_id", "")
            # rank DESC → negate; created_at DESC → negate ts_float; id ASC
            return (-rs, -ts_float, eid)

        raw_rows.sort(key=_sort_key)

    events = [_map_row_to_event(row) for row in raw_rows]

    log_info(
        f"[CSVLoader] Mapped {len(events)} events; "
        f"sorted_by_rank={sorted_by_rank}; "
        f"timestamp->created_at mapping applied (CSV columns unchanged)"
    )
    return events


# ---------------------------------------------------------------------------
# Config-aware helper for automatic CSV loading
# ---------------------------------------------------------------------------

_JIT_VALID_TRIGGERS = frozenset({"time_reference", "remember", "fact_recall"})
_JIT_DISABLED_WARNED = False  # once-per-process sentinel


def maybe_load_csv_events(
    small_model_mode: bool = False,
    trigger: Optional[str] = None,
    conversation_id: Optional[str] = None,
    start_ts: Optional[datetime] = None,
    end_ts: Optional[datetime] = None,
    actions: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Load CSV events if all config flags permit it (Points 7 & 8).

    Checks (in order):
    1. TYPEDSTATE_CSV_ENABLE must be True
    2. TYPEDSTATE_MODE must not be 'off'
    3. If TYPEDSTATE_ENABLE_SMALL_ONLY=True, small_model_mode must also be True
    4. (Commit B) If TYPEDSTATE_CSV_JIT_ONLY=True, trigger must be a valid JIT trigger.
       None trigger with JIT_ONLY → returns [] (no CSV-IO at all).
    5. (Point 8) If DIGEST_FILTERS_ENABLE=True, compute time window from trigger type
       and pass it (along with conversation_id/actions) to load_csv_events.

    Trigger → time window mapping (Point 8, DIGEST_FILTERS_ENABLE=true):
       time_reference → JIT_WINDOW_TIME_REFERENCE_H hours (default 48h)
       fact_recall    → JIT_WINDOW_FACT_RECALL_H hours   (default 168h / 7d)
       remember       → JIT_WINDOW_REMEMBER_H hours      (default 336h / 14d)
       None           → no window filter

    After load: emits [DigestRuntime] JIT telemetry (fail-open).
    Returns [] on any gate failure or CSV absence.
    Rollback: TYPEDSTATE_CSV_JIT_ONLY=false / DIGEST_FILTERS_ENABLE=false.
    """
    try:
        import config  # avoid circular import at module level
    except ImportError:
        return []

    if not config.get_typedstate_csv_enable():
        return []

    mode = config.get_typedstate_mode()
    if mode == "off":
        return []

    if config.get_typedstate_enable_small_only() and not small_model_mode:
        return []

    # Point 7: JIT-only gate — strictly no CSV-IO when trigger absent.
    if config.get_typedstate_csv_jit_only() and trigger not in _JIT_VALID_TRIGGERS:
        log_info(
            f"[CSVLoader] JIT_ONLY=true and trigger={trigger!r} — skipping CSV load"
        )
        return []

    # JIT-disabled warning: emit once-per-process when loading without a trigger
    global _JIT_DISABLED_WARNED
    if not _JIT_DISABLED_WARNED and trigger is None:
        _JIT_DISABLED_WARNED = True
        log_warn(
            "[CSVLoader] TYPEDSTATE_CSV_JIT_ONLY=false and trigger=None — "
            "CSV loaded without JIT trigger; set JIT_ONLY=true to restrict CSV-IO "
            "to explicit triggers only (time_reference/remember/fact_recall)"
        )

    csv_path = config.get_typedstate_csv_path()
    if not os.path.isabs(csv_path):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        csv_path = os.path.join(base, csv_path)

    if not os.path.exists(csv_path):
        log_warn(f"[CSVLoader] CSV not found at resolved path: {csv_path}")
        return []

    # Point 8: trigger → time-window filter (when DIGEST_FILTERS_ENABLE=true)
    _start_ts = start_ts
    _end_ts   = end_ts
    if config.get_digest_filters_enable() and trigger in _JIT_VALID_TRIGGERS:
        now_utc = datetime.now(tz=timezone.utc)
        try:
            if trigger == "time_reference":
                window_h = config.get_jit_window_time_reference_h()
            elif trigger == "fact_recall":
                window_h = config.get_jit_window_fact_recall_h()
            else:  # "remember"
                window_h = config.get_jit_window_remember_h()
            if _start_ts is None:
                from datetime import timedelta as _td
                _start_ts = now_utc - _td(hours=window_h)
            log_info(
                f"[CSVLoader] trigger={trigger!r} window_h={window_h} "
                f"start_ts={_start_ts.isoformat()}"
            )
        except Exception as exc:
            log_warn(f"[CSVLoader] Trigger-window compute error: {exc}")

    try:
        events = load_csv_events(
            csv_path,
            start_ts=_start_ts,
            end_ts=_end_ts,
            conversation_id=conversation_id,
            actions=actions,
        )
        # Point 7: JIT telemetry (fail-open)
        try:
            from core.digest import runtime_state
            runtime_state.update_jit(trigger=trigger, rows=len(events))
        except Exception:
            pass
        return events
    except Exception as exc:
        log_warn(f"[CSVLoader] Failed to load CSV events: {exc}")
        return []
