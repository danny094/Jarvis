from pathlib import Path


def _source() -> str:
    root = Path(__file__).resolve().parents[2]
    path = root / "adapters" / "admin-api" / "runtime_routes.py"
    return path.read_text(encoding="utf-8")


def test_runtime_routes_exposes_autonomy_status_endpoint():
    src = _source()
    assert '@router.get("/api/runtime/autonomy-status")' in src
    assert "def get_autonomy_status" in src


def test_runtime_autonomy_status_contract_keys_present():
    src = _source()
    required = [
        '"planning_tools"',
        '"all_required_available"',
        '"home"',
        '"master"',
    ]
    for key in required:
        assert key in src


def test_runtime_autonomy_status_supports_tool_aliases_for_sequential_readiness():
    src = _source()
    assert '"required_aliases"' in src
    assert '"sequential_thinking"' in src
    assert '"think_simple"' in src
