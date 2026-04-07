from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_admin_api_startup_seeds_filestash_blueprint():
    src = _read("adapters/admin-api/main.py")
    assert "from container_commander.filestash_blueprint import ensure_filestash_blueprint" in src
    assert "await asyncio.to_thread(ensure_filestash_blueprint)" in src


def test_filestash_package_manifest_declares_blueprint_and_access_link():
    src = _read("marketplace/packages/filestash/package.json")
    assert '"id": "filestash"' in src
    assert '"blueprints": [' in src
    assert '"filestash"' in src
    assert '"kind": "access_links_only"' in src
    assert '"host_port": "8334"' in src


def test_ensure_filestash_blueprint_creates_volume_backed_reference_service(monkeypatch, tmp_path):
    from container_commander import blueprint_store
    from container_commander.filestash_blueprint import ensure_filestash_blueprint

    db_path = tmp_path / "commander.db"
    monkeypatch.setattr(blueprint_store, "DB_PATH", str(db_path))
    monkeypatch.setattr(blueprint_store, "_INIT_DONE", False)

    ensure_filestash_blueprint()

    bp = blueprint_store.get_blueprint("filestash")
    assert bp is not None
    assert bp.image == "machines/filestash:latest"
    assert bp.ports == ["8334:8334/tcp"]
    assert len(bp.mounts) == 1
    assert bp.mounts[0].type == "volume"
    assert bp.mounts[0].host == "filestash_state"
    assert bp.mounts[0].container == "/app/data/state"
    assert "TRION_FILESTASH_CONNECTIONS_JSON" in bp.environment
