from pathlib import Path


def _source() -> str:
    root = Path(__file__).resolve().parents[2]
    path = root / "adapters" / "admin-api" / "commander_api" / "containers.py"
    return path.read_text(encoding="utf-8")


def test_commander_exposes_home_status_endpoint():
    src = _source()
    assert '@router.get("/home/status")' in src
    assert "def api_home_status" in src
    assert "evaluate_home_status" in src
