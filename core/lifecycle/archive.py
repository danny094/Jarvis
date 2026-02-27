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
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional, List

from utils.logger import log_info, log_error, log_warning
from config import get_embedding_model
from config import (
    get_embedding_runtime_policy, get_embedding_fallback_policy,
    get_embedding_gpu_endpoint, get_embedding_cpu_endpoint,
    get_embedding_endpoint_mode,
)
from utils.embedding_resolver import resolve_embedding_target
from utils.embedding_metrics import increment_fallback, increment_error, record_latency
from utils.role_endpoint_resolver import resolve_role_endpoint

# ═══════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════

DB_PATH = os.getenv("MEMORY_DB_PATH", "/app/memory_data/memory.db")
OLLAMA_URL = os.getenv("OLLAMA_BASE", "http://host.docker.internal:11434")

# Search defaults
DEFAULT_SEARCH_LIMIT = 5
DEFAULT_MIN_SIMILARITY = 0.5


logger = logging.getLogger(__name__)
_EMBED_SCHEMA_READY = False


def _compute_embedding_version_id(model: str, runtime_policy: str) -> str:
    model_norm = (model or "").strip()
    policy_norm = (runtime_policy or "auto").strip().lower()
    digest = hashlib.sha256(f"{model_norm}|{policy_norm}".encode("utf-8")).hexdigest()[:16]
    return f"embv1_{digest}"


def _get_active_embedding_context() -> Dict[str, Any]:
    model = get_embedding_model()
    policy = get_embedding_runtime_policy()
    version_id = _compute_embedding_version_id(model, policy)
    return {
        "embedding_model": model,
        "runtime_policy": policy,
        "embedding_version": version_id,
    }


def _ensure_embeddings_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
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
    cur.execute("PRAGMA table_info(embeddings)")
    cols = {row[1] for row in cur.fetchall()}
    if "embedding_model" not in cols:
        cur.execute("ALTER TABLE embeddings ADD COLUMN embedding_model TEXT")
    if "embedding_dim" not in cols:
        cur.execute("ALTER TABLE embeddings ADD COLUMN embedding_dim INTEGER")
    if "embedding_version" not in cols:
        cur.execute("ALTER TABLE embeddings ADD COLUMN embedding_version TEXT")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_embeddings_conv ON embeddings(conversation_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_embeddings_version ON embeddings(embedding_version)")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_embeddings_type_version "
        "ON embeddings(content_type, embedding_version)"
    )


def _get_db() -> sqlite3.Connection:
    """Get SQLite connection with WAL mode and busy timeout."""
    global _EMBED_SCHEMA_READY
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    if not _EMBED_SCHEMA_READY:
        _ensure_embeddings_schema(conn)
        conn.commit()
        _EMBED_SCHEMA_READY = True
    return conn


# ═══════════════════════════════════════════════════════════
# EMBEDDING HELPERS (self-contained, no import from sql-memory)
# ═══════════════════════════════════════════════════════════

def _request_embedding(
    url: str,
    model: str,
    text: str,
    options: dict,
) -> Optional[List[float]]:
    """Single Ollama /api/embeddings call; returns None on any failure."""
    try:
        payload: dict = {"model": model, "prompt": text.strip()[:2000]}
        if options:
            payload["options"] = options
        response = requests.post(f"{url}/api/embeddings", json=payload, timeout=60)
        response.raise_for_status()
        return response.json().get("embedding") or None
    except requests.Timeout:
        log_error(f"[ArchiveManager] Embedding timed out (60s) @ {url}")
        return None
    except Exception as e:
        log_error(f"[ArchiveManager] Embedding failed @ {url}: {e}")
        return None


def _get_embedding(text: str) -> Optional[List[float]]:
    """
    Generate embedding vector via Ollama API.

    Self-contained (no dependency on sql-memory container).
    Routes to GPU or CPU endpoint based on embedding_runtime_policy.
    Emits structured log per Scope 3.1 observability spec.
    Increments routing metrics on fallback or hard error.
    """
    if not text or not text.strip():
        return None

    import time as _time
    _start_ms = _time.monotonic() * 1000

    policy = get_embedding_runtime_policy()

    # Phase C: explicit per-layer pinning for embedding role.
    # Auto-mode continues to use embedding_runtime_policy resolver.
    role_route = resolve_role_endpoint("embedding", default_endpoint=OLLAMA_URL)
    requested_pin = role_route.get("requested_target", "auto")
    if requested_pin != "auto":
        if role_route.get("hard_error"):
            log_error(
                f"[Embedding] role=archive_embedding policy={policy} "
                f"requested_target={requested_pin} effective_target=none "
                f"fallback=true reason={role_route.get('fallback_reason') or 'requested_unavailable'}"
            )
            increment_error()
            return None

        eff_target = role_route.get("effective_target") or requested_pin
        endpoint = role_route.get("endpoint") or OLLAMA_URL
        options = {}
        if eff_target == "cpu" and endpoint == OLLAMA_URL:
            options = {"num_gpu": 0}
        decision = {
            "requested_policy": policy,
            "requested_target": requested_pin,
            "effective_target": eff_target,
            "fallback_reason": role_route.get("fallback_reason"),
            "hard_error": False,
            "error_code": None,
            "endpoint": endpoint,
            "options": options,
            "fallback_endpoint": None,
            "fallback_policy": get_embedding_fallback_policy(),
            "reason": f"layer_routing_pin:{requested_pin}",
            "target": eff_target,
        }
    else:
        decision = resolve_embedding_target(
            mode=policy,
            endpoint_mode=get_embedding_endpoint_mode(),
            base_endpoint=OLLAMA_URL,
            gpu_endpoint=get_embedding_gpu_endpoint(),
            cpu_endpoint=get_embedding_cpu_endpoint(),
            fallback_policy=get_embedding_fallback_policy(),
            # availability: not checked pre-flight (single-mode, optimistic)
        )

    # Structured log per Scope 3.1
    _fallback = decision["fallback_reason"] is not None
    _log_msg = (
        f"[Embedding] role=archive_embedding "
        f"policy={decision['requested_policy']} "
        f"requested_target={decision['requested_target']} "
        f"effective_target={decision['effective_target'] or 'none'} "
        f"fallback={_fallback} "
        f"reason={decision['reason']}"
    )
    if decision["hard_error"]:
        log_error(_log_msg)
        increment_error()
        return None
    if _fallback and policy == "prefer_gpu":
        log_warning(_log_msg)
    else:
        log_info(_log_msg)

    model = get_embedding_model()
    embedding = _request_embedding(decision["endpoint"], model, text, decision["options"])

    if embedding is None and decision.get("fallback_endpoint"):
        log_info(
            f"[Embedding] role=archive_embedding policy={policy} "
            f"primary_failed=true retrying_fallback={decision['fallback_endpoint']}"
        )
        embedding = _request_embedding(
            decision["fallback_endpoint"], model, text, decision["options"]
        )
        if embedding is not None:
            increment_fallback()

    if embedding is not None:
        _latency_ms = _time.monotonic() * 1000 - _start_ms
        record_latency(decision["effective_target"] or "unknown", _latency_ms)

    return embedding


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
        Process archived tasks with missing or stale embeddings.

        Called by MaintenanceWorker or after_request hook.
        Returns number of tasks processed.

        Target: <200ms per task (100ms model + 100ms query).
        """
        processed = 0
        selected = 0
        active_ctx = _get_active_embedding_context()
        active_version = active_ctx["embedding_version"]
        active_model = active_ctx["embedding_model"]

        try:
            conn = _get_db()
            try:
                # Missing embedding_id OR stale embedding_version/model.
                pending = conn.execute(
                    """
                    SELECT a.id, a.conversation_id, a.task_id, a.content, a.embedding_id,
                           e.embedding_version, e.embedding_model
                    FROM task_archive a
                    LEFT JOIN embeddings e ON a.embedding_id = e.id
                    WHERE a.embedding_id IS NULL
                       OR e.embedding_version IS NULL
                       OR e.embedding_version != ?
                       OR e.embedding_model IS NULL
                       OR e.embedding_model != ?
                    ORDER BY a.archived_at ASC
                    LIMIT ?
                    """,
                    (active_version, active_model, batch_size),
                ).fetchall()
                selected = len(pending)

                if not pending:
                    return 0

                log_info(
                    f"[ArchiveManager] Processing {selected} pending/stale embeddings "
                    f"(active_version={active_version})"
                )

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

                        # Upsert in shared embeddings table (stores version metadata).
                        embedding_id = self._upsert_task_embedding(
                            conn,
                            embedding_id=task["embedding_id"],
                            conversation_id=task["conversation_id"],
                            content=summary,
                            embedding=embedding,
                            embedding_context=active_ctx,
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

                conn.commit()
            finally:
                conn.close()

        except Exception as e:
            log_error(f"[ArchiveManager] process_pending_embeddings failed: {e}")

        if processed > 0:
            log_info(f"[ArchiveManager] Processed {processed}/{selected} embeddings")

        return processed

    def backfill_embeddings(self, batch_size: int = 100) -> Dict[str, Any]:
        """
        Re-embedding/Backfill entry point for Scope 3.2.

        Resume semantics:
          - Only rows with missing/stale embedding_version are selected.
          - Repeated calls continue until pending_embedding reaches 0.
        """
        processed = self.process_pending_embeddings(batch_size=batch_size)
        stats = self.get_archive_stats()
        return {
            "success": True,
            "processed": processed,
            "active_embedding_version": stats.get("active_embedding_version"),
            "remaining_pending": stats.get("pending_embedding"),
            "remaining_stale": stats.get("stale_embedding"),
            "coverage_pct": stats.get("coverage_pct"),
        }

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
        """Search using cosine similarity over active embedding_version."""
        try:
            active_version = _get_active_embedding_context()["embedding_version"]
            conn = _get_db()
            try:
                # Fetch task embeddings
                sql = """
                    SELECT e.id, e.content, e.embedding, e.metadata,
                           e.embedding_version,
                           a.task_id, a.content as archive_content, a.archived_at
                    FROM embeddings e
                    JOIN task_archive a ON a.embedding_id = e.id
                    WHERE e.content_type = 'task'
                      AND e.embedding_version = ?
                """
                params = [active_version]

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
                                "embedding_version": row["embedding_version"],
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

                active_version = _get_active_embedding_context()["embedding_version"]
                active_version_count = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM task_archive a
                    JOIN embeddings e ON a.embedding_id = e.id
                    WHERE e.embedding_version = ?
                    """,
                    (active_version,),
                ).fetchone()[0]
                stale_embedding = max(0, with_embedding - active_version_count)
                pending = total - active_version_count

                return {
                    "total_archived": total,
                    "with_embedding": with_embedding,
                    "active_embedding_version": active_version,
                    "active_version_count": active_version_count,
                    "stale_embedding": stale_embedding,
                    "pending_embedding": pending,
                    "coverage_pct": round(
                        (active_version_count / total * 100) if total > 0 else 0, 1
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

    def _upsert_task_embedding(
        self,
        conn: sqlite3.Connection,
        embedding_id: Optional[int],
        conversation_id: str,
        content: str,
        embedding: List[float],
        embedding_context: Dict[str, Any],
        metadata: Dict[str, Any] = None,
    ) -> Optional[int]:
        """
        Upsert embedding in the shared embeddings table.

        Uses content_type='task' to segregate from facts.
        Stores Scope-3.2 metadata (model/dim/version).
        """
        try:
            cursor = conn.cursor()
            metadata_obj: Dict[str, Any] = dict(metadata or {})
            metadata_obj["embedding_version"] = embedding_context["embedding_version"]
            metadata_obj["embedding_model"] = embedding_context["embedding_model"]
            metadata_json = json.dumps(metadata_obj)

            if embedding_id is not None:
                prev = cursor.execute(
                    "SELECT metadata FROM embeddings WHERE id = ?",
                    (embedding_id,),
                ).fetchone()
                if prev is not None:
                    if prev[0]:
                        try:
                            old_meta = json.loads(prev[0])
                            if isinstance(old_meta, dict):
                                old_meta.update(metadata_obj)
                                metadata_json = json.dumps(old_meta)
                        except Exception:
                            pass

                    cursor.execute(
                        """
                        UPDATE embeddings
                        SET conversation_id = ?, content = ?, content_type = 'task',
                            metadata = ?, embedding = ?,
                            embedding_model = ?, embedding_dim = ?, embedding_version = ?
                        WHERE id = ?
                        """,
                        (
                            conversation_id,
                            content,
                            metadata_json,
                            json.dumps(embedding),
                            embedding_context["embedding_model"],
                            len(embedding),
                            embedding_context["embedding_version"],
                            embedding_id,
                        ),
                    )
                    if cursor.rowcount > 0:
                        return embedding_id

            cursor.execute(
                """
                INSERT INTO embeddings
                (conversation_id, content, content_type, metadata, embedding,
                 embedding_model, embedding_dim, embedding_version, created_at)
                VALUES (?, ?, 'task', ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    content,
                    metadata_json,
                    json.dumps(embedding),
                    embedding_context["embedding_model"],
                    len(embedding),
                    embedding_context["embedding_version"],
                    datetime.utcnow().isoformat(),
                ),
            )
            return cursor.lastrowid

        except Exception as e:
            log_error(f"[ArchiveManager] _upsert_task_embedding failed: {e}")
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
