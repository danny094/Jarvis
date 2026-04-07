from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
BROKER_ROOT = ROOT / "mcp-servers" / "storage-broker"
if str(BROKER_ROOT) not in sys.path:
    sys.path.insert(0, str(BROKER_ROOT))

from storage_broker_mcp import discovery as sb_discovery


def test_list_disks_clears_stale_lsblk_mountpoints_without_host_or_live_confirmation(monkeypatch):
    monkeypatch.setattr(sb_discovery, "_df_map", lambda: {})
    monkeypatch.setattr(
        sb_discovery,
        "_parse_lsblk",
        lambda: [
            {
                "name": "sdd1",
                "path": "/dev/sdd1",
                "uuid": "",
                "label": "WII",
                "fstype": "ext4",
                "size": 100,
                "mountpoints": ["/media/devmon/WII"],
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
    assert disks[0].mountpoint == ""
    assert disks[0].mountpoints == []


def test_list_disks_prefers_host_mount_map_when_available(monkeypatch):
    monkeypatch.setattr(sb_discovery, "_df_map", lambda: {"/srv/storage": 4096})
    monkeypatch.setattr(
        sb_discovery,
        "_parse_lsblk",
        lambda: [
            {
                "name": "sdd1",
                "path": "/dev/sdd1",
                "uuid": "",
                "label": "DATA",
                "fstype": "ext4",
                "size": 100,
                "mountpoints": ["/stale/from/lsblk"],
                "removable": True,
                "ro": False,
                "type": "part",
            }
        ],
    )
    monkeypatch.setattr(sb_discovery, "_host_mount_map", lambda: {"/dev/sdd1": ["/srv/storage"]})
    monkeypatch.setattr(sb_discovery, "_build_system_disk_set", lambda *_args, **_kwargs: set())
    monkeypatch.setattr(sb_discovery, "_live_mount_targets", lambda _device: ["/ignored/live"])

    disks = sb_discovery.list_disks()

    assert len(disks) == 1
    assert disks[0].mountpoint == "/srv/storage"
    assert disks[0].mountpoints == ["/srv/storage"]
    assert disks[0].available_bytes == 4096
