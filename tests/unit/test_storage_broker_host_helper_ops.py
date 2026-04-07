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


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = str(payload)

    def json(self):
        return self._payload


def _register(monkeypatch):
    monkeypatch.setattr(sb_tools, "init_db", lambda: None)
    fake = _FakeMCP()
    sb_tools.register_tools(fake)
    return fake.registered


def test_storage_unmount_uses_host_helper_for_live_mount_check_and_exec(monkeypatch):
    tools = _register(monkeypatch)
    monkeypatch.setattr(sb_tools, "list_disks", lambda: [])
    monkeypatch.setattr(
        sb_tools,
        "enrich_disks",
        lambda _disks: [
            SimpleNamespace(
                device="/dev/sdd1",
                id="sdd1",
                disk_type="part",
                is_system=False,
                mountpoints=[],
            )
        ],
    )
    monkeypatch.setattr(sb_tools, "log_operation", lambda *args, **kwargs: None)

    calls = []

    def _post(url, json, timeout):
        calls.append((url, json, timeout))
        if url.endswith("/v1/mount-targets"):
            return _Response({"ok": True, "targets": ["/media/devmon/WII"]})
        if url.endswith("/v1/unmount"):
            return _Response({"ok": True, "device": "/dev/sdd1"})
        raise AssertionError(url)

    monkeypatch.setattr(sb_tools.requests, "post", _post)

    result = tools["storage_unmount_device"]("/dev/sdd1", dry_run=False)["result"]

    assert result["ok"] is True
    assert result["executed"] is True
    assert [url for url, *_rest in calls] == [
        "http://storage-host-helper:8090/v1/mount-targets",
        "http://storage-host-helper:8090/v1/unmount",
    ]


def test_storage_format_uses_host_helper_for_execution(monkeypatch):
    tools = _register(monkeypatch)
    monkeypatch.setattr(sb_tools, "list_disks", lambda: [])
    monkeypatch.setattr(
        sb_tools,
        "enrich_disks",
        lambda _disks: [
            SimpleNamespace(
                device="/dev/sdd1",
                id="sdd1",
                disk_type="part",
                is_system=False,
                mountpoints=[],
            )
        ],
    )
    monkeypatch.setattr(sb_tools, "log_operation", lambda *args, **kwargs: None)

    calls = []

    def _post(url, json, timeout):
        calls.append((url, json, timeout))
        if url.endswith("/v1/mount-targets"):
            return _Response({"ok": True, "targets": []})
        if url.endswith("/v1/format"):
            return _Response({"ok": True, "device": "/dev/sdd1", "filesystem": "ext4"})
        raise AssertionError(url)

    monkeypatch.setattr(sb_tools.requests, "post", _post)

    result = tools["storage_format_device"]("/dev/sdd1", "ext4", label="gaming", dry_run=False)["result"]

    assert result["ok"] is True
    assert result["executed"] is True
    assert calls[-1][0] == "http://storage-host-helper:8090/v1/format"
    assert calls[-1][1] == {"device": "/dev/sdd1", "filesystem": "ext4", "label": "gaming"}
