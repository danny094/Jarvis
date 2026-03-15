from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_settings_routes_exposes_sequential_runtime_endpoints():
    src = _read("adapters/admin-api/settings_routes.py")
    assert '@router.get("/sequential/runtime")' in src
    assert '@router.post("/sequential/runtime")' in src
    assert "class SequentialRuntimeUpdate" in src


def test_settings_routes_sequential_runtime_contains_core_policy_keys():
    src = _read("adapters/admin-api/settings_routes.py")
    assert "DEFAULT_RESPONSE_MODE" in src
    assert "RESPONSE_MODE_SEQUENTIAL_THRESHOLD" in src
    assert "SEQUENTIAL_TIMEOUT_S" in src
    assert "QUERY_BUDGET_SKIP_THINKING_MIN_CONFIDENCE" in src
    assert "LOOP_ENGINE_TRIGGER_COMPLEXITY" in src
