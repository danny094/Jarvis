import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import core.tools.fast_lane.definitions as defs


class TestFastLaneMemoryFtsRepair(unittest.TestCase):
    def test_memory_save_repairs_broken_memory_fts_trigger(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = f"{td}/memory.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE memory (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        conversation_id TEXT,
                        role TEXT,
                        content TEXT,
                        created_at TEXT
                    )
                    """
                )
                # Broken legacy trigger: references memory_fts before table exists.
                conn.execute(
                    """
                    CREATE TRIGGER memory_ai AFTER INSERT ON memory BEGIN
                        INSERT INTO memory_fts(rowid, content, conversation_id, role, created_at)
                        VALUES (new.id, new.content, new.conversation_id, new.role, new.created_at);
                    END;
                    """
                )
                conn.commit()
            finally:
                conn.close()

            def _db_conn():
                c = sqlite3.connect(db_path, timeout=5.0, check_same_thread=False)
                c.row_factory = sqlite3.Row
                return c

            defs._SCHEMA_READY = False
            with patch("core.tools.fast_lane.definitions.get_db_connection", side_effect=_db_conn):
                result = defs.MemorySaveTool(
                    content="hello",
                    role="assistant",
                    conversation_id="conv-1",
                ).execute()

            self.assertIn("Memory saved", result)

            conn = sqlite3.connect(db_path)
            try:
                row = conn.execute("SELECT COUNT(*) FROM memory_fts").fetchone()
                self.assertEqual(row[0], 1)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()

