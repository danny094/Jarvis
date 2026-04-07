from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_storage_scope_registry_persists_metadata(tmp_path, monkeypatch):
    import container_commander.storage_scope as scopes

    monkeypatch.setattr(scopes, "SCOPES_PATH", str(tmp_path / "storage_scopes.json"))

    stored = scopes.upsert_scope(
        name="deploy_auto_asset_games",
        roots=[{"path": "/data/games", "mode": "ro"}],
        approved_by="system:auto",
        metadata={
            "origin": "storage_asset_auto_scope",
            "asset_ids": ["games-lib"],
            "blueprint_id": "retro-box",
            "auto_generated": True,
        },
    )

    assert stored["metadata"]["origin"] == "storage_asset_auto_scope"
    assert stored["metadata"]["asset_ids"] == ["games-lib"]
    assert stored["metadata"]["blueprint_id"] == "retro-box"
    assert stored["created_at"]
