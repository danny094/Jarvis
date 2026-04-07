from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
BROKER_ROOT = ROOT / "mcp-servers" / "storage-broker"
if str(BROKER_ROOT) not in sys.path:
    sys.path.insert(0, str(BROKER_ROOT))

from storage_broker_mcp import discovery as sb_discovery


def test_list_disks_falls_back_to_partlabel_when_filesystem_label_missing(monkeypatch):
    monkeypatch.setattr(sb_discovery, "_df_map", lambda: {})
    monkeypatch.setattr(
        sb_discovery,
        "_parse_lsblk",
        lambda: [
            {
                "name": "sdd1",
                "path": "/dev/sdd1",
                "uuid": "",
                "label": "games",
                "partlabel": "games",
                "fstype": "",
                "size": 100,
                "mountpoints": [],
                "removable": True,
                "ro": False,
                "type": "part",
            }
        ],
    )
    monkeypatch.setattr(sb_discovery, "_host_mount_map", lambda: {})
    monkeypatch.setattr(sb_discovery, "_build_system_disk_set", lambda *_args, **_kwargs: set())
    monkeypatch.setattr(sb_discovery, "_live_mount_targets", lambda _device: [])

    disks = sb_discovery.list_disks()

    assert len(disks) == 1
    assert disks[0].label == "games"
    assert disks[0].partlabel == "games"


def test_list_disks_uses_dev_disk_symlink_and_blkid_fallbacks(monkeypatch):
    monkeypatch.setattr(sb_discovery, "_df_map", lambda: {})
    monkeypatch.setattr(
        sb_discovery,
        "_parse_lsblk",
        lambda: [
            {
                "name": "sdc2",
                "path": "/dev/sdc2",
                "uuid": "",
                "label": "",
                "partlabel": "",
                "fstype": "",
                "size": 100,
                "mountpoints": [],
                "removable": True,
                "ro": False,
                "type": "part",
            }
        ],
    )
    monkeypatch.setattr(sb_discovery, "_host_mount_map", lambda: {})
    monkeypatch.setattr(sb_discovery, "_build_system_disk_set", lambda *_args, **_kwargs: set())
    monkeypatch.setattr(sb_discovery, "_live_mount_targets", lambda _device: [])
    monkeypatch.setattr(
        sb_discovery,
        "_device_symlink_name_map",
        lambda directory: {"/dev/sdc2": "Basic data partition"} if directory.endswith("by-partlabel") else {},
    )
    monkeypatch.setattr(
        sb_discovery,
        "_blkid_info",
        lambda device: {"TYPE": "ntfs"} if device == "/dev/sdc2" else {},
    )

    disks = sb_discovery.list_disks()

    assert len(disks) == 1
    assert disks[0].partlabel == "Basic data partition"
    assert disks[0].label == "Basic data partition"
    assert disks[0].filesystem == "ntfs"
