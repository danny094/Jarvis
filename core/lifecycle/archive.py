"""
TaskArchiveManager - Phase 2: Long-term Task Storage + Semantic Search

Responsibilities:
  - Process archived tasks (generate embeddings for task_archive)
  - Semantic search over archived tasks via VectorStore
  - Retry failed embeddings (embedding_id IS NULL)
  - Compact summaries for efficient storage

Decoupled Design (from Spec Risk Analysis):
  - trion-runtime (Fast Lane) only MOVES data to task_archive
  - This SlowLaneWorker processes embeddings INDEPENDENTLY
  - No blocking of the main pipeline

Created: Phase 2 - Week 2 (Task Lifecycle)
"""

import json
import os
import sqlite3
import requests
import logging
import math
from datetime import datetime
from typing import Dict, Any, Optional, List

from utils.logger import log_info, log_error, log_warning

# ═══════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════

DB_PATH = os.getenv("MEMORY_DB_PATH", "/app/memory_data/memory.db")
OLLAMA_URL = os.getenv("OLLAMA_BASE", "http://host.docker.internal:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "hellord/mxbai-embed-large-v1:f16")

# Search defaults
DEFAULT_SEARCH_LIMIT = 5
DEFAULT_MIN_SIMILARITY = 0.5


logger = logging.getLogger(__name__)


def _get_db() -> sqlite3.Connection:
    """Get SQLite connection with WAL mode and busy timeout."""
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


# ═══════════════════════════════════════════════════════════
# EMBEDDING HELPERS (self-contained, no import from sql-memory)
# ═══════════════════════════════════════════════════════════

def _get_embedding(text: str) -> Optional[List[float]]:
    """
    Generate embedding vector via Ollama API.

    Self-contained (no dependency on sql-memory container).
    Uses same model as VectorStore for compatibility.
    """
    if not text or not text.strip():
        return None

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={
                "model": EMBEDDING_MODEL,
                "prompt": text.strip()[:2000],  # Truncate for safety
            },
            timeout=60,
        )
        response.raise_for_status()

        data = response.json()
        embedding = data.get("embedding")

        if embedding:
            return embedding
        else:
            log_error("[ArchiveManager] No embedding in Ollama response")
            return None

    except requests.Timeout:
        log_error("[ArchiveManager] Embedding request timed out (60s)")
        return None
    except Exception as e:
        log_error(f"[ArchiveManager] Embedding generation failed: {e}")
        return None


def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Cosine similarity between two vectors."""
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))

    if norm1 == 0 or norm2 == 0:
        return 0.0

    return dot_product / (norm1 * norm2)


# ═══════════════════════════════════════════════════════════
# ARCHIVE MANAGER
# ═══════════════════════════════════════════════════════════

class TaskArchiveManager:
    """
    Manages long-term task archive with semantic search.

    Architecture:
      task_archive (text) ←→ embeddings (vectors)
      Linked via: task_archive.embedding_id → embeddings.id

    Embedding generation is DECOUPLED:
      1. Task is archived immediately (text only)
      2. process_pending_embeddings() runs later
      3. FTS fallback if embedding not yet ready
    """

    def __init__(self):
        log_info("[ArchiveManager] Initialized")

    # ═══════════════════════════════════════════════════════
    # EMBEDDING PROCESSING (Slow Lane)
    # ═══════════════════════════════════════════════════════

    def process_pending_embeddings(self, batch_size: int = 10) -> int:
        """
        Process archived tasks that don't have embeddings yet.

        Called by MaintenanceWorker or after_request hook.
        Returns number of tasks processed.

        Target: <200ms per task (100ms model + 100ms query).
        """
        processed = 0

        try:
            conn = _get_db()
            try:
                # Find tasks without embeddings
                pending = conn.execute(
                    """
                    SELECT id, conversation_id, task_id, content
                    FROM task_archive
                    WHERE embedding_id IS NULL
                    ORDER BY archived_at ASC
                    LIMIT ?
                    """,
                    (batch_size,)
                ).fetchall()

                if not pending:
                    return 0

                log_info(f"[ArchiveManager] Processing {len(pending)} pending embeddings")

                for task in pending:
                    try:
                        # Build searchable summary from task content
                        content_data = json.loads(task["content"])
                        summary = _build_search_summary(content_data)

                        # Generate embedding
                        embedding = _get_embedding(summary)
                        if not embedding:
                            log_warning(
                                f"[ArchiveManager] Skipping {task['task_id']} "
                                f"(embedding failed, will retry)"
                            )
                            continue

                        # Store embedding in embeddings table
                        embedding_id = self._store_embedding(
                            conn,
                            conversation_id=task["conversation_id"],
                            content=summary,
                            embedding=embedding,
                            metadata={
                                "task_id": task["task_id"],
                                "archive_id": task["id"],
                            },
                        )

                        if embedding_id:
                            # Link back to archive
                            conn.execute(
                                "UPDATE task_archive SET embedding_id = ? WHERE id = ?",
                                (embedding_id, task["id"])
                            )
                            conn.commit()
                            processed += 1
                            log_info(
                                f"[ArchiveManager] Embedded {task['task_id']} "
                                f"→ embedding_id={embedding_id}"
                            )

                    except json.JSONDecodeError:
                        log_error(
                            f"[ArchiveManager] Corrupted content in {task['task_id']}"
                        )
                    except Exception as e:
                        log_error(
                            f"[ArchiveManager] Failed to process {task['task_id']}: {e}"
                        )

            finally:
                conn.close()

        except Exception as e:
            log_error(f"[ArchiveManager] process_pending_embeddings failed: {e}")

        if processed > 0:
            log_info(f"[ArchiveManager] Processed {processed}/{len(pending)} embeddings")

        return processed

    # ═══════════════════════════════════════════════════════
    # SEMANTIC SEARCH
    # ═══════════════════════════════════════════════════════

    def search_archive(
        self,
        query: str,
        conversation_id: Optional[str] = None,
        limit: int = DEFAULT_SEARCH_LIMIT,
        min_similarity: float = DEFAULT_MIN_SIMILARITY,
    ) -> List[Dict[str, Any]]:
        """
        Semantic search over archived tasks.

        Flow:
          1. Generate embedding for query
          2. Search embeddings table (content_type='task')
          3. Join with task_archive for full JSON content
          4. Return ranked results

        Fallback: If embedding fails, uses FTS text search.

        Target: <200ms (100ms model + 100ms query).
        """
        # Try semantic search first
        query_embedding = _get_embedding(query)

        if query_embedding:
            results = self._semantic_search(
                query_embedding, conversation_id, limit, min_similarity
            )
            if results:
                return results

        # Fallback: text search (FTS not available for archive, use LIKE)
        log_info("[ArchiveManager] Falling back to text search")
        return self._text_search(query, conversation_id, limit)

    def _semantic_search(
        self,
        query_embedding: List[float],
        conversation_id: Optional[str],
        limit: int,
        min_similarity: float,
    ) -> List[Dict[str, Any]]:
        """Search using cosine similarity over embeddings."""
        try:
            conn = _get_db()
            try:
                # Fetch task embeddings
                sql = """
                    SELECT e.id, e.content, e.embedding, e.metadata,
                           a.task_id, a.content as archive_content, a.archived_at
                    FROM embeddings e
                    JOIN task_archive a ON a.embedding_id = e.id
                    WHERE e.content_type = 'task'
                """
                params = []

                if conversation_id:
                    sql += " AND (e.conversation_id = ? OR e.conversation_id = 'global')"
                    params.append(conversation_id)

                rows = conn.execute(sql, params).fetchall()

                results = []
                for row in rows:
                    if not row["embedding"]:
                        continue

                    try:
                        stored_embedding = json.loads(row["embedding"])
                        similarity = _cosine_similarity(query_embedding, stored_embedding)

                        if similarity >= min_similarity:
                            # Parse full archive content
                            archive_data = json.loads(row["archive_content"])

                            results.append({
                                "task_id": row["task_id"],
                                "summary": row["content"],
                                "content": archive_data,
                                "similarity": round(similarity, 4),
                                "archived_at": row["archived_at"],
                            })
                    except (json.JSONDecodeError, TypeError):
                        continue

                # Sort by similarity descending
                results.sort(key=lambda x: x["similarity"], reverse=True)
                return results[:limit]

            finally:
                conn.close()

        except Exception as e:
            log_error(f"[ArchiveManager] Semantic search failed: {e}")
            return []

    def _text_search(
        self,
        query: str,
        conversation_id: Optional[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Fallback text search using LIKE on archive content."""
        try:
            conn = _get_db()
            try:
                sql = """
                    SELECT task_id, content, archived_at
                    FROM task_archive
                    WHERE content LIKE ?
                """
                params = [f"%{query}%"]

                if conversation_id:
                    sql += " AND conversation_id = ?"
                    params.append(conversation_id)

                sql += " ORDER BY archived_at DESC LIMIT ?"
                params.append(limit)

                rows = conn.execute(sql, params).fetchall()

                return [
                    {
                        "task_id": row["task_id"],
                        "summary": query,
                        "content": json.loads(row["content"]),
                        "similarity": 0.0,  # No semantic score for text search
                        "archived_at": row["archived_at"],
                        "search_type": "text_fallback",
                    }
                    for row in rows
                ]

            finally:
                conn.close()

        except Exception as e:
            log_error(f"[ArchiveManager] Text search failed: {e}")
            return []

    # ═══════════════════════════════════════════════════════
    # STATS & MONITORING
    # ═══════════════════════════════════════════════════════

    def get_archive_stats(self) -> Dict[str, Any]:
        """Returns archive statistics for monitoring."""
        try:
            conn = _get_db()
            try:
                total = conn.execute(
                    "SELECT COUNT(*) FROM task_archive"
                ).fetchone()[0]

                with_embedding = conn.execute(
                    "SELECT COUNT(*) FROM task_archive WHERE embedding_id IS NOT NULL"
                ).fetchone()[0]

                pending = total - with_embedding

                return {
                    "total_archived": total,
                    "with_embedding": with_embedding,
                    "pending_embedding": pending,
                    "coverage_pct": round(
                        (with_embedding / total * 100) if total > 0 else 0, 1
                    ),
                }
            finally:
                conn.close()

        except Exception as e:
            log_error(f"[ArchiveManager] get_archive_stats failed: {e}")
            return {"error": str(e)}

    # ═══════════════════════════════════════════════════════
    # INTERNAL HELPERS
    # ═══════════════════════════════════════════════════════

    def _store_embedding(
        self,
        conn: sqlite3.Connection,
        conversation_id: str,
        content: str,
        embedding: List[float],
        metadata: Dict[str, Any] = None,
    ) -> Optional[int]:
        """
        Store embedding in the shared embeddings table.

        Uses content_type='task' to segregate from facts.
        Compatible with existing VectorStore.search() filtering.
        """
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO embeddings
                (conversation_id, content, content_type, metadata, embedding, created_at)
                VALUES (?, ?, 'task', ?, ?, ?)
                """,
                (
                    conversation_id,
                    content,
                    json.dumps(metadata) if metadata else None,
                    json.dumps(embedding),
                    datetime.utcnow().isoformat(),
                ),
            )
            return cursor.lastrowid

        except Exception as e:
            log_error(f"[ArchiveManager] _store_embedding failed: {e}")
            return None


# ═══════════════════════════════════════════════════════════
# MODULE-LEVEL HELPERS
# ═══════════════════════════════════════════════════════════

def _build_search_summary(content: Dict) -> str:
    """
    Build a compact, searchable summary from task content JSON.

    This is what gets embedded — needs to capture the SEMANTIC MEANING
    of the task for later retrieval.
    """
    parts = []

    # Status
    status = content.get("status", "unknown")
    parts.append(f"Task {status}.")

    # Summary (user intent)
    summary = content.get("summary", "")
    if summary:
        parts.append(summary)

    # Context user text (truncated)
    ctx = content.get("context", {})
    user_text = ctx.get("user_text", "")
    if user_text and user_text != summary:
        parts.append(user_text[:300])

    # Result info
    result = content.get("result")
    if isinstance(result, dict):
        result_status = result.get("status", "")
        if result_status:
            parts.append(f"Result: {result_status}")

    # Duration
    duration = content.get("duration_s")
    if duration:
        parts.append(f"Duration: {duration}s")

    # Error
    error = content.get("error")
    if error:
        parts.append(f"Error: {error[:200]}")

    return " | ".join(parts)


# ═══════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════

_archive_manager: Optional[TaskArchiveManager] = None


def get_archive_manager() -> TaskArchiveManager:
    """Get singleton TaskArchiveManager instance."""
    global _archive_manager
    if _archive_manager is None:
        _archive_manager = TaskArchiveManager()
    return _archive_manager
