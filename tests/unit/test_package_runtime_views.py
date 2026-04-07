from container_commander.models import Blueprint


def test_filestash_runtime_view_mounts_only_broker_assets_and_sets_connections_env(monkeypatch):
    from container_commander import package_runtime_views as views

    monkeypatch.setattr(
        views,
        "_list_broker_assets",
        lambda published_only, source_kinds: [
            {
                "id": "games-lib",
                "label": "Games Library",
                "path": "/mnt/games/services/gaming-station-games/data",
                "default_mode": "rw",
                "source_kind": "service_dir",
            },
            {
                "id": "media-import",
                "label": "Media Import",
                "path": "/mnt/media",
                "default_mode": "ro",
                "source_kind": "import",
            },
        ],
    )

    bp = Blueprint(id="filestash", name="Filestash", image="machines/filestash:latest")
    manifest = {
        "runtime_storage_views": {
            "broker_assets": {
                "enabled": True,
                "published_only": True,
                "source_kinds": ["service_dir", "existing_path", "import"],
                "container_root": "/srv/storage-broker",
                "connection_mode": "filestash_local",
                "label_prefix": "TRION /",
            }
        }
    }

    effective, mounts = views.apply_package_runtime_views("filestash", bp, manifest)

    assert len(mounts) == 2
    assert mounts[0]["asset_id"] == "games-lib"
    assert mounts[0]["container"] == "/srv/storage-broker/games-lib"
    assert mounts[0]["mode"] == "rw"
    assert mounts[1]["asset_id"] == "media-import"
    assert mounts[1]["container"] == "/srv/storage-broker/media-import"
    assert mounts[1]["mode"] == "ro"

    payload = effective.environment["TRION_FILESTASH_CONNECTIONS_JSON"]
    assert '"type":"local"' in payload
    assert '"label":"TRION / Games Library"' in payload
    assert '"label":"TRION / Media Import"' in payload
    assert '"path":"/srv/storage-broker/games-lib"' in payload


def test_filestash_runtime_view_no_assets_keeps_blueprint_unchanged(monkeypatch):
    from container_commander import package_runtime_views as views

    monkeypatch.setattr(views, "_list_broker_assets", lambda published_only, source_kinds: [])

    bp = Blueprint(id="filestash", name="Filestash", image="machines/filestash:latest")
    manifest = {
        "runtime_storage_views": {
            "broker_assets": {
                "enabled": True,
            }
        }
    }

    effective, mounts = views.apply_package_runtime_views("filestash", bp, manifest)

    assert effective.environment == {}
    assert mounts == []
