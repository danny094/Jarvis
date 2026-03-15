from pathlib import Path


def _read_settings_routes() -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / "adapters" / "admin-api" / "settings_routes.py").read_text(encoding="utf-8")


def test_reference_links_routes_exist():
    src = _read_settings_routes()
    assert '@router.get("/reference-links")' in src
    assert '@router.post("/reference-links")' in src
    assert "class ReferenceLinksUpdate" in src


def test_reference_links_policy_is_github_only_and_read_only():
    src = _read_settings_routes()
    assert "REFERENCE_LINKS_ALLOWED_HOSTS" in src
    assert "github.com" in src
    assert "raw.githubusercontent.com" in src
    assert "gist.github.com" in src
    assert '"read_only": True' in src
    assert "TRION_REFERENCE_LINK_COLLECTIONS" in src
