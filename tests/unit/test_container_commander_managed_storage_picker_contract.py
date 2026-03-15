from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_terminal_preflight_contains_managed_storage_picker_and_payload_wiring():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    assert "apiRequest('/storage/managed-paths'" in src
    assert 'id="pf-storage-path"' in src
    assert 'id="pf-devices"' in src
    assert "parseDeviceOverrides" in src
    assert "payload.device_overrides = devices;" in src
    assert "payload.mount_overrides = [" in src
    assert "payload.storage_scope_override = '__auto__';" in src


def test_commander_route_forwards_mount_overrides_and_scope_override():
    src = _read("adapters/admin-api/commander_routes.py")
    assert "mount_overrides = data.get(\"mount_overrides\")" in src
    assert "storage_scope_override = data.get(\"storage_scope_override\")" in src
    assert "device_overrides = data.get(\"device_overrides\")" in src
    assert "mount_overrides=mount_overrides" in src
    assert "storage_scope_override=storage_scope_override" in src
    assert "device_overrides=device_overrides" in src


def test_storage_router_exposes_managed_paths_catalog_endpoint():
    src = _read("adapters/admin-api/commander_api/storage.py")
    assert "@router.get(\"/storage/managed-paths\")" in src
    assert "storage_list_managed_paths" in src
    assert "\"catalog\":" in src


def test_engine_runtime_mount_override_and_auto_scope_present():
    src = _read("container_commander/engine.py")
    assert "def _normalize_runtime_mount_overrides" in src
    assert "def _normalize_runtime_device_overrides" in src
    assert "def _compose_runtime_blueprint" in src
    assert "runtime_device_overrides" in src
    assert "force_auto_scope" in src
    assert "deploy_auto_" in src


def test_approval_persists_and_replays_mount_override_context():
    src = _read("container_commander/approval.py")
    assert "self.mount_overrides" in src
    assert "self.storage_scope_override" in src
    assert "self.device_overrides" in src
    assert "\"mount_overrides\":" in src
    assert "\"storage_scope_override\":" in src
    assert "\"device_overrides\":" in src
    assert "mount_overrides=approval.mount_overrides" in src
    assert "device_overrides=approval.device_overrides" in src
