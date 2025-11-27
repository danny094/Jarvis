import os
import sqlite3
from datetime import datetime
from typing import Optional, Dict

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

        conn.commit()
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