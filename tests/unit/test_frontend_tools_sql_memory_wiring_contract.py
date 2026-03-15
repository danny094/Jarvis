from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_tools_app_has_sql_memory_detail_panel_wiring():
    src = _read("adapters/Jarvis/js/apps/tools.js")
    assert "isSqlMemoryMcp" in src
    assert "renderSqlMemoryDetail" in src
    assert "mmLoadAll" in src
    assert "memory_search_fts" in src
    assert "/api/maintenance/start" in src
    assert "memory_embedding_backfill" in src
    assert "secret_list" in src


def test_tools_css_has_sql_memory_panel_styles():
    src = _read("adapters/Jarvis/static/css/tools.css")
    assert ".mm-shell" in src
    assert ".mm-tabs" in src
    assert ".mm-search-grid" in src
    assert ".mm-danger" in src
