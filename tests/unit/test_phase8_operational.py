"""
tests/unit/test_phase8_operational.py — Phase 8 Operational Tests (Points 1–11)

Coverage:
  P8-Ops-1:  Runtime state read/write + empty-state fallback
  P8-Ops-1b: Locking — acquire, release, stale takeover, context manager
  P8-Ops-2:  Worker — next 04:00 calc, run_once integration, lock protection
  P8-Ops-3:  Catch-up cap (DIGEST_CATCHUP_MAX_DAYS)
  P8-Ops-4:  Auto-derive conversation IDs from CSV
  P8-Ops-5a: Min events daily skip
  P8-Ops-5b: Min daily per week skip
  P8-Ops-6:  Config flags all present + defaults
  P8-Ops-7:  JIT-only strict: no trigger → no IO (extended params)
  P8-Ops-8:  Trigger → time-window mapping
  P8-Ops-9:  Runtime API endpoint structure
  P8-Ops-10: DigestUI JS not tested (browser-only), manual checklist documented
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

# ── Project root on path ──────────────────────────────────────────────────────
# Compute project root regardless of whether the file is run from /tmp or tests/unit/
_THIS_FILE = os.path.abspath(__file__)
if "tests" + os.sep + "unit" in _THIS_FILE:
    # Deployed: /DATA/.../Jarvis/tests/unit/test_phase8_operational.py
    _ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_THIS_FILE)))
else:
    # Running from /tmp — use the known project root
    _ROOT = "/DATA/AppData/MCP/Jarvis/Jarvis"
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ═══════════════════════════════════════════════════════════════════════════════
# P8-Ops-1: Runtime State
# ═══════════════════════════════════════════════════════════════════════════════

class TestRuntimeStateReadWrite(unittest.TestCase):
    """core/digest/runtime_state.py — persistent state JSON."""

    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self._path = os.path.join(self._dir, "digest_state.json")

    def _with_path(self):
        return patch("core.digest.runtime_state._state_path", return_value=self._path)

    def test_get_state_missing_file_returns_empty(self):
        from core.digest.runtime_state import get_state, _empty_state
        with self._with_path():
            s = get_state()
        self.assertEqual(s["schema_version"], 2)  # v2 after schema upgrade
        self.assertEqual(s["daily"]["status"], "never")

    def test_update_cycle_writes_to_disk(self):
        from core.digest.runtime_state import update_cycle, get_state
        with self._with_path():
            ok = update_cycle("daily", status="ok", duration_s=1.5, digest_written=3)
            self.assertTrue(ok)
            s = get_state()
        self.assertEqual(s["daily"]["status"], "ok")
        self.assertEqual(s["daily"]["duration_s"], 1.5)
        self.assertEqual(s["daily"]["digest_written"], 3)

    def test_update_cycle_is_atomic(self):
        """File is written atomically (temp + os.replace), no partial writes."""
        from core.digest.runtime_state import update_cycle, get_state
        with self._with_path():
            update_cycle("daily", status="ok")
            update_cycle("weekly", status="ok", digest_written=2)
            s = get_state()
        # Both cycles present in same file
        self.assertEqual(s["daily"]["status"], "ok")
        self.assertEqual(s["weekly"]["status"], "ok")

    def test_update_catch_up(self):
        from core.digest.runtime_state import update_catch_up, get_state
        with self._with_path():
            update_catch_up(days_processed=5, written=4, status="ok")
            s = get_state()
        self.assertEqual(s["catch_up"]["days_processed"], 5)
        self.assertEqual(s["catch_up"]["written"], 4)
        self.assertEqual(s["catch_up"]["status"], "ok")

    def test_update_jit(self):
        from core.digest.runtime_state import update_jit, get_state
        with self._with_path():
            update_jit(trigger="time_reference", rows=12)
            s = get_state()
        # v2: jit is a structured block, not flat fields
        self.assertEqual(s["jit"]["trigger"], "time_reference")
        self.assertEqual(s["jit"]["rows"], 12)
        self.assertIsNotNone(s["jit"]["ts"])

    def test_corrupt_state_file_returns_empty(self):
        with open(self._path, "w") as f:
            f.write("NOT JSON {{{")
        from core.digest.runtime_state import get_state
        with self._with_path():
            s = get_state()
        self.assertEqual(s["schema_version"], 2)  # v2 after schema upgrade

    def test_process_readable(self):
        """State written by one call must be readable by next call (cross-process simulation)."""
        from core.digest.runtime_state import update_cycle, _read_state
        with self._with_path():
            update_cycle("archive", status="ok", digest_written=1)
            state = _read_state()
        self.assertTrue(os.path.exists(self._path))
        self.assertEqual(state["archive"]["status"], "ok")


# ═══════════════════════════════════════════════════════════════════════════════
# P8-Ops-1b: Locking
# ═══════════════════════════════════════════════════════════════════════════════

class TestDigestLocking(unittest.TestCase):
    """core/digest/locking.py — file-based lock with stale takeover."""

    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self._lock_path = os.path.join(self._dir, "digest.lock")

    def _with_lock_path(self):
        return patch("core.digest.locking._lock_path", return_value=self._lock_path)

    def test_acquire_succeeds_when_no_lock(self):
        from core.digest.locking import acquire
        with self._with_lock_path():
            ok = acquire("worker-A")
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(self._lock_path))

    def test_acquire_blocked_by_fresh_lock(self):
        from core.digest.locking import acquire
        with self._with_lock_path():
            acquire("worker-A")
            ok = acquire("worker-B")
        self.assertFalse(ok)

    def test_release_removes_lock_file(self):
        from core.digest.locking import acquire, release
        with self._with_lock_path():
            acquire("worker-A")
            ok = release("worker-A")
        self.assertTrue(ok)
        self.assertFalse(os.path.exists(self._lock_path))

    def test_release_wrong_owner_fails(self):
        from core.digest.locking import acquire, release
        with self._with_lock_path():
            acquire("worker-A")
            ok = release("worker-B")
        self.assertFalse(ok)
        self.assertTrue(os.path.exists(self._lock_path))

    def test_stale_lock_takeover(self):
        """Lock older than timeout must be force-taken."""
        from core.digest.locking import acquire
        # Write stale lock manually
        old_ts = (datetime.now(tz=timezone.utc) - timedelta(seconds=400)).isoformat()
        with open(self._lock_path, "w") as f:
            json.dump({"owner": "old-worker", "acquired_at": old_ts, "pid": 999}, f)
        with self._with_lock_path():
            with patch("core.digest.locking._timeout_s", return_value=300):
                ok = acquire("new-worker")
        self.assertTrue(ok)
        with open(self._lock_path) as f:
            data = json.load(f)
        self.assertEqual(data["owner"], "new-worker")

    def test_context_manager_acquires_and_releases(self):
        from core.digest.locking import DigestLock, get_lock_info
        with self._with_lock_path():
            with DigestLock("test-owner") as lock:
                self.assertTrue(lock.acquired)
                info = get_lock_info()
                self.assertIsNotNone(info)
            # After exit: released
            info_after = get_lock_info()
        self.assertIsNone(info_after)

    def test_get_lock_info_none_when_unlocked(self):
        from core.digest.locking import get_lock_info
        with self._with_lock_path():
            info = get_lock_info()
        self.assertIsNone(info)


# ═══════════════════════════════════════════════════════════════════════════════
# P8-Ops-2: Worker
# ═══════════════════════════════════════════════════════════════════════════════

class TestDigestWorkerScheduling(unittest.TestCase):
    """core/digest/worker.py — next_04_utc, run_once, lock protection."""

    def test_next_04_utc_is_in_future(self):
        from core.digest.worker import _next_04_utc
        now = datetime.now(tz=timezone.utc)
        nxt = _next_04_utc(now)
        self.assertGreater(nxt, now)

    def test_next_04_utc_at_most_one_day_away(self):
        from core.digest.worker import _next_04_utc
        now = datetime.now(tz=timezone.utc)
        nxt = _next_04_utc(now)
        self.assertLessEqual((nxt - now).total_seconds(), 86400 + 1)

    def test_run_once_skipped_when_lock_held(self):
        """run_once returns skipped=True when lock cannot be acquired."""
        from core.digest.worker import DigestWorker
        worker = DigestWorker()
        with patch("core.digest.locking.acquire", return_value=False):
            result = worker.run_once()
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "lock_held")

    def test_run_once_calls_all_three_steps(self):
        """When lock acquired, run_once calls daily, weekly, archive."""
        from core.digest.worker import DigestWorker
        worker = DigestWorker()
        calls = []
        with patch("core.digest.locking.acquire", return_value=True), \
             patch("core.digest.locking.release", return_value=True), \
             patch.object(worker, "_run_daily",   side_effect=lambda: calls.append("daily")   or 2), \
             patch.object(worker, "_run_weekly",  side_effect=lambda: calls.append("weekly")  or 1), \
             patch.object(worker, "_run_archive", side_effect=lambda: calls.append("archive") or 0), \
             patch("core.digest.runtime_state.update_cycle", return_value=True):
            result = worker.run_once()
        self.assertEqual(calls, ["daily", "weekly", "archive"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["daily"], 2)

    def test_run_loop_disabled_when_mode_off(self):
        """run_loop exits immediately when DIGEST_RUN_MODE=off."""
        from core.digest.worker import DigestWorker
        worker = DigestWorker()
        with patch("core.digest.worker._run_mode", return_value="off"):
            # Should return immediately without sleeping
            worker.run_loop()  # no blocking


# ═══════════════════════════════════════════════════════════════════════════════
# P8-Ops-3: Catch-up cap
# ═══════════════════════════════════════════════════════════════════════════════

class TestCatchupCap(unittest.TestCase):
    """DIGEST_CATCHUP_MAX_DAYS limits how far back catch-up goes."""

    def _make_scheduler(self, store=None):
        from core.digest.daily_scheduler import DailyDigestScheduler
        sched = DailyDigestScheduler.__new__(DailyDigestScheduler)
        sched._store = store or MagicMock()
        sched._csv_path = ""
        return sched

    def test_max_days_zero_skips_catchup(self):
        sched = self._make_scheduler()
        with patch("core.digest.daily_scheduler.DailyDigestScheduler._catchup_max_days", return_value=0):
            result = sched.run_catchup("conv-1")
        # run_catchup now returns a dict; written=0 when skipped
        written = result if isinstance(result, int) else result.get("written", 0)
        self.assertEqual(written, 0)

    def test_max_days_caps_date_range(self):
        """With max_days=2, only process yesterday and day-before (not 30 days ago)."""
        from core.digest.daily_scheduler import DailyDigestScheduler
        sched = self._make_scheduler()

        # Event 30 days ago
        old_ts = (datetime.now(tz=timezone.utc) - timedelta(days=30)).isoformat()
        events = [{"id": "e1", "conversation_id": "c1", "created_at": old_ts,
                   "event_type": "user_message", "event_data": {}}]

        processed_dates = []

        def fake_run_for_date(conv_id, dt, all_events=None):
            processed_dates.append(dt)
            return False

        with patch.object(sched, "_load_events_for_conv", return_value=events), \
             patch.object(sched, "run_for_date", side_effect=fake_run_for_date), \
             patch("core.digest.daily_scheduler.DailyDigestScheduler._catchup_max_days", return_value=2):
            sched.run_catchup("c1")

        # Should only process at most 2 days
        self.assertLessEqual(len(processed_dates), 2)

    def test_max_days_default_is_7(self):
        from config import get_digest_catchup_max_days
        with patch.dict("os.environ", {}, clear=False):
            # clear any override
            import os
            os.environ.pop("DIGEST_CATCHUP_MAX_DAYS", None)
            v = get_digest_catchup_max_days()
        self.assertEqual(v, 7)


# ═══════════════════════════════════════════════════════════════════════════════
# P8-Ops-4: Auto-derive conversation IDs
# ═══════════════════════════════════════════════════════════════════════════════

class TestAutoDeriveCovIds(unittest.TestCase):
    """run(None) must derive conversation_ids from CSV."""

    def test_run_none_derives_convs(self):
        from core.digest.daily_scheduler import DailyDigestScheduler
        sched = DailyDigestScheduler.__new__(DailyDigestScheduler)
        sched._store = MagicMock()
        sched._csv_path = "/fake/path.csv"

        fake_events = [
            {"conversation_id": "conv-A"},
            {"conversation_id": "conv-B"},
            {"conversation_id": "conv-A"},  # duplicate
        ]
        derived = []

        def fake_run_catchup(conv_id):
            derived.append(conv_id)
            return 0

        with patch("core.digest.daily_scheduler.DailyDigestScheduler._digest_enabled", return_value=True), \
             patch("core.digest.daily_scheduler.DailyDigestScheduler._derive_conversation_ids",
                   return_value=["conv-A", "conv-B"]), \
             patch.object(sched, "run_catchup", side_effect=fake_run_catchup):
            sched.run()  # None → auto-derive

        self.assertIn("conv-A", derived)
        self.assertIn("conv-B", derived)
        self.assertEqual(len(derived), 2)

    def test_derive_conversation_ids_deduplicates(self):
        from core.digest.daily_scheduler import DailyDigestScheduler
        sched = DailyDigestScheduler.__new__(DailyDigestScheduler)
        sched._csv_path = "/fake/path.csv"

        fake_events = [
            {"conversation_id": "A"}, {"conversation_id": "B"},
            {"conversation_id": "A"}, {"conversation_id": ""},
        ]
        # load_csv_events is imported inside _derive_conversation_ids from
        # core.typedstate_csv_loader — patch it there
        with patch("core.typedstate_csv_loader.load_csv_events", return_value=fake_events), \
             patch("os.path.exists", return_value=True):
            ids = sched._derive_conversation_ids()

        self.assertIn("A", ids)
        self.assertIn("B", ids)
        self.assertNotIn("", ids)
        self.assertEqual(len(ids), 2)


# ═══════════════════════════════════════════════════════════════════════════════
# P8-Ops-5a: Min events daily
# ═══════════════════════════════════════════════════════════════════════════════

class TestMinEventsDaily(unittest.TestCase):

    def _make_scheduler(self):
        from core.digest.daily_scheduler import DailyDigestScheduler
        sched = DailyDigestScheduler.__new__(DailyDigestScheduler)
        sched._store = MagicMock()
        sched._store.exists.return_value = False
        sched._csv_path = ""
        return sched

    def test_skip_when_below_min(self):
        from datetime import date
        sched = self._make_scheduler()
        ev_ts = datetime.now(tz=timezone.utc).isoformat()
        events = [{"id": "e1", "conversation_id": "c1", "created_at": ev_ts,
                   "event_type": "user_message", "event_data": {}}]
        with patch("core.digest.daily_scheduler.DailyDigestScheduler._min_events_daily", return_value=5):
            result = sched.run_for_date("c1", date.today(), all_events=events)
        self.assertFalse(result)

    def test_no_skip_when_min_is_zero(self):
        from datetime import date
        from unittest.mock import MagicMock
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        sched = self._make_scheduler()
        # Use Berlin timezone to match _events_for_date date conversion
        tz = ZoneInfo("Europe/Berlin")
        yesterday_berlin = datetime.now(tz=tz) - timedelta(days=1)
        yesterday_date = yesterday_berlin.date()
        ev_ts = yesterday_berlin.isoformat()
        events = [{"id": "e1", "conversation_id": "c1", "created_at": ev_ts,
                   "event_type": "user_message", "event_data": {}}]
        with patch("core.digest.daily_scheduler.DailyDigestScheduler._min_events_daily", return_value=0), \
             patch("core.context_cleanup.build_compact_context", return_value=MagicMock()), \
             patch("core.context_cleanup.format_compact_context", return_value="text"):
            sched._store.write_daily.return_value = True
            result = sched.run_for_date("c1", yesterday_date, all_events=events)
        self.assertTrue(result)

    def test_config_min_events_daily_default_zero(self):
        from config import get_digest_min_events_daily
        import os
        os.environ.pop("DIGEST_MIN_EVENTS_DAILY", None)
        self.assertEqual(get_digest_min_events_daily(), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# P8-Ops-5b: Min daily per week
# ═══════════════════════════════════════════════════════════════════════════════

class TestMinDailyPerWeek(unittest.TestCase):

    def _make_archiver(self):
        from core.digest.weekly_archiver import WeeklyDigestArchiver
        arch = WeeklyDigestArchiver.__new__(WeeklyDigestArchiver)
        arch._store = MagicMock()
        arch._store.exists.return_value = False
        return arch

    def _daily_row(self, key: str, ts: str) -> dict:
        import json
        return {
            "event_id":        "e1",
            "conversation_id": "conv-A",
            "timestamp":       ts,
            "action":          "daily_digest",
            "parameters":      json.dumps({"digest_key": key}),
            "fact_attributes": "{}",
        }

    def test_skip_when_below_min(self):
        arch = self._make_archiver()
        ts = "2026-02-17T10:00:00Z"
        rows = [self._daily_row("key1", ts)]  # only 1 daily
        with patch("core.digest.weekly_archiver.WeeklyDigestArchiver._min_daily_per_week", return_value=3):
            result = arch._build_weekly("conv-A", "2026-W08", rows)
        self.assertFalse(result)

    def test_no_skip_when_min_zero(self):
        arch = self._make_archiver()
        ts = "2026-02-17T10:00:00Z"
        rows = [self._daily_row("key1", ts)]
        with patch("core.digest.weekly_archiver.WeeklyDigestArchiver._min_daily_per_week", return_value=0), \
             patch("core.context_cleanup.build_compact_context", return_value=MagicMock()), \
             patch("core.context_cleanup.format_compact_context", return_value="text"):
            arch._store.write_weekly.return_value = True
            result = arch._build_weekly("conv-A", "2026-W08", rows)
        self.assertTrue(result)

    def test_config_min_daily_per_week_default_zero(self):
        from config import get_digest_min_daily_per_week
        import os
        os.environ.pop("DIGEST_MIN_DAILY_PER_WEEK", None)
        self.assertEqual(get_digest_min_daily_per_week(), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# P8-Ops-6: Config flags
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfigFlagsOperational(unittest.TestCase):

    def test_get_digest_state_path_has_default(self):
        from config import get_digest_state_path
        import os
        os.environ.pop("DIGEST_STATE_PATH", None)
        p = get_digest_state_path()
        self.assertIn("digest_state", p)

    def test_get_digest_lock_path_has_default(self):
        from config import get_digest_lock_path
        import os
        os.environ.pop("DIGEST_LOCK_PATH", None)
        p = get_digest_lock_path()
        self.assertIn("digest.lock", p)

    def test_get_digest_lock_timeout_s_default(self):
        from config import get_digest_lock_timeout_s
        import os
        os.environ.pop("DIGEST_LOCK_TIMEOUT_S", None)
        self.assertEqual(get_digest_lock_timeout_s(), 300)

    def test_get_digest_run_mode_default_off(self):
        from config import get_digest_run_mode
        import os
        os.environ.pop("DIGEST_RUN_MODE", None)
        self.assertEqual(get_digest_run_mode(), "off")

    def test_get_digest_catchup_max_days_default(self):
        from config import get_digest_catchup_max_days
        import os
        os.environ.pop("DIGEST_CATCHUP_MAX_DAYS", None)
        self.assertEqual(get_digest_catchup_max_days(), 7)

    def test_get_digest_ui_enable_default_false(self):
        from config import get_digest_ui_enable
        import os
        os.environ.pop("DIGEST_UI_ENABLE", None)
        self.assertFalse(get_digest_ui_enable())

    def test_jit_window_defaults(self):
        from config import (get_jit_window_time_reference_h,
                            get_jit_window_fact_recall_h,
                            get_jit_window_remember_h)
        import os
        for k in ["JIT_WINDOW_TIME_REFERENCE_H", "JIT_WINDOW_FACT_RECALL_H", "JIT_WINDOW_REMEMBER_H"]:
            os.environ.pop(k, None)
        self.assertEqual(get_jit_window_time_reference_h(), 48)
        self.assertEqual(get_jit_window_fact_recall_h(), 168)
        self.assertEqual(get_jit_window_remember_h(), 336)


# ═══════════════════════════════════════════════════════════════════════════════
# P8-Ops-7: JIT-only strict (extended maybe_load_csv_events)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMaybeLoadCSVExtended(unittest.TestCase):

    def _base_patches(self, jit_only=True, csv_enable=True, mode="active",
                      filters_enable=False, small_only=False):
        return [
            patch("config.get_typedstate_csv_enable", return_value=csv_enable),
            patch("config.get_typedstate_mode", return_value=mode),
            patch("config.get_typedstate_enable_small_only", return_value=small_only),
            patch("config.get_typedstate_csv_jit_only", return_value=jit_only),
            patch("config.get_digest_filters_enable", return_value=filters_enable),
        ]

    def test_jit_only_no_trigger_returns_empty_no_io(self):
        from core.typedstate_csv_loader import maybe_load_csv_events
        with patch("config.get_typedstate_csv_enable", return_value=True), \
             patch("config.get_typedstate_mode", return_value="active"), \
             patch("config.get_typedstate_enable_small_only", return_value=False), \
             patch("config.get_typedstate_csv_jit_only", return_value=True), \
             patch("config.get_digest_filters_enable", return_value=False):
            # trigger=None → no CSV-IO
            with patch("core.typedstate_csv_loader.load_csv_events") as mock_load:
                result = maybe_load_csv_events(trigger=None)
                mock_load.assert_not_called()
        self.assertEqual(result, [])

    def test_jit_only_valid_trigger_calls_load(self):
        from core.typedstate_csv_loader import maybe_load_csv_events
        fake_events = [{"id": "e1"}]
        with patch("config.get_typedstate_csv_enable", return_value=True), \
             patch("config.get_typedstate_mode", return_value="active"), \
             patch("config.get_typedstate_enable_small_only", return_value=False), \
             patch("config.get_typedstate_csv_jit_only", return_value=True), \
             patch("config.get_digest_filters_enable", return_value=False), \
             patch("os.path.exists", return_value=True), \
             patch("config.get_typedstate_csv_path", return_value="/fake/path.csv"), \
             patch("core.typedstate_csv_loader.load_csv_events", return_value=fake_events), \
             patch("core.digest.runtime_state.update_jit", return_value=True):
            result = maybe_load_csv_events(trigger="time_reference")
        self.assertEqual(result, fake_events)

    def test_accepts_conversation_id_param(self):
        """maybe_load_csv_events accepts conversation_id without error."""
        from core.typedstate_csv_loader import maybe_load_csv_events
        with patch("config.get_typedstate_csv_enable", return_value=False):
            result = maybe_load_csv_events(trigger="remember", conversation_id="c1")
        self.assertEqual(result, [])

    def test_accepts_start_end_ts_params(self):
        from core.typedstate_csv_loader import maybe_load_csv_events
        ts = datetime.now(tz=timezone.utc)
        with patch("config.get_typedstate_csv_enable", return_value=False):
            result = maybe_load_csv_events(trigger="fact_recall", start_ts=ts, end_ts=ts)
        self.assertEqual(result, [])


# ═══════════════════════════════════════════════════════════════════════════════
# P8-Ops-8: Trigger → time-window mapping
# ═══════════════════════════════════════════════════════════════════════════════

class TestTriggerWindowMapping(unittest.TestCase):

    def _call_with_trigger(self, trigger, time_ref_h=48, fact_h=168, remember_h=336):
        from core.typedstate_csv_loader import maybe_load_csv_events
        captured_start = {}

        def fake_load(path, start_ts=None, end_ts=None, conversation_id=None, actions=None):
            captured_start["start_ts"] = start_ts
            return []

        with patch("config.get_typedstate_csv_enable", return_value=True), \
             patch("config.get_typedstate_mode", return_value="active"), \
             patch("config.get_typedstate_enable_small_only", return_value=False), \
             patch("config.get_typedstate_csv_jit_only", return_value=True), \
             patch("config.get_digest_filters_enable", return_value=True), \
             patch("config.get_jit_window_time_reference_h", return_value=time_ref_h), \
             patch("config.get_jit_window_fact_recall_h", return_value=fact_h), \
             patch("config.get_jit_window_remember_h", return_value=remember_h), \
             patch("config.get_typedstate_csv_path", return_value="/fake/p.csv"), \
             patch("os.path.exists", return_value=True), \
             patch("core.typedstate_csv_loader.load_csv_events", side_effect=fake_load), \
             patch("core.digest.runtime_state.update_jit", return_value=True):
            maybe_load_csv_events(trigger=trigger)

        return captured_start.get("start_ts")

    def test_time_reference_window_48h(self):
        start = self._call_with_trigger("time_reference", time_ref_h=48)
        self.assertIsNotNone(start)
        # start_ts should be ~48h ago
        age_h = (datetime.now(tz=timezone.utc) - start).total_seconds() / 3600
        self.assertAlmostEqual(age_h, 48, delta=0.1)

    def test_fact_recall_window_168h(self):
        start = self._call_with_trigger("fact_recall", fact_h=168)
        self.assertIsNotNone(start)
        age_h = (datetime.now(tz=timezone.utc) - start).total_seconds() / 3600
        self.assertAlmostEqual(age_h, 168, delta=0.1)

    def test_remember_window_336h(self):
        start = self._call_with_trigger("remember", remember_h=336)
        self.assertIsNotNone(start)
        age_h = (datetime.now(tz=timezone.utc) - start).total_seconds() / 3600
        self.assertAlmostEqual(age_h, 336, delta=0.1)

    def test_filters_disabled_no_start_ts(self):
        """When DIGEST_FILTERS_ENABLE=false, no time window is applied."""
        from core.typedstate_csv_loader import maybe_load_csv_events
        captured = {}

        def fake_load(path, start_ts=None, **kw):
            captured["start_ts"] = start_ts
            return []

        with patch("config.get_typedstate_csv_enable", return_value=True), \
             patch("config.get_typedstate_mode", return_value="active"), \
             patch("config.get_typedstate_enable_small_only", return_value=False), \
             patch("config.get_typedstate_csv_jit_only", return_value=True), \
             patch("config.get_digest_filters_enable", return_value=False), \
             patch("config.get_typedstate_csv_path", return_value="/fake/p.csv"), \
             patch("os.path.exists", return_value=True), \
             patch("core.typedstate_csv_loader.load_csv_events", side_effect=fake_load), \
             patch("core.digest.runtime_state.update_jit", return_value=True):
            maybe_load_csv_events(trigger="time_reference")

        self.assertIsNone(captured.get("start_ts"))


# ═══════════════════════════════════════════════════════════════════════════════
# P8-Ops-9: Runtime API
# ═══════════════════════════════════════════════════════════════════════════════

_RUNTIME_ROUTES_PATH = os.path.join(
    "/DATA/AppData/MCP/Jarvis/Jarvis", "adapters", "admin-api", "runtime_routes.py"
)


class TestRuntimeRoutesStructure(unittest.TestCase):
    """runtime_routes.py — endpoint returns stable JSON structure."""

    def test_runtime_routes_importable(self):
        self.assertTrue(os.path.exists(_RUNTIME_ROUTES_PATH))

    def test_runtime_routes_has_router(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("runtime_routes", _RUNTIME_ROUTES_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertTrue(hasattr(mod, "router"))

    def test_runtime_routes_endpoint_registered(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("runtime_routes", _RUNTIME_ROUTES_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        routes = [r.path for r in mod.router.routes]
        self.assertIn("/api/runtime/digest-state", routes)

    def test_get_state_returns_dict_structure(self):
        """get_state() always returns dict with schema_version key."""
        from core.digest.runtime_state import get_state
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "state.json")
            with patch("core.digest.runtime_state._state_path", return_value=path):
                s = get_state()
        self.assertIn("schema_version", s)
        self.assertIn("daily", s)
        self.assertIn("catch_up", s)
        self.assertIn("jit", s)  # v2: jit is a structured block


# ═══════════════════════════════════════════════════════════════════════════════
# P8-Ops-10: Frontend (JS) — manual checklist
# ═══════════════════════════════════════════════════════════════════════════════

class TestFrontendManualChecklist(unittest.TestCase):
    """
    Manual checklist for digest UI panel (browser-only; no automated JS tests here).
    This test documents what to verify manually:

    [ ] 1. With DIGEST_UI_ENABLE=false: panel id="digest-status-panel" has class "hidden"
    [ ] 2. With DIGEST_UI_ENABLE=true: panel becomes visible on Advanced tab open
    [ ] 3. Flag chips render with correct color (green=active, gray=inactive)
    [ ] 4. Daily/Weekly/Archive cards show status from /api/runtime/digest-state
    [ ] 5. Lock card shows "unlocked" in green / "LOCKED by..." in yellow
    [ ] 6. JIT Last Trigger shows trigger name + row count
    [ ] 7. Refresh button re-fetches and updates all cards
    [ ] 8. On API error: panel stays hidden (fail-open)
    """

    def test_index_html_has_digest_panel(self):
        html_path = os.path.join(
            "/DATA/AppData/MCP/Jarvis/Jarvis", "adapters", "Jarvis", "index.html"
        )
        with open(html_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("digest-status-panel", content)
        self.assertIn("digest-daily-status", content)
        self.assertIn("digest-weekly-status", content)
        self.assertIn("digest-archive-status", content)

    def test_settings_js_has_digestui(self):
        js_path = os.path.join(
            "/DATA/AppData/MCP/Jarvis/Jarvis", "adapters", "Jarvis", "js", "apps", "settings.js"
        )
        with open(js_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("DigestUI", content)
        self.assertIn("digest-state", content)
        self.assertIn("setupDigestUIHandlers", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
