from pathlib import Path


def _read_main() -> str:
    root = Path(__file__).resolve().parents[2]
    path = root / "adapters" / "admin-api" / "main.py"
    return path.read_text(encoding="utf-8")


def _read_config() -> str:
    root = Path(__file__).resolve().parents[2]
    path = root / "config.py"
    return path.read_text(encoding="utf-8")


def test_autonomy_jobs_endpoints_exist():
    src = _read_main()
    assert '@app.post("/api/autonomous/jobs")' in src
    assert '@app.get("/api/autonomous/jobs/{job_id}")' in src
    assert '@app.post("/api/autonomous/jobs/{job_id}/cancel")' in src
    assert '@app.post("/api/autonomous/jobs/{job_id}/retry")' in src
    assert '@app.get("/api/autonomous/jobs-stats")' in src


def test_autonomy_jobs_have_queue_timeout_and_retry_contract():
    src = _read_main()
    assert "_AUTONOMY_JOB_MAX_CONCURRENCY = get_autonomy_job_max_concurrency()" in src
    assert "_AUTONOMY_JOB_TIMEOUT_S = get_autonomy_job_timeout_s()" in src
    assert "_autonomy_job_slots = asyncio.Semaphore(_AUTONOMY_JOB_MAX_CONCURRENCY)" in src
    assert "async with _autonomy_job_slots:" in src
    assert "async with asyncio.timeout(float(_AUTONOMY_JOB_TIMEOUT_S)):" in src
    assert '"poll_url": f"/api/autonomous/jobs/{job_id}"' in src
    assert "/api/autonomous/jobs/{job_id}/retry" in src
    assert '"error_code": "job_not_retryable"' in src


def test_autonomous_sync_endpoint_uses_normalized_request_with_error_code():
    src = _read_main()
    assert "payload, error_code, error = _normalize_autonomy_request(data)" in src
    assert 'return {"success": False, "error_code": error_code, "error": error}' in src


def test_config_exposes_autonomy_job_runtime_knobs():
    src = _read_config()
    assert "def get_autonomy_job_timeout_s()" in src
    assert "AUTONOMY_JOB_TIMEOUT_S" in src
    assert "def get_autonomy_job_max_concurrency()" in src
    assert "AUTONOMY_JOB_MAX_CONCURRENCY" in src
