"""
core/digest/daily_scheduler.py — Daily Digest Scheduler (Phase 8, Commit F)

Compression job: runs at 04:00 Europe/Berlin → builds daily_digest per conversation.

Architecture:
    - Reads workspace events for a target date from CSV (via load_csv_events filter)
    - Builds CompactContext using existing build_compact_context pipeline
    - Stores as daily_digest in DigestStore (idempotent, digest_key guard)
    - Catch-up: on startup, fills gaps from last success to yesterday

Rollback: DIGEST_DAILY_ENABLE=false (or DIGEST_ENABLE=false master switch).

Digest key:
    sha256("daily:v1:{conversation_id}:{date_berlin}:{source_hash}")[:32]
    source_hash: sha256(",".join(sorted(event_ids)))[:16]

Idempotency:
    - DigestStore.exists("daily_digest", digest_key) before any write.
    - Re-runs on same events → same key → skip.

Logging markers:
    [DailyDigest] date={date} conv={conv_id} status=skip|ok|error
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from utils.logger import log_info, log_warn

# ---------------------------------------------------------------------------
# Timezone helper (ZoneInfo Python 3.9+, fallback to UTC offset for older)
# ---------------------------------------------------------------------------

def _get_berlin_tz():
    """Return ZoneInfo('Europe/Berlin') or UTC offset +1/+2 as fallback."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Berlin")
    except Exception:
        try:
            from config import get_digest_tz
            tz_name = get_digest_tz()
            from zoneinfo import ZoneInfo
            return ZoneInfo(tz_name)
        except Exception:
            pass
    # Fallback: UTC (safe, no external dependency)
    return timezone.utc


def _today_berlin() -> date:
    """Return today's date in the configured digest timezone."""
    tz = _get_berlin_tz()
    return datetime.now(tz=tz).date()


def _yesterday_berlin() -> date:
    """Return yesterday's date in the configured digest timezone."""
    return _today_berlin() - timedelta(days=1)


def _date_to_iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# DailyDigestScheduler
# ---------------------------------------------------------------------------

class DailyDigestScheduler:
    """
    Builds daily_digest entries for a given conversation and date range.

    Args:
        store:      DigestStore instance (injected; testable).
        csv_path:   Path to the source event CSV (default from config).
    """

    def __init__(
        self,
        store=None,
        csv_path: Optional[str] = None,
    ) -> None:
        if store is None:
            from core.digest.store import DigestStore
            store = DigestStore()
        self._store = store
        self._csv_path = csv_path or self._resolve_csv_path()

    @staticmethod
    def _resolve_csv_path() -> str:
        try:
            from config import get_typedstate_csv_path
            import os
            p = get_typedstate_csv_path()
            if not os.path.isabs(p):
                import core.digest.store as _s
                base = os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.abspath(_s.__file__)))
                )
                p = os.path.join(base, p)
            return p
        except Exception:
            return ""

    # ── Public entry-point ────────────────────────────────────────────────

    def run(self, conversation_ids: Optional[List[str]] = None) -> dict:
        """
        Main scheduler entry-point (called at 04:00 Berlin or on startup).

        1. Auto-derives conversation_ids from CSV if None (Point 4).
        2. Runs catch-up (capped at DIGEST_CATCHUP_MAX_DAYS) per conversation.
        3. Returns structured summary dict (written, input_events, skipped, reason,
           conversation_ids, catch_up).

        Backward compat: callers using int return can use _extract_count(run()).
        """
        if not self._digest_enabled():
            log_info("[DailyDigest] DIGEST_DAILY_ENABLE=false — skipped")
            return {"written": 0, "input_events": 0, "skipped": 0,
                    "reason": "DAILY_DISABLED", "conversation_ids": [],
                    "catch_up": {"written": 0, "days_examined": 0, "missed_runs": 0,
                                 "recovered": None, "generated": 0, "mode": "off"}}

        # Point 4: auto-derive conversation list from CSV when not provided
        if conversation_ids is None:
            convs = self._derive_conversation_ids()
            log_info(f"[DailyDigest] auto-derived conv_ids={len(convs)} from CSV")
        else:
            convs = list(conversation_ids)

        total_written = 0
        agg_catchup: dict = {
            "written": 0, "days_examined": 0, "missed_runs": 0,
            "recovered": None, "generated": 0, "mode": "off",
        }
        for conv_id in convs:
            cu = self.run_catchup(conv_id)
            if isinstance(cu, dict):
                total_written    += cu.get("written", 0)
                agg_catchup["written"]       += cu.get("written", 0)
                agg_catchup["days_examined"] += cu.get("days_examined", 0)
                agg_catchup["missed_runs"]   += cu.get("missed_runs", 0)
                agg_catchup["generated"]     += cu.get("generated", 0)
                if cu.get("mode") and cu["mode"] != "off":
                    agg_catchup["mode"] = cu["mode"]
            else:
                total_written += int(cu or 0)

        agg_catchup["recovered"] = (
            agg_catchup["generated"] > 0
            if agg_catchup["missed_runs"] > 0
            else None
        )

        return {
            "written":          total_written,
            "input_events":     0,
            "skipped":          0,
            "reason":           None,
            "conversation_ids": convs,
            "catch_up":         agg_catchup,
        }

    def run_catchup(self, conversation_id: str) -> dict:
        """
        Fill gaps for conversation_id: process every missing date up to yesterday.
        Capped by DIGEST_CATCHUP_MAX_DAYS (Point 3).

        Returns structured dict:
          written, days_examined, missed_runs, recovered, generated, mode
        """
        yesterday = _yesterday_berlin()

        # Point 3: respect catch-up cap
        max_days = self._catchup_max_days()
        if max_days == 0:
            log_info(
                f"[DailyDigest] conv={conversation_id} "
                "catch_up=skip reason=max_days=0"
            )
            return {"written": 0, "days_examined": 0, "missed_runs": 0,
                    "recovered": None, "generated": 0, "mode": "off"}

        events = self._load_events_for_conv(conversation_id)
        if not events:
            log_info(f"[DailyDigest] conv={conversation_id} no events — skipped")
            return {"written": 0, "days_examined": 0, "missed_runs": 0,
                    "recovered": None, "generated": 0, "mode": "off"}

        # Determine date range from available events
        dates = self._extract_event_dates(events)
        if not dates:
            return {"written": 0, "days_examined": 0, "missed_runs": 0,
                    "recovered": None, "generated": 0, "mode": "off"}

        # Cap: start at most max_days ago from yesterday
        first_date = min(dates)
        mode = "full"
        if max_days > 0:
            cap_start = yesterday - timedelta(days=max_days - 1)
            if first_date < cap_start:
                first_date = cap_start
                mode = "cap"

        # Count total days in window (= missed_runs in catch-up context)
        days_in_window = (yesterday - first_date).days + 1

        # Process from first_date to yesterday (inclusive)
        written = 0
        current = first_date
        while current <= yesterday:
            try:
                ok = self.run_for_date(conversation_id, current, events)
                if ok:
                    written += 1
            except Exception as exc:
                log_warn(
                    f"[DailyDigest] date={_date_to_iso(current)} "
                    f"conv={conversation_id} error={exc}"
                )
            current += timedelta(days=1)

        return {
            "written":       written,
            "days_examined": days_in_window,
            "missed_runs":   days_in_window,   # all days in window needed catch-up
            "recovered":     written > 0,
            "generated":     written,
            "mode":          mode,
        }

    def run_for_date(
        self,
        conversation_id: str,
        target_date: date,
        all_events: Optional[List[dict]] = None,
    ) -> bool:
        """
        Build and persist a daily_digest for (conversation_id, target_date).

        Returns True if a new digest was written, False if skipped (already exists or empty).
        Logs [DailyDigest] markers with status.
        """
        from core.digest.keys import (
            make_source_hash, make_daily_digest_key, make_daily_digest_key_v2,
        )
        from core.context_cleanup import build_compact_context, format_compact_context

        date_str = _date_to_iso(target_date)

        # Load events for target date and conversation
        events = self._events_for_date(all_events, conversation_id, target_date)
        if not events:
            log_info(
                f"[DailyDigest] date={date_str} conv={conversation_id} "
                "status=skip reason=no_events"
            )
            return False

        # Point 5: input quality guard
        min_events = self._min_events_daily()
        if min_events > 0 and len(events) < min_events:
            log_info(
                f"[DailyDigest] date={date_str} conv={conversation_id} "
                f"status=skip reason=insufficient_input "
                f"events={len(events)} min={min_events}"
            )
            return False

        # Compute idempotency key (v1 or v2 based on config)
        event_ids = [ev.get("id", ev.get("event_id", "")) for ev in events]
        source_hash = make_source_hash(event_ids)
        key_version = self._key_version()
        if key_version == "v2":
            digest_key = make_daily_digest_key_v2(conversation_id, date_str, source_hash)
        else:
            digest_key = make_daily_digest_key(conversation_id, date_str, source_hash)

        # Re-run detection
        if self._store.exists("daily_digest", digest_key):
            log_info(
                f"[DailyDigest] date={date_str} conv={conversation_id} "
                f"status=skip reason=already_exists key={digest_key}"
            )
            return False

        # Build compact context from events
        try:
            ctx = build_compact_context(events)
            compact_text = format_compact_context(ctx)
        except Exception as exc:
            log_warn(
                f"[DailyDigest] date={date_str} conv={conversation_id} "
                f"status=error reason=build_failed: {exc}"
            )
            return False

        # Persist (v2: include explicit window bounds in fact_attributes)
        event_id = str(uuid.uuid4())
        _window = date_str if key_version == "v2" else None
        ok = self._store.write_daily(
            event_id=event_id,
            conversation_id=conversation_id,
            digest_key=digest_key,
            digest_date=date_str,
            event_count=len(events),
            source_hash=source_hash,
            compact_text=compact_text,
            window_start=_window,
            window_end=_window,
        )

        status = "ok" if ok else "error"
        log_info(
            f"[DailyDigest] date={date_str} conv={conversation_id} "
            f"status={status} events={len(events)} key={digest_key}"
        )
        return ok

    # ── Private helpers ───────────────────────────────────────────────────

    def _derive_conversation_ids(self) -> List[str]:
        """Point 4: extract unique conversation_ids from CSV (when run(None) is called)."""
        if not self._csv_path:
            return []
        try:
            import os as _os
            if not _os.path.exists(self._csv_path):
                return []
            from core.typedstate_csv_loader import load_csv_events
            events = load_csv_events(self._csv_path, sorted_by_rank=False)
            seen: set = set()
            for ev in events:
                cid = ev.get("conversation_id", "")
                if cid:
                    seen.add(cid)
            return sorted(seen)
        except Exception as exc:
            log_warn(f"[DailyDigest] _derive_conversation_ids error: {exc}")
            return []

    @staticmethod
    def _catchup_max_days() -> int:
        try:
            from config import get_digest_catchup_max_days
            return get_digest_catchup_max_days()
        except Exception:
            return 7

    @staticmethod
    def _min_events_daily() -> int:
        try:
            from config import get_digest_min_events_daily
            return get_digest_min_events_daily()
        except Exception:
            return 0

    @staticmethod
    def _digest_enabled() -> bool:
        try:
            from config import get_digest_daily_enable
            return get_digest_daily_enable()
        except Exception:
            return False

    @staticmethod
    def _key_version() -> str:
        try:
            from config import get_digest_key_version
            return get_digest_key_version()
        except Exception:
            return "v1"

    def _load_events_for_conv(self, conversation_id: str) -> List[dict]:
        """Load all events from CSV for a given conversation_id."""
        if not self._csv_path:
            return []
        try:
            import os
            if not os.path.exists(self._csv_path):
                return []
            from core.typedstate_csv_loader import load_csv_events
            return load_csv_events(
                self._csv_path,
                sorted_by_rank=False,
                conversation_id=conversation_id,
            )
        except Exception as exc:
            log_warn(f"[DailyDigest] CSV load failed: {exc}")
            return []

    @staticmethod
    def _extract_event_dates(events: List[dict]) -> List[date]:
        """Extract unique dates (in Berlin TZ) from event created_at timestamps."""
        tz = _get_berlin_tz()
        dates = []
        for ev in events:
            ts_str = ev.get("created_at", "")
            if not ts_str:
                continue
            try:
                dt = datetime.fromisoformat(ts_str.rstrip("Z"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                dates.append(dt.astimezone(tz).date())
            except Exception:
                pass
        return list(set(dates))

    @staticmethod
    def _events_for_date(
        all_events: Optional[List[dict]],
        conversation_id: str,
        target_date: date,
    ) -> List[dict]:
        """Filter events to those matching conversation_id and target_date."""
        if all_events is None:
            return []
        tz = _get_berlin_tz()
        result = []
        for ev in all_events:
            # Conversation filter
            if ev.get("conversation_id", "") != conversation_id:
                continue
            # Date filter
            ts_str = ev.get("created_at", "")
            if not ts_str:
                continue
            try:
                dt = datetime.fromisoformat(ts_str.rstrip("Z"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                ev_date = dt.astimezone(tz).date()
                if ev_date == target_date:
                    result.append(ev)
            except Exception:
                pass
        return result
