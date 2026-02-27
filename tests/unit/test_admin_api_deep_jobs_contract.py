from pathlib import Path


def _read_main() -> str:
    root = Path(__file__).resolve().parents[2]
    path = root / "adapters" / "admin-api" / "main.py"
    return path.read_text(encoding="utf-8")


def test_deep_jobs_endpoints_exist():
    src = _read_main()
    assert '@app.post("/api/chat/deep-jobs")' in src
    assert '@app.get("/api/chat/deep-jobs/{job_id}")' in src


def test_deep_jobs_force_response_mode_and_non_stream():
    src = _read_main()
    assert 'force_data["response_mode"] = "deep"' in src
    assert 'force_data["stream"] = False' in src
    assert '"poll_url": f"/api/chat/deep-jobs/{job_id}"' in src
