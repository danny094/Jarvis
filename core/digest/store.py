"""
core/digest/store.py — DigestStore: idempotent read/write for digest records.

The digest store is a CSV file (digest_store.csv) that holds daily_digest,
weekly_digest, and archive_digest records in the same column schema as
memory_150_rows.csv (fully compatible with load_csv_events).

Truth: workspace_events via MCP hub (when available).
Index: digest_store.csv — fast re-run detection without MCP round-trip.

Re-run detection:
    1. Scan CSV index for (action, digest_key in parameters) — O(n), n ≤ few hundred rows.
    2. If not found in index, optionally cross-check MCP hub (archive_digest only).

Write path:
    - Appends a new CSV row to digest_store.csv (creates file + header if missing).
    - One row per digest event, idempotent key guards duplicate writes.

CSV columns (same as main memory CSV):
    event_id, conversation_id, timestamp, source_type, source_reliability,
    entity_ids, entity_match_type, action, raw_text, parameters, fact_type,
    fact_attributes, confidence_overall, confidence_breakdown, scenario_type,
    category, derived_from, stale_at, expires_at
"""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils.logger import log_info, log_warn

_CSV_FIELDNAMES = [
    "event_id", "conversation_id", "timestamp", "source_type", "source_reliability",
    "entity_ids", "entity_match_type", "action", "raw_text", "parameters",
    "fact_type", "fact_attributes", "confidence_overall", "confidence_breakdown",
    "scenario_type", "category", "derived_from", "stale_at", "expires_at",
]


def _resolve_store_path(store_path: str) -> str:
    """Resolve relative store path against project root (parent of core/)."""
    if os.path.isabs(store_path):
        return store_path
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, store_path)


def _read_rows(store_path: str) -> List[Dict[str, str]]:
    """Read all rows from digest store CSV. Returns [] if file does not exist."""
    resolved = _resolve_store_path(store_path)
    if not os.path.exists(resolved):
        return []
    try:
        with open(resolved, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]
    except Exception as exc:
        log_warn(f"[DigestStore] Failed to read {resolved}: {exc}")
        return []


def _write_row(store_path: str, row: Dict[str, str]) -> bool:
    """
    Append a single row to the digest store CSV.
    Creates the file with header if it does not exist.
    Returns True on success, False on error.
    """
    resolved = _resolve_store_path(store_path)
    try:
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        file_exists = os.path.exists(resolved)
        with open(resolved, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_CSV_FIELDNAMES, extrasaction="ignore")
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
        return True
    except Exception as exc:
        log_warn(f"[DigestStore] Failed to write to {resolved}: {exc}")
        return False


class DigestStore:
    """
    Thin wrapper around the digest store CSV for idempotent digest persistence.

    Usage:
        store = DigestStore(store_path)
        if not store.exists("daily_digest", digest_key):
            store.write_daily(...)
    """

    def __init__(self, store_path: Optional[str] = None) -> None:
        if store_path is None:
            try:
                from config import get_digest_store_path
                store_path = get_digest_store_path()
            except Exception:
                store_path = "memory_speicher/digest_store.csv"
        self._path = store_path

    # ── Re-run detection ──────────────────────────────────────────────────────

    def exists(self, action: str, digest_key: str) -> bool:
        """
        Return True if a row with the given action AND digest_key already exists.
        digest_key is matched against parameters.digest_key in the CSV row.
        """
        rows = _read_rows(self._path)
        for row in rows:
            if row.get("action") != action:
                continue
            try:
                params = json.loads(row.get("parameters", "{}") or "{}")
            except Exception:
                continue
            if params.get("digest_key") == digest_key:
                return True
        return False

    def list_by_action(self, action: str) -> List[Dict[str, str]]:
        """Return all rows matching the given action type."""
        return [r for r in _read_rows(self._path) if r.get("action") == action]

    # ── Write helpers ─────────────────────────────────────────────────────────

    def _base_row(
        self,
        event_id: str,
        conversation_id: str,
        action: str,
        fact_type: str,
        parameters: Dict[str, Any],
        fact_attributes: Dict[str, Any],
        raw_text: str = "",
    ) -> Dict[str, str]:
        now_iso = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
        return {
            "event_id":          event_id,
            "conversation_id":   conversation_id,
            "timestamp":         now_iso,
            "source_type":       "system",
            "source_reliability": "1.0",
            "entity_ids":        "",
            "entity_match_type": "exact",
            "action":            action,
            "raw_text":          raw_text[:500] if raw_text else "",
            "parameters":        json.dumps(parameters, default=str),
            "fact_type":         fact_type,
            "fact_attributes":   json.dumps(fact_attributes, default=str),
            "confidence_overall": "high",
            "confidence_breakdown": "{}",
            "scenario_type":     "digest",
            "category":          "knowledge",
            "derived_from":      "[]",
            "stale_at":          "",
            "expires_at":        "",
        }

    def write_daily(
        self,
        event_id: str,
        conversation_id: str,
        digest_key: str,
        digest_date: str,         # "YYYY-MM-DD"
        event_count: int,
        source_hash: str,
        compact_text: str,
        window_start: Optional[str] = None,  # "YYYY-MM-DD" (v2 key support)
        window_end: Optional[str] = None,    # "YYYY-MM-DD" (v2 key support)
    ) -> bool:
        """Write a daily_digest record. Idempotency: caller must call exists() first."""
        params: Dict[str, Any] = {
            "digest_key":  digest_key,
            "digest_date": digest_date,
            "source_hash": source_hash,
        }
        fa: Dict[str, Any] = {
            "digest_date": digest_date,
            "event_count": event_count,
            "digest_key":  digest_key,
        }
        if window_start is not None:
            params["window_start"] = window_start
            fa["window_start"] = window_start
        if window_end is not None:
            params["window_end"] = window_end
            fa["window_end"] = window_end
        row = self._base_row(
            event_id=event_id,
            conversation_id=conversation_id,
            action="daily_digest",
            fact_type="DAILY_DIGEST",
            parameters=params,
            fact_attributes=fa,
            raw_text=compact_text[:500],
        )
        ok = _write_row(self._path, row)
        if ok:
            log_info(
                f"[DigestStore] Wrote daily_digest "
                f"date={digest_date} conv={conversation_id} key={digest_key}"
            )
        return ok

    def write_weekly(
        self,
        event_id: str,
        conversation_id: str,
        digest_key: str,
        iso_week: str,             # "YYYY-Www"
        daily_digest_keys: List[str],
        compact_text: str,
        window_start: Optional[str] = None,  # "YYYY-MM-DD" Monday of week (v2 key support)
        window_end: Optional[str] = None,    # "YYYY-MM-DD" Sunday of week (v2 key support)
    ) -> bool:
        """Write a weekly_digest record. Idempotency: caller must call exists() first."""
        params: Dict[str, Any] = {
            "digest_key":        digest_key,
            "iso_week":          iso_week,
            "input_digest_keys": sorted(daily_digest_keys),
        }
        fa: Dict[str, Any] = {
            "iso_week":           iso_week,
            "daily_digest_count": len(daily_digest_keys),
            "digest_key":         digest_key,
        }
        if window_start is not None:
            params["window_start"] = window_start
            fa["window_start"] = window_start
        if window_end is not None:
            params["window_end"] = window_end
            fa["window_end"] = window_end
        row = self._base_row(
            event_id=event_id,
            conversation_id=conversation_id,
            action="weekly_digest",
            fact_type="WEEKLY_DIGEST",
            parameters=params,
            fact_attributes=fa,
            raw_text=compact_text[:500],
        )
        ok = _write_row(self._path, row)
        if ok:
            log_info(
                f"[DigestStore] Wrote weekly_digest "
                f"week={iso_week} conv={conversation_id} key={digest_key}"
            )
        return ok

    def write_archive(
        self,
        event_id: str,
        conversation_id: str,
        archive_key: str,
        weekly_digest_key: str,
        archive_date: str,         # "YYYY-MM-DD"
        archive_graph_node_id: str,
    ) -> bool:
        """Write an archive_digest record. Idempotency: caller must call exists() first."""
        row = self._base_row(
            event_id=event_id,
            conversation_id=conversation_id,
            action="archive_digest",
            fact_type="ARCHIVE_DIGEST",
            parameters={
                "digest_key":        archive_key,
                "archive_key":       archive_key,
                "weekly_digest_key": weekly_digest_key,
                "archive_date":      archive_date,
            },
            fact_attributes={
                "archived_at":             archive_date,
                "archive_key":             archive_key,
                "archive_graph_node_id":   archive_graph_node_id,
                "input_digest_keys":       [weekly_digest_key],
            },
        )
        ok = _write_row(self._path, row)
        if ok:
            log_info(
                f"[DigestStore] Wrote archive_digest "
                f"date={archive_date} conv={conversation_id} key={archive_key}"
            )
        return ok
