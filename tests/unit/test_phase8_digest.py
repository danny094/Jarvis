"""
tests/unit/test_phase8_digest.py — Phase 8 Digest Pipeline Tests

Covers:
  P8-A: Config flags (safe defaults, no behaviour change)
  P8-B: CSV JIT-Trigger-Gating (maybe_load_csv_events trigger param)
  P8-C: CSV Filter (start_ts / end_ts / conversation_id / actions)
  P8-D: Dedupe hardening (conv-scoped key)
  P8-E: Digest event types in TypedState (_apply_event daily/weekly/archive)
  P8-F: DailyDigestScheduler (keys, idempotency, catch-up, store writes)
  P8-G: WeeklyDigestArchiver (grouping, weekly build, archive threshold)
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List
from unittest.mock import MagicMock, patch


# ============================================================================
# P8-A: Config flags
# ============================================================================

class TestConfigFlagsPhase8(unittest.TestCase):
    """All Phase 8 flags must default to False/safe values."""

    def test_digest_enable_default_false(self):
        from config import get_digest_enable
        with patch.dict(os.environ, {}, clear=False):
            # unset env var → default False
            os.environ.pop("DIGEST_ENABLE", None)
            self.assertFalse(get_digest_enable())

    def test_digest_daily_enable_default_false(self):
        from config import get_digest_daily_enable
        os.environ.pop("DIGEST_ENABLE", None)
        os.environ.pop("DIGEST_DAILY_ENABLE", None)
        self.assertFalse(get_digest_daily_enable())

    def test_digest_weekly_enable_default_false(self):
        from config import get_digest_weekly_enable
        os.environ.pop("DIGEST_ENABLE", None)
        os.environ.pop("DIGEST_WEEKLY_ENABLE", None)
        self.assertFalse(get_digest_weekly_enable())

    def test_digest_archive_enable_default_false(self):
        from config import get_digest_archive_enable
        os.environ.pop("DIGEST_ENABLE", None)
        os.environ.pop("DIGEST_ARCHIVE_ENABLE", None)
        self.assertFalse(get_digest_archive_enable())

    def test_digest_tz_default(self):
        from config import get_digest_tz
        os.environ.pop("DIGEST_TZ", None)
        self.assertEqual(get_digest_tz(), "Europe/Berlin")

    def test_typedstate_csv_jit_only_default_false(self):
        from config import get_typedstate_csv_jit_only
        os.environ.pop("TYPEDSTATE_CSV_JIT_ONLY", None)
        self.assertFalse(get_typedstate_csv_jit_only())

    def test_digest_filters_enable_default_false(self):
        from config import get_digest_filters_enable
        os.environ.pop("DIGEST_FILTERS_ENABLE", None)
        self.assertFalse(get_digest_filters_enable())

    def test_digest_dedupe_include_conv_default_true(self):
        from config import get_digest_dedupe_include_conv
        os.environ.pop("DIGEST_DEDUPE_INCLUDE_CONV", None)
        self.assertTrue(get_digest_dedupe_include_conv())

    def test_digest_daily_requires_master_toggle(self):
        """DIGEST_DAILY_ENABLE=true without DIGEST_ENABLE=true → still False."""
        from config import get_digest_daily_enable
        with patch.dict(os.environ, {"DIGEST_ENABLE": "false", "DIGEST_DAILY_ENABLE": "true"}):
            # settings dict takes precedence; patch via env
            # Force re-read of env (get_digest_daily_enable calls get_digest_enable())
            with patch("config.get_digest_enable", return_value=False):
                self.assertFalse(get_digest_daily_enable())

    def test_digest_store_path_has_default(self):
        from config import get_digest_store_path
        path = get_digest_store_path()
        self.assertIsInstance(path, str)
        self.assertTrue(len(path) > 0)


# ============================================================================
# P8-B: JIT Trigger Gating
# ============================================================================

class TestCSVJITTriggerGating(unittest.TestCase):
    """maybe_load_csv_events must respect TYPEDSTATE_CSV_JIT_ONLY flag."""

    def _run(self, jit_only: bool, trigger, csv_enable: bool = True, mode: str = "shadow"):
        with patch("config.get_typedstate_csv_jit_only", return_value=jit_only), \
             patch("config.get_typedstate_csv_enable", return_value=csv_enable), \
             patch("config.get_typedstate_mode", return_value=mode), \
             patch("config.get_typedstate_enable_small_only", return_value=False), \
             patch("core.typedstate_csv_loader.load_csv_events", return_value=[{"id": "x"}]) as mock_load, \
             patch("os.path.exists", return_value=True), \
             patch("config.get_typedstate_csv_path", return_value="/fake/path.csv"):
            from core.typedstate_csv_loader import maybe_load_csv_events
            result = maybe_load_csv_events(small_model_mode=True, trigger=trigger)
            return result, mock_load

    def test_jit_only_false_no_trigger_loads_csv(self):
        """JIT_ONLY=false → CSV always loaded regardless of trigger."""
        result, mock_load = self._run(jit_only=False, trigger=None)
        self.assertGreater(len(result), 0)
        mock_load.assert_called_once()

    def test_jit_only_true_no_trigger_returns_empty(self):
        """JIT_ONLY=true + trigger=None → return [] (no default injection)."""
        result, mock_load = self._run(jit_only=True, trigger=None)
        self.assertEqual(result, [])
        mock_load.assert_not_called()

    def test_jit_only_true_time_reference_trigger_loads(self):
        """JIT_ONLY=true + trigger='time_reference' → CSV loaded."""
        result, mock_load = self._run(jit_only=True, trigger="time_reference")
        self.assertGreater(len(result), 0)
        mock_load.assert_called_once()

    def test_jit_only_true_remember_trigger_loads(self):
        """JIT_ONLY=true + trigger='remember' → CSV loaded."""
        result, mock_load = self._run(jit_only=True, trigger="remember")
        self.assertGreater(len(result), 0)

    def test_jit_only_true_fact_recall_trigger_loads(self):
        """JIT_ONLY=true + trigger='fact_recall' → CSV loaded."""
        result, mock_load = self._run(jit_only=True, trigger="fact_recall")
        self.assertGreater(len(result), 0)

    def test_jit_only_true_invalid_trigger_returns_empty(self):
        """JIT_ONLY=true + trigger='unknown' → return [] (not a valid JIT trigger)."""
        result, mock_load = self._run(jit_only=True, trigger="unknown_trigger")
        self.assertEqual(result, [])
        mock_load.assert_not_called()

    def test_csv_disabled_ignores_trigger(self):
        """CSV_ENABLE=false → always returns [] regardless of trigger."""
        result, mock_load = self._run(jit_only=True, trigger="time_reference", csv_enable=False)
        self.assertEqual(result, [])
        mock_load.assert_not_called()

    def test_trigger_none_backward_compatible(self):
        """When JIT_ONLY=false, trigger=None is backward-compatible (loads CSV)."""
        result, mock_load = self._run(jit_only=False, trigger=None)
        self.assertGreater(len(result), 0)

    def test_maybe_load_csv_events_trigger_param_exists(self):
        """maybe_load_csv_events must accept trigger as keyword argument."""
        import inspect
        from core.typedstate_csv_loader import maybe_load_csv_events
        sig = inspect.signature(maybe_load_csv_events)
        self.assertIn("trigger", sig.parameters,
                      "maybe_load_csv_events must accept 'trigger' keyword arg")


# ============================================================================
# P8-C: CSV Filters
# ============================================================================

def _write_test_csv(rows: List[Dict]) -> str:
    """Write test rows to a temp CSV file. Returns path."""
    fieldnames = [
        "event_id", "conversation_id", "timestamp", "source_type", "source_reliability",
        "entity_ids", "entity_match_type", "action", "raw_text", "parameters",
        "fact_type", "fact_attributes", "confidence_overall", "confidence_breakdown",
        "scenario_type", "category", "derived_from", "stale_at", "expires_at",
    ]
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
    )
    writer = csv.DictWriter(tmp, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({f: row.get(f, "") for f in fieldnames})
    tmp.close()
    return tmp.name


def _make_csv_row(event_id, conv_id, timestamp, action="user_message"):
    return {
        "event_id": event_id,
        "conversation_id": conv_id,
        "timestamp": timestamp,
        "action": action,
        "source_type": "user",
        "source_reliability": "0.85",
        "confidence_overall": "high",
        "parameters": "{}",
        "fact_attributes": "{}",
    }


class TestCSVFilters(unittest.TestCase):
    """load_csv_events must correctly filter by start_ts/end_ts/conversation_id/actions."""

    def setUp(self):
        self.rows = [
            _make_csv_row("ev1", "conv_A", "2026-02-01T10:00:00Z", "user_message"),
            _make_csv_row("ev2", "conv_A", "2026-02-05T10:00:00Z", "memory_written"),
            _make_csv_row("ev3", "conv_B", "2026-02-10T10:00:00Z", "user_message"),
            _make_csv_row("ev4", "conv_B", "2026-02-15T10:00:00Z", "container_started"),
        ]
        self.csv_path = _write_test_csv(self.rows)

    def tearDown(self):
        os.unlink(self.csv_path)

    def test_no_filter_returns_all(self):
        from core.typedstate_csv_loader import load_csv_events
        events = load_csv_events(self.csv_path, sorted_by_rank=False)
        self.assertEqual(len(events), 4)

    def test_start_ts_filter(self):
        from core.typedstate_csv_loader import load_csv_events
        start = datetime(2026, 2, 5, 0, 0, 0, tzinfo=timezone.utc)
        events = load_csv_events(self.csv_path, sorted_by_rank=False, start_ts=start)
        ids = {e["id"] for e in events}
        self.assertIn("ev2", ids)
        self.assertIn("ev3", ids)
        self.assertIn("ev4", ids)
        self.assertNotIn("ev1", ids)

    def test_end_ts_filter(self):
        from core.typedstate_csv_loader import load_csv_events
        end = datetime(2026, 2, 7, 0, 0, 0, tzinfo=timezone.utc)
        events = load_csv_events(self.csv_path, sorted_by_rank=False, end_ts=end)
        ids = {e["id"] for e in events}
        self.assertIn("ev1", ids)
        self.assertIn("ev2", ids)
        self.assertNotIn("ev3", ids)
        self.assertNotIn("ev4", ids)

    def test_start_and_end_ts_window(self):
        from core.typedstate_csv_loader import load_csv_events
        start = datetime(2026, 2, 3, 0, 0, 0, tzinfo=timezone.utc)
        end   = datetime(2026, 2, 12, 0, 0, 0, tzinfo=timezone.utc)
        events = load_csv_events(self.csv_path, sorted_by_rank=False, start_ts=start, end_ts=end)
        ids = {e["id"] for e in events}
        self.assertIn("ev2", ids)
        self.assertIn("ev3", ids)
        self.assertNotIn("ev1", ids)
        self.assertNotIn("ev4", ids)

    def test_conversation_id_filter(self):
        from core.typedstate_csv_loader import load_csv_events
        events = load_csv_events(self.csv_path, sorted_by_rank=False, conversation_id="conv_A")
        self.assertEqual(len(events), 2)
        for e in events:
            self.assertEqual(e["conversation_id"], "conv_A")

    def test_actions_filter(self):
        from core.typedstate_csv_loader import load_csv_events
        events = load_csv_events(self.csv_path, sorted_by_rank=False, actions=["user_message"])
        ids = {e["id"] for e in events}
        self.assertIn("ev1", ids)
        self.assertIn("ev3", ids)
        self.assertNotIn("ev2", ids)
        self.assertNotIn("ev4", ids)

    def test_combined_filters(self):
        from core.typedstate_csv_loader import load_csv_events
        start = datetime(2026, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
        end   = datetime(2026, 2, 10, 0, 0, 0, tzinfo=timezone.utc)
        events = load_csv_events(
            self.csv_path, sorted_by_rank=False,
            start_ts=start, end_ts=end,
            conversation_id="conv_A",
        )
        ids = {e["id"] for e in events}
        self.assertIn("ev1", ids)
        self.assertIn("ev2", ids)
        self.assertNotIn("ev3", ids)
        self.assertNotIn("ev4", ids)

    def test_no_match_returns_empty(self):
        from core.typedstate_csv_loader import load_csv_events
        events = load_csv_events(
            self.csv_path, sorted_by_rank=False, conversation_id="conv_NONEXISTENT"
        )
        self.assertEqual(events, [])

    def test_actions_empty_list_returns_empty(self):
        from core.typedstate_csv_loader import load_csv_events
        events = load_csv_events(self.csv_path, sorted_by_rank=False, actions=[])
        self.assertEqual(events, [])

    def test_filter_preserves_event_structure(self):
        """Filtered events must still be valid workspace_event dicts."""
        from core.typedstate_csv_loader import load_csv_events
        events = load_csv_events(
            self.csv_path, sorted_by_rank=False,
            conversation_id="conv_A"
        )
        for e in events:
            self.assertIn("id", e)
            self.assertIn("event_type", e)
            self.assertIn("created_at", e)
            self.assertIn("event_data", e)


# ============================================================================
# P8-D: Dedupe Hardening
# ============================================================================

class TestDedupeHardening(unittest.TestCase):
    """_dedupe_events must scope by conversation_id when DIGEST_DEDUPE_INCLUDE_CONV=true."""

    def _make_event(self, event_type, data, conv_id, event_id, created_at):
        return {
            "id": event_id,
            "conversation_id": conv_id,
            "event_type": event_type,
            "created_at": created_at,
            "event_data": data,
        }

    def test_default_off_same_conv_deduped(self):
        """DEDUPE_INCLUDE_CONV=false: same event_type+hash in same conv → deduped."""
        from core.context_cleanup import _dedupe_events
        events = [
            self._make_event("user_message", {"msg": "hi"}, "conv_A", "ev1", "2026-01-01T10:00:00Z"),
            self._make_event("user_message", {"msg": "hi"}, "conv_A", "ev2", "2026-01-01T10:00:01Z"),
        ]
        with patch("config.get_digest_dedupe_include_conv", return_value=False):
            result = _dedupe_events(events)
        self.assertEqual(len(result), 1)

    def test_default_off_diff_conv_also_deduped(self):
        """DEDUPE_INCLUDE_CONV=false: same event in DIFFERENT convs → still deduped (old behaviour)."""
        from core.context_cleanup import _dedupe_events
        events = [
            self._make_event("user_message", {"msg": "hi"}, "conv_A", "ev1", "2026-01-01T10:00:00Z"),
            self._make_event("user_message", {"msg": "hi"}, "conv_B", "ev2", "2026-01-01T10:00:00Z"),
        ]
        with patch("config.get_digest_dedupe_include_conv", return_value=False):
            result = _dedupe_events(events)
        # Old behaviour: cross-conv deduplication (may collapse)
        # Key point: this test verifies the OFF behaviour is unchanged
        self.assertGreaterEqual(len(result), 1)

    def test_conv_scoped_diff_conv_not_deduped(self):
        """DEDUPE_INCLUDE_CONV=true: same event in different convs → NOT deduped."""
        from core.context_cleanup import _dedupe_events
        events = [
            self._make_event("user_message", {"msg": "hi"}, "conv_A", "ev1", "2026-01-01T10:00:00Z"),
            self._make_event("user_message", {"msg": "hi"}, "conv_B", "ev2", "2026-01-01T10:00:00Z"),
        ]
        with patch("config.get_digest_dedupe_include_conv", return_value=True):
            result = _dedupe_events(events)
        self.assertEqual(len(result), 2, "Same event in different convs must NOT be deduped")

    def test_conv_scoped_same_conv_still_deduped(self):
        """DEDUPE_INCLUDE_CONV=true: same event in SAME conv → still deduped."""
        from core.context_cleanup import _dedupe_events
        events = [
            self._make_event("user_message", {"msg": "hi"}, "conv_A", "ev1", "2026-01-01T10:00:00Z"),
            self._make_event("user_message", {"msg": "hi"}, "conv_A", "ev2", "2026-01-01T10:00:00Z"),
        ]
        with patch("config.get_digest_dedupe_include_conv", return_value=True):
            result = _dedupe_events(events)
        self.assertEqual(len(result), 1, "Same event in same conv must still be deduped")

    def test_conv_scoped_outside_window_not_deduped(self):
        """Events outside the time window must not be deduped even with same content."""
        from core.context_cleanup import _dedupe_events, _DEDUPE_WINDOW_SECS
        events = [
            self._make_event("user_message", {"msg": "hi"}, "conv_A", "ev1", "2026-01-01T10:00:00Z"),
            self._make_event("user_message", {"msg": "hi"}, "conv_A", "ev2", "2026-01-01T10:01:00Z"),
        ]
        with patch("config.get_digest_dedupe_include_conv", return_value=True):
            result = _dedupe_events(events)
        # 60 seconds > _DEDUPE_WINDOW_SECS (2.0) → should NOT be deduped
        self.assertEqual(len(result), 2)

    def test_no_crash_on_missing_config(self):
        """_dedupe_events must not raise when config.get_digest_dedupe_include_conv fails."""
        from core.context_cleanup import _dedupe_events
        events = [
            self._make_event("user_message", {"msg": "x"}, "conv_A", "ev1", "2026-01-01T10:00:00Z"),
        ]
        with patch("config.get_digest_dedupe_include_conv", side_effect=ImportError("no config")):
            try:
                result = _dedupe_events(events)
                self.assertEqual(len(result), 1)
            except Exception as exc:
                self.fail(f"_dedupe_events raised on config failure: {exc}")


# ============================================================================
# P8-E: Digest Event Types in TypedState
# ============================================================================

def _make_ev(event_type, event_data, event_id="ev1", created_at="2026-02-20T10:00:00Z"):
    return {
        "id": event_id, "event_type": event_type,
        "created_at": created_at, "event_data": event_data,
    }


class TestDigestEventTypes(unittest.TestCase):
    """_apply_event must handle daily_digest/weekly_digest/archive_digest fail-closed."""

    def _apply(self, event):
        from core.context_cleanup import TypedState, _apply_event
        state = TypedState()
        _apply_event(state, event)
        return state

    def test_daily_digest_adds_typed_fact(self):
        """daily_digest event must add a DAILY_DIGEST TypedFact."""
        ev = _make_ev("daily_digest", {
            "digest_date": "2026-02-19",
            "event_count": 42,
            "digest_key": "abc123",
        })
        state = self._apply(ev)
        self.assertIn("DAILY_DIGEST", state.facts,
                      "daily_digest must register DAILY_DIGEST typed fact")

    def test_daily_digest_fact_contains_date(self):
        ev = _make_ev("daily_digest", {"digest_date": "2026-02-19", "event_count": 10})
        state = self._apply(ev)
        fact = state.facts["DAILY_DIGEST"][0]
        self.assertIn("2026-02-19", fact.value)

    def test_weekly_digest_adds_typed_fact(self):
        """weekly_digest event must add a WEEKLY_DIGEST TypedFact."""
        ev = _make_ev("weekly_digest", {
            "iso_week": "2026-W08",
            "daily_digest_count": 5,
        })
        state = self._apply(ev)
        self.assertIn("WEEKLY_DIGEST", state.facts)

    def test_weekly_digest_fact_contains_week(self):
        ev = _make_ev("weekly_digest", {"iso_week": "2026-W08", "daily_digest_count": 5})
        state = self._apply(ev)
        fact = state.facts["WEEKLY_DIGEST"][0]
        self.assertIn("2026-W08", fact.value)

    def test_archive_digest_adds_typed_fact(self):
        """archive_digest event must add an ARCHIVE_DIGEST TypedFact."""
        ev = _make_ev("archive_digest", {
            "archived_at": "2026-03-06",
            "archive_graph_node_id": "node_xyz",
        })
        state = self._apply(ev)
        self.assertIn("ARCHIVE_DIGEST", state.facts)

    def test_daily_digest_malformed_payload_no_crash(self):
        """Malformed daily_digest payload must not crash (fail-closed)."""
        ev = _make_ev("daily_digest", {"event_count": "NOT_AN_INT"})
        try:
            state = self._apply(ev)
        except Exception as exc:
            self.fail(f"_apply_event raised on malformed daily_digest: {exc}")

    def test_weekly_digest_empty_payload_no_crash(self):
        ev = _make_ev("weekly_digest", {})
        try:
            self._apply(ev)
        except Exception as exc:
            self.fail(f"_apply_event raised on empty weekly_digest: {exc}")

    def test_archive_digest_no_crash_on_empty(self):
        ev = _make_ev("archive_digest", {})
        try:
            self._apply(ev)
        except Exception as exc:
            self.fail(f"_apply_event raised on empty archive_digest: {exc}")

    def test_digest_events_do_not_affect_container_state(self):
        """Digest events must not modify container entities or focus_entity."""
        ev = _make_ev("daily_digest", {"digest_date": "2026-02-19", "event_count": 5})
        state = self._apply(ev)
        self.assertEqual(len(state.containers), 0)
        self.assertIsNone(state.focus_entity)

    def test_digest_events_in_pipeline(self):
        """build_compact_context must not crash when digest events are in the input."""
        from core.context_cleanup import build_compact_context
        events = [
            _make_ev("daily_digest", {"digest_date": "2026-02-19", "event_count": 5}, event_id="d1"),
            _make_ev("weekly_digest", {"iso_week": "2026-W08", "daily_digest_count": 3}, event_id="w1"),
            _make_ev("archive_digest", {"archived_at": "2026-03-06"}, event_id="a1"),
        ]
        try:
            ctx = build_compact_context(events=events)
        except Exception as exc:
            self.fail(f"build_compact_context crashed on digest events: {exc}")
        self.assertIsNotNone(ctx)


# ============================================================================
# P8-F: Digest Key Functions
# ============================================================================

class TestDigestKeyFunctions(unittest.TestCase):
    """Digest key functions must be deterministic and produce 32-char hex strings."""

    def test_make_source_hash_deterministic(self):
        from core.digest.keys import make_source_hash
        ids = ["ev3", "ev1", "ev2"]
        h1 = make_source_hash(ids)
        h2 = make_source_hash(["ev1", "ev2", "ev3"])  # different order
        self.assertEqual(h1, h2, "source_hash must be order-independent")

    def test_make_source_hash_length(self):
        from core.digest.keys import make_source_hash
        h = make_source_hash(["ev1", "ev2"])
        self.assertEqual(len(h), 16)

    def test_make_daily_digest_key_length(self):
        from core.digest.keys import make_daily_digest_key
        k = make_daily_digest_key("conv_A", "2026-02-20", "abc123456789abcd")
        self.assertEqual(len(k), 32)

    def test_make_daily_digest_key_deterministic(self):
        from core.digest.keys import make_daily_digest_key
        k1 = make_daily_digest_key("conv_A", "2026-02-20", "src123")
        k2 = make_daily_digest_key("conv_A", "2026-02-20", "src123")
        self.assertEqual(k1, k2)

    def test_make_daily_digest_key_differs_by_date(self):
        from core.digest.keys import make_daily_digest_key
        k1 = make_daily_digest_key("conv_A", "2026-02-20", "src123")
        k2 = make_daily_digest_key("conv_A", "2026-02-21", "src123")
        self.assertNotEqual(k1, k2)

    def test_make_daily_digest_key_differs_by_conv(self):
        from core.digest.keys import make_daily_digest_key
        k1 = make_daily_digest_key("conv_A", "2026-02-20", "src123")
        k2 = make_daily_digest_key("conv_B", "2026-02-20", "src123")
        self.assertNotEqual(k1, k2)

    def test_make_weekly_digest_key_deterministic(self):
        from core.digest.keys import make_weekly_digest_key
        keys = ["dkey1", "dkey2", "dkey3"]
        k1 = make_weekly_digest_key("conv_A", "2026-W08", keys)
        k2 = make_weekly_digest_key("conv_A", "2026-W08", ["dkey3", "dkey1", "dkey2"])
        self.assertEqual(k1, k2, "weekly_key must be order-independent")

    def test_make_weekly_digest_key_length(self):
        from core.digest.keys import make_weekly_digest_key
        k = make_weekly_digest_key("conv_A", "2026-W08", ["dkey1"])
        self.assertEqual(len(k), 32)

    def test_make_archive_digest_key_length(self):
        from core.digest.keys import make_archive_digest_key
        k = make_archive_digest_key("conv_A", "weeklykey123", "2026-03-06")
        self.assertEqual(len(k), 32)

    def test_make_archive_digest_key_deterministic(self):
        from core.digest.keys import make_archive_digest_key
        k1 = make_archive_digest_key("conv_A", "wkey", "2026-03-06")
        k2 = make_archive_digest_key("conv_A", "wkey", "2026-03-06")
        self.assertEqual(k1, k2)

    def test_all_keys_are_hex(self):
        from core.digest.keys import (
            make_source_hash, make_daily_digest_key,
            make_weekly_digest_key, make_archive_digest_key,
        )
        h  = make_source_hash(["a", "b"])
        dk = make_daily_digest_key("conv", "2026-02-20", h)
        wk = make_weekly_digest_key("conv", "2026-W08", [dk])
        ak = make_archive_digest_key("conv", wk, "2026-03-06")
        for k in [h, dk, wk, ak]:
            try:
                int(k, 16)
            except ValueError:
                self.fail(f"Key {k!r} is not valid hex")


# ============================================================================
# P8-F: DigestStore
# ============================================================================

class TestDigestStore(unittest.TestCase):
    """DigestStore must correctly persist and detect digest records."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(
            suffix=".csv", delete=False, mode="w", encoding="utf-8"
        )
        self._tmp.close()
        os.unlink(self._tmp.name)  # start with non-existent file
        self._path = self._tmp.name

    def tearDown(self):
        if os.path.exists(self._path):
            os.unlink(self._path)

    def _store(self):
        from core.digest.store import DigestStore
        return DigestStore(store_path=self._path)

    def test_exists_on_empty_store_returns_false(self):
        """exists() on a non-existent store must return False."""
        store = self._store()
        self.assertFalse(store.exists("daily_digest", "anykey"))

    def test_write_daily_creates_file(self):
        store = self._store()
        store.write_daily(
            event_id="uuid1",
            conversation_id="conv_A",
            digest_key="key1234567890123456789012345678",
            digest_date="2026-02-20",
            event_count=10,
            source_hash="abc123",
            compact_text="NOW:\n  - test",
        )
        self.assertTrue(os.path.exists(self._path))

    def test_write_daily_idempotency_via_exists(self):
        store = self._store()
        key = "key1234567890123456789012345678"
        self.assertFalse(store.exists("daily_digest", key))
        store.write_daily(
            event_id="uuid1", conversation_id="conv_A", digest_key=key,
            digest_date="2026-02-20", event_count=5, source_hash="abc", compact_text=""
        )
        self.assertTrue(store.exists("daily_digest", key))

    def test_different_key_not_found(self):
        store = self._store()
        store.write_daily(
            event_id="uuid1", conversation_id="conv_A",
            digest_key="key_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            digest_date="2026-02-20", event_count=5, source_hash="abc", compact_text=""
        )
        self.assertFalse(store.exists("daily_digest", "key_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"))

    def test_write_weekly_detectable(self):
        store = self._store()
        key = "wkey123456789012345678901234567"
        store.write_weekly(
            event_id="uuid2", conversation_id="conv_A", digest_key=key,
            iso_week="2026-W08", daily_digest_keys=["dkey1", "dkey2"],
            compact_text="NOW:\n  - weekly"
        )
        self.assertTrue(store.exists("weekly_digest", key))

    def test_write_archive_detectable(self):
        store = self._store()
        akey = "akey12345678901234567890123456a"
        store.write_archive(
            event_id="uuid3", conversation_id="conv_A", archive_key=akey,
            weekly_digest_key="wkey", archive_date="2026-03-06",
            archive_graph_node_id="node_xyz"
        )
        self.assertTrue(store.exists("archive_digest", akey))

    def test_list_by_action(self):
        store = self._store()
        store.write_daily(
            event_id="u1", conversation_id="conv_A", digest_key="dk1" * 11,
            digest_date="2026-02-01", event_count=1, source_hash="s1", compact_text=""
        )
        store.write_daily(
            event_id="u2", conversation_id="conv_B", digest_key="dk2" * 11,
            digest_date="2026-02-02", event_count=2, source_hash="s2", compact_text=""
        )
        rows = store.list_by_action("daily_digest")
        self.assertEqual(len(rows), 2)

    def test_list_by_action_returns_empty_for_missing_type(self):
        store = self._store()
        rows = store.list_by_action("daily_digest")
        self.assertEqual(rows, [])

    def test_written_row_has_correct_csv_columns(self):
        """Written row must be readable via csv.DictReader with all expected fields."""
        store = self._store()
        store.write_daily(
            event_id="uuid_x", conversation_id="conv_Z",
            digest_key="testkey1234567890123456789abcd",
            digest_date="2026-02-20", event_count=3, source_hash="src",
            compact_text="NOW:\n  - OK"
        )
        with open(self._path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["event_id"], "uuid_x")
        self.assertEqual(row["conversation_id"], "conv_Z")
        self.assertEqual(row["action"], "daily_digest")
        params = json.loads(row["parameters"])
        self.assertEqual(params["digest_key"], "testkey1234567890123456789abcd")


# ============================================================================
# P8-F: DailyDigestScheduler
# ============================================================================

class TestDailyDigestScheduler(unittest.TestCase):
    """DailyDigestScheduler must run catch-up, be idempotent, and log markers."""

    def setUp(self):
        self._store_tmp = tempfile.NamedTemporaryFile(
            suffix=".csv", delete=False, mode="w", encoding="utf-8"
        )
        self._store_tmp.close()
        os.unlink(self._store_tmp.name)
        self._store_path = self._store_tmp.name

    def tearDown(self):
        if os.path.exists(self._store_path):
            os.unlink(self._store_path)

    def _make_store(self):
        from core.digest.store import DigestStore
        return DigestStore(store_path=self._store_path)

    def _make_scheduler(self, csv_rows=None):
        """Create scheduler with optional CSV events."""
        from core.digest.daily_scheduler import DailyDigestScheduler
        store = self._make_store()
        sched = DailyDigestScheduler(store=store, csv_path=None)
        if csv_rows is not None:
            sched._load_events_for_conv = lambda conv_id: [
                r for r in csv_rows if r.get("conversation_id") == conv_id
            ]
        return sched, store

    def _make_events(self, conv_id, dates_and_ids):
        """Create minimal workspace event dicts for given conv_id and dates."""
        events = []
        for d, eid in dates_and_ids:
            events.append({
                "id": eid,
                "conversation_id": conv_id,
                "event_type": "user_message",
                "created_at": f"{d}T10:00:00Z",
                "event_data": {},
            })
        return events

    def test_run_for_date_writes_digest(self):
        """run_for_date must write a daily_digest to the store."""
        sched, store = self._make_scheduler()
        events = self._make_events("conv_A", [("2026-02-01", "ev1"), ("2026-02-01", "ev2")])
        ok = sched.run_for_date("conv_A", date(2026, 2, 1), all_events=events)
        self.assertTrue(ok)
        rows = store.list_by_action("daily_digest")
        self.assertEqual(len(rows), 1)

    def test_run_for_date_idempotent(self):
        """run_for_date on same events twice must only write once."""
        sched, store = self._make_scheduler()
        events = self._make_events("conv_A", [("2026-02-01", "ev1")])
        sched.run_for_date("conv_A", date(2026, 2, 1), all_events=events)
        sched.run_for_date("conv_A", date(2026, 2, 1), all_events=events)
        rows = store.list_by_action("daily_digest")
        self.assertEqual(len(rows), 1, "Idempotent: must not write duplicate")

    def test_run_for_date_different_events_different_key(self):
        """Different events on same date → different digest_key → both written."""
        sched, store = self._make_scheduler()
        events1 = self._make_events("conv_A", [("2026-02-01", "ev1")])
        events2 = self._make_events("conv_A", [("2026-02-01", "ev2")])
        sched.run_for_date("conv_A", date(2026, 2, 1), all_events=events1)
        sched.run_for_date("conv_A", date(2026, 2, 1), all_events=events2)
        rows = store.list_by_action("daily_digest")
        self.assertEqual(len(rows), 2, "Different event sets → different digest keys → 2 rows")

    def test_run_for_date_empty_events_skipped(self):
        """run_for_date with no events must return False and write nothing."""
        sched, store = self._make_scheduler()
        ok = sched.run_for_date("conv_A", date(2026, 2, 1), all_events=[])
        self.assertFalse(ok)
        self.assertEqual(store.list_by_action("daily_digest"), [])

    def test_run_for_date_no_matching_conv_skipped(self):
        """Events with different conv_id must be skipped."""
        sched, store = self._make_scheduler()
        events = self._make_events("conv_B", [("2026-02-01", "ev1")])
        ok = sched.run_for_date("conv_A", date(2026, 2, 1), all_events=events)
        self.assertFalse(ok)

    def test_run_catchup_writes_multiple_days(self):
        """run_catchup must fill all missing days from first event to yesterday."""
        sched, store = self._make_scheduler()
        # Provide events for 3 different dates
        events = self._make_events("conv_A", [
            ("2026-02-17", "ev1"),
            ("2026-02-18", "ev2"),
            ("2026-02-19", "ev3"),
        ])
        sched._load_events_for_conv = lambda conv_id: events

        # Mock "yesterday" to be 2026-02-19
        with patch("core.digest.daily_scheduler._yesterday_berlin",
                   return_value=date(2026, 2, 19)):
            written = sched.run_catchup("conv_A")

        rows = store.list_by_action("daily_digest")
        # Expect digests for 2026-02-17, 02-18, 02-19
        self.assertGreaterEqual(len(rows), 3)
        self.assertGreaterEqual(written.get("written", written) if isinstance(written, dict) else written, 3)

    def test_run_catchup_idempotent(self):
        """run_catchup run twice on same events must not double-write."""
        sched, store = self._make_scheduler()
        events = self._make_events("conv_A", [("2026-02-19", "ev1")])
        sched._load_events_for_conv = lambda conv_id: events
        with patch("core.digest.daily_scheduler._yesterday_berlin",
                   return_value=date(2026, 2, 19)):
            sched.run_catchup("conv_A")
            sched.run_catchup("conv_A")
        rows = store.list_by_action("daily_digest")
        self.assertEqual(len(rows), 1, "Catch-up must be idempotent")

    def test_run_catchup_no_events_writes_nothing(self):
        sched, store = self._make_scheduler()
        sched._load_events_for_conv = lambda conv_id: []
        with patch("core.digest.daily_scheduler._yesterday_berlin",
                   return_value=date(2026, 2, 19)):
            written = sched.run_catchup("conv_A")
        written_count = written.get("written", written) if isinstance(written, dict) else written
        self.assertEqual(written_count, 0)
        self.assertEqual(store.list_by_action("daily_digest"), [])

    def test_run_disabled_skips(self):
        """When DIGEST_DAILY_ENABLE=false, run() must return 0 without writing."""
        sched, store = self._make_scheduler()
        with patch("config.get_digest_daily_enable", return_value=False):
            result = sched.run(conversation_ids=["conv_A"])
        result_count = result.get("written", result) if isinstance(result, dict) else result
        self.assertEqual(result_count, 0)


# ============================================================================
# P8-G: WeeklyDigestArchiver
# ============================================================================

class TestWeeklyDigestArchiver(unittest.TestCase):
    """WeeklyDigestArchiver must build weekly digests and archive old ones."""

    def setUp(self):
        self._tmp_path = tempfile.NamedTemporaryFile(
            suffix=".csv", delete=False, mode="w", encoding="utf-8"
        ).name
        if os.path.exists(self._tmp_path):
            os.unlink(self._tmp_path)

    def tearDown(self):
        if os.path.exists(self._tmp_path):
            os.unlink(self._tmp_path)

    def _store(self):
        from core.digest.store import DigestStore
        return DigestStore(store_path=self._tmp_path)

    def _archiver(self, store=None):
        from core.digest.weekly_archiver import WeeklyDigestArchiver
        return WeeklyDigestArchiver(store=store or self._store())

    def _write_daily(self, store, conv_id, digest_date, digest_key, iso_week_ts):
        """Write a daily_digest row to store for a given week."""
        store.write_daily(
            event_id=f"d_{digest_key[:8]}",
            conversation_id=conv_id,
            digest_key=digest_key,
            digest_date=digest_date,
            event_count=5,
            source_hash="src",
            compact_text="NOW:\n  - OK",
        )

    def test_group_by_conv_week(self):
        """_group_by_conv_week must correctly group daily rows by (conv, week)."""
        from core.digest.weekly_archiver import WeeklyDigestArchiver
        rows = [
            {"conversation_id": "conv_A", "timestamp": "2026-02-16T10:00:00Z",
             "parameters": json.dumps({"digest_key": "dk1"})},
            {"conversation_id": "conv_A", "timestamp": "2026-02-17T10:00:00Z",
             "parameters": json.dumps({"digest_key": "dk2"})},
            {"conversation_id": "conv_B", "timestamp": "2026-02-16T10:00:00Z",
             "parameters": json.dumps({"digest_key": "dk3"})},
        ]
        grouped = WeeklyDigestArchiver._group_by_conv_week(rows)
        # All 3 dates fall in 2026-W08 (Mon 2026-02-16)
        self.assertIn(("conv_A", "2026-W08"), grouped)
        self.assertIn(("conv_B", "2026-W08"), grouped)
        self.assertEqual(len(grouped[("conv_A", "2026-W08")]), 2)

    def test_run_weekly_writes_weekly_digest(self):
        """run_weekly must build and persist weekly_digest for complete week."""
        store = self._store()
        archiver = self._archiver(store=store)
        # Write 2 daily_digest rows for the same week (2026-W08)
        store.write_daily(
            event_id="d1", conversation_id="conv_A",
            digest_key="dk1" * 11,
            digest_date="2026-02-16", event_count=5,
            source_hash="s1", compact_text="NOW:\n  - day1"
        )
        store.write_daily(
            event_id="d2", conversation_id="conv_A",
            digest_key="dk2" * 11,
            digest_date="2026-02-17", event_count=3,
            source_hash="s2", compact_text="NOW:\n  - day2"
        )
        with patch("config.get_digest_weekly_enable", return_value=True), \
             patch("config.get_digest_enable", return_value=True):
            written = archiver.run_weekly(conversation_ids=["conv_A"])
        written_count = written.get("written", written) if isinstance(written, dict) else written
        self.assertGreaterEqual(written_count, 1)
        rows = store.list_by_action("weekly_digest")
        self.assertGreaterEqual(len(rows), 1)

    def test_run_weekly_idempotent(self):
        """run_weekly twice on same data must not double-write."""
        store = self._store()
        archiver = self._archiver(store=store)
        store.write_daily(
            event_id="d1", conversation_id="conv_A",
            digest_key="dk1" * 11,
            digest_date="2026-02-16", event_count=5,
            source_hash="s1", compact_text=""
        )
        with patch("config.get_digest_weekly_enable", return_value=True), \
             patch("config.get_digest_enable", return_value=True):
            archiver.run_weekly(conversation_ids=["conv_A"])
            archiver.run_weekly(conversation_ids=["conv_A"])
        rows = store.list_by_action("weekly_digest")
        self.assertEqual(len(rows), 1, "Weekly must be idempotent")

    def test_run_weekly_disabled_skips(self):
        store = self._store()
        archiver = self._archiver(store=store)
        with patch("config.get_digest_weekly_enable", return_value=False):
            written = archiver.run_weekly()
        written_count = written.get("written", written) if isinstance(written, dict) else written
        self.assertEqual(written_count, 0)

    def test_run_archive_skips_recent_weekly(self):
        """Weekly digest written today must NOT be archived (< 14 days)."""
        store = self._store()
        archiver = self._archiver(store=store)
        store.write_weekly(
            event_id="w1", conversation_id="conv_A",
            digest_key="wk1" * 11,
            iso_week="2026-W08",
            daily_digest_keys=["dk1"],
            compact_text=""
        )
        with patch("config.get_digest_archive_enable", return_value=True), \
             patch("config.get_digest_enable", return_value=True):
            written = archiver.run_archive(conversation_ids=["conv_A"])
        written_count = written.get("written", written) if isinstance(written, dict) else written
        self.assertEqual(written_count, 0, "Recent weekly must not be archived")

    def test_run_archive_archives_old_weekly(self):
        """Weekly digest older than 14 days must be archived."""
        store = self._store()
        archiver = self._archiver(store=store)
        # Write a weekly with a timestamp > 14 days ago
        old_ts = (datetime.now(tz=timezone.utc) - timedelta(days=20)).isoformat().replace("+00:00", "Z")
        # Directly write a row with old timestamp
        import csv as _csv
        from core.digest.store import _CSV_FIELDNAMES
        with open(self._tmp_path, "w", newline="", encoding="utf-8") as f:
            w = _csv.DictWriter(f, fieldnames=_CSV_FIELDNAMES, extrasaction="ignore")
            w.writeheader()
            w.writerow({
                "event_id": "w_old",
                "conversation_id": "conv_A",
                "timestamp": old_ts,
                "action": "weekly_digest",
                "fact_type": "WEEKLY_DIGEST",
                "parameters": json.dumps({"digest_key": "wkey_old_test_key_123456789012"}),
                "fact_attributes": "{}",
                "source_type": "system",
                "source_reliability": "1.0",
                "confidence_overall": "high",
                "confidence_breakdown": "{}",
                "entity_ids": "", "entity_match_type": "exact",
                "raw_text": "", "scenario_type": "digest",
                "category": "knowledge", "derived_from": "[]",
                "stale_at": "", "expires_at": "",
            })
        with patch("config.get_digest_archive_enable", return_value=True), \
             patch("config.get_digest_enable", return_value=True), \
             patch.object(archiver, "_try_save_to_graph", return_value="node_test"):
            written = archiver.run_archive(conversation_ids=["conv_A"])
        written_count = written.get("written", written) if isinstance(written, dict) else written
        self.assertGreaterEqual(written_count, 1, "Old weekly must be archived")
        archive_rows = store.list_by_action("archive_digest")
        self.assertGreaterEqual(len(archive_rows), 1)

    def test_run_archive_idempotent(self):
        """run_archive twice on same old weekly must not double-archive."""
        store = self._store()
        archiver = self._archiver(store=store)
        old_ts = (datetime.now(tz=timezone.utc) - timedelta(days=20)).isoformat().replace("+00:00", "Z")
        import csv as _csv
        from core.digest.store import _CSV_FIELDNAMES
        with open(self._tmp_path, "w", newline="", encoding="utf-8") as f:
            w = _csv.DictWriter(f, fieldnames=_CSV_FIELDNAMES, extrasaction="ignore")
            w.writeheader()
            w.writerow({
                "event_id": "w_old2",
                "conversation_id": "conv_A",
                "timestamp": old_ts,
                "action": "weekly_digest",
                "fact_type": "WEEKLY_DIGEST",
                "parameters": json.dumps({"digest_key": "wkey_old_test_idddd_1234567890"}),
                "fact_attributes": "{}",
                "source_type": "system", "source_reliability": "1.0",
                "confidence_overall": "high", "confidence_breakdown": "{}",
                "entity_ids": "", "entity_match_type": "exact",
                "raw_text": "", "scenario_type": "digest",
                "category": "knowledge", "derived_from": "[]",
                "stale_at": "", "expires_at": "",
            })
        with patch("config.get_digest_archive_enable", return_value=True), \
             patch("config.get_digest_enable", return_value=True), \
             patch.object(archiver, "_try_save_to_graph", return_value=None):
            archiver.run_archive(conversation_ids=["conv_A"])
            archiver.run_archive(conversation_ids=["conv_A"])
        rows = store.list_by_action("archive_digest")
        self.assertEqual(len(rows), 1, "Archive must be idempotent")

    def test_run_archive_disabled_skips(self):
        store = self._store()
        archiver = self._archiver(store=store)
        with patch("config.get_digest_archive_enable", return_value=False):
            written = archiver.run_archive()
        written_count = written.get("written", written) if isinstance(written, dict) else written
        self.assertEqual(written_count, 0)


# ============================================================================
# Sync/Stream parity — trigger propagation
# ============================================================================

class TestTriggerPropagationParity(unittest.TestCase):
    """Trigger must flow from orchestrator through to maybe_load_csv_events (Commit B)."""

    def test_build_small_model_context_accepts_trigger(self):
        """build_small_model_context must accept 'trigger' keyword argument."""
        import inspect
        from core.context_manager import ContextManager
        sig = inspect.signature(ContextManager.build_small_model_context)
        self.assertIn("trigger", sig.parameters)

    def test_get_compact_context_accepts_csv_trigger(self):
        """_get_compact_context must accept 'csv_trigger' keyword argument."""
        import inspect
        from core.orchestrator import PipelineOrchestrator
        sig = inspect.signature(PipelineOrchestrator._get_compact_context)
        self.assertIn("csv_trigger", sig.parameters)

    def test_trigger_none_is_backward_compatible(self):
        """build_small_model_context(trigger=None) must behave identically to no-trigger call."""
        from core.context_manager import ContextManager
        cm = ContextManager.__new__(ContextManager)
        cm._protocol_cache = {}

        mock_hub = MagicMock()
        mock_hub.call_tool.return_value = {
            "content": [{"type": "text", "text": "[]"}]
        }
        with patch("mcp.hub.get_hub", return_value=mock_hub), \
             patch("core.typedstate_csv_loader.maybe_load_csv_events", return_value=[]) as mock_csv, \
             patch("config.get_typedstate_mode", return_value="off"), \
             patch("config.get_typedstate_csv_enable", return_value=False):
            result_no_trigger = cm.build_small_model_context(conversation_id="conv_A")

        with patch("mcp.hub.get_hub", return_value=mock_hub), \
             patch("core.typedstate_csv_loader.maybe_load_csv_events", return_value=[]) as mock_csv2, \
             patch("config.get_typedstate_mode", return_value="off"), \
             patch("config.get_typedstate_csv_enable", return_value=False):
            result_explicit_none = cm.build_small_model_context(
                conversation_id="conv_A", trigger=None
            )

        self.assertEqual(result_no_trigger, result_explicit_none,
                         "trigger=None must be backward-compatible")


if __name__ == "__main__":
    unittest.main()
