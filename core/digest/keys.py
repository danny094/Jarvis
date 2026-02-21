"""
core/digest/keys.py — Deterministic digest key computation (Phase 8).

All digest keys are sha256-based, hex-encoded, truncated to 32 characters.
Keys are collision-resistant within their scope (daily / weekly / archive).

Key schemas v1 (default, DIGEST_KEY_VERSION=v1):
    daily:   sha256("daily:v1:{conversation_id}:{date_berlin}:{source_hash}")[:32]
    weekly:  sha256("weekly:v1:{conversation_id}:{iso_week}:{sorted_daily_keys}")[:32]
    archive: sha256("archive:v1:{conversation_id}:{weekly_digest_key}:{archive_date}")[:32]

Key schemas v2 (DIGEST_KEY_VERSION=v2, explicit window bounds in hash):
    daily:   sha256("daily:v2:{conversation_id}:{date}:{date}:{source_hash}")[:32]
             (window_start == window_end for daily)
    weekly:  sha256("weekly:v2:{conversation_id}:{iso_week}:{week_start}:{week_end}:{sorted_keys}")[:32]
    archive: sha256("archive:v2:{conversation_id}:{weekly_key}:{archive_date}")[:32]

source_hash: sha256(",".join(sorted(event_ids)))[:16]   — covers event set identity
sorted_daily_keys: ",".join(sorted(daily_digest_keys))  — covers weekly content identity
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta
from typing import List, Tuple


def _sha256_hex(text: str) -> str:
    """Return lowercase hex sha256 of UTF-8 encoded text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_source_hash(event_ids: List[str]) -> str:
    """
    16-character hash of a sorted list of event IDs.
    Deterministic: same set in any order → same hash.
    """
    canonical = ",".join(sorted(event_ids))
    return _sha256_hex(canonical)[:16]


def make_daily_digest_key(
    conversation_id: str,
    date_berlin: str,      # "YYYY-MM-DD"
    source_hash: str,
) -> str:
    """
    32-char digest key for a daily digest.

    Uniquely identifies: (conversation, date, event-set).
    Idempotent: re-running on the same events produces the same key.
    """
    raw = f"daily:v1:{conversation_id}:{date_berlin}:{source_hash}"
    return _sha256_hex(raw)[:32]


def make_weekly_digest_key(
    conversation_id: str,
    iso_week: str,            # "YYYY-Www" e.g. "2026-W08"
    daily_digest_keys: List[str],
) -> str:
    """
    32-char digest key for a weekly digest.

    Uniquely identifies: (conversation, ISO week, contributing daily digests).
    Idempotent: same daily keys in any order → same weekly key.
    """
    sorted_keys = ",".join(sorted(daily_digest_keys))
    raw = f"weekly:v1:{conversation_id}:{iso_week}:{sorted_keys}"
    return _sha256_hex(raw)[:32]


def make_archive_digest_key(
    conversation_id: str,
    weekly_digest_key: str,
    archive_date: str,        # "YYYY-MM-DD" — the date archiving occurred
) -> str:
    """
    32-char digest key for an archive_digest entry.

    Uniquely identifies: (conversation, weekly digest, archive date).
    """
    raw = f"archive:v1:{conversation_id}:{weekly_digest_key}:{archive_date}"
    return _sha256_hex(raw)[:32]


# ── Key V2 helpers ────────────────────────────────────────────────────────────

def _iso_week_bounds(iso_week: str) -> Tuple[str, str]:
    """
    Return (Monday, Sunday) date strings for a given ISO-week label "YYYY-Www".

    Example: "2026-W08" → ("2026-02-16", "2026-02-22")
    """
    year, week_part = iso_week.split("-W")
    year_i = int(year)
    week_i = int(week_part)
    # ISO week starts on Monday; date.fromisocalendar available Python 3.8+
    try:
        monday = date.fromisocalendar(year_i, week_i, 1)
    except AttributeError:
        # Fallback for Python < 3.8
        jan4 = date(year_i, 1, 4)
        week_start = jan4 - timedelta(days=jan4.isoweekday() - 1)
        monday = week_start + timedelta(weeks=week_i - 1)
    sunday = monday + timedelta(days=6)
    return monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")


def make_daily_digest_key_v2(
    conversation_id: str,
    date_str: str,       # "YYYY-MM-DD" — target date
    source_hash: str,
) -> str:
    """
    32-char digest key v2 for a daily digest.
    Window bounds explicitly included: window_start == window_end (same day).
    """
    raw = f"daily:v2:{conversation_id}:{date_str}:{date_str}:{source_hash}"
    return _sha256_hex(raw)[:32]


def make_weekly_digest_key_v2(
    conversation_id: str,
    iso_week: str,              # "YYYY-Www"
    daily_digest_keys: List[str],
) -> str:
    """
    32-char digest key v2 for a weekly digest.
    Explicitly includes week_start and week_end (Monday/Sunday of iso_week).
    """
    week_start, week_end = _iso_week_bounds(iso_week)
    sorted_keys = ",".join(sorted(daily_digest_keys))
    raw = f"weekly:v2:{conversation_id}:{iso_week}:{week_start}:{week_end}:{sorted_keys}"
    return _sha256_hex(raw)[:32]


def make_archive_digest_key_v2(
    conversation_id: str,
    weekly_digest_key: str,
    archive_date: str,          # "YYYY-MM-DD"
) -> str:
    """
    32-char digest key v2 for an archive_digest entry.
    Structurally same as v1 but uses v2 prefix for explicit versioning.
    """
    raw = f"archive:v2:{conversation_id}:{weekly_digest_key}:{archive_date}"
    return _sha256_hex(raw)[:32]
