import importlib
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


class TestSqlMemoryLegacyEmbeddingMigration(unittest.TestCase):
    def test_init_db_handles_legacy_embeddings_table_without_embedding_version(self):
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
                    CREATE TABLE embeddings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        conversation_id TEXT NOT NULL,
                        content TEXT NOT NULL,
                        content_type TEXT DEFAULT 'fact',
                        metadata TEXT,
                        embedding BLOB,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
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

                db.init_db()
                db.migrate_db()

                conn = sqlite3.connect(db_path)
                try:
                    cols = {
                        r[1] for r in conn.execute("PRAGMA table_info(embeddings)").fetchall()
                    }
                finally:
                    conn.close()

                self.assertIn("embedding_model", cols)
                self.assertIn("embedding_dim", cols)
                self.assertIn("embedding_version", cols)
            finally:
                if prev_db_path is None:
                    os.environ.pop("DB_PATH", None)
                else:
                    os.environ["DB_PATH"] = prev_db_path


if __name__ == "__main__":
    unittest.main()
