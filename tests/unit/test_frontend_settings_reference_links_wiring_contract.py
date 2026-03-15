from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_advanced_page_contains_reference_links_panel_and_tabs():
    src = _read("adapters/Jarvis/index.html")
    assert "GitHub Reference Collections" in src
    assert 'id="reference-links-tabs"' in src
    assert 'data-tab="cronjobs"' in src
    assert 'data-tab="skills"' in src
    assert 'data-tab="blueprints"' in src
    assert 'id="reference-links-rows"' in src
    assert 'id="save-reference-links-settings"' in src


def test_settings_js_wires_reference_links_load_and_save():
    src = _read("adapters/Jarvis/js/apps/settings.js")
    assert "loadReferenceLinksSettings" in src
    assert "saveReferenceLinksSettings" in src
    assert "setupReferenceLinksSettingsHandlers" in src
    assert "/api/settings/reference-links" in src
