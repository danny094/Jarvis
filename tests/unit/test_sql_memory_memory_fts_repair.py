import importlib
import os
import sqlite3
import sys
import tempfile
from pathlib import Path


def test_insert_row_repairs_broken_memory_fts_state():
    root = Path(__file__).resolve().parents[2]
    sql_memory_root = root / "sql-memory"
    if str(sql_memory_root) not in sys.path:
        sys.path.insert(0, str(sql_memory_root))

    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "memory.db")

        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """
                CREATE TABLE memory (
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
            # Broken trigger references missing/invalid memory_fts.
            conn.execute(
                """
                CREATE TRIGGER memory_ai AFTER INSERT ON memory BEGIN
                    INSERT INTO memory_fts(rowid, content, conversation_id, role, tags, layer, created_at)
                    VALUES (new.id, new.content, new.conversation_id, new.role, new.tags, new.layer, new.created_at);
                END;
                """
            )
            conn.commit()
        finally:
            conn.close()

        prev_db_path = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = db_path
        try:
            cfg = importlib.import_module("memory_mcp.config")
            db = importlib.import_module("memory_mcp.database")
            importlib.reload(cfg)
            importlib.reload(db)

            new_id = db.insert_row("conv-1", "assistant", "hello", "", "stm")
            assert isinstance(new_id, int) and new_id > 0

            conn = sqlite3.connect(db_path)
            try:
                cnt = conn.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0]
            finally:
                conn.close()
            assert cnt == 1
        finally:
            if prev_db_path is None:
                os.environ.pop("DB_PATH", None)
            else:
                os.environ["DB_PATH"] = prev_db_path

