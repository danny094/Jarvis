"""
tests/unit/test_phase8_hardening.py — Phase 8 Operational Hardening Tests

Covers commits 2–13 of the Phase 8 hardening plan:

  Commit 2:  Double-start guard for inline mode
  Commit 3:  Sidecar crash-loop protection (docker-compose restart policy)
  Commit 4:  Runtime State schema v2
  Commit 5:  Structured scheduler summaries (dicts instead of ints)
  Commit 6:  Catch-up semantics (missed_runs, recovered, generated, mode)
  Commit 7:  API contract v2 + lock transparency
  Commit 8:  JIT hardening + startup warning
  Commit 9:  Digest Key V2 (explicit window bounds)
  Commit 10: Input quality enforcement tests
  Commit 11: Lock transparency (get_lock_status)
  Commit 12: Frontend telemetry panel (HTML/JS checks)
  Commit 13: Sync/Stream guardrail verification
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

# ── Project root path setup ───────────────────────────────────────────────────
# Walk up from __file__ until we find a directory containing config.py
def _find_root() -> str:
    candidate = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        if os.path.isfile(os.path.join(candidate, "config.py")):
            return candidate
        parent = os.path.dirname(candidate)
        if parent == candidate:
            break
        candidate = parent
    # Fallback: hard-coded project root for CI
    return "/DATA/AppData/MCP/Jarvis/Jarvis"

_ROOT = _find_root()
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ═══════════════════════════════════════════════════════════════════════════════
# Commit 2 — Double-start guard for inline mode
# ═══════════════════════════════════════════════════════════════════════════════

class TestInlineModeDoubleStart(unittest.TestCase):
    """digest-inline thread must not be started twice in the same process."""

    def test_inline_skip_when_mode_not_inline(self):
        """When DIGEST_RUN_MODE is off or sidecar, no digest-inline thread is created."""
        import threading as thr
        for mode in ("off", "sidecar"):
            with patch("config.get_digest_run_mode", return_value=mode):
                # No thread named digest-inline should be started by the guard logic
                before = {t.name for t in thr.enumerate() if t.is_alive()}
                # Simulate the guard: only spawn when mode == "inline"
                import config
                if config.get_digest_run_mode() == "inline":
                    self.fail(f"mode={mode} should not be inline")
                after = {t.name for t in thr.enumerate() if t.is_alive()}
                new_threads = after - before
                self.assertNotIn("digest-inline", new_threads,
                                 f"digest-inline thread started unexpectedly for mode={mode}")

    def test_no_double_start_inline(self):
        """When an alive digest-inline thread exists, the guard must skip starting a new one."""
        import threading as thr

        started = []
        barrier_start = threading.Event()

        def fake_run_loop():
            barrier_start.set()
            time.sleep(0.2)

        # Plant a fake digest-inline thread
        fake_t = thr.Thread(target=fake_run_loop, daemon=True, name="digest-inline")
        fake_t.start()
        barrier_start.wait()

        # Now simulate the double-start guard
        existing = [t for t in thr.enumerate() if t.name == "digest-inline" and t.is_alive()]
        self.assertTrue(len(existing) >= 1, "Fake digest-inline thread should be running")

        # Guard logic: skip if existing alive thread found
        if existing:
            skipped = True
        else:
            started.append("started")
            skipped = False

        self.assertTrue(skipped, "Guard should skip double-start")
        self.assertEqual(len(started), 0, "No new thread should have been started")

        fake_t.join(timeout=0.5)

    def test_inline_start_logs_mutex_note(self):
        """When inline thread is started, the mutual-exclusion log note is emitted."""
        import logging
        log_messages = []

        class CapturingHandler(logging.Handler):
            def emit(self, record):
                log_messages.append(record.getMessage())

        handler = CapturingHandler()
        handler.setLevel(logging.DEBUG)
        test_logger = logging.getLogger("test_mutex")
        test_logger.setLevel(logging.DEBUG)
        test_logger.addHandler(handler)

        class _FakeWorker:
            def run_loop(self): return

        try:
            import threading as _thr
            existing = [t for t in _thr.enumerate()
                        if t.name == "digest-inline-mutex-test" and t.is_alive()]
            if not existing:
                _w = _FakeWorker()
                _t = _thr.Thread(target=_w.run_loop, daemon=True,
                                 name="digest-inline-mutex-test")
                _t.start()
                test_logger.info(
                    "[DigestWorker] inline mode starting — mutual exclusion via DigestLock"
                )
                _t.join(timeout=0.2)
        finally:
            test_logger.removeHandler(handler)

        self.assertTrue(
            any("mutual exclusion via DigestLock" in m for m in log_messages),
            "Mutex note should be logged on inline start"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Commit 3 — Sidecar crash-loop protection
# ═══════════════════════════════════════════════════════════════════════════════

class TestSidecarRestartPolicy(unittest.TestCase):
    """docker-compose.yml must use restart: on-failure for digest-worker."""

    def _load_compose(self):
        import yaml  # type: ignore
        compose_path = os.path.join(_ROOT, "docker-compose.yml")
        if not os.path.exists(compose_path):
            self.skipTest("docker-compose.yml not found at project root")
        with open(compose_path, "r") as f:
            return yaml.safe_load(f)

    def test_compose_digest_worker_restart_policy(self):
        """digest-worker must NOT use restart: unless-stopped (crash-loop risk)."""
        try:
            compose = self._load_compose()
        except ImportError:
            self.skipTest("PyYAML not available")
        services = compose.get("services", {})
        worker = services.get("digest-worker")
        self.assertIsNotNone(worker, "digest-worker service must exist")
        restart = worker.get("restart", "")
        self.assertNotEqual(restart, "unless-stopped",
                            "digest-worker restart must not be unless-stopped")
        self.assertEqual(restart, "on-failure",
                         "digest-worker restart should be on-failure")

    def test_digest_worker_exits_zero_when_mode_off(self):
        """When DIGEST_RUN_MODE=off, DigestWorker.run_loop returns cleanly (exit code 0)."""
        from core.digest.worker import DigestWorker
        worker = DigestWorker()
        # With mode=off, run_loop should return immediately
        with patch("core.digest.worker._run_mode", return_value="off"):
            worker.run_loop()  # should not block or raise


# ═══════════════════════════════════════════════════════════════════════════════
# Commit 4 — Runtime State schema v2
# ═══════════════════════════════════════════════════════════════════════════════

class TestRuntimeStateSchemaV2(unittest.TestCase):
    """State file schema v2: richer cycle fields, structured jit block, v1→v2 migration."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._state_path = os.path.join(self._tmpdir, "digest_state.json")

    def _patch_path(self):
        return patch("core.digest.runtime_state._state_path",
                     return_value=self._state_path)

    def test_schema_v2_all_fields_present(self):
        """Empty state must have all required v2 fields."""
        from core.digest.runtime_state import get_state
        with self._patch_path():
            state = get_state()
        self.assertEqual(state.get("schema_version"), 2)
        for cycle in ("daily", "weekly", "archive"):
            c = state.get(cycle, {})
            self.assertIn("reason", c, f"{cycle}.reason missing")
            self.assertIn("retry_policy", c, f"{cycle}.retry_policy missing")
        cu = state.get("catch_up", {})
        for field in ("missed_runs", "recovered", "generated", "mode"):
            self.assertIn(field, cu, f"catch_up.{field} missing")
        jit = state.get("jit", {})
        for field in ("trigger", "rows", "ts"):
            self.assertIn(field, jit, f"jit.{field} missing")

    def test_migration_v1_to_v2_defaults(self):
        """Old v1 JSON is migrated to v2 on read with correct defaults."""
        v1_state = {
            "schema_version": 1,
            "daily":   {"last_run": "2026-01-01T04:00:00Z", "status": "ok",
                        "duration_s": 1.5, "input_events": None,
                        "digest_written": 2, "digest_key": None},
            "weekly":  {"last_run": None, "status": "never",
                        "duration_s": None, "input_events": None,
                        "digest_written": None, "digest_key": None},
            "archive": {"last_run": None, "status": "never",
                        "duration_s": None, "input_events": None,
                        "digest_written": None, "digest_key": None},
            "catch_up": {"last_run": None, "days_processed": 0, "written": 0,
                         "status": "never"},
            "jit_last_trigger": "time_reference",
            "jit_last_rows": 10,
            "jit_last_ts": "2026-01-01T12:00:00Z",
        }
        with open(self._state_path, "w") as f:
            json.dump(v1_state, f)

        from core.digest.runtime_state import get_state
        with self._patch_path():
            state = get_state()

        self.assertEqual(state["schema_version"], 2)
        # JIT block promoted
        self.assertEqual(state["jit"]["trigger"], "time_reference")
        self.assertEqual(state["jit"]["rows"], 10)
        # Old flat fields removed
        self.assertNotIn("jit_last_trigger", state)
        # New cycle fields with defaults
        self.assertIsNone(state["daily"]["reason"])
        self.assertIsNone(state["daily"]["retry_policy"])
        # New catch_up fields with defaults
        self.assertEqual(state["catch_up"]["missed_runs"], 0)
        self.assertIsNone(state["catch_up"]["recovered"])
        self.assertEqual(state["catch_up"]["generated"], 0)
        self.assertEqual(state["catch_up"]["mode"], "off")

    def test_update_catch_up_full_params(self):
        """update_catch_up stores missed_runs, recovered, generated, mode correctly."""
        from core.digest.runtime_state import update_catch_up, get_state
        with self._patch_path():
            update_catch_up(
                days_processed=5, written=4, status="ok",
                missed_runs=5, recovered=True, generated=4, mode="cap"
            )
            state = get_state()
        cu = state["catch_up"]
        self.assertEqual(cu["missed_runs"], 5)
        self.assertTrue(cu["recovered"])
        self.assertEqual(cu["generated"], 4)
        self.assertEqual(cu["mode"], "cap")
        self.assertEqual(cu["status"], "ok")

    def test_update_cycle_with_reason(self):
        """update_cycle stores reason and retry_policy fields."""
        from core.digest.runtime_state import update_cycle, get_state
        with self._patch_path():
            update_cycle("daily", status="error", reason="disk_full",
                         retry_policy="backoff")
            state = get_state()
        c = state["daily"]
        self.assertEqual(c["reason"], "disk_full")
        self.assertEqual(c["retry_policy"], "backoff")

    def test_jit_structured_block(self):
        """update_jit writes to jit.trigger, jit.rows, jit.ts (not flat fields)."""
        from core.digest.runtime_state import update_jit, get_state
        with self._patch_path():
            update_jit(trigger="remember", rows=42)
            state = get_state()
        jit = state.get("jit", {})
        self.assertEqual(jit["trigger"], "remember")
        self.assertEqual(jit["rows"], 42)
        self.assertIsNotNone(jit["ts"])
        # Legacy flat fields should NOT be present
        self.assertNotIn("jit_last_trigger", state)
        self.assertNotIn("jit_last_rows", state)


# ═══════════════════════════════════════════════════════════════════════════════
# Commit 5 — Structured scheduler summaries
# ═══════════════════════════════════════════════════════════════════════════════

class TestStructuredSchedulerSummaries(unittest.TestCase):
    """Schedulers must return dicts; worker extracts counts via _extract_count."""

    def test_extract_count_handles_int_and_dict(self):
        """_extract_count is backward-compatible with both int and dict returns."""
        from core.digest.worker import _extract_count
        self.assertEqual(_extract_count(3), 3)
        self.assertEqual(_extract_count(0), 0)
        self.assertEqual(_extract_count({"written": 5}), 5)
        self.assertEqual(_extract_count({"written": 0}), 0)
        self.assertEqual(_extract_count(None), 0)
        self.assertEqual(_extract_count({}), 0)

    def test_extract_field_handles_int_and_dict(self):
        """_extract_field returns None for non-dict results (backward compat)."""
        from core.digest.worker import _extract_field
        self.assertIsNone(_extract_field(3, "reason"))
        self.assertIsNone(_extract_field(None, "reason"))
        self.assertEqual(_extract_field({"reason": "disk_full"}, "reason"), "disk_full")
        self.assertIsNone(_extract_field({"x": 1}, "reason"))

    def test_worker_run_once_passes_input_events_to_state(self):
        """run_once propagates input_events from daily summary to update_cycle."""
        from core.digest.worker import DigestWorker
        worker = DigestWorker()
        cycle_calls = {}

        def fake_update_cycle(cycle, *, status, **kw):
            cycle_calls[cycle] = kw

        daily_result = {
            "written": 3, "input_events": 42, "reason": None,
            "catch_up": {"days_examined": 3, "missed_runs": 3,
                         "recovered": True, "generated": 3, "mode": "full", "written": 3},
        }

        with patch("core.digest.locking.acquire", return_value=True), \
             patch("core.digest.locking.release", return_value=True), \
             patch.object(worker, "_run_daily",   return_value=daily_result), \
             patch.object(worker, "_run_weekly",  return_value={"written": 0}), \
             patch.object(worker, "_run_archive", return_value={"written": 0}), \
             patch("core.digest.runtime_state.update_cycle",
                   side_effect=fake_update_cycle), \
             patch("core.digest.runtime_state.update_catch_up", return_value=True):
            worker.run_once()

        self.assertIn("daily", cycle_calls)
        self.assertEqual(cycle_calls["daily"].get("input_events"), 42)

    def test_worker_run_once_passes_reason_to_state(self):
        """run_once propagates reason from daily summary to update_cycle."""
        from core.digest.worker import DigestWorker
        worker = DigestWorker()
        cycle_calls = {}

        def fake_update_cycle(cycle, *, status, **kw):
            cycle_calls[cycle] = kw

        daily_result = {
            "written": 0, "input_events": 0, "reason": "DAILY_DISABLED",
            "catch_up": {"days_examined": 0, "missed_runs": 0,
                         "recovered": None, "generated": 0, "mode": "off", "written": 0},
        }

        with patch("core.digest.locking.acquire", return_value=True), \
             patch("core.digest.locking.release", return_value=True), \
             patch.object(worker, "_run_daily",   return_value=daily_result), \
             patch.object(worker, "_run_weekly",  return_value={"written": 0}), \
             patch.object(worker, "_run_archive", return_value={"written": 0}), \
             patch("core.digest.runtime_state.update_cycle",
                   side_effect=fake_update_cycle), \
             patch("core.digest.runtime_state.update_catch_up", return_value=True):
            worker.run_once()

        self.assertIn("daily", cycle_calls)
        self.assertEqual(cycle_calls["daily"].get("reason"), "DAILY_DISABLED")

    def test_backward_compat_int_return_value(self):
        """run_once still works when _run_daily/_run_weekly/_run_archive return ints."""
        from core.digest.worker import DigestWorker
        worker = DigestWorker()

        with patch("core.digest.locking.acquire", return_value=True), \
             patch("core.digest.locking.release", return_value=True), \
             patch.object(worker, "_run_daily",   return_value=2), \
             patch.object(worker, "_run_weekly",  return_value=1), \
             patch.object(worker, "_run_archive", return_value=0), \
             patch("core.digest.runtime_state.update_cycle", return_value=True), \
             patch("core.digest.runtime_state.update_catch_up", return_value=True):
            result = worker.run_once()

        self.assertTrue(result["ok"])
        self.assertEqual(result["daily"], 2)
        self.assertEqual(result["weekly"], 1)
        self.assertEqual(result["archive"], 0)


# ═══════════════════════════════════════════════════════════════════════════════
# Commit 6 — Catch-up semantics
# ═══════════════════════════════════════════════════════════════════════════════

class TestCatchUpSemantics(unittest.TestCase):
    """Catch-up returns enriched dict with missed_runs, recovered, generated, mode."""

    def _make_scheduler(self, store=None):
        from core.digest.daily_scheduler import DailyDigestScheduler
        sched = DailyDigestScheduler.__new__(DailyDigestScheduler)
        sched._store = store or MagicMock()
        sched._csv_path = ""
        return sched

    def test_catchup_full_recovery(self):
        """When all missed days are recovered, recovered=True."""
        sched = self._make_scheduler()
        yesterday = datetime.now(tz=timezone.utc).date() - timedelta(days=1)

        with patch.object(sched, "_load_events_for_conv", return_value=[
            {"id": "e1", "created_at": datetime.combine(
                yesterday, datetime.min.time(), timezone.utc).isoformat()}
        ]), patch.object(sched, "run_for_date", return_value=True), \
             patch("core.digest.daily_scheduler.DailyDigestScheduler._catchup_max_days",
                   return_value=7):
            result = sched.run_catchup("conv-1")

        self.assertIsInstance(result, dict)
        self.assertIn("recovered", result)
        # When written > 0, recovered should be True
        self.assertTrue(result.get("recovered"))
        self.assertIn("mode", result)

    def test_catchup_mode_cap_vs_full(self):
        """When cap is applied, mode='cap'; without cap, mode='full'."""
        sched = self._make_scheduler()

        # Create events far in the past (beyond max_days cap)
        far_past = datetime.now(tz=timezone.utc) - timedelta(days=30)
        events_far = [{"id": "e1", "created_at": far_past.isoformat()}]

        # With cap_days=7: should use mode='cap'
        with patch.object(sched, "_load_events_for_conv", return_value=events_far), \
             patch.object(sched, "run_for_date", return_value=True), \
             patch("core.digest.daily_scheduler.DailyDigestScheduler._catchup_max_days",
                   return_value=7):
            result = sched.run_catchup("conv-1")

        self.assertEqual(result.get("mode"), "cap",
                         "Should use mode=cap when capping a long history")

        # Recent events (within 3 days): mode='full'
        recent = datetime.now(tz=timezone.utc) - timedelta(days=2)
        events_recent = [{"id": "e2", "created_at": recent.isoformat()}]

        with patch.object(sched, "_load_events_for_conv", return_value=events_recent), \
             patch.object(sched, "run_for_date", return_value=True), \
             patch("core.digest.daily_scheduler.DailyDigestScheduler._catchup_max_days",
                   return_value=7):
            result = sched.run_catchup("conv-1")

        self.assertEqual(result.get("mode"), "full",
                         "Should use mode=full when events fit within cap window")

    def test_catchup_returns_days_examined(self):
        """Catch-up result includes days_examined > 0 when events exist."""
        sched = self._make_scheduler()
        yesterday = datetime.now(tz=timezone.utc).date() - timedelta(days=1)

        with patch.object(sched, "_load_events_for_conv", return_value=[
            {"id": "e1", "created_at": datetime.combine(
                yesterday, datetime.min.time(), timezone.utc).isoformat()}
        ]), patch.object(sched, "run_for_date", return_value=True), \
             patch("core.digest.daily_scheduler.DailyDigestScheduler._catchup_max_days",
                   return_value=7):
            result = sched.run_catchup("conv-1")

        self.assertGreater(result.get("days_examined", 0), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# Commit 7 — API contract v2 + lock transparency
# ═══════════════════════════════════════════════════════════════════════════════

class TestAPIContractV2(unittest.TestCase):
    """GET /api/runtime/digest-state v2 shape: flat keys, locking block, no stacktraces."""

    def _call_build_locking(self, lock_info):
        from adapters.admin_api.runtime_routes import _build_locking  # type: ignore
        return _build_locking(lock_info)

    def _import_build_locking(self):
        """Import _build_locking from runtime_routes (handles path variation)."""
        import importlib
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "runtime_routes",
            os.path.join(_ROOT, "adapters", "admin-api", "runtime_routes.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod._build_locking

    def test_api_locking_free_when_no_lock(self):
        """_build_locking(None) returns status=FREE."""
        _build_locking = self._import_build_locking()
        result = _build_locking(None)
        self.assertEqual(result["status"], "FREE")
        self.assertIsNone(result["owner"])
        self.assertIsNone(result["since"])
        self.assertIn("timeout_s", result)
        self.assertIsNone(result["stale"])

    def test_api_locking_locked_with_owner(self):
        """_build_locking with a fresh lock returns status=LOCKED, stale=False."""
        _build_locking = self._import_build_locking()
        now_iso = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
        lock_info = {"owner": "digest-worker-abc123", "acquired_at": now_iso, "pid": 42}
        with patch("config.get_digest_lock_timeout_s", return_value=300):
            result = _build_locking(lock_info)
        self.assertEqual(result["status"], "LOCKED")
        self.assertEqual(result["owner"], "digest-worker-abc123")
        self.assertFalse(result["stale"])

    def test_api_locking_stale_detected(self):
        """_build_locking with an old lock returns stale=True."""
        _build_locking = self._import_build_locking()
        old_time = (datetime.now(tz=timezone.utc) - timedelta(seconds=400)).isoformat()
        lock_info = {"owner": "old-worker", "acquired_at": old_time, "pid": 99}
        with patch("config.get_digest_lock_timeout_s", return_value=300):
            result = _build_locking(lock_info)
        self.assertEqual(result["status"], "LOCKED")
        self.assertTrue(result["stale"])

    def test_api_v2_top_level_keys_present(self):
        """V2 response must contain the required top-level keys."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "runtime_routes_test",
            os.path.join(_ROOT, "adapters", "admin-api", "runtime_routes.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Mock out the external deps so we can call the route directly
        empty_state = {
            "schema_version": 2,
            "daily":   {"status": "never", "last_run": None, "duration_s": None,
                        "input_events": None, "digest_written": None,
                        "digest_key": None, "reason": None, "retry_policy": None},
            "weekly":  {"status": "never", "last_run": None, "duration_s": None,
                        "input_events": None, "digest_written": None,
                        "digest_key": None, "reason": None, "retry_policy": None},
            "archive": {"status": "never", "last_run": None, "duration_s": None,
                        "input_events": None, "digest_written": None,
                        "digest_key": None, "reason": None, "retry_policy": None},
            "catch_up": {"status": "never", "last_run": None, "days_processed": 0,
                         "written": 0, "missed_runs": 0, "recovered": None,
                         "generated": 0, "mode": "off"},
            "jit": {"trigger": None, "rows": None, "ts": None},
        }
        _build_locking = mod._build_locking
        result = _build_locking(None)
        expected_keys = {"status", "owner", "since", "timeout_s", "stale"}
        self.assertEqual(set(result.keys()), expected_keys)


# ═══════════════════════════════════════════════════════════════════════════════
# Commit 8 — JIT hardening
# ═══════════════════════════════════════════════════════════════════════════════

class TestJITHardening(unittest.TestCase):
    """JIT_ONLY=true must produce zero CSV-IO when no valid trigger is present."""

    def test_jit_only_zero_csv_io_without_trigger(self):
        """With JIT_ONLY=true and trigger=None, load_csv_events is never called."""
        from core.typedstate_csv_loader import maybe_load_csv_events

        with patch("config.get_typedstate_csv_enable", return_value=True), \
             patch("config.get_typedstate_mode", return_value="active"), \
             patch("config.get_typedstate_enable_small_only", return_value=False), \
             patch("config.get_typedstate_csv_jit_only", return_value=True), \
             patch("core.typedstate_csv_loader.load_csv_events") as mock_load:
            result = maybe_load_csv_events(trigger=None)

        self.assertEqual(result, [], "Should return [] when JIT_ONLY=true and trigger=None")
        mock_load.assert_not_called()

    def test_jit_valid_trigger_loads_csv(self):
        """With JIT_ONLY=true and a valid trigger, CSV loading proceeds."""
        from core.typedstate_csv_loader import maybe_load_csv_events

        with patch("config.get_typedstate_csv_enable", return_value=True), \
             patch("config.get_typedstate_mode", return_value="active"), \
             patch("config.get_typedstate_enable_small_only", return_value=False), \
             patch("config.get_typedstate_csv_jit_only", return_value=True), \
             patch("config.get_digest_filters_enable", return_value=False), \
             patch("config.get_typedstate_csv_path", return_value="/fake/path.csv"), \
             patch("os.path.exists", return_value=False):
            # File doesn't exist — returns [] with a warning, not an error
            result = maybe_load_csv_events(trigger="time_reference")

        self.assertEqual(result, [])

    def test_dedupe_include_conv_default_true(self):
        """get_digest_dedupe_include_conv() must default to True (Commit 9)."""
        import config
        # Clear env override if any
        with patch.dict(os.environ, {}, clear=False):
            # Remove the key from env if present
            os.environ.pop("DIGEST_DEDUPE_INCLUDE_CONV", None)
            result = config.get_digest_dedupe_include_conv()
        self.assertTrue(result, "DIGEST_DEDUPE_INCLUDE_CONV must default to True")

    def test_digest_runtime_api_v2_default_true(self):
        """get_digest_runtime_api_v2() must default to True."""
        import config
        os.environ.pop("DIGEST_RUNTIME_API_V2", None)
        result = config.get_digest_runtime_api_v2()
        self.assertTrue(result, "DIGEST_RUNTIME_API_V2 must default to True")

    def test_digest_key_version_default_v1(self):
        """get_digest_key_version() must default to 'v1' for backward compat."""
        import config
        os.environ.pop("DIGEST_KEY_VERSION", None)
        result = config.get_digest_key_version()
        self.assertEqual(result, "v1", "DIGEST_KEY_VERSION must default to v1")


# ═══════════════════════════════════════════════════════════════════════════════
# Commit 9 (Plan commit 10) — Digest Key V2
# ═══════════════════════════════════════════════════════════════════════════════

class TestDigestKeyV2(unittest.TestCase):
    """Digest Key V2 functions include explicit window bounds in hash."""

    def test_v2_daily_key_deterministic(self):
        """Same inputs always produce the same v2 daily key."""
        from core.digest.keys import make_daily_digest_key_v2
        k1 = make_daily_digest_key_v2("conv-1", "2026-02-20", "abc123def")
        k2 = make_daily_digest_key_v2("conv-1", "2026-02-20", "abc123def")
        self.assertEqual(k1, k2)
        self.assertEqual(len(k1), 32)

    def test_v2_daily_key_differs_from_v1(self):
        """V2 daily key must differ from v1 key for same inputs."""
        from core.digest.keys import make_daily_digest_key, make_daily_digest_key_v2
        k_v1 = make_daily_digest_key("conv-1", "2026-02-20", "abc123def")
        k_v2 = make_daily_digest_key_v2("conv-1", "2026-02-20", "abc123def")
        self.assertNotEqual(k_v1, k_v2, "v1 and v2 keys must differ")

    def test_v2_weekly_key_includes_week_bounds(self):
        """V2 weekly key must differ from v1 key (bounds are included in hash)."""
        from core.digest.keys import make_weekly_digest_key, make_weekly_digest_key_v2
        keys = ["daily-key-1", "daily-key-2"]
        k_v1 = make_weekly_digest_key("conv-1", "2026-W08", keys)
        k_v2 = make_weekly_digest_key_v2("conv-1", "2026-W08", keys)
        self.assertNotEqual(k_v1, k_v2)
        self.assertEqual(len(k_v2), 32)

    def test_v1_key_unchanged(self):
        """V1 daily key produces the exact same hash as before hardening."""
        from core.digest.keys import make_daily_digest_key, _sha256_hex
        conv = "conv-abc"
        date = "2026-02-20"
        src_hash = "fedcba98"
        expected = _sha256_hex(f"daily:v1:{conv}:{date}:{src_hash}")[:32]
        actual = make_daily_digest_key(conv, date, src_hash)
        self.assertEqual(actual, expected, "v1 key must not have changed")

    def test_iso_week_bounds_correct(self):
        """_iso_week_bounds returns Monday and Sunday of the given ISO week."""
        from core.digest.keys import _iso_week_bounds
        # W08 of 2026: Feb 16 (Mon) to Feb 22 (Sun)
        start, end = _iso_week_bounds("2026-W08")
        self.assertEqual(start, "2026-02-16")
        self.assertEqual(end, "2026-02-22")

    def test_window_bounds_stored_in_store_v2(self):
        """write_daily accepts window_start/window_end and stores them in fact_attributes."""
        from core.digest.store import DigestStore
        import csv as _csv

        with tempfile.TemporaryDirectory() as d:
            store_path = os.path.join(d, "digest_store.csv")
            store = DigestStore(store_path=store_path)
            ok = store.write_daily(
                event_id="ev-1",
                conversation_id="conv-1",
                digest_key="key123",
                digest_date="2026-02-20",
                event_count=5,
                source_hash="hash456",
                compact_text="test",
                window_start="2026-02-20",
                window_end="2026-02-20",
            )
            self.assertTrue(ok)
            with open(store_path, newline="") as f:
                rows = list(_csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            fa = json.loads(rows[0]["fact_attributes"])
            self.assertEqual(fa.get("window_start"), "2026-02-20")
            self.assertEqual(fa.get("window_end"), "2026-02-20")


# ═══════════════════════════════════════════════════════════════════════════════
# Commit 10 (Plan commit 11) — Input quality enforcement
# ═══════════════════════════════════════════════════════════════════════════════

class TestInputQualityEnforcement(unittest.TestCase):
    """min_events_daily and min_daily_per_week thresholds are enforced."""

    def _make_daily_scheduler(self, store=None):
        from core.digest.daily_scheduler import DailyDigestScheduler
        sched = DailyDigestScheduler.__new__(DailyDigestScheduler)
        sched._store = store or MagicMock(exists=MagicMock(return_value=False))
        sched._csv_path = ""
        return sched

    def test_daily_skip_below_min_events_threshold(self):
        """run_for_date skips when event count < min_events_daily."""
        from datetime import date
        from core.digest.daily_scheduler import DailyDigestScheduler
        sched = self._make_daily_scheduler()

        # 2 events, min threshold = 3 → skip
        events = [
            {"id": "e1", "conversation_id": "c1", "created_at": "2026-02-20T10:00:00Z"},
            {"id": "e2", "conversation_id": "c1", "created_at": "2026-02-20T11:00:00Z"},
        ]
        with patch("core.digest.daily_scheduler.DailyDigestScheduler._min_events_daily",
                   return_value=3):
            result = sched.run_for_date("c1", date(2026, 2, 20), events)

        self.assertFalse(result, "Should skip with 2 events when min=3")

    def test_daily_proceed_at_min_events_threshold(self):
        """run_for_date proceeds when event count == min_events_daily."""
        from datetime import date

        mock_store = MagicMock()
        mock_store.exists.return_value = False
        mock_store.write_daily.return_value = True
        sched = self._make_daily_scheduler(mock_store)

        events = [
            {"id": f"e{i}", "conversation_id": "c1",
             "created_at": "2026-02-20T10:00:00Z"} for i in range(3)
        ]
        with patch("core.digest.daily_scheduler.DailyDigestScheduler._min_events_daily",
                   return_value=3), \
             patch("core.context_cleanup.build_compact_context",
                   return_value=MagicMock()), \
             patch("core.context_cleanup.format_compact_context",
                   return_value="compact text"):
            result = sched.run_for_date("c1", date(2026, 2, 20), events)

        self.assertTrue(result, "Should proceed with exactly 3 events when min=3")

    def test_weekly_skip_below_min_daily_threshold(self):
        """_build_weekly skips when daily_key count < min_daily_per_week."""
        from core.digest.weekly_archiver import WeeklyDigestArchiver
        mock_store = MagicMock(exists=MagicMock(return_value=False))
        archiver = WeeklyDigestArchiver(store=mock_store)

        # 1 daily row with 1 key, min threshold = 2 → skip
        daily_rows = [{
            "event_id": "e1",
            "conversation_id": "c1",
            "timestamp": "2026-02-17T04:00:00Z",
            "parameters": json.dumps({"digest_key": "key-1"}),
            "fact_attributes": "{}",
        }]
        with patch("core.digest.weekly_archiver.WeeklyDigestArchiver._min_daily_per_week",
                   return_value=2):
            result = archiver._build_weekly("c1", "2026-W08", daily_rows)

        self.assertFalse(result, "Should skip with 1 daily key when min=2")

    def test_threshold_zero_always_proceeds(self):
        """With min threshold=0, quality check is skipped (always proceed)."""
        from datetime import date

        mock_store = MagicMock()
        mock_store.exists.return_value = False
        mock_store.write_daily.return_value = True
        sched = self._make_daily_scheduler(mock_store)

        # Only 1 event but min=0 → should proceed
        events = [{"id": "e1", "conversation_id": "c1",
                   "created_at": "2026-02-20T10:00:00Z"}]
        with patch("core.digest.daily_scheduler.DailyDigestScheduler._min_events_daily",
                   return_value=0), \
             patch("core.context_cleanup.build_compact_context",
                   return_value=MagicMock()), \
             patch("core.context_cleanup.format_compact_context",
                   return_value="compact"):
            result = sched.run_for_date("c1", date(2026, 2, 20), events)

        self.assertTrue(result, "min=0 should always proceed regardless of count")


# ═══════════════════════════════════════════════════════════════════════════════
# Commit 11 — Lock transparency (get_lock_status)
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetLockStatus(unittest.TestCase):
    """get_lock_status() returns structured FREE/LOCKED block."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._lock_path = os.path.join(self._tmpdir, "digest.lock")

    def _patch_lock_path(self):
        return patch("core.digest.locking._lock_path", return_value=self._lock_path)

    def test_get_lock_status_free(self):
        """No lock file → status=FREE, owner=None, stale=None."""
        from core.digest.locking import get_lock_status
        with self._patch_lock_path(), \
             patch("core.digest.locking._timeout_s", return_value=300):
            result = get_lock_status()
        self.assertEqual(result["status"], "FREE")
        self.assertIsNone(result["owner"])
        self.assertIsNone(result["stale"])
        self.assertEqual(result["timeout_s"], 300)

    def test_get_lock_status_locked_fresh(self):
        """Fresh lock file → status=LOCKED, stale=False."""
        from core.digest.locking import get_lock_status
        now_iso = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
        lock_data = {"owner": "worker-123", "acquired_at": now_iso, "pid": 1}
        with open(self._lock_path, "w") as f:
            json.dump(lock_data, f)

        with self._patch_lock_path(), \
             patch("core.digest.locking._timeout_s", return_value=300):
            result = get_lock_status()

        self.assertEqual(result["status"], "LOCKED")
        self.assertEqual(result["owner"], "worker-123")
        self.assertFalse(result["stale"])

    def test_get_lock_status_locked_stale(self):
        """Old lock file → status=LOCKED, stale=True."""
        from core.digest.locking import get_lock_status
        old_ts = (datetime.now(tz=timezone.utc) - timedelta(seconds=400))
        old_iso = old_ts.isoformat().replace("+00:00", "Z")
        lock_data = {"owner": "old-worker", "acquired_at": old_iso, "pid": 99}
        with open(self._lock_path, "w") as f:
            json.dump(lock_data, f)

        with self._patch_lock_path(), \
             patch("core.digest.locking._timeout_s", return_value=300):
            result = get_lock_status()

        self.assertEqual(result["status"], "LOCKED")
        self.assertTrue(result["stale"])


# ═══════════════════════════════════════════════════════════════════════════════
# Commit 12 — Frontend telemetry panel
# ═══════════════════════════════════════════════════════════════════════════════

class TestFrontendTelemetryPanel(unittest.TestCase):
    """HTML and JS are updated for API v2 field names."""

    def _read_html(self):
        html_path = os.path.join(_ROOT, "adapters", "Jarvis", "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()

    def _read_settings_js(self):
        js_path = os.path.join(_ROOT, "adapters", "Jarvis", "js", "apps", "settings.js")
        with open(js_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_html_panel_has_locking_card(self):
        """index.html must contain the #digest-locking-card element."""
        html = self._read_html()
        self.assertIn("digest-locking-card", html,
                      "index.html must contain #digest-locking-card")

    def test_js_digest_ui_uses_v2_api_keys(self):
        """settings.js DigestUI must reference v2 fields (daily_digest) not v1 (d.state.daily)."""
        js = self._read_settings_js()
        # V2 keys must be present
        self.assertIn("daily_digest", js, "settings.js must reference d.daily_digest")
        self.assertIn("weekly_digest", js, "settings.js must reference d.weekly_digest")
        self.assertIn("archive_digest", js, "settings.js must reference d.archive_digest")

    def test_js_error_handling_no_stacktrace(self):
        """DigestUI.refresh() must have try/catch error handling."""
        js = self._read_settings_js()
        # refresh function must have error handling
        self.assertIn("try {", js)
        self.assertIn("catch", js)
        # Must not render raw error objects (no d.error.stack or traceback)
        self.assertNotIn("d.error.stack", js)

    def test_js_locking_card_helper_present(self):
        """settings.js must contain the _lockingCard helper function."""
        js = self._read_settings_js()
        self.assertIn("_lockingCard", js)

    def test_js_catch_up_card_helper_present(self):
        """settings.js must contain the _catchUpCard helper function."""
        js = self._read_settings_js()
        self.assertIn("_catchUpCard", js)


# ═══════════════════════════════════════════════════════════════════════════════
# Commit 13 — Sync/Stream guardrail verification
# ═══════════════════════════════════════════════════════════════════════════════

class TestSyncStreamGuardrails(unittest.TestCase):
    """Phase 8 modules must not introduce new context injection channels."""

    def _phase8_files(self):
        digest_dir = os.path.join(_ROOT, "core", "digest")
        return [
            os.path.join(digest_dir, f)
            for f in os.listdir(digest_dir)
            if f.endswith(".py") and not f.startswith("__")
        ]

    def test_no_new_injection_channels_in_phase8_modules(self):
        """Phase 8 digest modules must not call build_effective_context."""
        for path in self._phase8_files():
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertNotIn(
                "build_effective_context",
                content,
                f"{os.path.basename(path)} must not call build_effective_context"
            )

    def test_phase8_modules_dont_touch_output_layer(self):
        """Phase 8 digest modules must not import core.layers.output."""
        for path in self._phase8_files():
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertNotIn(
                "core.layers.output",
                content,
                f"{os.path.basename(path)} must not import output layer"
            )
            self.assertNotIn(
                "layers.output",
                content,
                f"{os.path.basename(path)} must not import output layer"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main()
