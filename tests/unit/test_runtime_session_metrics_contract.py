from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_runtime_routes_exposes_session_endpoint_with_cloud_budget():
    src = _read("adapters/admin-api/runtime_routes.py")
    assert '@router.get("/api/runtime/session")' in src
    assert "get_session_snapshot" in src
    assert "get_rate_limit_snapshot" in src
    assert '"cloud_budget"' in src
    assert '"has_limit_headers"' in src
    assert '"observed"' in src


def test_admin_chat_records_session_metrics():
    src = _read("adapters/admin-api/main.py")
    assert "count_input_chars" in src
    assert "record_chat_turn(" in src
    assert "session metrics update failed" in src


def test_session_metrics_module_tracks_tokens_and_latency():
    src = _read("core/session_metrics.py")
    assert "estimate_tokens_from_chars" in src
    assert "record_chat_turn(" in src
    assert '"p95_latency_ms"' in src
