"""
core/digest/worker.py — Digest pipeline scheduling worker (Phase 8 Operational).

Run modes (DIGEST_RUN_MODE):
  off      → no scheduling (default; zero behaviour change on existing deployments)
  sidecar  → standalone blocking loop; use via scripts/digest_worker.py
  inline   → hooked into API startup via adapters/admin-api/main.py

Scheduling:
  - Runs at 04:00 in configured TZ (DIGEST_TZ, default Europe/Berlin).
  - Startup: immediately runs catch-up, then waits for next 04:00.
  - Pipeline order per cycle: daily → weekly → archive.

Locking:
  - DigestLock prevents concurrent runs (two sidecars, API + sidecar).
  - Stale locks (> DIGEST_LOCK_TIMEOUT_S) are force-taken.

Logging markers:
  [DigestWorker] start|run|next_run|catch_up|complete|error|disabled
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from utils.logger import log_info, log_warn


# ── TZ / scheduling helpers ───────────────────────────────────────────────────

def _get_tz():
    try:
        from zoneinfo import ZoneInfo
        from config import get_digest_tz
        return ZoneInfo(get_digest_tz())
    except Exception:
        return timezone.utc


def _next_04_utc(now: datetime) -> datetime:
    """Return next 04:00 in configured TZ as UTC-aware datetime."""
    tz  = _get_tz()
    loc = now.astimezone(tz)
    target = loc.replace(hour=4, minute=0, second=0, microsecond=0)
    if loc >= target:
        target += timedelta(days=1)
    return target.astimezone(timezone.utc)


def _run_mode() -> str:
    try:
        from config import get_digest_run_mode
        return get_digest_run_mode()
    except Exception:
        return "off"


# ── Summary helpers ───────────────────────────────────────────────────────────

def _extract_count(result) -> int:
    """Extract 'written' count from scheduler result (dict or int, backward compat)."""
    if isinstance(result, dict):
        return result.get("written", 0)
    try:
        return int(result or 0)
    except (TypeError, ValueError):
        return 0


def _extract_field(result, field: str):
    """Extract a named field from a scheduler result dict. Returns None if not dict."""
    if isinstance(result, dict):
        return result.get(field)
    return None


# ── Worker ────────────────────────────────────────────────────────────────────

class DigestWorker:
    """
    Orchestrates the full digest pipeline: daily → weekly → archive.

    Usage (sidecar):
        worker = DigestWorker()
        worker.run_loop()   # blocking

    Usage (one-shot / inline):
        worker = DigestWorker()
        worker.run_once()
    """

    def __init__(self) -> None:
        self._owner = f"digest-worker-{uuid.uuid4().hex[:8]}"

    # ── Public API ────────────────────────────────────────────────────────────

    def run_loop(self) -> None:
        """Blocking scheduler loop (sidecar mode). Runs catch-up on startup then 04:00 daily."""
        if _run_mode() == "off":
            log_info("[DigestWorker] DIGEST_RUN_MODE=off — loop not started")
            return

        log_info(f"[DigestWorker] start owner={self._owner}")
        self.run_once(is_startup=True)

        while True:
            now_utc  = datetime.now(tz=timezone.utc)
            next_run = _next_04_utc(now_utc)
            wait_s   = (next_run - now_utc).total_seconds()
            log_info(
                f"[DigestWorker] next_run={next_run.isoformat()} wait_s={wait_s:.0f}"
            )
            _sleep_until(next_run)
            self.run_once(is_startup=False)

    def run_once(self, is_startup: bool = False) -> dict:
        """
        Single pipeline cycle: daily → weekly → archive.
        Protected by DigestLock. Returns summary dict.
        """
        from core.digest.locking import DigestLock

        summary: dict = {
            "ok": False, "daily": 0, "weekly": 0, "archive": 0,
            "skipped": False, "reason": None,
        }

        with DigestLock(self._owner) as lock:
            if not lock.acquired:
                log_warn(f"[DigestWorker] run=skipped reason=lock_held owner={self._owner}")
                summary["skipped"] = True
                summary["reason"]  = "lock_held"
                return summary

            t_start = time.monotonic()
            label   = "startup" if is_startup else "scheduled"
            log_info(f"[DigestWorker] run={label} owner={self._owner}")

            daily_r   = None
            weekly_r  = None
            archive_r = None

            try:
                daily_r   = self._run_daily()
                weekly_r  = self._run_weekly()
                archive_r = self._run_archive()
                summary["daily"]   = _extract_count(daily_r)
                summary["weekly"]  = _extract_count(weekly_r)
                summary["archive"] = _extract_count(archive_r)
                summary["ok"]      = True
            except Exception as exc:
                log_warn(f"[DigestWorker] run=error: {exc}")
                summary["reason"] = str(exc)
                # Ensure counts are set even on partial failure
                if daily_r is not None:
                    summary["daily"] = _extract_count(daily_r)
                if weekly_r is not None:
                    summary["weekly"] = _extract_count(weekly_r)
                if archive_r is not None:
                    summary["archive"] = _extract_count(archive_r)

            duration_s = time.monotonic() - t_start
            log_info(
                f"[DigestWorker] run={label} ok={summary['ok']} "
                f"daily={summary['daily']} weekly={summary['weekly']} "
                f"archive={summary['archive']} duration_s={duration_s:.2f}"
            )

            # Persist state (fail-open)
            try:
                from core.digest import runtime_state
                _cycle_status = "ok" if summary["ok"] else "error"

                # Extract rich telemetry from structured summaries
                _daily_input   = _extract_field(daily_r,   "input_events")
                _daily_reason  = _extract_field(daily_r,   "reason")
                _weekly_reason = _extract_field(weekly_r,  "reason")

                runtime_state.update_cycle(
                    "daily",
                    status=_cycle_status,
                    duration_s=round(duration_s, 2),
                    digest_written=summary["daily"],
                    input_events=_daily_input,
                    reason=_daily_reason,
                )
                if summary["weekly"]:
                    runtime_state.update_cycle(
                        "weekly",
                        status="ok",
                        digest_written=summary["weekly"],
                        reason=_weekly_reason,
                    )
                if summary["archive"]:
                    runtime_state.update_cycle(
                        "archive",
                        status="ok",
                        digest_written=summary["archive"],
                    )

                # Catch-up telemetry: use rich catch_up sub-dict from daily result
                _cu = (daily_r.get("catch_up", {}) if isinstance(daily_r, dict) else {})
                runtime_state.update_catch_up(
                    days_processed=_cu.get("days_examined", summary["daily"]),
                    written=summary["daily"],
                    status=_cycle_status,
                    missed_runs=_cu.get("missed_runs", 0),
                    recovered=_cu.get("recovered"),
                    generated=_cu.get("generated", summary["daily"]),
                    mode=_cu.get("mode", "off"),
                )
            except Exception:
                pass

        return summary

    # ── Internal pipeline steps ───────────────────────────────────────────────

    def _run_daily(self) -> dict:
        try:
            from core.digest.daily_scheduler import DailyDigestScheduler
            return DailyDigestScheduler().run()  # conv_ids=None → auto-derive
        except Exception as exc:
            log_warn(f"[DigestWorker] daily error: {exc}")
            return {"written": 0, "input_events": 0, "reason": str(exc),
                    "catch_up": {"written": 0, "days_examined": 0, "missed_runs": 0,
                                 "recovered": None, "generated": 0, "mode": "off"}}

    def _run_weekly(self) -> dict:
        try:
            from core.digest.weekly_archiver import WeeklyDigestArchiver
            return WeeklyDigestArchiver().run_weekly()
        except Exception as exc:
            log_warn(f"[DigestWorker] weekly error: {exc}")
            return {"written": 0, "skipped": 0, "reason": str(exc)}

    def _run_archive(self) -> dict:
        try:
            from core.digest.weekly_archiver import WeeklyDigestArchiver
            return WeeklyDigestArchiver().run_archive()
        except Exception as exc:
            log_warn(f"[DigestWorker] archive error: {exc}")
            return {"written": 0, "skipped": 0}


# ── Sleep helper ──────────────────────────────────────────────────────────────

def _sleep_until(target_utc: datetime) -> None:
    """Sleep until target_utc in 60-second chunks (allows clean shutdown signals)."""
    while True:
        remaining = (target_utc - datetime.now(tz=timezone.utc)).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(60.0, remaining))
