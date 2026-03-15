from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_marketplace_module_exposes_remote_catalog_sync_and_install_contract():
    src = _read("container_commander/marketplace.py")
    assert "def sync_remote_catalog(" in src
    assert "def list_catalog(" in src
    assert "def install_catalog_blueprint(" in src
    assert "raw.githubusercontent.com" in src
    assert "TRION_BLUEPRINT_CATALOG_REPO" in src
    assert "TRION_REFERENCE_LINK_COLLECTIONS" in src
    assert "_SECRET_REF_RE" in src
    assert "vault://" in src


def test_commander_operations_exposes_catalog_routes():
    src = _read("adapters/admin-api/commander_api/operations.py")
    assert '@router.get("/marketplace/catalog")' in src
    assert '@router.post("/marketplace/catalog/sync")' in src
    assert '@router.post("/marketplace/catalog/install/{blueprint_id}")' in src
    assert "marketplace_sync_failed" in src
    assert "marketplace_install_failed" in src


def test_terminal_cli_exposes_market_commands_for_user_flow():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    assert "{ cmd: 'market', desc: 'Marketplace: market sync|list|install <id>' }" in src
    assert "case 'market': {" in src
    assert "'/marketplace/catalog/sync'" in src
    assert "/marketplace/catalog/install/${encodeURIComponent(id)}" in src
    assert "/marketplace/catalog${query}" in src
