"""
core/digest/locking.py — File-based lock for digest pipeline (Phase 8 Operational).

Lock file: DIGEST_LOCK_PATH (default: memory_speicher/digest.lock)
Format:    JSON { "owner": str, "acquired_at": ISO, "pid": int }
Stale lock: if lock age > DIGEST_LOCK_TIMEOUT_S → force-take.

Race-safety:
  Fresh lock:   O_CREAT|O_EXCL — atomic at the OS level; only one process wins.
  Stale lock:   A second O_EXCL sentinel file (.takeover) serialises concurrent
                stale-takeovers.  Only the process that creates the sentinel
                atomically proceeds; all others return False immediately.
                The sentinel is removed in a finally block (stale sentinels
                > 30 s from a crashed winner are cleaned up on the next attempt).

Logging marker: [DigestLock]
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from typing import Optional

from utils.logger import log_info, log_warn


# ── Path / config helpers ─────────────────────────────────────────────────────

def _lock_path() -> str:
    try:
        from config import get_digest_lock_path
        p = get_digest_lock_path()
    except Exception:
        p = "memory_speicher/digest.lock"
    if os.path.isabs(p):
        return p
    base = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    return os.path.join(base, p)


def _timeout_s() -> int:
    try:
        from config import get_digest_lock_timeout_s
        return get_digest_lock_timeout_s()
    except Exception:
        return 300


# ── Core operations ───────────────────────────────────────────────────────────

def acquire(owner: str) -> bool:
    """
    Try to acquire the digest lock for `owner`.
    Returns True on success, False if a fresh lock is held by someone else.
    Stale locks (age > DIGEST_LOCK_TIMEOUT_S) are force-taken.

    Race-safety: uses O_CREAT|O_EXCL for the initial create — atomic at the
    OS level.  Only one process can win the exclusive create; all others get
    FileExistsError and fall through to the stale-check path.
    """
    path = _lock_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    now_utc   = datetime.now(tz=timezone.utc)
    timeout_s = _timeout_s()

    lock_payload = json.dumps({
        "owner":       owner,
        "acquired_at": now_utc.isoformat().replace("+00:00", "Z"),
        "pid":         os.getpid(),
    }).encode("utf-8")

    # ── Attempt 1: atomic exclusive create (TOCTOU-free) ────────────────────
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        try:
            os.write(fd, lock_payload)
        finally:
            os.close(fd)
        log_info(f"[DigestLock] Acquired (exclusive-create) by owner={owner}")
        return True
    except FileExistsError:
        pass  # Someone else holds it — check if stale below.
    except OSError as exc:
        log_warn(f"[DigestLock] O_EXCL create failed: {exc}")
        return False

    # ── Check existing lock for staleness ────────────────────────────────────
    try:
        with open(path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        acquired_str = existing.get("acquired_at", "")
        acquired_dt  = datetime.fromisoformat(acquired_str.rstrip("Z"))
        if acquired_dt.tzinfo is None:
            acquired_dt = acquired_dt.replace(tzinfo=timezone.utc)
        age_s = (now_utc - acquired_dt).total_seconds()
        if age_s < timeout_s:
            log_warn(
                f"[DigestLock] Held by owner={existing.get('owner')} "
                f"age={age_s:.0f}s < timeout={timeout_s}s — BLOCK"
            )
            return False
        log_warn(
            f"[DigestLock] Stale lock (age={age_s:.0f}s) by "
            f"owner={existing.get('owner')} — force-taking"
        )
    except Exception as exc:
        log_warn(f"[DigestLock] Cannot read lock: {exc} — attempting takeover")

    # ── Force-take stale lock via exclusive takeover sentinel ─────────────────
    # Two workers that both detect a stale lock race here.  We serialise them
    # with a second O_EXCL sentinel file (.takeover): only the process that
    # atomically creates the sentinel proceeds; all others return False.
    takeover_path = path + ".takeover"

    # Clean up a stale sentinel left by a crashed prior winner (guard: > 30 s).
    try:
        st = os.stat(takeover_path)
        if (time.time() - st.st_mtime) > 30:
            os.unlink(takeover_path)
    except FileNotFoundError:
        pass
    except OSError:
        pass

    try:
        tfd = os.open(takeover_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        os.close(tfd)
    except FileExistsError:
        log_warn(
            f"[DigestLock] Stale-takeover in progress by another worker — "
            f"BLOCK owner={owner}"
        )
        return False
    except OSError as exc:
        log_warn(f"[DigestLock] Takeover-sentinel create failed: {exc}")
        return False

    try:
        # Re-validate lock freshness after winning the takeover sentinel.
        # Without this second check, a worker that evaluated "stale" earlier
        # could still overwrite a lock that was already refreshed by another
        # worker between stale-check and sentinel-acquire.
        try:
            with open(path, "r", encoding="utf-8") as f:
                current = json.load(f)
            current_acquired = str(current.get("acquired_at", ""))
            current_dt = datetime.fromisoformat(current_acquired.rstrip("Z"))
            if current_dt.tzinfo is None:
                current_dt = current_dt.replace(tzinfo=timezone.utc)
            current_age_s = (datetime.now(tz=timezone.utc) - current_dt).total_seconds()
            if current_age_s < timeout_s:
                log_warn(
                    f"[DigestLock] Takeover re-check: lock refreshed by "
                    f"owner={current.get('owner')} age={current_age_s:.0f}s "
                    f"< timeout={timeout_s}s — BLOCK"
                )
                return False
        except FileNotFoundError:
            # Lock disappeared between checks; proceed with takeover write.
            pass
        except Exception as exc:
            # Fail-open for malformed lock payloads: winner repairs lock file.
            log_warn(f"[DigestLock] Takeover re-check parse failed: {exc} — proceeding")

        dir_ = os.path.dirname(path)
        fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(lock_payload.decode("utf-8"))
        os.replace(tmp, path)
        log_info(f"[DigestLock] Acquired (stale-takeover) by owner={owner}")
        return True
    except Exception as exc:
        log_warn(f"[DigestLock] Failed to write lock: {exc}")
        return False
    finally:
        try:
            os.unlink(takeover_path)
        except Exception:
            pass


def release(owner: str) -> bool:
    """Release lock if owned by `owner`. Returns True if released."""
    path = _lock_path()
    if not os.path.exists(path):
        return True
    try:
        with open(path, "r", encoding="utf-8") as f:
            lock_data = json.load(f)
        if lock_data.get("owner") != owner:
            log_warn(
                f"[DigestLock] Cannot release: held by {lock_data.get('owner')}, "
                f"not by {owner}"
            )
            return False
        os.unlink(path)
        log_info(f"[DigestLock] Released by owner={owner}")
        return True
    except Exception as exc:
        log_warn(f"[DigestLock] Failed to release: {exc}")
        return False


def get_lock_info() -> Optional[dict]:
    """Return current lock info dict, or None if unlocked."""
    path = _lock_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def get_lock_status() -> dict:
    """
    Return structured lock status dict consumed by the runtime API.

    Returns:
        {
          "status":    "FREE" | "LOCKED",
          "owner":     str | None,
          "since":     ISO str | None,
          "timeout_s": int,
          "stale":     bool | None,   # None when FREE; True when age > timeout_s
        }
    """
    lock_info = get_lock_info()
    timeout_s = _timeout_s()
    if lock_info is None:
        return {
            "status":    "FREE",
            "owner":     None,
            "since":     None,
            "timeout_s": timeout_s,
            "stale":     None,
        }
    since = lock_info.get("acquired_at")
    stale: Optional[bool] = None
    if since:
        try:
            dt = datetime.fromisoformat(since.rstrip("Z"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age_s = (datetime.now(tz=timezone.utc) - dt).total_seconds()
            stale = age_s > timeout_s
        except Exception:
            pass
    return {
        "status":    "LOCKED",
        "owner":     lock_info.get("owner"),
        "since":     since,
        "timeout_s": timeout_s,
        "stale":     stale,
    }


# ── Context manager ───────────────────────────────────────────────────────────

class DigestLock:
    """Context manager wrapper around acquire/release."""

    def __init__(self, owner: str) -> None:
        self._owner    = owner
        self._acquired = False

    def __enter__(self) -> "DigestLock":
        self._acquired = acquire(self._owner)
        return self

    def __exit__(self, *args) -> None:
        if self._acquired:
            release(self._owner)

    @property
    def acquired(self) -> bool:
        return self._acquired
