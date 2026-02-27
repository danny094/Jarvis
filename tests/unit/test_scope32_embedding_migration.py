from __future__ import annotations

import importlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
_SQL_MEMORY_PATH = os.path.join(_REPO_ROOT, "sql-memory")
if _SQL_MEMORY_PATH not in sys.path:
    sys.path.insert(0, _SQL_MEMORY_PATH)


class TestScope32VectorStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "memory.db")
        self.vector_store = importlib.import_module("vector_store")
        self.vs = self.vector_store.VectorStore(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def test_add_persists_embedding_version_metadata(self):
        emb_payload = {
            "embedding": [0.1, 0.2, 0.3],
            "embedding_model": "mxbai:v1",
            "embedding_dim": 3,
            "embedding_version": "embv1_test123",
            "runtime_policy": "auto",
        }
        with patch.object(self.vector_store, "get_embedding_with_metadata", return_value=emb_payload):
            row_id = self.vs.add("c1", "hello world", "fact", {"k": "v"})
        self.assertIsNotNone(row_id)

        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT embedding_model, embedding_dim, embedding_version FROM embeddings WHERE id = ?",
                (row_id,),
            ).fetchone()
            self.assertEqual(row[0], "mxbai:v1")
            self.assertEqual(row[1], 3)
            self.assertEqual(row[2], "embv1_test123")
        finally:
            conn.close()

    def test_search_default_active_only_avoids_mixing(self):
        conn = self._conn()
        try:
            conn.execute(
                """
                INSERT INTO embeddings
                (conversation_id, content, content_type, metadata, embedding,
                 embedding_model, embedding_dim, embedding_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("c1", "active-row", "fact", "{}", json.dumps([1.0, 0.0]), "model-a", 2, "v-active"),
            )
            conn.execute(
                """
                INSERT INTO embeddings
                (conversation_id, content, content_type, metadata, embedding,
                 embedding_model, embedding_dim, embedding_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("c1", "stale-row", "fact", "{}", json.dumps([1.0, 0.0]), "model-b", 2, "v-old"),
            )
            conn.commit()
        finally:
            conn.close()

        with patch.object(self.vector_store, "get_embedding", return_value=[1.0, 0.0]), patch.object(
            self.vector_store, "get_active_embedding_version", return_value="v-active"
        ):
            only_active = self.vs.search("query", conversation_id="c1", min_similarity=0.0)
            mixed = self.vs.search(
                "query",
                conversation_id="c1",
                min_similarity=0.0,
                allow_mixed_versions=True,
            )

        self.assertEqual(len(only_active), 1)
        self.assertEqual(only_active[0]["content"], "active-row")
        self.assertEqual(len(mixed), 2)

    def test_backfill_reembeds_stale_rows(self):
        conn = self._conn()
        try:
            conn.execute(
                """
                INSERT INTO embeddings
                (conversation_id, content, content_type, metadata, embedding,
                 embedding_model, embedding_dim, embedding_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("c1", "needs-reembed", "fact", "{}", json.dumps([0.0, 1.0]), "old-model", 2, "v-old"),
            )
            conn.commit()
        finally:
            conn.close()

        emb_payload = {
            "embedding": [0.3, 0.4, 0.5],
            "embedding_model": "new-model",
            "embedding_dim": 3,
            "embedding_version": "v-new",
            "runtime_policy": "auto",
        }
        with patch.object(self.vector_store, "get_active_embedding_version", return_value="v-new"), patch.object(
            self.vector_store, "get_embedding_with_metadata", return_value=emb_payload
        ):
            result = self.vs.backfill_embeddings(batch_size=10)

        self.assertTrue(result["success"])
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["remaining_stale"], 0)

        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT embedding_model, embedding_dim, embedding_version, embedding FROM embeddings"
            ).fetchone()
            self.assertEqual(row[0], "new-model")
            self.assertEqual(row[1], 3)
            self.assertEqual(row[2], "v-new")
            self.assertEqual(json.loads(row[3]), [0.3, 0.4, 0.5])
        finally:
            conn.close()


class TestScope32ArchiveManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "archive.db")
        self.archive_mod = importlib.import_module("core.lifecycle.archive")
        self.prev_db_path = self.archive_mod.DB_PATH
        self.prev_schema_ready = self.archive_mod._EMBED_SCHEMA_READY
        self.archive_mod.DB_PATH = self.db_path
        self.archive_mod._EMBED_SCHEMA_READY = False

        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
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
            conn.execute(
                """
                CREATE TABLE embeddings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_type TEXT DEFAULT 'fact',
                    metadata TEXT,
                    embedding BLOB,
                    embedding_model TEXT,
                    embedding_dim INTEGER,
                    embedding_version TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        self.archive_mod.DB_PATH = self.prev_db_path
        self.archive_mod._EMBED_SCHEMA_READY = self.prev_schema_ready
        self.tmp.cleanup()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def test_process_pending_embeddings_reembeds_stale_archive_rows(self):
        content_json = json.dumps(
            {
                "status": "completed",
                "summary": "old summary",
                "context": {"user_text": "old summary"},
            }
        )
        conn = self._conn()
        try:
            conn.execute(
                """
                INSERT INTO embeddings
                (id, conversation_id, content, content_type, metadata, embedding,
                 embedding_model, embedding_dim, embedding_version)
                VALUES (1, 'c1', 'old summary', 'task', '{}', ?, 'old-model', 2, 'v-old')
                """,
                (json.dumps([0.1, 0.2]),),
            )
            conn.execute(
                """
                INSERT INTO task_archive
                (id, conversation_id, task_id, content, embedding_id)
                VALUES (1, 'c1', 'task_1', ?, 1)
                """,
                (content_json,),
            )
            conn.commit()
        finally:
            conn.close()

        with patch.object(self.archive_mod, "_get_embedding", return_value=[0.9, 0.8, 0.7]), patch.object(
            self.archive_mod, "get_embedding_model", return_value="new-model"
        ), patch.object(self.archive_mod, "get_embedding_runtime_policy", return_value="auto"):
            mgr = self.archive_mod.TaskArchiveManager()
            processed = mgr.process_pending_embeddings(batch_size=10)

        self.assertEqual(processed, 1)

        expected_version = self.archive_mod._compute_embedding_version_id("new-model", "auto")
        conn = self._conn()
        try:
            row = conn.execute(
                """
                SELECT e.embedding_model, e.embedding_dim, e.embedding_version, e.embedding
                FROM embeddings e
                JOIN task_archive a ON a.embedding_id = e.id
                WHERE a.task_id = 'task_1'
                """
            ).fetchone()
            self.assertEqual(row["embedding_model"], "new-model")
            self.assertEqual(row["embedding_dim"], 3)
            self.assertEqual(row["embedding_version"], expected_version)
            self.assertEqual(json.loads(row["embedding"]), [0.9, 0.8, 0.7])
        finally:
            conn.close()

    def test_semantic_search_filters_by_active_version(self):
        active_version = self.archive_mod._compute_embedding_version_id("active-model", "auto")
        conn = self._conn()
        try:
            conn.execute(
                """
                INSERT INTO embeddings
                (id, conversation_id, content, content_type, metadata, embedding,
                 embedding_model, embedding_dim, embedding_version)
                VALUES (1, 'c1', 'active summary', 'task', '{}', ?, 'active-model', 2, ?)
                """,
                (json.dumps([1.0, 0.0]), active_version),
            )
            conn.execute(
                """
                INSERT INTO embeddings
                (id, conversation_id, content, content_type, metadata, embedding,
                 embedding_model, embedding_dim, embedding_version)
                VALUES (2, 'c1', 'stale summary', 'task', '{}', ?, 'old-model', 2, 'v-old')
                """,
                (json.dumps([1.0, 0.0]),),
            )
            conn.execute(
                """
                INSERT INTO task_archive (id, conversation_id, task_id, content, embedding_id)
                VALUES (1, 'c1', 'task_active', ?, 1)
                """,
                (json.dumps({"summary": "active"}),),
            )
            conn.execute(
                """
                INSERT INTO task_archive (id, conversation_id, task_id, content, embedding_id)
                VALUES (2, 'c1', 'task_stale', ?, 2)
                """,
                (json.dumps({"summary": "stale"}),),
            )
            conn.commit()
        finally:
            conn.close()

        with patch.object(self.archive_mod, "get_embedding_model", return_value="active-model"), patch.object(
            self.archive_mod, "get_embedding_runtime_policy", return_value="auto"
        ):
            mgr = self.archive_mod.TaskArchiveManager()
            results = mgr._semantic_search(
                query_embedding=[1.0, 0.0],
                conversation_id="c1",
                limit=10,
                min_similarity=0.0,
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["task_id"], "task_active")
        self.assertEqual(results[0]["embedding_version"], active_version)


if __name__ == "__main__":
    unittest.main()
