from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_commander_routes_mount_trion_memory_alias_for_webui():
    src = _read("adapters/admin-api/commander_routes.py")
    assert "from trion_memory_routes import router as trion_memory_router" in src
    assert 'router.include_router(trion_memory_router, prefix="/trion/memory")' in src


def test_terminal_memory_panel_calls_trion_memory_endpoints():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    required = [
        'id="term-memory-status"',
        'id="term-memory-list"',
        'id="term-memory-query"',
        "apiRequest('/trion/memory/status', {}, 'Could not load memory status')",
        "apiRequest('/trion/memory/recent?limit=25', {}, 'Could not load recent memory')",
        "'/trion/memory/remember',",
        "apiRequest(`/trion/memory/recall?query=${encodeURIComponent(query)}&limit=25`, {}, 'Could not search memory')",
    ]
    for marker in required:
        assert marker in src


def test_terminal_refreshes_memory_panel_on_memory_ws_events():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    assert "event === 'memory_saved' || event === 'memory_skipped' || event === 'memory_denied'" in src
    assert "loadMemoryPanelSnapshot({ silent: true })" in src
