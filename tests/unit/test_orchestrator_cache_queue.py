import sqlite3
import time
from pathlib import Path
from unittest.mock import MagicMock, patch


def _make_orchestrator():
    from core.orchestrator import PipelineOrchestrator

    with patch("core.orchestrator.ThinkingLayer", return_value=MagicMock()), \
         patch("core.orchestrator.ControlLayer", return_value=MagicMock()), \
         patch("core.orchestrator.OutputLayer", return_value=MagicMock()), \
         patch("core.orchestrator.ToolSelector", return_value=MagicMock()), \
         patch("core.orchestrator.ContextManager", return_value=MagicMock()), \
         patch("core.orchestrator.get_hub", return_value=MagicMock()), \
         patch("core.orchestrator.get_registry", return_value=MagicMock()), \
         patch("core.orchestrator.get_master_orchestrator", return_value=MagicMock()), \
         patch("core.orchestrator.get_archive_manager", return_value=MagicMock()):
        return PipelineOrchestrator()


def test_sqlite_plan_cache_shared_between_instances(tmp_path):
    from core.orchestrator import _SqlitePlanCache

    db_path = str(tmp_path / "plan_cache.sqlite")
    c1 = _SqlitePlanCache(ttl_seconds=120, db_path=db_path, namespace="thinking")
    c2 = _SqlitePlanCache(ttl_seconds=120, db_path=db_path, namespace="thinking")

    payload = {"intent": "create_skill", "score": 0.91}
    c1.set("Bitte erstelle Skill X", payload)

    loaded = c2.get("Bitte erstelle Skill X")
    assert loaded == payload


def test_sqlite_plan_cache_ttl_expires_entries(tmp_path):
    from core.orchestrator import _SqlitePlanCache

    db_path = str(tmp_path / "plan_cache_ttl.sqlite")
    cache = _SqlitePlanCache(ttl_seconds=60, db_path=db_path, namespace="seq")
    key_text = "Run sequential task"
    cache.set(key_text, {"ok": True})

    # Force-expire the row in DB to validate TTL enforcement deterministically.
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE plan_cache SET created_at=? WHERE namespace=?",
                     (time.time() - 3600, "seq"))

    assert cache.get(key_text) is None


def test_archive_embedding_job_queue_run_once_success(tmp_path):
    from core.orchestrator import _ArchiveEmbeddingJobQueue

    q = _ArchiveEmbeddingJobQueue(
        db_path=str(tmp_path / "posttask_jobs.sqlite"),
        poll_interval_s=0.1,
        retry_base_s=0.0,
        retry_max_s=0.0,
    )
    calls = {"n": 0}
    q.set_processor(lambda: calls.__setitem__("n", calls["n"] + 1) or 2)

    q.enqueue()
    did_work = q.run_once()

    assert did_work is True
    assert calls["n"] == 1
    assert q.stats()["total"] == 0
    q.stop()


def test_archive_embedding_job_queue_retries_failed_jobs(tmp_path):
    from core.orchestrator import _ArchiveEmbeddingJobQueue

    q = _ArchiveEmbeddingJobQueue(
        db_path=str(tmp_path / "posttask_jobs_retry.sqlite"),
        poll_interval_s=0.1,
        retry_base_s=0.0,  # immediate retry eligibility in test
        retry_max_s=0.0,
    )

    state = {"first": True}

    def _processor():
        if state["first"]:
            state["first"] = False
            raise RuntimeError("transient embedding error")
        return 1

    q.set_processor(_processor)
    q.enqueue()

    first = q.run_once()
    assert first is True
    assert q.stats()["pending"] == 1

    second = q.run_once()
    assert second is True
    assert q.stats()["total"] == 0
    q.stop()


def test_post_task_processing_enqueues_durable_job():
    orch = _make_orchestrator()
    mock_q = MagicMock()
    mock_q.enqueue.return_value = 42
    mock_q.pending_count.return_value = 1

    with patch("core.orchestrator._get_archive_embedding_queue", return_value=mock_q):
        orch._post_task_processing()

    mock_q.ensure_worker_running.assert_called_once()
    mock_q.enqueue.assert_called_once()


def test_post_task_processing_falls_back_inline_on_queue_error():
    orch = _make_orchestrator()
    orch.archive_manager.process_pending_embeddings = MagicMock(return_value=3)

    with patch("core.orchestrator._get_archive_embedding_queue", side_effect=RuntimeError("queue down")):
        orch._post_task_processing()

    orch.archive_manager.process_pending_embeddings.assert_called_once_with(batch_size=5)
