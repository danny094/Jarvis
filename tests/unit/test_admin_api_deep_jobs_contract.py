from pathlib import Path


def _read_main() -> str:
    root = Path(__file__).resolve().parents[2]
    path = root / "adapters" / "admin-api" / "main.py"
    return path.read_text(encoding="utf-8")


def test_deep_jobs_endpoints_exist():
    src = _read_main()
    assert '@app.post("/api/chat/deep-jobs")' in src
    assert '@app.get("/api/chat/deep-jobs/{job_id}")' in src
    assert '@app.post("/api/chat/deep-jobs/{job_id}/cancel")' in src
    assert '@app.get("/api/chat/deep-jobs-stats")' in src


def test_deep_jobs_force_response_mode_and_non_stream():
    src = _read_main()
    assert 'force_data["response_mode"] = "deep"' in src
    assert 'force_data["stream"] = False' in src
    assert '"poll_url": f"/api/chat/deep-jobs/{job_id}"' in src


def test_deep_jobs_has_concurrency_gate_and_queue_fields():
    src = _read_main()
    assert "_DEEP_JOB_MAX_CONCURRENCY = get_deep_job_max_concurrency()" in src
    assert "_DEEP_JOB_TIMEOUT_S = get_deep_job_timeout_s()" in src
    assert "_deep_job_slots = asyncio.Semaphore(_DEEP_JOB_MAX_CONCURRENCY)" in src
    assert "async with _deep_job_slots:" in src
    assert "async with asyncio.timeout(float(_DEEP_JOB_TIMEOUT_S)):" in src
    assert '_deep_job_tasks: Dict[str, asyncio.Task] = {}' in src
    assert "task.cancel()" in src
    assert '"queue_position": queue_position' in src
    assert '"max_concurrency": _DEEP_JOB_MAX_CONCURRENCY' in src
    assert '"timeout_s": _DEEP_JOB_TIMEOUT_S' in src
