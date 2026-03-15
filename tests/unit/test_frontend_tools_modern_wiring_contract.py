from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_index_includes_tools_css_for_modern_mcp_ui():
    src = _read("adapters/Jarvis/index.html")
    assert 'static/css/tools.css' in src


def test_tools_app_wires_toggle_restart_and_config_save_actions():
    src = _read("adapters/Jarvis/js/apps/tools.js")
    assert 'apiJson("/api/mcp/list")' in src
    assert 'apiJson("/mcp/refresh", { method: "POST" })' in src
    assert '/api/mcp/${encodeURIComponent(name)}/toggle' in src
    assert '/api/mcp/${encodeURIComponent(name)}/config' in src
    assert 'function saveSelectedConfig()' in src
    assert 'function toggleSelectedMcp()' in src
    assert 'function restartHub()' in src


def test_tools_app_loads_details_panel_on_list_selection():
    src = _read("adapters/Jarvis/js/apps/tools.js")
    assert '/api/mcp/${encodeURIComponent(name)}/details' in src
    assert 'data-action="select"' in src
    assert 'loadSelectedDetails()' in src
