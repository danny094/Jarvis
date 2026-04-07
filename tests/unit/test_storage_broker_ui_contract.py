from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_storage_broker_tools_ui_has_basic_advanced_navigation_and_setup_wizard():
    src = _read("adapters/Jarvis/js/apps/storage-broker.js")
    assert 'id: "disks"' in src
    assert 'id: "managed_paths"' in src
    assert 'id: "policies"' in src
    assert "function sbKdeToolbar(" in src
    assert 'data-sb-kde-tab="' in src
    assert 'sb-kde-tb-wizard' in src
    assert 'data-sb-setup-start="services"' in src


def test_storage_broker_tools_ui_calls_new_storage_admin_endpoints():
    src = _read("adapters/Jarvis/js/apps/storage-broker.js")
    assert "/api/storage-broker/managed-paths" in src
    assert "/api/storage-broker/validate-path" in src
    assert "/api/storage-broker/provision/service-dir" in src
    assert "/api/storage-broker/mount" in src
    assert "/api/storage-broker/unmount" in src
    assert "/api/storage-broker/format" in src
    assert "/api/commander/storage/assets" in src


def test_storage_broker_tools_ui_formats_and_mounts_selected_partition_targets():
    src = _read("adapters/Jarvis/js/apps/storage-broker.js")
    assert "selectedPartId" in src
    assert "const usablePartitions = partitions.filter((part) => !sbIsSmallSystemPart(part));" in src
    assert "function sbPartitionDevicePath(partition)" in src
    assert "function sbStorageItemLabel(item, fallback = \"\")" in src
    assert "function sbStorageItemDisplayName(item, fallback = \"\")" in src
    assert "function sbKdeRenderPartTable(disk, tree)" in src
    assert "function sbKdeRenderDiskBar(disk, tree)" in src
    assert 'id="sb-kde-table"' in src
    assert 'id="sb-kde-format-btn"' in src
    assert "window.confirm(" in src
    assert "sb-kde-output-status" in src
    assert "sb-kde-usage-bar" in src
    assert "sb-kde-mount-dot" in src
    assert "sb-kde-badge-dot" in src
    assert "Mountpoint in managed_bases aufgenommen." in src
    assert "SB_SERVICE_DIR_PROFILES" in src
    assert "publish_to_commander" in src
    assert "asset_default_mode" in src
    assert "asset_allowed_for" in src
    assert "Commander-Freigabe" in src


def test_storage_broker_setup_wizard_stops_after_format_failure():
    src = _read("adapters/Jarvis/js/apps/storage-broker.js")
    assert "function sbRequireResultOk(result, fallbackMessage)" in src
    assert 'sbRequireResultOk(formatRes, "Formatierung fehlgeschlagen.");' in src


def test_storage_broker_setup_wizard_has_bound_navigation_and_four_step_completion():
    src = _read("adapters/Jarvis/js/apps/storage-broker.js")
    assert 'querySelector("[data-sb-setup-cancel]")' in src
    assert 'querySelector("[data-sb-setup-back]")' in src
    assert 'querySelector("[data-sb-setup-next]")' in src
    assert 'querySelectorAll("[data-sb-setup-run]")' in src
    assert 'querySelector("[data-sb-setup-done]")' in src
    assert "sbReadSetupFields(root);" in src
    assert "sbValidateSetupStep" in src
    assert "state.sb.setup.step = 4;" in src
    assert "Schritt ${step} von ${totalSteps}" in src


def test_tools_app_imports_storage_broker_module():
    src = _read("adapters/Jarvis/js/apps/tools.js")
    assert 'from "./storage-broker.js"' in src
    assert "renderStorageBrokerPanel({" in src
    assert "createStorageBrokerState()" in src


def test_storage_broker_admin_api_exposes_new_proxy_routes():
    src = _read("adapters/admin-api/storage_broker_routes.py")
    assert '@router.get("/managed-paths")' in src
    assert '@router.post("/validate-path")' in src
    assert '@router.post("/provision/service-dir")' in src
    assert '@router.post("/mount")' in src
    assert '@router.post("/unmount")' in src
    assert '@router.post("/format")' in src
    assert '"storage_list_managed_paths"' in src
    assert '"storage_validate_path"' in src
    assert '"storage_create_service_dir"' in src
    assert '"storage_mount_device"' in src
    assert '"storage_unmount_device"' in src
    assert '"storage_format_device"' in src


def test_storage_broker_css_contains_new_shell_layout_components():
    src = _read("adapters/Jarvis/static/css/tools.css")
    assert ".sb-layout" in src
    assert ".sb-side-nav" in src
    assert ".sb-mode-toggle" in src
    assert ".sb-wizard" in src
    assert ".sb-summary-grid" in src
    assert ".sb-advanced-table" in src
