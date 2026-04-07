from pathlib import Path
from types import SimpleNamespace
import sys


ROOT = Path(__file__).resolve().parents[2]
BROKER_ROOT = ROOT / "mcp-servers" / "storage-broker"
if str(BROKER_ROOT) not in sys.path:
    sys.path.insert(0, str(BROKER_ROOT))

from storage_broker_mcp import tools as sb_tools


class _FakeMCP:
    def __init__(self):
        self.registered = {}

    def tool(self, fn):
        self.registered[fn.__name__] = fn
        return fn


def _register(monkeypatch):
    monkeypatch.setattr(sb_tools, "init_db", lambda: None)
    fake = _FakeMCP()
    sb_tools.register_tools(fake)
    return fake.registered


def test_storage_format_blocks_whole_disk_when_child_partitions_exist(monkeypatch):
    tools = _register(monkeypatch)
    monkeypatch.setattr(sb_tools, "list_disks", lambda: [])
    monkeypatch.setattr(
        sb_tools,
        "enrich_disks",
        lambda _disks: [
            SimpleNamespace(device="/dev/sdd", id="sdd", disk_type="disk", is_system=False, mountpoints=[]),
            SimpleNamespace(device="/dev/sdd1", id="sdd1", disk_type="part", is_system=False, mountpoints=["/media/test"]),
        ],
    )
    monkeypatch.setattr(sb_tools, "log_operation", lambda *args, **kwargs: None)

    result = tools["storage_format_device"]("/dev/sdd", "ext4", dry_run=False)["result"]

    assert result["ok"] is False
    assert "whole disk with partitions" in result["error"]
    assert "/dev/sdd1" in result["error"]


def test_storage_mount_blocks_whole_disk_when_child_partitions_exist(monkeypatch):
    tools = _register(monkeypatch)
    monkeypatch.setattr(sb_tools, "list_disks", lambda: [])
    monkeypatch.setattr(
        sb_tools,
        "enrich_disks",
        lambda _disks: [
            SimpleNamespace(device="/dev/sdd", id="sdd", disk_type="disk", is_system=False, mountpoints=[]),
            SimpleNamespace(device="/dev/sdd1", id="sdd1", disk_type="part", is_system=False, mountpoints=["/media/test"]),
        ],
    )
    monkeypatch.setattr(sb_tools, "log_operation", lambda *args, **kwargs: None)

    result = tools["storage_mount_device"]("/dev/sdd", "/mnt/test", dry_run=False)["result"]

    assert result["ok"] is False
    assert "whole disk with partitions" in result["error"]
    assert "/dev/sdd1" in result["error"]


def test_storage_unmount_blocks_whole_disk_when_child_partitions_exist(monkeypatch):
    tools = _register(monkeypatch)
    monkeypatch.setattr(sb_tools, "list_disks", lambda: [])
    monkeypatch.setattr(
        sb_tools,
        "enrich_disks",
        lambda _disks: [
            SimpleNamespace(device="/dev/sdd", id="sdd", disk_type="disk", is_system=False, mountpoints=[]),
            SimpleNamespace(device="/dev/sdd1", id="sdd1", disk_type="part", is_system=False, mountpoints=["/media/test"]),
        ],
    )
    monkeypatch.setattr(sb_tools, "log_operation", lambda *args, **kwargs: None)

    result = tools["storage_unmount_device"]("/dev/sdd", dry_run=False)["result"]

    assert result["ok"] is False
    assert "whole disk with partitions" in result["error"]
    assert "/dev/sdd1" in result["error"]


def test_storage_format_delegates_to_host_helper_when_live_mount_exists(monkeypatch):
    tools = _register(monkeypatch)
    monkeypatch.setattr(sb_tools, "list_disks", lambda: [])
    monkeypatch.setattr(
        sb_tools,
        "enrich_disks",
        lambda _disks: [
            SimpleNamespace(device="/dev/sdd1", id="sdd1", disk_type="part", is_system=False, mountpoints=[]),
        ],
    )
    monkeypatch.setattr(sb_tools, "log_operation", lambda *args, **kwargs: None)

    class _Response:
        def __init__(self, payload):
            self._payload = payload
            self.status_code = 200
            self.ok = True
            self.text = str(payload)

        def json(self):
            return self._payload

    calls = []

    def _post(url, json, timeout):
        calls.append((url, json, timeout))
        return _Response({"ok": True})

    monkeypatch.setattr(sb_tools.requests, "post", _post)

    result = tools["storage_format_device"]("/dev/sdd1", "ext4", dry_run=False)["result"]

    assert result["ok"] is True
    assert result["executed"] is True
    assert calls == [
        ("http://storage-host-helper:8090/v1/format", {"device": "/dev/sdd1", "filesystem": "ext4", "label": ""}, 120),
    ]
