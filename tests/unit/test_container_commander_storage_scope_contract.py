from pathlib import Path
from types import SimpleNamespace


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_models_expose_storage_scope_and_mount_type():
    src = _read("container_commander/models.py")
    assert "type: str = Field(default=\"bind\"" in src
    assert "storage_scope: str" in src


def test_storage_scope_module_contract_present():
    src = _read("container_commander/storage_scope.py")
    assert "def list_scopes" in src
    assert "def get_scope" in src
    assert "def upsert_scope" in src
    assert "def delete_scope" in src
    assert "def validate_blueprint_mounts" in src


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
