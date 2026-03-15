"""
Storage Broker — Audit Log (SQLite)
════════════════════════════════════
Every write-intent operation is logged here, including dry-runs.
Schema: id, operation, target, actor, dry_run, before_state, after_state, result, error, created_at
"""

import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import List, Optional
from .models import AuditEntry

DB_PATH = os.environ.get("STORAGE_BROKER_DB", "/app/data/storage_broker.db")
_LOCK = threading.Lock()


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db():
    with _LOCK:
        c = _conn()
        try:
            c.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation   TEXT NOT NULL,
                    target      TEXT NOT NULL,
                    actor       TEXT DEFAULT 'trion',
                    dry_run     INTEGER DEFAULT 1,
                    before_state TEXT DEFAULT '',
                    after_state  TEXT DEFAULT '',
                    result       TEXT DEFAULT '',
                    error        TEXT DEFAULT '',
                    created_at   TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            c.commit()
        finally:
            c.close()


def log_operation(
    operation: str,
    target: str,
    actor: str = "trion",
    dry_run: bool = True,
    before_state: str = "",
    after_state: str = "",
    result: str = "",
    error: str = "",
) -> int:
    """Insert an audit record. Returns the new row id."""
    with _LOCK:
        c = _conn()
        try:
            cur = c.execute(
                """INSERT INTO audit_log
                   (operation, target, actor, dry_run, before_state, after_state, result, error, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (operation, target, actor, int(dry_run),
                 before_state, after_state, result, error,
                 datetime.now(timezone.utc).isoformat()),
            )
            c.commit()
            return cur.lastrowid
        finally:
            c.close()


def get_log(limit: int = 50, operation: Optional[str] = None) -> List[AuditEntry]:
    with _LOCK:
        c = _conn()
        try:
            if operation:
                rows = c.execute(
                    "SELECT * FROM audit_log WHERE operation=? ORDER BY id DESC LIMIT ?",
                    (operation, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [AuditEntry(**dict(r)) for r in rows]
        finally:
            c.close()
