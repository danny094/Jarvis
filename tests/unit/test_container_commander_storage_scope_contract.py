from pathlib import Path
from types import SimpleNamespace


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_models_expose_storage_scope_and_mount_type():
    src = _read("container_commander/models.py")
    assert "type: str = Field(default=\"bind\"" in src
    assert "storage_scope: str" in src
    assert "asset_id: Optional[str]" in src
    assert "class StorageAsset(BaseModel):" in src


def test_storage_scope_module_contract_present():
    src = _read("container_commander/storage_scope.py")
    assert "def list_scopes" in src
    assert "def get_scope" in src
    assert "def upsert_scope" in src
    assert "def delete_scope" in src
    assert "def validate_blueprint_mounts" in src
    assert "\"metadata\"" in src


def test_storage_asset_module_contract_present():
    src = _read("container_commander/storage_assets.py")
    assert "def list_assets" in src
    assert "def get_asset" in src
    assert "def upsert_asset" in src
    assert "def delete_asset" in src


def test_engine_enforces_storage_scope_and_vault_refs():
    src = _read("container_commander/engine.py")
    assert "validate_blueprint_mounts(bp)" in src
    assert "vault://" in src
    assert "inject_vault_ref" in src
    assert "mount_type = str(getattr(mount, \"type\", \"bind\")" in src


def test_storage_scope_endpoints_and_mcp_tools_present():
    storage_src = _read("adapters/admin-api/commander_api/storage.py")
    assert "@router.get(\"/storage/scopes\")" in storage_src
    assert "@router.post(\"/storage/scopes\")" in storage_src
    assert "@router.delete(\"/storage/scopes/{scope_name}\")" in storage_src
    assert "@router.get(\"/storage/assets\")" in storage_src
    assert "@router.post(\"/storage/assets\")" in storage_src
    assert "@router.delete(\"/storage/assets/{asset_id}\")" in storage_src
    assert "_extend_catalog_with_assets" in storage_src

    mcp_src = _read("container_commander/mcp_tools.py")
    assert "\"name\": \"storage_scope_list\"" in mcp_src
    assert "\"name\": \"storage_scope_upsert\"" in mcp_src
    assert "\"name\": \"storage_scope_delete\"" in mcp_src


def test_validate_blueprint_mounts_blocks_unscoped_bind_mounts():
    import container_commander.storage_scope as scopes

    bp = SimpleNamespace(
        storage_scope="",
        mounts=[SimpleNamespace(host="/etc", container="/data", mode="rw", type="bind")],
    )
    ok, reason = scopes.validate_blueprint_mounts(bp)
    assert ok is False
    assert "storage_scope_required" in reason


def test_validate_blueprint_mounts_allows_volume_mount_without_scope():
    import container_commander.storage_scope as scopes

    bp = SimpleNamespace(
        storage_scope="",
        mounts=[SimpleNamespace(host="trion_home_data", container="/home/trion", mode="rw", type="volume")],
    )
    ok, reason = scopes.validate_blueprint_mounts(bp)
    assert ok is True
    assert reason == "ok"


def test_validate_blueprint_mounts_allows_runtime_system_bind_outside_storage_scope(monkeypatch):
    import container_commander.storage_scope as scopes

    monkeypatch.setattr(
        scopes,
        "get_scope",
        lambda name: {
            "name": name,
            "roots": [{"path": "/data/services/gaming-station", "mode": "rw"}],
        },
    )

    bp = SimpleNamespace(
        storage_scope="gaming-station",
        mounts=[SimpleNamespace(host="/dev/input", container="/dev/input", mode="rw", type="bind")],
    )
    ok, reason = scopes.validate_blueprint_mounts(bp)
    assert ok is True
    assert reason == "ok"


def test_validate_blueprint_mounts_blocks_retargeted_runtime_bind(monkeypatch):
    import container_commander.storage_scope as scopes

    monkeypatch.setattr(
        scopes,
        "get_scope",
        lambda name: {
            "name": name,
            "roots": [{"path": "/data/services/gaming-station", "mode": "rw"}],
        },
    )

    bp = SimpleNamespace(
        storage_scope="gaming-station",
        mounts=[SimpleNamespace(host="/dev/input", container="/workspace/dev-input", mode="rw", type="bind")],
    )
    ok, reason = scopes.validate_blueprint_mounts(bp)
    assert ok is False
    assert "storage_scope_violation" in reason


def test_validate_blueprint_mounts_allows_runtime_udev_bind_without_scope():
    import container_commander.storage_scope as scopes

    bp = SimpleNamespace(
        storage_scope="",
        mounts=[SimpleNamespace(host="/run/udev/data", container="/run/udev/data", mode="rw", type="bind")],
    )
    ok, reason = scopes.validate_blueprint_mounts(bp)
    assert ok is True
    assert reason == "ok"
