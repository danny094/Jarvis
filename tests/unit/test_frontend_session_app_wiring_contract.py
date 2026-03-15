from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_index_wires_session_tab_window_and_styles():
    src = _read("adapters/Jarvis/index.html")
    assert 'data-app="session"' in src
    assert 'id="app-session"' in src
    assert "./static/css/session.css" in src
    assert 'data-action="app:session"' in src


def test_shell_wires_session_app_loader():
    src = _read("adapters/Jarvis/js/shell.js")
    assert "sessionLoaded" in src
    assert "app-session" in src
    assert "import('./apps/session.js')" in src
    assert "initSessionApp" in src


def test_session_app_calls_runtime_session_endpoint():
    src = _read("adapters/Jarvis/js/apps/session.js")
    assert "/api/runtime/session" in src
    assert "/api/runtime/compute/instances" in src
