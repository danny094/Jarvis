"""
TaskLifecycleManager - Phase 2: DB-backed Task Lifecycle

Manages active task context with automatic eviction and archival.
Uses task_active (max 10 items, fast) and task_archive (long-term, searchable).

Backward-compatible with existing Orchestrator calls:
  - start_task(request_id, context)
  - finish_task(request_id, result)

New capabilities:
  - DB persistence (survives restarts)
  - Automatic flush (evict oldest beyond 10 items)
  - Archive system (move evicted tasks to task_archive)
  - 48h auto-expiry for stale tasks

Created: Phase 2 - Week 2 (Task Lifecycle)
"""

import json
import time
import uuid
import sqlite3
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from utils.logger import log_info, log_error, log_warning

# ═══════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════

ACTIVE_LIMIT = 10          # Max items in task_active per conversation
EXPIRY_HOURS = 48          # Auto-archive after 48h
DB_PATH = os.getenv("MEMORY_DB_PATH", "/app/memory_data/memory.db")


def _get_db() -> sqlite3.Connection:
    """Get SQLite connection with WAL mode and busy timeout."""
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


class TaskLifecycleManager:
    """
    Manages the lifecycle of tasks with DB persistence.

    Active Context (task_active):
      - Max 10 items per conversation
      - Fast access, WAL optimized
      - Eviction: LRU (oldest by last_updated)

    Archive (task_archive):
      - Long-term storage
      - Linked to embeddings table for semantic search
      - Embedding generation is async (Slow Lane)
    """

    def __init__(self):
        # In-memory tracking for timing (not persisted)
        self._timers: Dict[str, float] = {}
        log_info("[TaskLifecycle] Initialized (DB-backed)")

    # ═══════════════════════════════════════════════════════
    # PUBLIC API (Backward-compatible)
    # ═══════════════════════════════════════════════════════

    def start_task(self, request_id: str, context: Dict[str, Any]):
        """
        Start tracking a task. Writes to task_active.

        Args:
            request_id: Unique request identifier
            context: Must contain 'conversation_id' and 'user_text'
        """
        self._timers[request_id] = time.time()

        conversation_id = context.get("conversation_id", "unknown")
        user_text = context.get("user_text", "")

        task_id = f"task_{request_id}"
        content = json.dumps({
            "status": "running",
            "summary": user_text[:200] if user_text else "",
            "context": {
                "user_text": user_text[:500] if user_text else "",
                "request_id": request_id,
            },
            "result": None,
        })

        try:
            conn = _get_db()
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO task_active
                    (conversation_id, task_id, content, created_at, last_updated, importance_score)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        conversation_id,
                        task_id,
                        content,
                        datetime.utcnow().isoformat(),
                        datetime.utcnow().isoformat(),
                        0.0,
                    )
                )
                conn.commit()
                log_info(f"[TaskLifecycle] Started task {task_id}")
            finally:
                conn.close()

        except Exception as e:
            # Non-fatal: log and continue (don't break the pipeline)
            log_error(f"[TaskLifecycle] Failed to persist start_task: {e}")

    def finish_task(self, request_id: str, result: Any, error: Optional[Exception] = None):
        """
        Finish a task. Updates task_active, then triggers flush.

        Args:
            request_id: The request ID from start_task
            result: Result data (dict or any serializable)
            error: Optional exception if task failed
        """
        # Calculate duration
        duration = 0.0
        if request_id in self._timers:
            duration = time.time() - self._timers[request_id]
            del self._timers[request_id]

        task_id = f"task_{request_id}"
        status = "failed" if error else "completed"

        try:
            conn = _get_db()
            try:
                # Read existing content to merge
                row = conn.execute(
                    "SELECT content, conversation_id FROM task_active WHERE task_id = ?",
                    (task_id,)
                ).fetchone()

                if row:
                    existing = json.loads(row["content"])
                    conversation_id = row["conversation_id"]

                    # Update content
                    existing["status"] = status
                    existing["result"] = _safe_serialize(result)
                    existing["duration_s"] = round(duration, 2)
                    if error:
                        existing["error"] = str(error)

                    # Calculate importance (simple heuristic)
                    importance = _calculate_importance(existing, duration)

                    conn.execute(
                        """
                        UPDATE task_active
                        SET content = ?, last_updated = ?, importance_score = ?
                        WHERE task_id = ?
                        """,
                        (
                            json.dumps(existing),
                            datetime.utcnow().isoformat(),
                            importance,
                            task_id,
                        )
                    )
                    conn.commit()
                    log_info(
                        f"[TaskLifecycle] Finished {task_id} in {duration:.2f}s "
                        f"status={status} importance={importance:.2f}"
                    )

                    # Trigger flush after completion
                    self.check_and_flush(conversation_id)
                else:
                    log_warning(f"[TaskLifecycle] Task {task_id} not found in active table")

            finally:
                conn.close()

        except Exception as e:
            log_error(f"[TaskLifecycle] Failed to persist finish_task: {e}")

    # ═══════════════════════════════════════════════════════
    # FLUSH & COMPACT
    # ═══════════════════════════════════════════════════════

    def check_and_flush(self, conversation_id: str):
        """
        Check active count and evict oldest tasks beyond ACTIVE_LIMIT.
        Also expires tasks older than EXPIRY_HOURS.

        Target: <10ms execution time.
        """
        try:
            conn = _get_db()
            try:
                # Use BEGIN IMMEDIATE for atomic transaction
                conn.execute("BEGIN IMMEDIATE")

                # 1. Expire stale tasks (older than 48h)
                expiry_cutoff = (
                    datetime.utcnow() - timedelta(hours=EXPIRY_HOURS)
                ).isoformat()

                expired = conn.execute(
                    """
                    SELECT task_id, content, conversation_id
                    FROM task_active
                    WHERE conversation_id = ? AND created_at < ?
                    """,
                    (conversation_id, expiry_cutoff)
                ).fetchall()

                for task in expired:
                    self._move_to_archive(conn, task)

                if expired:
                    log_info(f"[TaskLifecycle] Expired {len(expired)} stale tasks")

                # 2. Count remaining active tasks
                count = conn.execute(
                    "SELECT COUNT(*) FROM task_active WHERE conversation_id = ?",
                    (conversation_id,)
                ).fetchone()[0]

                if count > ACTIVE_LIMIT:
                    # Evict oldest (LRU) beyond limit
                    to_evict = conn.execute(
                        """
                        SELECT task_id, content, conversation_id
                        FROM task_active
                        WHERE conversation_id = ?
                        ORDER BY last_updated DESC
                        LIMIT -1 OFFSET ?
                        """,
                        (conversation_id, ACTIVE_LIMIT)
                    ).fetchall()

                    for task in to_evict:
                        self._move_to_archive(conn, task)

                    log_info(
                        f"[TaskLifecycle] Flushed {len(to_evict)} tasks "
                        f"(was {count}, now {ACTIVE_LIMIT})"
                    )

                conn.commit()

            except Exception as e:
                conn.rollback()
                raise e
            finally:
                conn.close()

        except Exception as e:
            log_error(f"[TaskLifecycle] Flush failed: {e}")

    # ═══════════════════════════════════════════════════════
    # ACTIVE CONTEXT API (for Master Orchestrator)
    # ═══════════════════════════════════════════════════════

    def get_active_context(self, conversation_id: str = None) -> List[Dict]:
        """
        Returns all active tasks for a conversation.
        Used by MasterOrchestrator for context awareness.
        """
        try:
            conn = _get_db()
            try:
                if conversation_id:
                    rows = conn.execute(
                        """
                        SELECT task_id, content, created_at, last_updated, importance_score
                        FROM task_active
                        WHERE conversation_id = ?
                        ORDER BY last_updated DESC
                        """,
                        (conversation_id,)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT task_id, content, created_at, last_updated, importance_score
                        FROM task_active
                        ORDER BY last_updated DESC
                        LIMIT ?
                        """,
                        (ACTIVE_LIMIT,)
                    ).fetchall()

                return [
                    {
                        "task_id": row["task_id"],
                        "content": json.loads(row["content"]),
                        "created_at": row["created_at"],
                        "last_updated": row["last_updated"],
                        "importance": row["importance_score"],
                    }
                    for row in rows
                ]

            finally:
                conn.close()

        except Exception as e:
            log_error(f"[TaskLifecycle] get_active_context failed: {e}")
            return []

    def get_active_count(self, conversation_id: str) -> int:
        """Returns count of active tasks for a conversation."""
        try:
            conn = _get_db()
            try:
                return conn.execute(
                    "SELECT COUNT(*) FROM task_active WHERE conversation_id = ?",
                    (conversation_id,)
                ).fetchone()[0]
            finally:
                conn.close()
        except Exception:
            return 0

    # ═══════════════════════════════════════════════════════
    # INTERNAL HELPERS
    # ═══════════════════════════════════════════════════════

    def _move_to_archive(self, conn: sqlite3.Connection, task: sqlite3.Row):
        """
        Move a task from active to archive (within same transaction).
        Embedding generation happens later (Slow Lane).
        """
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO task_archive
                (conversation_id, task_id, content, archived_at, embedding_id)
                VALUES (?, ?, ?, ?, NULL)
                """,
                (
                    task["conversation_id"],
                    task["task_id"],
                    task["content"],
                    datetime.utcnow().isoformat(),
                )
            )
            conn.execute(
                "DELETE FROM task_active WHERE task_id = ?",
                (task["task_id"],)
            )
        except Exception as e:
            log_error(f"[TaskLifecycle] Archive move failed for {task['task_id']}: {e}")


# ═══════════════════════════════════════════════════════════
# MODULE-LEVEL HELPERS
# ═══════════════════════════════════════════════════════════

def _calculate_importance(content: Dict, duration: float) -> float:
    """
    Simple importance heuristic for eviction priority.

    Higher importance = kept longer in active.
    Factors:
      - Failed tasks: +0.3 (might need retry)
      - Long duration: +0.2 (complex work)
      - Has result data: +0.1
    """
    score = 0.0

    if content.get("status") == "failed":
        score += 0.3
    if duration > 5.0:
        score += 0.2
    if content.get("result"):
        score += 0.1

    return min(score, 1.0)


def _safe_serialize(obj: Any) -> Any:
    """Safely serialize result data for JSON storage."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _safe_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_serialize(v) for v in obj]
    # Fallback: string representation
    try:
        return str(obj)[:500]
    except Exception:
        return "<unserializable>"
