from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
RUNTIME_HARDWARE_ROOT = ROOT / "adapters" / "runtime-hardware"

if str(RUNTIME_HARDWARE_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_HARDWARE_ROOT))


def test_container_connector_lists_storage_broker_block_refs(monkeypatch):
    from runtime_hardware.connectors import container_connector as cc
    from runtime_hardware.connectors import container_storage_discovery as csd

    def fake_fetch(path, params=None, timeout=8.0):
        if path == "/api/storage-broker/disks":
            return {
                "disks": [
                    {
                        "id": "sdb1",
                        "device": "/dev/sdb1",
                        "disk_type": "part",
                        "label": "Games SSD",
                        "filesystem": "ext4",
                        "policy_state": "managed_rw",
                        "zone": "managed_services",
                        "risk_level": "safe",
                        "managed": True,
                        "allowed_operations": ["assign_to_container"],
                        "mountpoints": ["/data/games"],
                        "notes": ["published for services"],
                        "size_bytes": 1000,
                        "available_bytes": 500,
                    }
                ]
            }
        if path == "/api/commander/storage/assets":
            return {"assets": {}}
        return {}

    monkeypatch.setattr(cc, "_discover_device_resources", lambda: [])
    monkeypatch.setattr(cc, "_discover_block_resources", lambda: [])
    monkeypatch.setattr(csd, "_fetch_admin_api_json", fake_fetch)

    resources = cc.ContainerConnector().list_resources()
    resource = next(item for item in resources if item.id == "container::block_device_ref::/dev/sdb1")

    assert resource.kind == "block_device_ref"
    assert resource.host_path == "/dev/sdb1"
    assert resource.metadata["storage_source"] == "storage_broker"
    assert resource.metadata["zone"] == "managed_services"
    assert resource.metadata["policy_state"] == "managed_rw"
    assert "policy:managed_rw" in resource.capabilities
    assert "zone:managed_services" in resource.capabilities


def test_container_connector_lists_published_storage_assets_as_mount_refs(monkeypatch):
    from runtime_hardware.connectors import container_connector as cc
    from runtime_hardware.connectors import container_storage_discovery as csd

    def fake_fetch(path, params=None, timeout=8.0):
        if path == "/api/storage-broker/disks":
            return {
                "disks": [
                    {
                        "id": "sdb1",
                        "device": "/dev/sdb1",
                        "disk_type": "part",
                        "label": "Games SSD",
                        "filesystem": "ext4",
                        "policy_state": "managed_rw",
                        "zone": "managed_services",
                        "risk_level": "safe",
                        "managed": True,
                        "is_external": True,
                        "allowed_operations": ["assign_to_container"],
                        "size_bytes": 1099511627776,
                        "available_bytes": 274877906944,
                    }
                ]
            }
        if path == "/api/commander/storage/assets":
            return {
                "assets": {
                    "games-lib": {
                        "id": "games-lib",
                        "label": "Games Library",
                        "path": "/data/games",
                        "zone": "managed_services",
                        "policy_state": "managed_rw",
                        "default_mode": "rw",
                        "published_to_commander": True,
                        "allowed_for": ["games", "workspace"],
                        "source_disk_id": "sdb1",
                        "source_kind": "existing_path",
                    }
                }
            }
        return {}

    monkeypatch.setattr(cc, "_discover_device_resources", lambda: [])
    monkeypatch.setattr(cc, "_discover_block_resources", lambda: [])
    monkeypatch.setattr(csd, "_fetch_admin_api_json", fake_fetch)

    connector = cc.ContainerConnector()
    resources = connector.list_resources()
    resource = next(item for item in resources if item.id == "container::mount_ref::games-lib")

    assert resource.kind == "mount_ref"
    assert resource.host_path == "/data/games"
    assert resource.metadata["storage_source"] == "storage_asset"
    assert resource.metadata["asset_id"] == "games-lib"
    assert resource.metadata["default_container_path"] == "/storage/games-lib"
    assert resource.metadata["source_disk_id"] == "sdb1"
    assert resource.metadata["source_disk_label"] == "Games SSD"
    assert resource.metadata["size_bytes"] == 1099511627776
    assert resource.metadata["available_bytes"] == 274877906944
    assert "published" in resource.capabilities
    assert "usage:games" in resource.capabilities
    assert "usage:workspace" in resource.capabilities
    assert "storage_broker" in resource.capabilities
    assert resource.metadata["broker_managed"] is True
    assert "Extern" in resource.metadata["display_badges"]
    assert "Games SSD" in resource.metadata["display_secondary"]
    assert "1.0 TB" in resource.metadata["display_secondary"]
    assert "256.0 GB frei" in resource.metadata["display_secondary"]

    mount_capability = next(item for item in connector.get_capabilities() if item.resource_kind == "mount_ref")
    assert mount_capability.stage_supported is True


def test_container_connector_skips_storage_assets_outside_current_managed_paths(monkeypatch):
    from runtime_hardware.connectors import container_connector as cc
    from runtime_hardware.connectors import container_storage_discovery as csd

    def fake_fetch(path, params=None, timeout=8.0):
        if path == "/api/storage-broker/disks":
            return {
                "disks": [
                    {
                        "id": "sdb1",
                        "device": "/dev/sdb1",
                        "disk_type": "part",
                        "label": "Games SSD",
                        "filesystem": "ext4",
                        "policy_state": "managed_rw",
                        "zone": "managed_services",
                        "risk_level": "safe",
                        "managed": True,
                        "allowed_operations": ["assign_to_container"],
                    }
                ]
            }
        if path == "/api/storage-broker/managed-paths":
            return {"managed_paths": ["/data/services/containers"]}
        if path == "/api/commander/storage/assets":
            return {
                "assets": {
                    "stale-games": {
                        "id": "stale-games",
                        "label": "Gaming Station Data",
                        "path": "/data/services/gaming-station/data",
                        "zone": "managed_services",
                        "policy_state": "managed_rw",
                        "default_mode": "rw",
                        "published_to_commander": True,
                        "source_disk_id": "sdb1",
                        "source_kind": "service_dir",
                    },
                    "containers": {
                        "id": "containers",
                        "label": "containers",
                        "path": "/data/services/containers",
                        "zone": "managed_services",
                        "policy_state": "managed_rw",
                        "default_mode": "rw",
                        "published_to_commander": True,
                        "source_disk_id": "sdb1",
                        "source_kind": "service_dir",
                    },
                }
            }
        return {}

    monkeypatch.setattr(cc, "_discover_device_resources", lambda: [])
    monkeypatch.setattr(cc, "_discover_block_resources", lambda: [])
    monkeypatch.setattr(csd, "_fetch_admin_api_json", fake_fetch)

    resources = cc.ContainerConnector().list_resources()
    ids = {item.id for item in resources if item.kind == "mount_ref"}

    assert "container::mount_ref::containers" in ids
    assert "container::mount_ref::stale-games" not in ids


def test_container_connector_keeps_broker_published_imports_even_outside_managed_paths(monkeypatch):
    from runtime_hardware.connectors import container_connector as cc
    from runtime_hardware.connectors import container_storage_discovery as csd

    def fake_fetch(path, params=None, timeout=8.0):
        if path == "/api/storage-broker/disks":
            return {
                "disks": [
                    {
                        "id": "sdc1",
                        "device": "/dev/sdc1",
                        "disk_type": "part",
                        "label": "USB Import",
                        "filesystem": "ext4",
                        "policy_state": "read_only",
                        "zone": "external",
                        "risk_level": "safe",
                        "managed": True,
                        "is_external": True,
                        "allowed_operations": ["assign_to_container"],
                    }
                ]
            }
        if path == "/api/storage-broker/managed-paths":
            return {"managed_paths": ["/data/services/containers"]}
        if path == "/api/commander/storage/assets":
            return {
                "assets": {
                    "usb-import": {
                        "id": "usb-import",
                        "label": "USB Import",
                        "path": "/mnt/usb-import",
                        "zone": "external",
                        "policy_state": "read_only",
                        "default_mode": "ro",
                        "published_to_commander": True,
                        "source_disk_id": "sdc1",
                        "source_kind": "import",
                    }
                }
            }
        return {}

    monkeypatch.setattr(cc, "_discover_device_resources", lambda: [])
    monkeypatch.setattr(cc, "_discover_block_resources", lambda: [])
    monkeypatch.setattr(csd, "_fetch_admin_api_json", fake_fetch)

    resources = cc.ContainerConnector().list_resources()
    resource = next(item for item in resources if item.id == "container::mount_ref::usb-import")

    assert resource.host_path == "/mnt/usb-import"
    assert resource.metadata["broker_managed"] is True
    assert "storage_broker" in resource.capabilities


def test_connectors_package_import_remains_usable_after_storage_split():
    import runtime_hardware.connectors as connectors

    assert connectors.ContainerConnector is not None


def test_input_resource_prefers_sysfs_name_when_udev_has_no_label(monkeypatch):
    from runtime_hardware.connectors import container_connector as cc

    monkeypatch.setattr(cc, "_parse_udev_properties", lambda path: {"ID_INPUT_MOUSE": "1"})
    monkeypatch.setattr(cc, "_read_sysfs_input_name", lambda path: "Gaming Mouse")

    resource = cc._resource_from_device("/dev/input/event21")

    assert resource is not None
    assert resource.kind == "input"
    assert resource.label == "Gaming Mouse"
    assert "mouse" in resource.capabilities
    assert resource.metadata["sysfs_input_name"] == "Gaming Mouse"


def test_container_connector_hides_technical_block_devices_from_simple_display(monkeypatch):
    from runtime_hardware.connectors import container_connector as cc
    from runtime_hardware.connectors import container_storage_discovery as csd

    def fake_fetch(path, params=None, timeout=8.0):
        if path == "/api/storage-broker/disks":
            return {
                "disks": [
                    {
                        "id": "dm-0",
                        "device": "/dev/dm-0",
                        "disk_type": "disk",
                        "label": "dm-0",
                        "filesystem": "",
                        "policy_state": "blocked",
                        "zone": "system",
                        "risk_level": "critical",
                        "is_system": True,
                        "allowed_operations": [],
                    },
                    {
                        "id": "sda1",
                        "device": "/dev/sda1",
                        "disk_type": "part",
                        "label": "EFI",
                        "filesystem": "fat32",
                        "policy_state": "managed_rw",
                        "zone": "managed_services",
                        "risk_level": "safe",
                        "managed": True,
                        "is_external": True,
                        "allowed_operations": ["assign_to_container"],
                        "size_bytes": 209715200,
                    },
                    {
                        "id": "sdb1",
                        "device": "/dev/sdb1",
                        "disk_type": "part",
                        "label": "Games SSD",
                        "filesystem": "ext4",
                        "policy_state": "managed_rw",
                        "zone": "managed_services",
                        "risk_level": "safe",
                        "managed": True,
                        "is_external": True,
                        "allowed_operations": ["assign_to_container"],
                        "size_bytes": 2147483648,
                    },
                ]
            }
        if path == "/api/commander/storage/assets":
            return {"assets": {}}
        return {}

    monkeypatch.setattr(cc, "_discover_device_resources", lambda: [])
    monkeypatch.setattr(cc, "_discover_block_resources", lambda: [])
    monkeypatch.setattr(csd, "_fetch_admin_api_json", fake_fetch)

    resources = cc.ContainerConnector().list_resources()
    dm_resource = next(item for item in resources if item.id == "container::block_device_ref::/dev/dm-0")
    tiny_resource = next(item for item in resources if item.id == "container::block_device_ref::/dev/sda1")
    games_resource = next(item for item in resources if item.id == "container::block_device_ref::/dev/sdb1")

    assert dm_resource.metadata["simple_visibility"] == "hidden"
    assert tiny_resource.metadata["simple_visibility"] == "hidden"
    assert "Systemkritisch" in dm_resource.metadata["display_badges"]
    assert games_resource.metadata["simple_visibility"] == "visible"
    assert games_resource.metadata["display_name"] == "Games SSD"
    assert "Extern" in games_resource.metadata["display_badges"]


def test_container_connector_groups_input_passthrough_variants_for_simple_display(monkeypatch):
    from runtime_hardware.connectors import container_connector as cc
    from runtime_hardware.models import HardwareResource

    mouse_group = "/sys/devices/pci0000:00/0000:00:14.0/usb1/1-1/input"
    resources = [
        HardwareResource(
            id="container::input::/dev/input/event21",
            kind="input",
            source_connector="container",
            label="Mouse passthrough",
            host_path="/dev/input/event21",
            capabilities=["mouse"],
            risk_level="high",
            metadata={
                "technical_label": "Mouse passthrough",
                "input_device_path": f"{mouse_group}/input21/device",
            },
        ),
        HardwareResource(
            id="container::input::/dev/input/event22",
            kind="input",
            source_connector="container",
            label="Mouse passthrough (absolute)",
            host_path="/dev/input/event22",
            capabilities=["mouse"],
            risk_level="high",
            metadata={
                "technical_label": "Mouse passthrough (absolute)",
                "input_device_path": f"{mouse_group}/input22/device",
            },
        ),
    ]

    monkeypatch.setattr(cc, "_discover_device_resources", lambda: resources)
    monkeypatch.setattr(cc, "_discover_block_resources", lambda: [])
    monkeypatch.setattr(cc, "discover_storage_broker_block_resources", lambda: [])
    monkeypatch.setattr(cc, "discover_storage_asset_mount_refs", lambda: [])

    resolved = cc.ContainerConnector().list_resources()
    visible_inputs = [
        item
        for item in resolved
        if item.kind == "input" and item.metadata.get("simple_visibility") != "hidden"
    ]
    hidden_inputs = [
        item
        for item in resolved
        if item.kind == "input" and item.metadata.get("simple_visibility") == "hidden"
    ]

    assert len(visible_inputs) == 1
    assert len(hidden_inputs) == 1
    assert visible_inputs[0].metadata["display_name"] == "Maus"
    assert visible_inputs[0].metadata["simple_select_resource_ids"] == [
        "container::input::/dev/input/event21",
        "container::input::/dev/input/event22",
    ]
    assert "Kanaele: absolute, event" in visible_inputs[0].metadata["display_secondary"]


def test_container_connector_usb_display_prefers_brand_and_marks_external(monkeypatch):
    from runtime_hardware.connectors import container_connector as cc
    from runtime_hardware.models import HardwareResource

    usb_resource = HardwareResource(
        id="container::usb::/dev/bus/usb/001/002",
        kind="usb",
        source_connector="container",
        label="USB Receiver",
        host_path="/dev/bus/usb/001/002",
        vendor="Logitech",
        product="MX Master 3",
        risk_level="high",
        metadata={
            "technical_label": "USB Receiver",
            "ID_BUS": "usb",
            "ID_PATH": "pci-0000:00:14.0-usb-0:2:1.0",
        },
    )

    monkeypatch.setattr(cc, "_discover_device_resources", lambda: [usb_resource])
    monkeypatch.setattr(cc, "_discover_block_resources", lambda: [])
    monkeypatch.setattr(cc, "discover_storage_broker_block_resources", lambda: [])
    monkeypatch.setattr(cc, "discover_storage_asset_mount_refs", lambda: [])

    resolved = cc.ContainerConnector().list_resources()
    resource = next(item for item in resolved if item.kind == "usb")

    assert resource.metadata["display_name"] == "Logitech MX Master 3"
    assert "USB" in resource.metadata["display_badges"]
    assert "Empfaenger" in resource.metadata["display_badges"]
    assert "Extern" in resource.metadata["display_badges"]
    assert resource.metadata["simple_visibility"] == "visible"


def test_container_connector_usb_root_hub_is_hidden_from_simple_display(monkeypatch):
    from runtime_hardware.connectors import container_connector as cc
    from runtime_hardware.models import HardwareResource

    usb_resource = HardwareResource(
        id="container::usb::/dev/bus/usb/001/001",
        kind="usb",
        source_connector="container",
        label="2.0 root hub",
        host_path="/dev/bus/usb/001/001",
        vendor="Linux Foundation",
        product="2.0 root hub",
        risk_level="high",
        metadata={
            "technical_label": "2.0 root hub",
            "ID_BUS": "usb",
            "ID_USB_DRIVER": "hub",
            "ID_PATH": "platform-xhci-hcd.0.auto-usb-0:1:1.0",
        },
    )

    monkeypatch.setattr(cc, "_discover_device_resources", lambda: [usb_resource])
    monkeypatch.setattr(cc, "_discover_block_resources", lambda: [])
    monkeypatch.setattr(cc, "discover_storage_broker_block_resources", lambda: [])
    monkeypatch.setattr(cc, "discover_storage_asset_mount_refs", lambda: [])

    resolved = cc.ContainerConnector().list_resources()
    resource = next(item for item in resolved if item.kind == "usb")

    assert resource.metadata["display_name"] == "Linux Foundation 2.0 root hub"
    assert resource.metadata["simple_visibility"] == "hidden"
    assert "Intern" in resource.metadata["display_badges"]


def test_container_connector_usb_sata_bridge_is_not_misclassified_as_audio(monkeypatch):
    from runtime_hardware.connectors import container_connector as cc
    from runtime_hardware.models import HardwareResource

    usb_resource = HardwareResource(
        id="container::usb::/dev/bus/usb/003/027",
        kind="usb",
        source_connector="container",
        label="JMS561U two ports SATA 6Gb/s bridge",
        host_path="/dev/bus/usb/003/027",
        vendor="JMicron Technology Corp.",
        product="JMS561U two ports SATA 6Gb/s bridge",
        risk_level="high",
        metadata={
            "technical_label": "JMS561U two ports SATA 6Gb/s bridge",
            "ID_BUS": "usb",
            "ID_PATH": "pci-0000:00:14.0-usb-0:3:1.0",
        },
    )

    monkeypatch.setattr(cc, "_discover_device_resources", lambda: [usb_resource])
    monkeypatch.setattr(cc, "_discover_block_resources", lambda: [])
    monkeypatch.setattr(cc, "discover_storage_broker_block_resources", lambda: [])
    monkeypatch.setattr(cc, "discover_storage_asset_mount_refs", lambda: [])

    resolved = cc.ContainerConnector().list_resources()
    resource = next(item for item in resolved if item.kind == "usb")

    assert "Speicher" in resource.metadata["display_badges"]
    assert "Audio" not in resource.metadata["display_badges"]


def test_container_connector_hides_internal_audio_input_from_simple_display(monkeypatch):
    from runtime_hardware.connectors import container_connector as cc
    from runtime_hardware.models import HardwareResource

    input_resource = HardwareResource(
        id="container::input::/dev/input/event8",
        kind="input",
        source_connector="container",
        label="HD-Audio Generic HDMI/DP,pcm=7",
        host_path="/dev/input/event8",
        capabilities=[],
        risk_level="high",
        metadata={
            "technical_label": "HD-Audio Generic HDMI/DP,pcm=7",
            "ID_PATH": "pci-0000:09:00.1-input",
        },
    )

    monkeypatch.setattr(cc, "_discover_device_resources", lambda: [input_resource])
    monkeypatch.setattr(cc, "_discover_block_resources", lambda: [])
    monkeypatch.setattr(cc, "discover_storage_broker_block_resources", lambda: [])
    monkeypatch.setattr(cc, "discover_storage_asset_mount_refs", lambda: [])

    resolved = cc.ContainerConnector().list_resources()
    resource = next(item for item in resolved if item.kind == "input")

    assert resource.metadata["display_name"] == "Monitor-Audio"
    assert resource.metadata["simple_visibility"] == "hidden"


def test_container_connector_formats_raw_block_partition_names_for_simple_display(monkeypatch):
    from runtime_hardware.connectors import container_connector as cc
    from runtime_hardware.connectors import container_storage_discovery as csd

    def fake_fetch(path, params=None, timeout=8.0):
        if path == "/api/storage-broker/disks":
            return {
                "disks": [
                    {
                        "id": "sdb3",
                        "device": "/dev/sdb3",
                        "disk_type": "part",
                        "label": "",
                        "filesystem": "",
                        "policy_state": "read_only",
                        "zone": "unzoned",
                        "risk_level": "caution",
                        "managed": False,
                        "is_external": False,
                        "allowed_operations": [],
                        "size_bytes": 479875563520,
                    },
                    {
                        "id": "sdd1",
                        "device": "/dev/sdd1",
                        "disk_type": "part",
                        "label": "",
                        "filesystem": "",
                        "policy_state": "managed_rw",
                        "zone": "managed_services",
                        "risk_level": "safe",
                        "managed": True,
                        "is_external": False,
                        "allowed_operations": ["assign_to_container"],
                        "mountpoint": "/data",
                        "mountpoints": ["/data"],
                        "size_bytes": 536870912000,
                    },
                ]
            }
        if path == "/api/commander/storage/assets":
            return {"assets": {}}
        return {}

    monkeypatch.setattr(cc, "_discover_device_resources", lambda: [])
    monkeypatch.setattr(cc, "_discover_block_resources", lambda: [])
    monkeypatch.setattr(csd, "_fetch_admin_api_json", fake_fetch)

    resources = cc.ContainerConnector().list_resources()
    readonly_resource = next(item for item in resources if item.id == "container::block_device_ref::/dev/sdb3")
    managed_resource = next(item for item in resources if item.id == "container::block_device_ref::/dev/sdd1")

    assert readonly_resource.metadata["display_name"] == "Read-only Partition 3"
    assert managed_resource.metadata["display_name"] == "Service-Speicher"
