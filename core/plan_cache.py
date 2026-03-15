"""
Shared plan cache backends (memory + sqlite) for Thinking/Sequential plans.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from typing import Dict, Optional

from utils.logger import log_info, log_warn


class PlanCache:
    """
    In-memory TTL cache for plan payloads.
    """

    def __init__(self, ttl_seconds: int = 300):
        self._cache: Dict[str, tuple] = {}
        self._ttl = ttl_seconds
        self._lock = threading.Lock()

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()

    def get(self, text: str) -> Optional[Dict]:
        key = self._key(text)
        with self._lock:
            if key in self._cache:
                ts, plan = self._cache[key]
                if time.time() - ts < self._ttl:
                    return plan
                del self._cache[key]
        return None

    def set(self, text: str, plan: Dict):
        key = self._key(text)
        with self._lock:
            self._cache[key] = (time.time(), plan)
            if len(self._cache) > 200:
                cutoff = time.time() - self._ttl
                self._cache = {
                    k: v for k, v in self._cache.items() if v[0] > cutoff
                }


class SqlitePlanCache:
    """
    SQLite-backed TTL cache for cross-worker cache sharing.
    """

    def __init__(
        self,
        ttl_seconds: int = 300,
        *,
        db_path: str = "/tmp/trion_plan_cache.sqlite",
        namespace: str = "default",
        max_entries: int = 1000,
    ):
        self._ttl = ttl_seconds
        self._db_path = db_path
        self._namespace = namespace
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS plan_cache (
                    namespace TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY(namespace, cache_key)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_plan_cache_ttl ON plan_cache(namespace, created_at)"
            )

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()

    def get(self, text: str) -> Optional[Dict]:
        key = self._key(text)
        now = time.time()
        cutoff = now - self._ttl
        try:
            with self._lock, self._conn() as conn:
                conn.execute(
                    "DELETE FROM plan_cache WHERE namespace=? AND created_at < ?",
                    (self._namespace, cutoff),
                )
                row = conn.execute(
                    """
                    SELECT payload
                    FROM plan_cache
                    WHERE namespace=? AND cache_key=? AND created_at >= ?
                    """,
                    (self._namespace, key, cutoff),
                ).fetchone()
                if not row:
                    return None
                return json.loads(row["payload"])
        except Exception as e:
            log_warn(f"[PlanCache:sqlite] get failed namespace={self._namespace}: {e}")
            return None

    def set(self, text: str, plan: Dict):
        key = self._key(text)
        now = time.time()
        payload = json.dumps(plan, ensure_ascii=False, default=str)
        cutoff = now - self._ttl
        try:
            with self._lock, self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO plan_cache(namespace, cache_key, created_at, payload)
                    VALUES(?,?,?,?)
                    ON CONFLICT(namespace, cache_key)
                    DO UPDATE SET created_at=excluded.created_at, payload=excluded.payload
                    """,
                    (self._namespace, key, now, payload),
                )
                conn.execute(
                    "DELETE FROM plan_cache WHERE namespace=? AND created_at < ?",
                    (self._namespace, cutoff),
                )
                count_row = conn.execute(
                    "SELECT COUNT(*) AS n FROM plan_cache WHERE namespace=?",
                    (self._namespace,),
                ).fetchone()
                count = int(count_row["n"]) if count_row else 0
                if count > self._max_entries:
                    drop = count - self._max_entries
                    conn.execute(
                        """
                        DELETE FROM plan_cache
                        WHERE rowid IN (
                            SELECT rowid FROM plan_cache
                            WHERE namespace=?
                            ORDER BY created_at ASC
                            LIMIT ?
                        )
                        """,
                        (self._namespace, drop),
                    )
        except Exception as e:
            log_warn(f"[PlanCache:sqlite] set failed namespace={self._namespace}: {e}")


def make_plan_cache(ttl_seconds: int, namespace: str):
    backend = os.getenv("TRION_PLAN_CACHE_BACKEND", "sqlite").strip().lower()
    if backend in {"sqlite", "shared", "sqlite_shared"}:
        db_path = os.getenv("TRION_PLAN_CACHE_DB", "/tmp/trion_plan_cache.sqlite")
        try:
            log_info(f"[PlanCache] backend=sqlite namespace={namespace} db={db_path}")
            return SqlitePlanCache(
                ttl_seconds=ttl_seconds,
                db_path=db_path,
                namespace=namespace,
            )
        except Exception as e:
            log_warn(f"[PlanCache] sqlite backend init failed, fallback=memory: {e}")
    return PlanCache(ttl_seconds=ttl_seconds)
