from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_storage_asset_registry_upsert_and_filter(tmp_path, monkeypatch):
    import container_commander.storage_assets as assets

    monkeypatch.setattr(assets, "ASSETS_PATH", str(tmp_path / "storage_assets.json"))

    stored = assets.upsert_asset(
        "games-library",
        {
            "path": "/mnt/trion-games",
            "label": "Games",
            "published_to_commander": True,
            "default_mode": "rw",
            "allowed_for": ["media", "workspace", "media"],
            "source_kind": "service_dir",
        },
    )

    assert stored["id"] == "games-library"
    assert stored["path"] == "/mnt/trion-games"
    assert stored["published_to_commander"] is True
    assert stored["default_mode"] == "rw"
    assert stored["allowed_for"] == ["media", "workspace"]

    all_assets = assets.list_assets()
    published = assets.list_assets(published_only=True)

    assert "games-library" in all_assets
    assert "games-library" in published


def test_storage_asset_registry_rejects_invalid_mode(tmp_path, monkeypatch):
    import container_commander.storage_assets as assets

    monkeypatch.setattr(assets, "ASSETS_PATH", str(tmp_path / "storage_assets.json"))

    try:
        assets.upsert_asset(
            "bad-mode",
            {
                "path": "/mnt/trion-bad",
                "default_mode": "execute",
            },
        )
    except ValueError as exc:
        assert "invalid default_mode" in str(exc)
    else:
        raise AssertionError("upsert_asset should reject invalid default_mode")


def test_storage_asset_registry_accepts_games_usage(tmp_path, monkeypatch):
    import container_commander.storage_assets as assets

    monkeypatch.setattr(assets, "ASSETS_PATH", str(tmp_path / "storage_assets.json"))

    stored = assets.upsert_asset(
        "games-library",
        {
            "path": "/mnt/trion-games",
            "published_to_commander": True,
            "default_mode": "rw",
            "allowed_for": ["games", "workspace", "games"],
        },
    )

    assert stored["allowed_for"] == ["games", "workspace"]
