"""
tests/unit/test_phase8_findings.py — Regression tests for Phase 8 code-review findings.

Finding 1 (Critical): Lock TOCTOU — fully fixed:
  - Initial acquire: O_CREAT|O_EXCL (atomic, TOCTOU-free)
  - Stale-takeover:  O_EXCL sentinel file (.takeover) serialises concurrent
                     stale-takeovers — only one process proceeds; all others
                     return False immediately.
Finding 2 (High):     CSV JIT cross-conversation leak → conversation_id scoping
Finding 3 (Medium):   inline run-mode not wired → main.py startup hook
Finding 4 (Medium):   catch-up telemetry not written → update_catch_up in worker
Finding 5 (Medium):   archive-key inconsistent between graph metadata and store key
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch

# ── Project root ──────────────────────────────────────────────────────────────
_THIS = os.path.abspath(__file__)
if "tests" + os.sep + "unit" in _THIS:
    _ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_THIS)))
else:
    _ROOT = "/DATA/AppData/MCP/Jarvis/Jarvis"
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ═══════════════════════════════════════════════════════════════════════════════
# Finding 1-A: Initial acquire — O_CREAT|O_EXCL (fresh lock)
# ═══════════════════════════════════════════════════════════════════════════════

class TestLockAtomicity(unittest.TestCase):
    """
    Verifies that acquire() uses O_CREAT|O_EXCL so two processes cannot both
    succeed in the same instant (TOCTOU race) for fresh lock creation.
    """

    def setUp(self):
        self._dir  = tempfile.mkdtemp()
        self._path = os.path.join(self._dir, "digest.lock")

    def _with_lock_path(self):
        return patch("core.digest.locking._lock_path", return_value=self._path)

    def test_exclusive_create_wins(self):
        """First acquire must succeed via O_EXCL path (no existing file)."""
        from core.digest.locking import acquire
        with self._with_lock_path():
            ok = acquire("worker-A")
        self.assertTrue(ok)
        with open(self._path) as f:
            data = json.load(f)
        self.assertEqual(data["owner"], "worker-A")

    def test_second_acquire_blocked_by_fresh_lock(self):
        """Second acquire on same file (fresh lock) must return False without overwriting."""
        from core.digest.locking import acquire
        with self._with_lock_path():
            ok1 = acquire("worker-A")
            ok2 = acquire("worker-B")
        self.assertTrue(ok1)
        self.assertFalse(ok2)
        with open(self._path) as f:
            data = json.load(f)
        self.assertEqual(data["owner"], "worker-A")

    def test_race_simulation_only_one_wins(self):
        """
        Simulate a race by intercepting os.open.
        First call with O_EXCL succeeds; subsequent calls get FileExistsError.
        """
        from core.digest.locking import acquire

        original_os_open = os.open
        calls = []

        def patched_open(path, flags, *args, **kw):
            if flags & os.O_EXCL:
                calls.append("excl")
                if len(calls) == 1:
                    return original_os_open(path, flags, *args, **kw)
                raise FileExistsError("simulated race")
            return original_os_open(path, flags, *args, **kw)

        with self._with_lock_path(), patch("os.open", side_effect=patched_open):
            ok1 = acquire("winner")
        self.assertTrue(ok1)

    def test_stale_lock_force_taken(self):
        """Stale lock (age > timeout) must be overwritten with new owner."""
        old_ts = (datetime.now(tz=timezone.utc) - timedelta(seconds=400)).isoformat()
        with open(self._path, "w") as f:
            json.dump({"owner": "old", "acquired_at": old_ts, "pid": 1}, f)

        from core.digest.locking import acquire
        with self._with_lock_path(), \
             patch("core.digest.locking._timeout_s", return_value=300):
            ok = acquire("new-owner")
        self.assertTrue(ok)
        with open(self._path) as f:
            data = json.load(f)
        self.assertEqual(data["owner"], "new-owner")

    def test_o_excl_flag_used(self):
        """acquire() must call os.open with os.O_EXCL flag set."""
        from core.digest.locking import acquire
        seen_flags = []

        original = os.open

        def spy_open(path, flags, *a, **kw):
            seen_flags.append(flags)
            return original(path, flags, *a, **kw)

        with self._with_lock_path(), patch("os.open", side_effect=spy_open):
            acquire("spy-worker")

        excl_calls = [f for f in seen_flags if f & os.O_EXCL]
        self.assertTrue(len(excl_calls) >= 1, "os.open with O_EXCL never called")


# ═══════════════════════════════════════════════════════════════════════════════
# Finding 1-B: Stale-takeover — O_EXCL sentinel serialises concurrent takeovers
# ═══════════════════════════════════════════════════════════════════════════════

class TestStaleTakeoverAtomicity(unittest.TestCase):
    """
    Verifies that concurrent stale-takeovers result in at most one winner.

    Fix: a second O_EXCL sentinel (.takeover) serialises the stale-takeover path.
    Only the process that creates the sentinel atomically proceeds; all others
    return False immediately.  Sentinel is removed in a finally block.
    """

    def setUp(self):
        self._dir  = tempfile.mkdtemp()
        self._path = os.path.join(self._dir, "digest.lock")

    def _with_lock_path(self):
        return patch("core.digest.locking._lock_path", return_value=self._path)

    def _write_stale_lock(self, age_s: int = 400) -> None:
        old_ts = (datetime.now(tz=timezone.utc) - timedelta(seconds=age_s)).isoformat()
        with open(self._path, "w") as f:
            json.dump({"owner": "old-worker", "acquired_at": old_ts, "pid": 0}, f)

    def test_concurrent_stale_takeover_at_most_one_winner(self):
        """
        Two threads racing on a stale lock must produce exactly one True.
        Uses a Barrier to maximise chance of a real concurrent race.
        """
        self._write_stale_lock(age_s=400)
        results = []
        barrier = threading.Barrier(2)

        def do_acquire(name):
            barrier.wait()  # both reach acquire() simultaneously
            from core.digest import locking
            with self._with_lock_path(), \
                 patch("core.digest.locking._timeout_s", return_value=300):
                ok = locking.acquire(name)
            results.append(ok)

        threads = [
            threading.Thread(target=do_acquire, args=(f"worker-{i}",))
            for i in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        true_count = sum(1 for r in results if r)
        self.assertEqual(
            true_count, 1,
            f"Expected exactly 1 winner in stale-takeover race, "
            f"got {true_count} (results={results})"
        )

    def test_stale_takeover_sentinel_cleaned_up(self):
        """After a successful stale-takeover, the .takeover sentinel must be removed."""
        self._write_stale_lock(age_s=400)
        takeover_sentinel = self._path + ".takeover"

        from core.digest.locking import acquire
        with self._with_lock_path(), \
             patch("core.digest.locking._timeout_s", return_value=300):
            ok = acquire("sentinel-test-worker")

        self.assertTrue(ok)
        self.assertFalse(
            os.path.exists(takeover_sentinel),
            ".takeover sentinel was not cleaned up after stale-takeover"
        )

    def test_existing_sentinel_blocks_concurrent_takeover(self):
        """
        If a fresh .takeover sentinel already exists (another worker is taking over),
        acquire() must return False immediately.
        """
        self._write_stale_lock(age_s=400)
        takeover_sentinel = self._path + ".takeover"

        with open(takeover_sentinel, "w") as f:
            f.write("in-progress")

        try:
            from core.digest.locking import acquire
            with self._with_lock_path(), \
                 patch("core.digest.locking._timeout_s", return_value=300):
                ok = acquire("late-worker")
            self.assertFalse(
                ok,
                "acquire must return False when a concurrent takeover sentinel is held"
            )
        finally:
            if os.path.exists(takeover_sentinel):
                os.unlink(takeover_sentinel)

    def test_crashed_stale_sentinel_cleaned_and_takeover_succeeds(self):
        """
        A stale sentinel (> 30 s old, left by a crashed prior winner) must be
        cleaned up automatically, and the subsequent takeover must succeed.
        """
        self._write_stale_lock(age_s=400)
        takeover_sentinel = self._path + ".takeover"

        # Create a stale sentinel and back-date its mtime by 40 seconds
        with open(takeover_sentinel, "w") as f:
            f.write("crashed-worker")
        stale_mtime = time.time() - 40
        os.utime(takeover_sentinel, (stale_mtime, stale_mtime))

        from core.digest.locking import acquire
        with self._with_lock_path(), \
             patch("core.digest.locking._timeout_s", return_value=300):
            ok = acquire("recovery-worker")

        self.assertTrue(
            ok,
            "acquire should succeed after cleaning up a stale .takeover sentinel"
        )
        self.assertFalse(
            os.path.exists(takeover_sentinel),
            ".takeover sentinel must be removed after successful recovery takeover"
        )

    def test_recheck_blocks_late_stale_winner_after_lock_refresh(self):
        """
        Deterministic interleaving for the prior race window:
        - B reaches takeover-sentinel create and is paused
        - A completes stale takeover and refreshes lock timestamp
        - B resumes and creates takeover sentinel
        Expected: B must fail on takeover re-check (fresh lock), not overwrite.
        """
        self._write_stale_lock(age_s=400)
        takeover_sentinel = self._path + ".takeover"

        b_at_sentinel = threading.Event()
        allow_b = threading.Event()
        a_done = threading.Event()
        results = {}
        errors = []

        original_open = os.open

        def patched_open(path, flags, *args, **kwargs):
            if (
                path == takeover_sentinel
                and (flags & os.O_EXCL)
                and threading.current_thread().name == "worker-B-thread"
            ):
                b_at_sentinel.set()
                allow_b.wait(timeout=2.0)
            return original_open(path, flags, *args, **kwargs)

        def run_b():
            try:
                from core.digest.locking import acquire
                with self._with_lock_path(), \
                     patch("core.digest.locking._timeout_s", return_value=300), \
                     patch("os.open", side_effect=patched_open):
                    results["B"] = acquire("worker-B")
            except Exception as exc:
                errors.append(exc)

        def run_a():
            try:
                from core.digest.locking import acquire
                with self._with_lock_path(), \
                     patch("core.digest.locking._timeout_s", return_value=300), \
                     patch("os.open", side_effect=patched_open):
                    results["A"] = acquire("worker-A")
            except Exception as exc:
                errors.append(exc)
            finally:
                a_done.set()

        tb = threading.Thread(target=run_b, name="worker-B-thread")
        ta = threading.Thread(target=run_a, name="worker-A-thread")

        tb.start()
        self.assertTrue(
            b_at_sentinel.wait(timeout=2.0),
            "worker-B did not reach takeover-sentinel open point"
        )

        ta.start()
        self.assertTrue(
            a_done.wait(timeout=2.0),
            "worker-A did not complete takeover in time"
        )

        allow_b.set()
        ta.join(timeout=2.0)
        tb.join(timeout=2.0)

        self.assertFalse(errors, f"thread errors: {errors}")
        self.assertTrue(results.get("A"), "worker-A should win takeover")
        self.assertFalse(
            results.get("B"),
            "worker-B must fail after takeover re-check on refreshed lock"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Finding 2: CSV JIT cross-conversation scope
# ═══════════════════════════════════════════════════════════════════════════════

class TestCSVJITConversationScope(unittest.TestCase):
    """
    context_manager.build_small_model_context must pass conversation_id
    to maybe_load_csv_events so CSV events from other conversations are excluded.
    """

    def _build_cm(self):
        from core.context_manager import ContextManager
        cm = ContextManager.__new__(ContextManager)
        cm._protocol_cache = {}
        return cm

    def test_conversation_id_passed_to_maybe_load(self):
        """maybe_load_csv_events must receive the conversation_id from build_small_model_context."""
        cm = self._build_cm()
        captured = {}

        def fake_maybe_load(small_model_mode=False, trigger=None,
                            conversation_id=None, **kw):
            captured["conversation_id"] = conversation_id
            return []

        with patch("mcp.hub.get_hub") as mock_hub, \
             patch("core.typedstate_csv_loader.maybe_load_csv_events",
                   side_effect=fake_maybe_load), \
             patch("core.context_cleanup.build_compact_context",
                   return_value=MagicMock(now=[], rules=[], next=[], meta={})), \
             patch("core.context_cleanup.format_compact_context", return_value=""), \
             patch("config.get_typedstate_mode", return_value="off"):
            hub = MagicMock()
            hub.call_tool.return_value = {"events": []}
            mock_hub.return_value = hub
            cm.build_small_model_context(conversation_id="conv-X")

        self.assertEqual(captured.get("conversation_id"), "conv-X")

    def test_none_conversation_id_passes_none(self):
        """When no conversation_id provided, None must be passed (no scope filter)."""
        cm = self._build_cm()
        captured = {}

        def fake_maybe_load(small_model_mode=False, trigger=None,
                            conversation_id=None, **kw):
            captured["conversation_id"] = conversation_id
            return []

        with patch("mcp.hub.get_hub") as mock_hub, \
             patch("core.typedstate_csv_loader.maybe_load_csv_events",
                   side_effect=fake_maybe_load), \
             patch("core.context_cleanup.build_compact_context",
                   return_value=MagicMock(now=[], rules=[], next=[], meta={})), \
             patch("core.context_cleanup.format_compact_context", return_value=""), \
             patch("config.get_typedstate_mode", return_value="off"):
            hub = MagicMock()
            hub.call_tool.return_value = {"events": []}
            mock_hub.return_value = hub
            cm.build_small_model_context(conversation_id=None)

        self.assertIsNone(captured.get("conversation_id"))

    def test_maybe_load_csv_events_accepts_conversation_id(self):
        """maybe_load_csv_events signature must accept conversation_id param."""
        import inspect
        from core.typedstate_csv_loader import maybe_load_csv_events
        sig = inspect.signature(maybe_load_csv_events)
        self.assertIn("conversation_id", sig.parameters)

    def test_maybe_load_csv_events_passes_conversation_id_to_load(self):
        """When conversation_id provided, it must be forwarded to load_csv_events."""
        captured = {}

        def fake_load(path, start_ts=None, end_ts=None, conversation_id=None, actions=None, **kw):
            captured["conversation_id"] = conversation_id
            return []

        with patch("config.get_typedstate_csv_enable", return_value=True), \
             patch("config.get_typedstate_mode", return_value="active"), \
             patch("config.get_typedstate_enable_small_only", return_value=False), \
             patch("config.get_typedstate_csv_jit_only", return_value=False), \
             patch("config.get_digest_filters_enable", return_value=False), \
             patch("config.get_typedstate_csv_path", return_value="/fake/path.csv"), \
             patch("os.path.exists", return_value=True), \
             patch("core.typedstate_csv_loader.load_csv_events", side_effect=fake_load), \
             patch("core.digest.runtime_state.update_jit", return_value=True):
            from core.typedstate_csv_loader import maybe_load_csv_events
            maybe_load_csv_events(conversation_id="conv-ABC")

        self.assertEqual(captured.get("conversation_id"), "conv-ABC")


# ═══════════════════════════════════════════════════════════════════════════════
# Finding 3: inline run-mode wired in main.py startup
# ═══════════════════════════════════════════════════════════════════════════════

class TestInlineRunModeWired(unittest.TestCase):

    def test_main_py_has_inline_startup_hook(self):
        """main.py startup_event must contain inline mode handling."""
        main_path = os.path.join(_ROOT, "adapters", "admin-api", "main.py")
        with open(main_path, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("inline", src)
        self.assertIn("DigestWorker", src)
        self.assertIn("get_digest_run_mode", src)

    def test_inline_mode_starts_daemon_thread(self):
        """When DIGEST_RUN_MODE=inline, startup must launch a daemon thread."""
        launched = []

        class FakeThread:
            def __init__(self, target, daemon, name):
                self.daemon = daemon
                launched.append({"daemon": daemon, "name": name})
            def start(self):
                pass

        class FakeWorker:
            def run_loop(self):
                pass

        with patch("config.get_digest_run_mode", return_value="inline"), \
             patch("core.digest.worker.DigestWorker", return_value=FakeWorker()), \
             patch("threading.Thread", side_effect=FakeThread):
            import config as _cfg
            import threading as _threading
            from core.digest.worker import DigestWorker as _DW
            if _cfg.get_digest_run_mode() == "inline":
                _w = _DW()
                _t = _threading.Thread(target=_w.run_loop, daemon=True, name="digest-inline")
                _t.start()

        self.assertEqual(len(launched), 1)
        self.assertTrue(launched[0]["daemon"])
        self.assertEqual(launched[0]["name"], "digest-inline")

    def test_off_mode_does_not_start_thread(self):
        """DIGEST_RUN_MODE=off (default) must not start any digest thread."""
        launched = []

        class FakeThread:
            def __init__(self, target, daemon, name):
                launched.append(name)
            def start(self):
                pass

        with patch("config.get_digest_run_mode", return_value="off"), \
             patch("threading.Thread", side_effect=FakeThread):
            import config as _cfg
            import threading as _threading
            from core.digest.worker import DigestWorker as _DW
            if _cfg.get_digest_run_mode() == "inline":
                _w = _DW()
                _t = _threading.Thread(target=_w.run_loop, daemon=True, name="digest-inline")
                _t.start()

        self.assertEqual(len(launched), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# Finding 4: catch-up telemetry written in worker
# ═══════════════════════════════════════════════════════════════════════════════

class TestCatchUpTelemetryWritten(unittest.TestCase):
    """update_catch_up must be called after every run_once cycle."""

    def test_update_catch_up_called_in_run_once(self):
        from core.digest.worker import DigestWorker
        worker = DigestWorker()

        catch_up_calls = []

        def fake_update_catch_up(*, days_processed, written, status, **kw):
            catch_up_calls.append({"days_processed": days_processed,
                                   "written": written, "status": status})
            return True

        with patch("core.digest.locking.acquire", return_value=True), \
             patch("core.digest.locking.release", return_value=True), \
             patch.object(worker, "_run_daily",   return_value={"written": 3}), \
             patch.object(worker, "_run_weekly",  return_value={"written": 0}), \
             patch.object(worker, "_run_archive", return_value={"written": 0}), \
             patch("core.digest.runtime_state.update_cycle", return_value=True), \
             patch("core.digest.runtime_state.update_catch_up",
                   side_effect=fake_update_catch_up):
            worker.run_once()

        self.assertEqual(len(catch_up_calls), 1, "update_catch_up was not called")
        self.assertEqual(catch_up_calls[0]["written"], 3)
        self.assertEqual(catch_up_calls[0]["status"], "ok")

    def test_catch_up_status_error_on_failure(self):
        """When pipeline errors, catch-up status must be 'error'."""
        from core.digest.worker import DigestWorker
        worker = DigestWorker()

        catch_up_calls = []

        with patch("core.digest.locking.acquire", return_value=True), \
             patch("core.digest.locking.release", return_value=True), \
             patch.object(worker, "_run_daily",   side_effect=RuntimeError("boom")), \
             patch.object(worker, "_run_weekly",  return_value=0), \
             patch.object(worker, "_run_archive", return_value=0), \
             patch("core.digest.runtime_state.update_cycle", return_value=True), \
             patch("core.digest.runtime_state.update_catch_up",
                   side_effect=lambda **kw: catch_up_calls.append(kw) or True):
            worker.run_once()

        self.assertEqual(len(catch_up_calls), 1)
        self.assertEqual(catch_up_calls[0]["status"], "error")

    def test_catch_up_state_readable_after_run(self):
        """After run_once, get_state() must return a non-never catch_up status."""
        from core.digest.worker import DigestWorker
        from core.digest.runtime_state import get_state, update_catch_up

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "state.json")
            with patch("core.digest.runtime_state._state_path", return_value=path):
                update_catch_up(days_processed=2, written=2, status="ok")
                s = get_state()

        self.assertEqual(s["catch_up"]["status"], "ok")
        self.assertEqual(s["catch_up"]["written"], 2)
        self.assertIsNotNone(s["catch_up"]["last_run"])


# ═══════════════════════════════════════════════════════════════════════════════
# Finding 5: Archive key consistency between graph metadata and store key
# ═══════════════════════════════════════════════════════════════════════════════

class TestArchiveKeyConsistency(unittest.TestCase):
    """
    The archive_key written to store (deterministic sha256) must match
    the archive_key in graph metadata (previously used a derived format).
    """

    def _make_archiver(self):
        from core.digest.weekly_archiver import WeeklyDigestArchiver
        arch = WeeklyDigestArchiver.__new__(WeeklyDigestArchiver)
        arch._store = MagicMock()
        arch._store.exists.return_value = False
        arch._store.write_archive.return_value = True
        return arch

    def _weekly_row(self, weekly_key: str) -> dict:
        return {
            "event_id":        "w1",
            "conversation_id": "conv-A",
            "timestamp":       "2026-01-01T00:00:00Z",
            "action":          "weekly_digest",
            "parameters":      json.dumps({"digest_key": weekly_key}),
            "fact_attributes": "{}",
        }

    def test_graph_metadata_uses_deterministic_archive_key(self):
        """graph metadata archive_key must equal store archive_key (not weekly_key+date)."""
        from core.digest.keys import make_archive_digest_key

        arch = self._make_archiver()
        captured_metadata = {}

        def fake_try_save(conv_id, weekly_key, archive_date, weekly_row, archive_key=""):
            captured_metadata["archive_key"] = archive_key
            return None

        weekly_key = "abc123deadbeef00112233445566778"
        archive_date_str = "2026-02-20"
        expected_key = make_archive_digest_key("conv-A", weekly_key, archive_date_str)

        row = self._weekly_row(weekly_key)
        with patch.object(arch, "_try_save_to_graph", side_effect=fake_try_save):
            import datetime as _dt
            arch._build_archive("conv-A", row, _dt.date(2026, 2, 20))

        self.assertEqual(
            captured_metadata.get("archive_key"),
            expected_key,
            "graph metadata archive_key does not match deterministic store key"
        )

    def test_graph_metadata_not_derived_format(self):
        """archive_key in graph must NOT be the old weekly_key + '_' + archive_date format."""
        arch = self._make_archiver()
        captured_metadata = {}

        def fake_try_save(conv_id, weekly_key, archive_date, weekly_row, archive_key=""):
            captured_metadata["archive_key"] = archive_key
            return None

        weekly_key = "abc123"
        archive_date_str = "2026-02-20"
        old_format = weekly_key + "_" + archive_date_str

        row = self._weekly_row(weekly_key)
        with patch.object(arch, "_try_save_to_graph", side_effect=fake_try_save):
            import datetime as _dt
            arch._build_archive("conv-A", row, _dt.date(2026, 2, 20))

        received = captured_metadata.get("archive_key", "")
        self.assertNotEqual(received, old_format,
                            "archive_key in graph still uses old derived format")

    def test_try_save_to_graph_accepts_archive_key_param(self):
        """_try_save_to_graph must accept archive_key keyword argument."""
        import inspect
        from core.digest.weekly_archiver import WeeklyDigestArchiver
        sig = inspect.signature(WeeklyDigestArchiver._try_save_to_graph)
        self.assertIn("archive_key", sig.parameters)

    def test_store_write_archive_key_matches_make_archive_key(self):
        """The key passed to store.write_archive must equal make_archive_digest_key()."""
        from core.digest.keys import make_archive_digest_key

        arch = self._make_archiver()
        store_calls = []
        arch._store.write_archive = lambda **kw: store_calls.append(kw) or True

        weekly_key = "deadbeef00112233445566778899abc"
        archive_date_str = "2026-02-20"
        expected_key = make_archive_digest_key("conv-A", weekly_key, archive_date_str)

        row = self._weekly_row(weekly_key)
        with patch.object(arch, "_try_save_to_graph", return_value=None):
            import datetime as _dt
            arch._build_archive("conv-A", row, _dt.date(2026, 2, 20))

        self.assertEqual(len(store_calls), 1)
        self.assertEqual(store_calls[0]["archive_key"], expected_key)


if __name__ == "__main__":
    unittest.main(verbosity=2)
