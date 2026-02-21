import os
import sqlite3
from datetime import datetime
from typing import Optional, Dict, List

from .config import DB_PATH


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        # Basistabelle
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT,
                role TEXT,
                content TEXT,
                tags TEXT,
                layer TEXT DEFAULT 'auto',
                created_at TEXT
            )
            """
        )

        # Tabelle für strukturierte Fakten
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT,
                subject TEXT,
                key TEXT,
                value TEXT,
                layer TEXT DEFAULT 'ltm',
                created_at TEXT
            )
            """
        )

        # Tabelle für Skill-Metriken
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS skill_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_id TEXT UNIQUE NOT NULL,
                version TEXT DEFAULT '1.0',
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                avg_exec_time_ms REAL DEFAULT 0,
                last_error TEXT,
                status TEXT DEFAULT 'active',
                created_at TEXT,
                updated_at TEXT
            )
            """
        )

        # Workspace Entries table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workspace_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                content TEXT NOT NULL,
                entry_type TEXT DEFAULT 'observation',
                source_layer TEXT DEFAULT 'thinking',
                created_at TEXT NOT NULL,
                updated_at TEXT,
                promoted BOOLEAN DEFAULT 0,
                promoted_at TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_workspace_conv ON workspace_entries(conversation_id)"
        )

        # ═══════════════════════════════════════════════════════════
        # TASK LIFECYCLE TABLES (Phase 2 - Week 2)
        # ═══════════════════════════════════════════════════════════

        # Active Task Memory (high-speed, max 10 items per conversation)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task_active (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                importance_score FLOAT DEFAULT 0.0,
                UNIQUE(task_id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_active_conv ON task_active(conversation_id, last_updated DESC)"
        )

        # Task Archive (long-term storage, linked to embeddings)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task_archive (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                content TEXT NOT NULL,
                archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                embedding_id INTEGER,
                UNIQUE(task_id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_archive_conv ON task_archive(conversation_id)"
        )

        # API Secrets (verschlüsselt gespeichert)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS secrets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                encrypted_value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT
            )
            """
        )

        conn.commit()
    finally:
        conn.close()


def _get_cipher():
    """Fernet cipher mit Master-Key aus Env-Var."""
    import base64, hashlib
    from cryptography.fernet import Fernet
    master = os.getenv("SECRET_MASTER_KEY", "jarvis-default-secret-key-change-me")
    key = base64.urlsafe_b64encode(hashlib.sha256(master.encode()).digest())
    return Fernet(key)


def save_secret(name: str, value: str):
    cipher = _get_cipher()
    encrypted = cipher.encrypt(value.encode()).decode()
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT INTO secrets (name, encrypted_value, created_at, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET encrypted_value=excluded.encrypted_value, updated_at=excluded.updated_at",
            (name, encrypted, now, now)
        )
        conn.commit()
    finally:
        conn.close()


def get_secret_value(name: str) -> Optional[str]:
    cipher = _get_cipher()
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute("SELECT encrypted_value FROM secrets WHERE name=?", (name,)).fetchone()
        if not row:
            return None
        return cipher.decrypt(row[0].encode()).decode()
    finally:
        conn.close()


def list_secrets() -> List[Dict]:
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute("SELECT name, created_at, updated_at FROM secrets ORDER BY name").fetchall()
        return [{"name": r[0], "created_at": r[1], "updated_at": r[2]} for r in rows]
    finally:
        conn.close()


def delete_secret(name: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute("DELETE FROM secrets WHERE name=?", (name,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def migrate_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Layer-Spalte prüfen
    cur.execute("PRAGMA table_info(memory)")
    columns = [row[1] for row in cur.fetchall()]
    if "layer" not in columns:
        cur.execute("ALTER TABLE memory ADD COLUMN layer TEXT DEFAULT 'auto'")

    # Facts-Tabelle prüfen
    cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='facts';
    """)
    if not cur.fetchone():
        cur.execute(
            """
            CREATE TABLE facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT,
                subject TEXT,
                key TEXT,
                value TEXT,
                layer TEXT DEFAULT 'ltm',
                created_at TEXT
            )
            """
        )

    # skill_metrics Tabelle prüfen
    cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='skill_metrics';
    """)
    if not cur.fetchone():
        cur.execute(
            """
            CREATE TABLE skill_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_id TEXT UNIQUE NOT NULL,
                version TEXT DEFAULT '1.0',
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                avg_exec_time_ms REAL DEFAULT 0,
                last_error TEXT,
                status TEXT DEFAULT 'active',
                created_at TEXT,
                updated_at TEXT
            )
            """
        )

    # workspace_entries Tabelle prüfen
    cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='workspace_entries';
    """)
    if not cur.fetchone():
        cur.execute(
            """
            CREATE TABLE workspace_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                content TEXT NOT NULL,
                entry_type TEXT DEFAULT 'observation',
                source_layer TEXT DEFAULT 'thinking',
                created_at TEXT NOT NULL,
                updated_at TEXT,
                promoted BOOLEAN DEFAULT 0,
                promoted_at TEXT
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_workspace_conv ON workspace_entries(conversation_id)"
        )

    # graph_nodes: add confidence if table exists and column missing
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='graph_nodes'")
    if cur.fetchone():
        cur.execute("PRAGMA table_info(graph_nodes)")
        graph_columns = [row[1] for row in cur.fetchall()]
        if "confidence" not in graph_columns:
            cur.execute("ALTER TABLE graph_nodes ADD COLUMN confidence REAL DEFAULT 0.5")

    # FTS5 prüfen
    cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='memory_fts';
    """)
    exists = cur.fetchone()

    if not exists:
        cur.execute("""
            CREATE VIRTUAL TABLE memory_fts USING fts5(
                content,
                conversation_id,
                role,
                tags,
                layer,
                created_at,
                content='memory',
                content_rowid='id'
            );
        """)

        cur.execute("""
            CREATE TRIGGER memory_ai AFTER INSERT ON memory BEGIN
                INSERT INTO memory_fts(rowid, content, conversation_id, role, tags, layer, created_at)
                VALUES (new.id, new.content, new.conversation_id, new.role, new.tags, new.layer, new.created_at);
            END;
        """)

        cur.execute("""
            CREATE TRIGGER memory_au AFTER UPDATE ON memory BEGIN
                UPDATE memory_fts
                SET content=new.content,
                    conversation_id=new.conversation_id,
                    role=new.role,
                    tags=new.tags,
                    layer=new.layer,
                    created_at=new.created_at
                WHERE rowid=new.id;
            END;
        """)

        cur.execute("""
            CREATE TRIGGER memory_ad AFTER DELETE ON memory BEGIN
                DELETE FROM memory_fts WHERE rowid=old.id;
            END;
        """)

    # ═══════════════════════════════════════════════════════════
    # TASK LIFECYCLE MIGRATION (Phase 2 - Week 2)
    # ═══════════════════════════════════════════════════════════

    # task_active table
    cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='task_active';
    """)
    if not cur.fetchone():
        cur.execute(
            """
            CREATE TABLE task_active (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                importance_score FLOAT DEFAULT 0.0,
                UNIQUE(task_id)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_active_conv ON task_active(conversation_id, last_updated DESC)"
        )

    # task_archive table
    cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='task_archive';
    """)
    if not cur.fetchone():
        cur.execute(
            """
            CREATE TABLE task_archive (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                content TEXT NOT NULL,
                archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                embedding_id INTEGER,
                UNIQUE(task_id)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_archive_conv ON task_archive(conversation_id)"
        )

    conn.commit()
    conn.close()


def insert_row(conversation_id: str, role: str, content: str,
               tags: Optional[str], layer: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO memory
            (conversation_id, role, content, tags, layer, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_id,
                role,
                content,
                tags or "",
                layer,
                datetime.utcnow().isoformat(timespec="seconds") + "Z",
            )
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def insert_fact(conversation_id: str, subject: str, key: str, value: str,
                layer: str = "ltm") -> int:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO facts
            (conversation_id, subject, key, value, layer, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_id,
                subject,
                key,
                value,
                layer,
                datetime.utcnow().isoformat(timespec="seconds") + "Z",
            )
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# MEMORY rows
def row_to_memory_dict(row) -> Dict:
    return {
        "id": row[0],
        "conversation_id": row[1],
        "role": row[2],
        "content": row[3],
        "tags": row[4],
        "layer": row[5],
        "created_at": row[6],
    }


# FACT rows
def row_to_fact_dict(row) -> Dict:
    return {
        "id": row[0],
        "conversation_id": row[1],
        "subject": row[2],
        "key": row[3],
        "value": row[4],
        "layer": row[5],
        "created_at": row[6],
    }


def upsert_skill_metric(skill_id: str, success: bool, exec_time_ms: float,
                        error: Optional[str] = None, version: str = "1.0") -> int:
    """Record a skill execution result. Creates or updates the metric row."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"

        cur.execute("SELECT id, success_count, failure_count, avg_exec_time_ms FROM skill_metrics WHERE skill_id = ?", (skill_id,))
        row = cur.fetchone()

        if row:
            old_id, s_count, f_count, avg_time = row
            total = s_count + f_count
            new_avg = ((avg_time * total) + exec_time_ms) / (total + 1) if total > 0 else exec_time_ms

            if success:
                cur.execute(
                    """UPDATE skill_metrics
                       SET success_count = success_count + 1,
                           avg_exec_time_ms = ?, version = ?, updated_at = ?
                       WHERE skill_id = ?""",
                    (new_avg, version, now, skill_id)
                )
            else:
                cur.execute(
                    """UPDATE skill_metrics
                       SET failure_count = failure_count + 1,
                           avg_exec_time_ms = ?, last_error = ?, version = ?, updated_at = ?
                       WHERE skill_id = ?""",
                    (new_avg, error, version, now, skill_id)
                )
            conn.commit()
            return old_id
        else:
            cur.execute(
                """INSERT INTO skill_metrics
                   (skill_id, version, success_count, failure_count, avg_exec_time_ms, last_error, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
                (skill_id, version, 1 if success else 0, 0 if success else 1,
                 exec_time_ms, error, now, now)
            )
            conn.commit()
            return cur.lastrowid
    finally:
        conn.close()


def get_skill_metric(skill_id: str) -> Optional[Dict]:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM skill_metrics WHERE skill_id = ?", (skill_id,))
        row = cur.fetchone()
        if not row:
            return None
        return _row_to_skill_metric(row)
    finally:
        conn.close()


def list_skill_metrics(status: Optional[str] = None, limit: int = 50) -> List[Dict]:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        if status:
            cur.execute("SELECT * FROM skill_metrics WHERE status = ? ORDER BY updated_at DESC LIMIT ?", (status, limit))
        else:
            cur.execute("SELECT * FROM skill_metrics ORDER BY updated_at DESC LIMIT ?", (limit,))
        return [_row_to_skill_metric(r) for r in cur.fetchall()]
    finally:
        conn.close()


def update_skill_status(skill_id: str, status: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        cur.execute("UPDATE skill_metrics SET status = ?, updated_at = ? WHERE skill_id = ?", (status, now, skill_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _row_to_skill_metric(row) -> Dict:
    return {
        "id": row[0],
        "skill_id": row[1],
        "version": row[2],
        "success_count": row[3],
        "failure_count": row[4],
        "avg_exec_time_ms": row[5],
        "last_error": row[6],
        "status": row[7],
        "created_at": row[8],
        "updated_at": row[9],
    }


# ═══════════════════════════════════════════════════════════
# WORKSPACE ENTRIES CRUD
# ═══════════════════════════════════════════════════════════

def save_workspace_entry(
    conversation_id: str,
    content: str,
    entry_type: str = "observation",
    source_layer: str = "thinking"
) -> int:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        cur.execute(
            """
            INSERT INTO workspace_entries
            (conversation_id, content, entry_type, source_layer, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (conversation_id, content, entry_type, source_layer, now)
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_workspace_entries(
    conversation_id: Optional[str] = None,
    limit: int = 50,
    entry_type: Optional[str] = None
) -> List[Dict]:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        conditions = []
        params = []
        if conversation_id:
            conditions.append("conversation_id = ?")
            params.append(conversation_id)
        if entry_type:
            conditions.append("entry_type = ?")
            params.append(entry_type)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        cur.execute(
            f"""
            SELECT id, conversation_id, content, entry_type, source_layer,
                   created_at, updated_at, promoted, promoted_at
            FROM workspace_entries
            {where}
            ORDER BY id DESC LIMIT ?
            """,
            (*params, limit)
        )
        return [_row_to_workspace_entry(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_workspace_entry(entry_id: int) -> Optional[Dict]:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, conversation_id, content, entry_type, source_layer,
                   created_at, updated_at, promoted, promoted_at
            FROM workspace_entries WHERE id = ?
            """,
            (entry_id,)
        )
        row = cur.fetchone()
        return _row_to_workspace_entry(row) if row else None
    finally:
        conn.close()


def update_workspace_entry(entry_id: int, content: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        cur.execute(
            "UPDATE workspace_entries SET content = ?, updated_at = ? WHERE id = ?",
            (content, now, entry_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_workspace_entry(entry_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM workspace_entries WHERE id = ?", (entry_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_unpromoted_entries() -> List[Dict]:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, conversation_id, content, entry_type, source_layer,
                   created_at, updated_at, promoted, promoted_at
            FROM workspace_entries
            WHERE promoted = 0
            ORDER BY id ASC
            """
        )
        return [_row_to_workspace_entry(r) for r in cur.fetchall()]
    finally:
        conn.close()


def mark_promoted(entry_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        cur.execute(
            "UPDATE workspace_entries SET promoted = 1, promoted_at = ? WHERE id = ?",
            (now, entry_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _row_to_workspace_entry(row) -> Dict:
    return {
        "id": row[0],
        "conversation_id": row[1],
        "content": row[2],
        "entry_type": row[3],
        "source_layer": row[4],
        "created_at": row[5],
        "updated_at": row[6],
        "promoted": bool(row[7]),
        "promoted_at": row[8],
    }


def load_fact(conversation_id: str, key: str) -> Optional[str]:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT value
            FROM facts
            WHERE conversation_id = ?
              AND key = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (conversation_id, key)
        )
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()