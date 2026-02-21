"""
Unit Tests: TypedState CSV Loader (core/typedstate_csv_loader.py)

Covers:
- _parse_json_field: JSON + ast.literal_eval fallback
- confidence_score, recency_score, fact_priority_score, rank_score
- _map_row_to_event: column mapping, event_data merge, timestamp->created_at
- load_csv_events: loads real CSV, deterministic sort
- build_compact_context(extra_events=...): integration path
- CSV column names remain unchanged in source
"""
from __future__ import annotations

import csv
import json
import os
import sys
import tempfile

import pytest

# Ensure project root is on path.
# Walk up the directory tree to find the repo root (contains memory_speicher/).
def _find_repo_root() -> str:
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        if os.path.isdir(os.path.join(current, "memory_speicher")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return ""

_REPO_ROOT = _find_repo_root()
if _REPO_ROOT:
    sys.path.insert(0, _REPO_ROOT)
else:
    # Fallback for tests/unit/ layout (3 levels up)
    _REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, _REPO_ROOT)

CSV_PATH = os.path.join(_REPO_ROOT, "memory_speicher", "memory_150_rows.csv")


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _make_test_row(**overrides) -> dict:
    """Build a minimal CSV-row dict for unit tests."""
    row = {
        "event_id":           "test-event-id-001",
        "conversation_id":    "conv_test_001",
        "timestamp":          "2026-02-18T01:09:35Z",
        "source_type":        "user",
        "source_reliability": "0.85",
        "entity_ids":         "user:frank",
        "entity_match_type":  "exact",
        "action":             "user_message",
        "raw_text":           "I prefer podman",
        "parameters":         "{}",
        "fact_type":          "USER_PREFERENCE",
        "fact_attributes":    '{"preference": "podman"}',
        "confidence_overall": "high",
        "confidence_breakdown": '{"base_reliability": 0.85}',
        "scenario_type":      "preference_update",
        "category":           "user",
        "derived_from":       "['test-event-id-001']",
        "stale_at":           "",
        "expires_at":         "",
    }
    row.update(overrides)
    return row


def _write_temp_csv(rows: list[dict]) -> str:
    """Write rows to a temp CSV and return path. Caller must delete."""
    fieldnames = list(rows[0].keys())
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
    ) as tf:
        tmp = tf.name
        writer = csv.DictWriter(tf, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return tmp


def _make_rank_rows(specs) -> list[dict]:
    """
    specs: list of (event_id, timestamp, source_reliability, confidence_overall, category)
    Returns list of CSV row dicts.
    """
    rows = []
    for eid, ts, sr, co, cat in specs:
        rows.append({
            "event_id":           eid,
            "conversation_id":    "conv_test",
            "timestamp":          ts,
            "source_type":        "system",
            "source_reliability": str(sr),
            "entity_ids":         "",
            "entity_match_type":  "exact",
            "action":             "test_event",
            "raw_text":           "",
            "parameters":         "{}",
            "fact_type":          "TEST",
            "fact_attributes":    "{}",
            "confidence_overall": co,
            "confidence_breakdown": "{}",
            "scenario_type":      "",
            "category":           cat,
            "derived_from":       "[]",
            "stale_at":           "",
            "expires_at":         "",
        })
    return rows


# ─────────────────────────────────────────────────────────────────
# _parse_json_field
# ─────────────────────────────────────────────────────────────────

class TestParseJsonField:
    def setup_method(self):
        from core.typedstate_csv_loader import _parse_json_field
        self.fn = _parse_json_field

    def test_valid_json_dict(self):
        assert self.fn('{"key": "val"}') == {"key": "val"}

    def test_valid_json_list(self):
        assert self.fn('["a", "b"]') == ["a", "b"]

    def test_empty_string_returns_empty_dict(self):
        assert self.fn("") == {}

    def test_whitespace_string_returns_empty_dict(self):
        assert self.fn("   ") == {}

    def test_invalid_json_no_fallback_returns_empty(self):
        # Python list literal with single quotes — JSON invalid, fallback disabled
        assert self.fn("['uuid-1']", fallback_eval=False) == {}

    def test_derived_from_ast_fallback_single(self):
        """Real CSV pattern: single-quoted Python list literal."""
        result = self.fn("['ea2c2d26-c8c6-4030-a763-012e1301b39b']", fallback_eval=True)
        assert result == ["ea2c2d26-c8c6-4030-a763-012e1301b39b"]

    def test_derived_from_ast_fallback_multiple(self):
        result = self.fn("['id-001', 'id-002', 'id-003']", fallback_eval=True)
        assert result == ["id-001", "id-002", "id-003"]

    def test_truly_invalid_returns_empty_dict(self):
        assert self.fn("{{not valid}}", fallback_eval=True) == {}


# ─────────────────────────────────────────────────────────────────
# confidence_score
# ─────────────────────────────────────────────────────────────────

class TestConfidenceScore:
    def setup_method(self):
        from core.typedstate_csv_loader import confidence_score
        self.fn = confidence_score

    def test_system_source_high_label(self):
        row = {"source_type": "system", "source_reliability": "1.0", "confidence_overall": "high"}
        assert self.fn(row) == pytest.approx(1.0)  # (1.0 + 1.0) / 2

    def test_user_source_high_label(self):
        row = {"source_type": "user", "source_reliability": "0.85", "confidence_overall": "high"}
        assert self.fn(row) == pytest.approx((0.85 + 1.0) / 2)

    def test_low_confidence_label(self):
        row = {"source_type": "system", "source_reliability": "1.0", "confidence_overall": "low"}
        assert self.fn(row) == pytest.approx((1.0 + 0.30) / 2)

    def test_float_source_reliability(self):
        row = {"source_type": "memory", "source_reliability": "0.70", "confidence_overall": "medium"}
        assert self.fn(row) == pytest.approx((0.70 + 0.65) / 2)

    def test_missing_fields_in_valid_range(self):
        score = self.fn({})
        assert 0.0 <= score <= 1.0


# ─────────────────────────────────────────────────────────────────
# recency_score
# ─────────────────────────────────────────────────────────────────

class TestRecencyScore:
    def setup_method(self):
        from core.typedstate_csv_loader import recency_score
        from datetime import timezone
        self.fn = recency_score
        from datetime import datetime
        self.now = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)

    def test_recent_timestamp_near_one(self):
        # ~2h ago → score ≈ 0.92
        score = self.fn({"timestamp": "2026-02-19T10:00:00Z"}, now_ts=self.now)
        assert score > 0.9

    def test_recent_beats_old(self):
        s_today = self.fn({"timestamp": "2026-02-19T10:00:00Z"}, now_ts=self.now)
        s_yesterday = self.fn({"timestamp": "2026-02-18T10:00:00Z"}, now_ts=self.now)
        assert s_today > s_yesterday

    def test_old_timestamp_low_score(self):
        score = self.fn({"timestamp": "2025-01-01T00:00:00Z"}, now_ts=self.now)
        assert score < 0.01

    def test_empty_timestamp_zero(self):
        assert self.fn({"timestamp": ""}, now_ts=self.now) == 0.0

    def test_missing_timestamp_zero(self):
        assert self.fn({}, now_ts=self.now) == 0.0

    def test_unparseable_timestamp_zero(self):
        assert self.fn({"timestamp": "not-a-date"}, now_ts=self.now) == 0.0


# ─────────────────────────────────────────────────────────────────
# fact_priority_score
# ─────────────────────────────────────────────────────────────────

class TestFactPriorityScore:
    def setup_method(self):
        from core.typedstate_csv_loader import fact_priority_score
        self.fn = fact_priority_score

    def test_knowledge_highest(self):
        assert self.fn({"category": "knowledge"}) == 1.0

    def test_decision_medium_high(self):
        assert self.fn({"category": "decision"}) == 0.8

    def test_user_medium(self):
        assert self.fn({"category": "user"}) == 0.6

    def test_unknown_default(self):
        assert self.fn({"category": "other"}) == 0.4

    def test_missing_default(self):
        assert self.fn({}) == 0.4


# ─────────────────────────────────────────────────────────────────
# rank_score formula
# ─────────────────────────────────────────────────────────────────

class TestRankScore:
    def setup_method(self):
        from core.typedstate_csv_loader import (
            rank_score, confidence_score, recency_score, fact_priority_score
        )
        from datetime import datetime, timezone
        self.rank = rank_score
        self.conf = confidence_score
        self.rec = recency_score
        self.prio = fact_priority_score
        self.now = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)

    def test_formula_matches_components(self):
        row = {
            "source_type": "system", "source_reliability": "1.0",
            "confidence_overall": "high",
            "timestamp": "2026-02-19T10:00:00Z",
            "category": "knowledge",
        }
        c = self.conf(row)
        r = self.rec(row, now_ts=self.now)
        p = self.prio(row)
        expected = 0.5 * c + 0.3 * r + 0.2 * p
        assert self.rank(row, now_ts=self.now) == pytest.approx(expected, abs=1e-9)

    def test_score_in_valid_range(self):
        row = {
            "source_type": "user", "source_reliability": "0.85",
            "confidence_overall": "high",
            "timestamp": "2026-02-18T01:09:35Z",
            "category": "user",
        }
        score = self.rank(row, now_ts=self.now)
        assert 0.0 <= score <= 1.0


# ─────────────────────────────────────────────────────────────────
# _map_row_to_event — column mapping
# ─────────────────────────────────────────────────────────────────

class TestMapRowToEvent:
    def setup_method(self):
        from core.typedstate_csv_loader import _map_row_to_event
        self.fn = _map_row_to_event

    def test_id_from_event_id(self):
        assert self.fn(_make_test_row())["id"] == "test-event-id-001"

    def test_event_type_from_action(self):
        assert self.fn(_make_test_row())["event_type"] == "user_message"

    def test_created_at_from_timestamp(self):
        """Core: CSV 'timestamp' column -> 'created_at' in event dict."""
        ev = self.fn(_make_test_row())
        assert ev["created_at"] == "2026-02-18T01:09:35Z"
        # timestamp must NOT appear at top level
        assert "timestamp" not in ev

    def test_conversation_id_preserved(self):
        assert self.fn(_make_test_row())["conversation_id"] == "conv_test_001"

    def test_fact_attributes_in_event_data(self):
        ev = self.fn(_make_test_row())
        assert ev["event_data"]["preference"] == "podman"

    def test_parameters_merged_into_event_data(self):
        row = _make_test_row(parameters='{"key": "container_runtime", "value": "podman"}')
        ev = self.fn(row)
        assert ev["event_data"]["key"] == "container_runtime"
        assert ev["event_data"]["value"] == "podman"

    def test_parameters_win_over_fact_attributes_on_key_conflict(self):
        row = _make_test_row(
            fact_attributes='{"preference": "docker"}',
            parameters='{"preference": "podman"}',
        )
        assert self.fn(row)["event_data"]["preference"] == "podman"

    def test_extra_context_fields_included(self):
        ev = self.fn(_make_test_row())
        ed = ev["event_data"]
        assert ed.get("fact_type") == "USER_PREFERENCE"
        assert ed.get("category") == "user"
        assert ed.get("scenario_type") == "preference_update"
        assert ed.get("entity_ids") == "user:frank"
        assert ed.get("raw_text") == "I prefer podman"

    def test_derived_from_ast_parsed_to_list(self):
        """derived_from Python list literal -> list in event_data."""
        ev = self.fn(_make_test_row())
        df = ev["event_data"].get("derived_from")
        assert isinstance(df, list)
        assert df == ["test-event-id-001"]

    def test_stale_at_included_when_present(self):
        row = _make_test_row(stale_at="2026-02-18T02:00:00Z")
        assert self.fn(row)["event_data"]["stale_at"] == "2026-02-18T02:00:00Z"

    def test_stale_at_absent_when_empty(self):
        ev = self.fn(_make_test_row(stale_at=""))
        assert "stale_at" not in ev["event_data"]

    def test_csv_source_provenance_fields(self):
        ev = self.fn(_make_test_row())
        assert ev["_csv_source"] is True
        assert ev["_source_type"] == "user"
        assert ev["_source_reliability"] == "0.85"


# ─────────────────────────────────────────────────────────────────
# load_csv_events — real CSV
# ─────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not os.path.exists(CSV_PATH), reason="CSV file not found")
class TestLoadCsvEvents:
    def setup_method(self):
        from core.typedstate_csv_loader import load_csv_events
        from datetime import datetime, timezone
        self.load = load_csv_events
        self.now = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)

    def test_loads_all_150_rows(self):
        events = self.load(CSV_PATH, now_ts=self.now)
        assert len(events) == 150

    def test_timestamp_to_created_at_mapping(self):
        """Every event: created_at set, 'timestamp' not at top-level."""
        events = self.load(CSV_PATH, now_ts=self.now)
        for ev in events:
            assert "created_at" in ev
            assert ev["created_at"] != ""
            assert "timestamp" not in ev

    def test_csv_columns_unchanged_in_source(self):
        """Verify original CSV still has 'timestamp' (not renamed to 'created_at')."""
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            fieldnames = csv.DictReader(f).fieldnames or []
        assert "timestamp" in fieldnames
        assert "created_at" not in fieldnames
        assert "event_id" in fieldnames
        assert "action" in fieldnames

    def test_derived_from_parsed_to_list_for_all_rows(self):
        events = self.load(CSV_PATH, now_ts=self.now)
        for ev in events:
            df = ev["event_data"].get("derived_from")
            if df is not None:
                assert isinstance(df, list), (
                    f"derived_from must be list, got {type(df)}: {df!r}"
                )

    def test_sorted_first_event_has_max_rank(self):
        from core.typedstate_csv_loader import rank_score
        raw_rows = []
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                raw_rows.append(dict(row))
        max_score = max(rank_score(r, self.now) for r in raw_rows)

        events = self.load(CSV_PATH, sorted_by_rank=True, now_ts=self.now)
        # Find raw row for first event
        first_id = events[0]["id"]
        first_raw = next(r for r in raw_rows if r["event_id"] == first_id)
        first_score = rank_score(first_raw, self.now)
        assert first_score == pytest.approx(max_score, abs=1e-6)

    def test_unsorted_preserves_csv_row_order(self):
        events = self.load(CSV_PATH, sorted_by_rank=False, now_ts=self.now)
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            first_csv_row = next(csv.DictReader(f))
        assert events[0]["id"] == first_csv_row["event_id"]


# ─────────────────────────────────────────────────────────────────
# Deterministic sort order (via temp CSV)
# ─────────────────────────────────────────────────────────────────

class TestDeterministicSort:
    """Verify sort contract: rank DESC, created_at DESC, id ASC."""

    def setup_method(self):
        from core.typedstate_csv_loader import load_csv_events
        from datetime import datetime, timezone
        self.load = load_csv_events
        self.now = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)

    def test_higher_rank_comes_first(self):
        # id-A: high confidence + knowledge → high rank
        # id-B: low confidence + user → low rank (same timestamp)
        rows = _make_rank_rows([
            ("id-B", "2026-02-19T10:00:00Z", 0.5, "low", "user"),
            ("id-A", "2026-02-19T10:00:00Z", 1.0, "high", "knowledge"),
        ])
        tmp = _write_temp_csv(rows)
        try:
            events = self.load(tmp, sorted_by_rank=True, now_ts=self.now)
        finally:
            os.unlink(tmp)
        assert events[0]["id"] == "id-A", f"Expected id-A first, got {events[0]['id']}"
        assert events[1]["id"] == "id-B"

    def test_newer_timestamp_wins_on_rank_tie(self):
        rows = _make_rank_rows([
            ("id-old", "2026-02-17T10:00:00Z", 1.0, "high", "knowledge"),
            ("id-new", "2026-02-19T10:00:00Z", 1.0, "high", "knowledge"),
        ])
        tmp = _write_temp_csv(rows)
        try:
            events = self.load(tmp, sorted_by_rank=True, now_ts=self.now)
        finally:
            os.unlink(tmp)
        assert events[0]["id"] == "id-new", f"Expected id-new first, got {events[0]['id']}"

    def test_id_asc_on_full_tie(self):
        """When rank and timestamp are identical, lower id comes first (ASC)."""
        rows = _make_rank_rows([
            ("id-Z", "2026-02-19T10:00:00Z", 1.0, "high", "knowledge"),
            ("id-A", "2026-02-19T10:00:00Z", 1.0, "high", "knowledge"),
            ("id-M", "2026-02-19T10:00:00Z", 1.0, "high", "knowledge"),
        ])
        tmp = _write_temp_csv(rows)
        try:
            events = self.load(tmp, sorted_by_rank=True, now_ts=self.now)
        finally:
            os.unlink(tmp)
        ids = [ev["id"] for ev in events]
        assert ids == ["id-A", "id-M", "id-Z"], f"Expected ASC id order, got {ids}"


# ─────────────────────────────────────────────────────────────────
# Integration: build_compact_context(extra_events=...)
# ─────────────────────────────────────────────────────────────────

class TestBuildCompactContextWithCsvEvents:

    def test_csv_container_started_appears_in_now(self):
        """CSV container_started event -> ACTIVE_CONTAINER in NOW."""
        from core.context_cleanup import build_compact_context
        csv_event = {
            "id": "csv-ev-001",
            "conversation_id": "conv_csv",
            "event_type": "container_started",
            "created_at": "2026-02-18T10:00:00Z",
            "event_data": {
                "container_id": "abc123def456",
                "blueprint_id": "nginx-latest",
            },
        }
        ctx = build_compact_context(events=[], extra_events=[csv_event])
        combined = " ".join(ctx.now)
        assert "ACTIVE_CONTAINER" in combined

    def test_live_stop_overrides_csv_start(self):
        """
        CSV (older): container_started
        Live (newer): container_stopped
        → Container must NOT be ACTIVE after correct chronological merge.
        """
        from core.context_cleanup import build_compact_context
        live_event = {
            "id": "live-ev-001",
            "event_type": "container_stopped",
            "created_at": "2026-02-19T11:00:00Z",
            "event_data": {"container_id": "abc123def456"},
        }
        csv_event = {
            "id": "csv-ev-001",
            "event_type": "container_started",
            "created_at": "2026-02-18T10:00:00Z",
            "event_data": {
                "container_id": "abc123def456",
                "blueprint_id": "nginx-latest",
            },
        }
        # live_event in DESC order (newest first — as expected from Fast-Lane)
        ctx = build_compact_context(events=[live_event], extra_events=[csv_event])
        combined = " ".join(ctx.now)
        assert "ACTIVE_CONTAINER" not in combined

    def test_no_regression_without_extra_events(self):
        """Omitting extra_events: original behavior fully preserved."""
        from core.context_cleanup import build_compact_context
        event = {
            "event_type": "container_started",
            "created_at": "2026-02-19T10:00:00Z",
            "event_data": {"container_id": "mycontainer123", "blueprint_id": "py39"},
        }
        ctx = build_compact_context(events=[event])
        assert "ACTIVE_CONTAINER" in " ".join(ctx.now)

    def test_empty_extra_events_list_is_no_op(self):
        """Passing extra_events=[] behaves same as no extra_events."""
        from core.context_cleanup import build_compact_context
        event = {
            "event_type": "container_started",
            "created_at": "2026-02-19T10:00:00Z",
            "event_data": {"container_id": "mycontainer123", "blueprint_id": "py39"},
        }
        ctx1 = build_compact_context(events=[event])
        ctx2 = build_compact_context(events=[event], extra_events=[])
        assert ctx1.now == ctx2.now
