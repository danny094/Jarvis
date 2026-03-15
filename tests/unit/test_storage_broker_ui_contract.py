from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_storage_broker_tools_ui_has_basic_advanced_navigation_and_setup_wizard():
    src = _read("adapters/Jarvis/js/apps/tools.js")
    assert 'data-sb-mode="basic"' in src
    assert 'data-sb-mode="advanced"' in src
    assert 'id: "overview"' in src
    assert 'id: "setup"' in src
    assert 'id: "managed_paths"' in src
    assert 'id: "policies"' in src
    assert "function sbRenderSetupWizard(" in src
    assert 'data-sb-setup-run="dry"' in src
    assert 'data-sb-setup-run="apply"' in src


def test_storage_broker_tools_ui_calls_new_storage_admin_endpoints():
    src = _read("adapters/Jarvis/js/apps/tools.js")
    assert "/api/storage-broker/managed-paths" in src
    assert "/api/storage-broker/validate-path" in src
    assert "/api/storage-broker/provision/service-dir" in src
    assert "/api/storage-broker/mount" in src
    assert "/api/storage-broker/format" in src


def test_storage_broker_admin_api_exposes_new_proxy_routes():
    src = _read("adapters/admin-api/storage_broker_routes.py")
    assert '@router.get("/managed-paths")' in src
    assert '@router.post("/validate-path")' in src
    assert '@router.post("/provision/service-dir")' in src
    assert '@router.post("/mount")' in src
    assert '@router.post("/format")' in src
    assert '"storage_list_managed_paths"' in src
    assert '"storage_validate_path"' in src
    assert '"storage_create_service_dir"' in src
    assert '"storage_mount_device"' in src
    assert '"storage_format_device"' in src


def test_storage_broker_css_contains_new_shell_layout_components():
    src = _read("adapters/Jarvis/static/css/tools.css")
    assert ".sb-layout" in src
    assert ".sb-side-nav" in src
    assert ".sb-mode-toggle" in src
    assert ".sb-wizard" in src
    assert ".sb-summary-grid" in src
    assert ".sb-advanced-table" in src
