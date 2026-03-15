from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_tools_app_has_sequential_detail_panel_wiring():
    src = _read("adapters/Jarvis/js/apps/tools.js")
    assert "isSequentialMcp" in src
    assert "renderSequentialMcpDetail" in src
    assert "/api/settings/sequential/runtime" in src
    assert "/api/settings/master" in src
    assert "/api/runtime/autonomy-status" in src
