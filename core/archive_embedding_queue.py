import os
import sqlite3
import threading
import time
from typing import Callable, Dict, Optional

from utils.logger import log_error, log_info


class _ArchiveEmbeddingJobQueue:
    """
    Durable local job queue for archive embedding post-processing.
    Uses SQLite so pending jobs survive process restarts.
    """

    def __init__(
        self,
        *,
        db_path: str = "/tmp/trion_posttask_jobs.sqlite",
        poll_interval_s: float = 0.8,
        retry_base_s: float = 1.0,
        retry_max_s: float = 60.0,
    ):
        self._db_path = db_path
        self._poll_interval_s = max(0.1, float(poll_interval_s))
        self._retry_base_s = max(0.0, float(retry_base_s))
        self._retry_max_s = max(self._retry_base_s, float(retry_max_s))
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._notify_event = threading.Event()
        self._start_lock = threading.Lock()
        self._db_lock = threading.Lock()
        self._processor: Optional[Callable[[], int]] = None
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS archive_embedding_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at REAL NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_error TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_archive_embedding_jobs_pending "
                "ON archive_embedding_jobs(status, available_at, id)"
            )

    def ensure_worker_running(self, processor: Callable[[], int]):
        self.set_processor(processor)
        if self._thread and self._thread.is_alive():
            return
        with self._start_lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._worker_loop,
                name="archive-embedding-worker",
                daemon=True,
            )
            self._thread.start()
            log_info("[PostTaskQueue] worker started")

    def set_processor(self, processor: Callable[[], int]):
        if callable(processor):
            self._processor = processor

    def enqueue(self) -> int:
        now = time.time()
        with self._db_lock, self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO archive_embedding_jobs(status, attempts, available_at, created_at, updated_at)
                VALUES('pending', 0, ?, ?, ?)
                """,
                (now, now, now),
            )
            job_id = int(cur.lastrowid)
        self._notify_event.set()
        return job_id

    def _claim_next(self) -> Optional[sqlite3.Row]:
        now = time.time()
        with self._db_lock, self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT id, attempts
                FROM archive_embedding_jobs
                WHERE status='pending' AND available_at <= ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (now,),
            ).fetchone()
            if not row:
                conn.execute("COMMIT")
                return None
            conn.execute(
                "UPDATE archive_embedding_jobs SET status='running', updated_at=? WHERE id=?",
                (now, int(row["id"])),
            )
            conn.execute("COMMIT")
            return row

    def _mark_done(self, job_id: int):
        with self._db_lock, self._conn() as conn:
            conn.execute("DELETE FROM archive_embedding_jobs WHERE id=?", (job_id,))

    def _mark_retry(self, job_id: int, attempts: int, error: str):
        backoff = min(self._retry_max_s, self._retry_base_s * (2 ** max(0, attempts)))
        next_at = time.time() + backoff
        with self._db_lock, self._conn() as conn:
            conn.execute(
                """
                UPDATE archive_embedding_jobs
                SET status='pending',
                    attempts=?,
                    available_at=?,
                    updated_at=?,
                    last_error=?
                WHERE id=?
                """,
                (attempts, next_at, time.time(), error[:1000], job_id),
            )

    def pending_count(self) -> int:
        with self._db_lock, self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM archive_embedding_jobs WHERE status='pending'"
            ).fetchone()
            return int(row["n"]) if row else 0

    def stats(self) -> Dict[str, int]:
        with self._db_lock, self._conn() as conn:
            pending = conn.execute(
                "SELECT COUNT(*) AS n FROM archive_embedding_jobs WHERE status='pending'"
            ).fetchone()
            running = conn.execute(
                "SELECT COUNT(*) AS n FROM archive_embedding_jobs WHERE status='running'"
            ).fetchone()
            total = conn.execute("SELECT COUNT(*) AS n FROM archive_embedding_jobs").fetchone()
            return {
                "pending": int(pending["n"]) if pending else 0,
                "running": int(running["n"]) if running else 0,
                "total": int(total["n"]) if total else 0,
            }

    def run_once(self) -> bool:
        if not callable(self._processor):
            return False
        row = self._claim_next()
        if not row:
            return False

        job_id = int(row["id"])
        attempts = int(row["attempts"])
        try:
            processed = int(self._processor() or 0)
            if processed > 0:
                log_info(f"[PostTaskQueue] processed archive embeddings: {processed} (job_id={job_id})")
            self._mark_done(job_id)
        except Exception as e:
            next_attempt = attempts + 1
            self._mark_retry(job_id, next_attempt, str(e))
            log_error(
                f"[PostTaskQueue] job failed (job_id={job_id}, attempts={next_attempt}) "
                f"error={e}"
            )
        return True

    def _worker_loop(self):
        while not self._stop_event.is_set():
            worked = self.run_once()
            if worked:
                continue
            self._notify_event.wait(self._poll_interval_s)
            self._notify_event.clear()

    def stop(self):
        self._stop_event.set()
        self._notify_event.set()


_archive_embedding_queue_lock = threading.Lock()
_archive_embedding_queue: Optional[_ArchiveEmbeddingJobQueue] = None


def get_archive_embedding_queue() -> _ArchiveEmbeddingJobQueue:
    global _archive_embedding_queue
    with _archive_embedding_queue_lock:
        if _archive_embedding_queue is None:
            db_path = os.getenv("TRION_POSTTASK_QUEUE_DB", "/tmp/trion_posttask_jobs.sqlite")
            poll = float(os.getenv("TRION_POSTTASK_QUEUE_POLL_S", "0.8") or "0.8")
            retry_base = float(os.getenv("TRION_POSTTASK_QUEUE_RETRY_BASE_S", "1.0") or "1.0")
            retry_max = float(os.getenv("TRION_POSTTASK_QUEUE_RETRY_MAX_S", "60.0") or "60.0")
            _archive_embedding_queue = _ArchiveEmbeddingJobQueue(
                db_path=db_path,
                poll_interval_s=poll,
                retry_base_s=retry_base,
                retry_max_s=retry_max,
            )
        return _archive_embedding_queue
