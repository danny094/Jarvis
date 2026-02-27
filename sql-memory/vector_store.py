# sql-memory/vector_store.py
"""
Vector Store - Speichert und sucht Embeddings in SQLite.

Scope 3.2:
  - Versionierung pro Vektor: embedding_model, embedding_dim, embedding_version.
  - Suchanfragen filtern standardmaessig auf aktive embedding_version
    (kein stilles Mischen alter/neuer Vektoren).
  - Re-Embedding/Backfill in Batches fuer veraltete Versionen.
"""

import json
import logging
import sqlite3
from typing import Any, Dict, List, Optional

from embedding import (
    cosine_similarity,
    get_active_embedding_version,
    get_embedding,
    get_embedding_with_metadata,
)
from memory_mcp.config import DB_PATH

logger = logging.getLogger(__name__)


class VectorStore:
    """SQLite-basierter Vector Store."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_table()

    def _init_table(self):
        """Erstellt/Migriert die Embedding-Tabelle."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS embeddings (
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
            self._migrate_embedding_schema(cursor)
            conn.commit()
            logger.info("[VectorStore] Table initialized/migrated")
        finally:
            conn.close()

    @staticmethod
    def _migrate_embedding_schema(cursor: sqlite3.Cursor) -> None:
        """Add missing Scope-3.2 columns/indexes on legacy DBs."""
        cursor.execute("PRAGMA table_info(embeddings)")
        cols = {row[1] for row in cursor.fetchall()}

        if "embedding_model" not in cols:
            cursor.execute("ALTER TABLE embeddings ADD COLUMN embedding_model TEXT")
        if "embedding_dim" not in cols:
            cursor.execute("ALTER TABLE embeddings ADD COLUMN embedding_dim INTEGER")
        if "embedding_version" not in cols:
            cursor.execute("ALTER TABLE embeddings ADD COLUMN embedding_version TEXT")

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_embeddings_conv ON embeddings(conversation_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_embeddings_version ON embeddings(embedding_version)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_embeddings_type_version "
            "ON embeddings(content_type, embedding_version)"
        )

    def add(
        self,
        conversation_id: str,
        content: str,
        content_type: str = "fact",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[int]:
        """
        Fuegt einen Eintrag mit Embedding hinzu (inkl. Version-Metadaten).
        """
        emb = get_embedding_with_metadata(content)
        if not emb:
            logger.error("[VectorStore] Could not generate embedding")
            return None

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO embeddings
                (conversation_id, content, content_type, metadata, embedding,
                 embedding_model, embedding_dim, embedding_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    content,
                    content_type,
                    json.dumps(metadata) if metadata else None,
                    json.dumps(emb["embedding"]),
                    emb["embedding_model"],
                    emb["embedding_dim"],
                    emb["embedding_version"],
                ),
            )
            conn.commit()
            entry_id = cursor.lastrowid
            logger.info(
                "[VectorStore] Added entry %s version=%s",
                entry_id,
                emb["embedding_version"],
            )
            return entry_id
        except Exception as e:
            logger.error(f"[VectorStore] Error adding: {e}")
            return None
        finally:
            conn.close()

    def search(
        self,
        query: str,
        conversation_id: Optional[str] = None,
        limit: int = 5,
        min_similarity: float = 0.5,
        content_type: Optional[str] = None,
        allow_mixed_versions: bool = False,
        embedding_version: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Semantische Suche nach aehnlichen Eintraegen.

        Default: kein Mixing. Es wird nur die aktive embedding_version gelesen.
        """
        query_embedding = get_embedding(query)
        if not query_embedding:
            return []

        version_filter: Optional[str] = embedding_version
        if version_filter is None and not allow_mixed_versions:
            version_filter = get_active_embedding_version()

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            sql = (
                "SELECT id, content, content_type, metadata, embedding, "
                "embedding_model, embedding_dim, embedding_version "
                "FROM embeddings WHERE 1=1"
            )
            params: List[Any] = []

            if conversation_id:
                sql += " AND (conversation_id = ? OR conversation_id = 'global')"
                params.append(conversation_id)

            if content_type:
                sql += " AND content_type = ?"
                params.append(content_type)

            if version_filter:
                sql += " AND embedding_version = ?"
                params.append(version_filter)

            cursor.execute(sql, params)
            rows = cursor.fetchall()
        finally:
            conn.close()

        results = []
        for row in rows:
            (
                entry_id,
                content_val,
                ctype,
                metadata_json,
                embedding_json,
                emb_model,
                emb_dim,
                emb_version,
            ) = row
            if not embedding_json:
                continue
            try:
                stored_embedding = json.loads(embedding_json)
                similarity = cosine_similarity(query_embedding, stored_embedding)
                if similarity >= min_similarity:
                    results.append(
                        {
                            "id": entry_id,
                            "content": content_val,
                            "type": ctype,
                            "metadata": json.loads(metadata_json) if metadata_json else {},
                            "similarity": round(similarity, 4),
                            "embedding_model": emb_model,
                            "embedding_dim": emb_dim,
                            "embedding_version": emb_version,
                        }
                    )
            except Exception:
                continue

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:limit]

    def get_version_status(
        self,
        conversation_id: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Status fuer aktive vs. veraltete embedding-Versionen."""
        active_version = get_active_embedding_version()
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            sql = (
                "SELECT embedding_version, COUNT(*) "
                "FROM embeddings WHERE 1=1"
            )
            params: List[Any] = []
            if conversation_id:
                sql += " AND conversation_id = ?"
                params.append(conversation_id)
            if content_type:
                sql += " AND content_type = ?"
                params.append(content_type)
            sql += " GROUP BY embedding_version"
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        finally:
            conn.close()

        by_version = {row[0] or "null": int(row[1]) for row in rows}
        total = sum(by_version.values())
        active_count = int(by_version.get(active_version, 0))
        return {
            "active_version": active_version,
            "total": total,
            "active_count": active_count,
            "stale_count": max(0, total - active_count),
            "by_version": by_version,
        }

    def backfill_embeddings(
        self,
        batch_size: int = 100,
        conversation_id: Optional[str] = None,
        content_type: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Re-embedding Batch fuer veraltete/fehlende embedding_version.
        Resume-faehig: naechster Aufruf arbeitet Restmenge weiter ab.
        """
        active_version = get_active_embedding_version()
        status_before = self.get_version_status(conversation_id, content_type)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            where = [
                "(embedding_version IS NULL OR embedding_version != ?)"
            ]
            params: List[Any] = [active_version]
            if conversation_id:
                where.append("conversation_id = ?")
                params.append(conversation_id)
            if content_type:
                where.append("content_type = ?")
                params.append(content_type)

            sql = (
                "SELECT id, content FROM embeddings WHERE "
                + " AND ".join(where)
                + " ORDER BY id ASC LIMIT ?"
            )
            params.append(batch_size)
            rows = conn.execute(sql, params).fetchall()

            if dry_run:
                return {
                    "success": True,
                    "dry_run": True,
                    "active_version": active_version,
                    "selected": len(rows),
                    "processed": 0,
                    "failed": 0,
                    "remaining_stale": status_before["stale_count"],
                }

            processed = 0
            failed = 0
            for row in rows:
                emb = get_embedding_with_metadata(row["content"])
                if not emb:
                    failed += 1
                    continue
                conn.execute(
                    """
                    UPDATE embeddings
                    SET embedding = ?, embedding_model = ?, embedding_dim = ?, embedding_version = ?
                    WHERE id = ?
                    """,
                    (
                        json.dumps(emb["embedding"]),
                        emb["embedding_model"],
                        emb["embedding_dim"],
                        emb["embedding_version"],
                        row["id"],
                    ),
                )
                processed += 1

            conn.commit()
        finally:
            conn.close()

        status_after = self.get_version_status(conversation_id, content_type)
        return {
            "success": True,
            "active_version": active_version,
            "selected": len(rows),
            "processed": processed,
            "failed": failed,
            "remaining_stale": status_after["stale_count"],
        }


# Singleton
_vector_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore(DB_PATH)
    return _vector_store
