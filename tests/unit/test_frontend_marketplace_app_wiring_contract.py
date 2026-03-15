from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_marketplace_app_container_and_launchpad_icon_wired_in_index():
    src = _read("adapters/Jarvis/index.html")
    assert 'id="app-marketplace"' in src
    assert 'data-action="app:marketplace"' in src
    assert 'static/css/marketplace.css' in src


def test_shell_switch_app_supports_marketplace_lazy_loading():
    src = _read("adapters/Jarvis/js/shell.js")
    assert "marketplaceLoaded" in src
    assert "marketplace: document.getElementById('app-marketplace')" in src
    assert "if (appName === 'marketplace')" in src
    assert "import('./apps/marketplace.js')" in src
    assert "initMarketplaceApp" in src


def test_marketplace_app_calls_catalog_and_install_endpoints():
    src = _read("adapters/Jarvis/js/apps/marketplace.js")
    assert "/marketplace/catalog" in src
    assert "/marketplace/catalog/sync" in src
    assert "/marketplace/catalog/install/" in src
    assert 'fetchJson("/blueprints"' in src
