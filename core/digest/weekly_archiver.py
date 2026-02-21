"""
core/digest/weekly_archiver.py — Weekly Digest + Archive Pipeline (Phase 8, Commit G)

Weekly digest:
    - Input: daily_digest entries from DigestStore (NOT raw events)
    - Groups by ISO week per conversation
    - Builds CompactContext from daily_digest events
    - Stores as weekly_digest (idempotent via digest_key)

Archive:
    - After 14 days from weekly_digest timestamp → archive_digest
    - Writes index-only record to DigestStore (archive_digest action)
    - Optionally persists to Graph via MCP hub (when hub available)

Rollback:
    - DIGEST_WEEKLY_ENABLE=false → weekly job skipped
    - DIGEST_ARCHIVE_ENABLE=false → archive step skipped

Idempotency:
    - weekly: DigestStore.exists("weekly_digest", weekly_key) before write
    - archive: DigestStore.exists("archive_digest", archive_key) before write

Logging markers:
    [WeeklyDigest] week={iso_week} conv={conv_id} status=skip|ok|error
    [ArchiveDigest] key={archive_key} conv={conv_id} status=skip|ok|error
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from utils.logger import log_info, log_warn

# Archive threshold: weekly digests older than this many days are archived
_ARCHIVE_AFTER_DAYS = 14


def _get_tz():
    try:
        from zoneinfo import ZoneInfo
        from config import get_digest_tz
        return ZoneInfo(get_digest_tz())
    except Exception:
        return timezone.utc


def _iso_week_label(d: date) -> str:
    """Return ISO-week label 'YYYY-Www' for a given date."""
    iso = d.isocalendar()
    return f"{iso[0]:04d}-W{iso[1]:02d}"


def _parse_ts(ts_str: str) -> Optional[datetime]:
    """Parse ISO timestamp string to UTC-aware datetime. Returns None on error."""
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str.rstrip("Z"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


class WeeklyDigestArchiver:
    """
    Builds weekly_digest entries from daily_digest rows and archives old ones.

    Args:
        store: DigestStore instance (injected; testable).
    """

    def __init__(self, store=None) -> None:
        if store is None:
            from core.digest.store import DigestStore
            store = DigestStore()
        self._store = store

    # ── Public entry-points ───────────────────────────────────────────────

    def run_weekly(self, conversation_ids: Optional[List[str]] = None) -> dict:
        """
        Build weekly digests for all complete ISO weeks with available daily_digests.

        Returns structured summary dict: {written, skipped, reason}.
        Backward compat: callers using int return can use _extract_count(run_weekly()).
        """
        if not self._weekly_enabled():
            log_info("[WeeklyDigest] DIGEST_WEEKLY_ENABLE=false — skipped")
            return {"written": 0, "skipped": 0, "reason": "WEEKLY_DISABLED"}

        # Group daily_digest rows by (conversation_id, iso_week)
        daily_rows = self._store.list_by_action("daily_digest")
        grouped = self._group_by_conv_week(daily_rows)

        conv_filter = set(conversation_ids) if conversation_ids else None
        written = 0
        skipped = 0

        for (conv_id, iso_week), rows in sorted(grouped.items()):
            if conv_filter and conv_id not in conv_filter:
                continue
            try:
                if self._build_weekly(conv_id, iso_week, rows):
                    written += 1
                else:
                    skipped += 1
            except Exception as exc:
                log_warn(
                    f"[WeeklyDigest] week={iso_week} conv={conv_id} "
                    f"status=error: {exc}"
                )

        return {"written": written, "skipped": skipped, "reason": None}

    def run_archive(self, conversation_ids: Optional[List[str]] = None) -> dict:
        """
        Archive weekly_digest records older than _ARCHIVE_AFTER_DAYS days.

        Returns structured summary dict: {written, skipped}.
        Backward compat: callers using int return can use _extract_count(run_archive()).
        """
        if not self._archive_enabled():
            log_info("[ArchiveDigest] DIGEST_ARCHIVE_ENABLE=false — skipped")
            return {"written": 0, "skipped": 0}

        weekly_rows = self._store.list_by_action("weekly_digest")
        now_utc = datetime.now(tz=timezone.utc)
        threshold = now_utc - timedelta(days=_ARCHIVE_AFTER_DAYS)

        conv_filter = set(conversation_ids) if conversation_ids else None
        written = 0
        skipped = 0

        for row in weekly_rows:
            conv_id = row.get("conversation_id", "")
            if conv_filter and conv_id not in conv_filter:
                continue
            try:
                ts = _parse_ts(row.get("timestamp", ""))
                if ts is None or ts > threshold:
                    skipped += 1
                    continue  # not old enough yet
                if self._build_archive(conv_id, row, now_utc.date()):
                    written += 1
                else:
                    skipped += 1
            except Exception as exc:
                log_warn(f"[ArchiveDigest] conv={conv_id} status=error: {exc}")

        return {"written": written, "skipped": skipped}

    # ── Weekly builder ────────────────────────────────────────────────────

    @staticmethod
    def _key_version() -> str:
        try:
            from config import get_digest_key_version
            return get_digest_key_version()
        except Exception:
            return "v1"

    def _build_weekly(
        self,
        conversation_id: str,
        iso_week: str,
        daily_rows: List[Dict[str, str]],
    ) -> bool:
        """Build and persist one weekly_digest. Returns True if written."""
        from core.digest.keys import (
            make_weekly_digest_key, make_weekly_digest_key_v2, _iso_week_bounds,
        )
        from core.context_cleanup import build_compact_context, format_compact_context

        # Collect daily digest keys (sorted for determinism)
        daily_keys: List[str] = []
        for row in daily_rows:
            try:
                params = json.loads(row.get("parameters", "{}") or "{}")
                dk = params.get("digest_key", "")
                if dk:
                    daily_keys.append(dk)
            except Exception:
                pass

        if not daily_keys:
            log_info(
                f"[WeeklyDigest] week={iso_week} conv={conversation_id} "
                "status=skip reason=no_daily_keys"
            )
            return False

        # Point 5: input quality guard
        min_daily = self._min_daily_per_week()
        if min_daily > 0 and len(daily_keys) < min_daily:
            log_info(
                f"[WeeklyDigest] week={iso_week} conv={conversation_id} "
                f"status=skip reason=insufficient_input "
                f"daily_keys={len(daily_keys)} min={min_daily}"
            )
            return False

        key_version = self._key_version()
        if key_version == "v2":
            weekly_key = make_weekly_digest_key_v2(conversation_id, iso_week, daily_keys)
            week_start, week_end = _iso_week_bounds(iso_week)
        else:
            weekly_key = make_weekly_digest_key(conversation_id, iso_week, daily_keys)
            week_start, week_end = None, None

        # Idempotency check
        if self._store.exists("weekly_digest", weekly_key):
            log_info(
                f"[WeeklyDigest] week={iso_week} conv={conversation_id} "
                f"status=skip reason=already_exists key={weekly_key}"
            )
            return False

        # Build CompactContext from daily digest events (treat daily rows as events)
        digest_events = self._daily_rows_to_events(daily_rows)
        try:
            ctx = build_compact_context(digest_events)
            compact_text = format_compact_context(ctx)
        except Exception as exc:
            log_warn(
                f"[WeeklyDigest] week={iso_week} conv={conversation_id} "
                f"status=error reason=build_failed: {exc}"
            )
            return False

        ok = self._store.write_weekly(
            event_id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            digest_key=weekly_key,
            iso_week=iso_week,
            daily_digest_keys=daily_keys,
            compact_text=compact_text,
            window_start=week_start,
            window_end=week_end,
        )
        status = "ok" if ok else "error"
        log_info(
            f"[WeeklyDigest] week={iso_week} conv={conversation_id} "
            f"status={status} daily_count={len(daily_keys)} key={weekly_key}"
        )
        return ok

    # ── Archive builder ───────────────────────────────────────────────────

    def _build_archive(
        self,
        conversation_id: str,
        weekly_row: Dict[str, str],
        archive_date: date,
    ) -> bool:
        """Build and persist one archive_digest for a weekly_digest row."""
        from core.digest.keys import make_archive_digest_key, make_archive_digest_key_v2

        try:
            params = json.loads(weekly_row.get("parameters", "{}") or "{}")
        except Exception:
            params = {}

        weekly_key = params.get("digest_key", "")
        if not weekly_key:
            return False

        archive_date_str = archive_date.strftime("%Y-%m-%d")
        key_version = self._key_version()
        if key_version == "v2":
            archive_key = make_archive_digest_key_v2(
                conversation_id, weekly_key, archive_date_str
            )
        else:
            archive_key = make_archive_digest_key(
                conversation_id, weekly_key, archive_date_str
            )

        # Idempotency check
        if self._store.exists("archive_digest", archive_key):
            log_info(
                f"[ArchiveDigest] date={archive_date_str} conv={conversation_id} "
                f"status=skip reason=already_exists key={archive_key}"
            )
            return False

        # Optionally push to graph (fail-open: archive store write is primary)
        # Finding #5: pass archive_key so graph metadata is consistent with store key
        graph_node_id = self._try_save_to_graph(
            conversation_id, weekly_key, archive_date_str, weekly_row,
            archive_key=archive_key,
        )

        ok = self._store.write_archive(
            event_id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            archive_key=archive_key,
            weekly_digest_key=weekly_key,
            archive_date=archive_date_str,
            archive_graph_node_id=graph_node_id or "",
        )
        status = "ok" if ok else "error"
        log_info(
            f"[ArchiveDigest] date={archive_date_str} conv={conversation_id} "
            f"status={status} key={archive_key} graph_node={graph_node_id or 'none'}"
        )
        return ok

    def _try_save_to_graph(
        self,
        conversation_id: str,
        weekly_key: str,
        archive_date: str,
        weekly_row: Dict[str, str],
        archive_key: str = "",
    ) -> Optional[str]:
        """
        Attempt to save archive index to Graph (via MCP hub).
        Fail-open: returns None on any error (archive store write is primary truth).
        Returns graph_node_id string on success.
        Finding #5: archive_key param ensures graph metadata matches the store key.
        """
        try:
            from mcp.hub import get_hub
            hub = get_hub()
            hub.initialize()
            content = (
                f"[archive_digest] conv={conversation_id} "
                f"weekly_key={weekly_key} date={archive_date}"
            )
            result = hub.call_tool("memory_save", {
                "conversation_id": conversation_id,
                "content": content,
                "metadata": {
                    "type":              "archive_digest",
                    "weekly_digest_key": weekly_key,
                    "archived_at":       archive_date,
                    "archive_key":       archive_key,   # deterministic — matches store key
                },
            })
            if isinstance(result, dict):
                node_id = str(result.get("node_id", result.get("id", "")))
                return node_id or None
        except Exception:
            pass  # fail-open
        return None

    # ── Grouping helpers ──────────────────────────────────────────────────

    @staticmethod
    def _group_by_conv_week(
        rows: List[Dict[str, str]],
    ) -> Dict[Tuple[str, str], List[Dict[str, str]]]:
        """Group daily_digest rows by (conversation_id, iso_week)."""
        tz = _get_tz()
        grouped: Dict[Tuple[str, str], List[Dict[str, str]]] = {}
        for row in rows:
            conv_id = row.get("conversation_id", "")
            ts = _parse_ts(row.get("timestamp", ""))
            if ts is None:
                continue
            try:
                local_date = ts.astimezone(tz).date()
            except Exception:
                local_date = ts.date()
            iso_week = _iso_week_label(local_date)
            key = (conv_id, iso_week)
            grouped.setdefault(key, []).append(row)
        return grouped

    @staticmethod
    def _daily_rows_to_events(rows: List[Dict[str, str]]) -> List[dict]:
        """
        Convert daily_digest CSV rows to workspace_event-compatible dicts
        so build_compact_context can process them.
        """
        events = []
        for row in rows:
            try:
                fa = json.loads(row.get("fact_attributes", "{}") or "{}")
            except Exception:
                fa = {}
            events.append({
                "id":              row.get("event_id", ""),
                "conversation_id": row.get("conversation_id", ""),
                "event_type":      "daily_digest",
                "created_at":      row.get("timestamp", ""),
                "event_data":      {
                    "digest_date": fa.get("digest_date", ""),
                    "event_count": fa.get("event_count", 0),
                    "digest_key":  fa.get("digest_key", ""),
                },
            })
        return events

    # ── Enable checks + quality thresholds ────────────────────────────────

    @staticmethod
    def _min_daily_per_week() -> int:
        try:
            from config import get_digest_min_daily_per_week
            return get_digest_min_daily_per_week()
        except Exception:
            return 0

    @staticmethod
    def _weekly_enabled() -> bool:
        try:
            from config import get_digest_weekly_enable
            return get_digest_weekly_enable()
        except Exception:
            return False

    @staticmethod
    def _archive_enabled() -> bool:
        try:
            from config import get_digest_archive_enable
            return get_digest_archive_enable()
        except Exception:
            return False
