from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
HELPER_ROOT = ROOT / "mcp-servers" / "storage-host-helper"
if str(HELPER_ROOT) not in sys.path:
    sys.path.insert(0, str(HELPER_ROOT))

from fastapi.testclient import TestClient

import app as storage_host_helper_app


def test_storage_host_helper_mount_targets_returns_parsed_lines(monkeypatch):
    class _Completed:
        returncode = 0
        stdout = "/media/devmon/WII\n"
        stderr = ""

    monkeypatch.setattr(storage_host_helper_app, "_run_host_command", lambda cmd, timeout: _Completed())

    client = TestClient(storage_host_helper_app.app)
    response = client.post("/v1/mount-targets", json={"device": "/dev/sdd1"})

    assert response.status_code == 200
    assert response.json()["targets"] == ["/media/devmon/WII"]


def test_storage_host_helper_format_rejects_unsupported_fs():
    client = TestClient(storage_host_helper_app.app)
    response = client.post("/v1/format", json={"device": "/dev/sdd1", "filesystem": "ntfs", "label": ""})

    assert response.status_code == 400
    assert "unsupported filesystem" in response.json()["detail"]


def test_storage_host_helper_format_retries_mkfs_busy_for_udev(monkeypatch):
    calls = []

    class _Completed:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    mkfs_busy_once = {"seen": False}
    fuser_busy_once = {"seen": False}

    def _fake_run(cmd, timeout):
        calls.append((list(cmd), timeout))
        if cmd[:2] == ["findmnt", "-rn"]:
            return _Completed(returncode=1, stdout="")
        if cmd[:2] == ["fuser", "-v"]:
            if not fuser_busy_once["seen"]:
                fuser_busy_once["seen"] = True
                return _Completed(returncode=0, stderr="/dev/sdd1:            root      f.... (udev-worker)")
            return _Completed(returncode=1, stdout="", stderr="")
        if cmd[:2] == ["udevadm", "settle"]:
            return _Completed()
        if cmd and cmd[0] == "mkfs.ext4":
            if not mkfs_busy_once["seen"]:
                mkfs_busy_once["seen"] = True
                return _Completed(returncode=1, stderr="/dev/sdd1 is apparently in use by the system; will not make a filesystem here!")
            return _Completed()
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(storage_host_helper_app, "_run_host_command", _fake_run)

    client = TestClient(storage_host_helper_app.app)
    response = client.post("/v1/format", json={"device": "/dev/sdd1", "filesystem": "ext4", "label": "games"})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    mkfs_calls = [cmd for cmd, _ in calls if cmd and cmd[0] == "mkfs.ext4"]
    assert len(mkfs_calls) == 2


def test_storage_host_helper_format_blocks_non_udev_busy_detail(monkeypatch):
    class _Completed:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake_run(cmd, timeout):
        if cmd[:2] == ["findmnt", "-rn"]:
            return _Completed(returncode=1, stdout="")
        if cmd[:2] == ["fuser", "-v"]:
            return _Completed(returncode=0, stderr="/dev/sdd1: root f.... (qemu-system-x86_64)")
        if cmd[:2] == ["udevadm", "settle"]:
            return _Completed()
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(storage_host_helper_app, "_run_host_command", _fake_run)

    client = TestClient(storage_host_helper_app.app)
    response = client.post("/v1/format", json={"device": "/dev/sdd1", "filesystem": "ext4", "label": "games"})

    assert response.status_code == 409
    assert "device still busy before format" in response.json()["detail"]
    assert "qemu-system-x86_64" in response.json()["detail"]


def test_storage_host_helper_mkdirs_calls_host_mkdir(monkeypatch):
    calls = []

    class _Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_shell(script, timeout):
        calls.append((script, timeout))
        return _Completed()

    monkeypatch.setattr(storage_host_helper_app, "_run_host_shell", _fake_shell)

    client = TestClient(storage_host_helper_app.app)
    response = client.post(
        "/v1/mkdirs",
        json={
            "paths": ["/data/services/gaming-station/data"],
            "mode": "0750",
            "owner": "1000",
            "group": "1000",
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["owner"] == "1000"
    assert response.json()["group"] == "1000"
    assert len(calls) == 1
    assert "mkdir -p -m 0750 /data/services/gaming-station/data" in calls[0][0]
    assert "chown 1000:1000 /data/services/gaming-station/data" in calls[0][0]


def test_storage_host_helper_mount_creates_mountpoint_and_persists(monkeypatch):
    calls = []
    shell_calls = []

    class _Completed:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake_run(cmd, timeout):
        calls.append((list(cmd), timeout))
        if cmd[:4] == ["blkid", "-o", "value", "-s"]:
            field = cmd[4]
            if field == "UUID":
                return _Completed(stdout="1111-2222\n")
            if field == "TYPE":
                return _Completed(stdout="ext4\n")
        return _Completed()

    monkeypatch.setattr(storage_host_helper_app, "_run_host_command", _fake_run)
    monkeypatch.setattr(storage_host_helper_app, "_run_host_shell", lambda script, timeout: shell_calls.append((script, timeout)) or _Completed())

    client = TestClient(storage_host_helper_app.app)
    response = client.post(
        "/v1/mount",
        json={
            "device": "/dev/sdd1",
            "mountpoint": "/mnt/games",
            "filesystem": "",
            "options": "defaults,noatime",
            "create_mountpoint": True,
            "persist": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["persisted"] is True
    assert calls[0] == (["mkdir", "-p", "/mnt/games"], 30)
    assert calls[1] == (["mount", "-o", "defaults,noatime", "/dev/sdd1", "/mnt/games"], 30)
    assert any("/etc/fstab" in script for script, _ in shell_calls)
    assert any("UUID=1111-2222" in script for script, _ in shell_calls)


def test_storage_host_helper_listdir_returns_directories(monkeypatch):
    class _Completed:
        returncode = 0
        stdout = "/data/services/a\n/data/services/b\n"
        stderr = ""

    monkeypatch.setattr(storage_host_helper_app, "_run_host_command", lambda cmd, timeout: _Completed())

    client = TestClient(storage_host_helper_app.app)
    response = client.post("/v1/listdir", json={"path": "/data/services"})

    assert response.status_code == 200
    assert response.json()["entries"] == ["/data/services/a", "/data/services/b"]


def test_storage_host_helper_write_file_uses_host_shell(monkeypatch):
    calls = []

    class _Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(storage_host_helper_app, "_run_host_command", lambda cmd, timeout: _Completed())
    monkeypatch.setattr(storage_host_helper_app, "_run_host_shell", lambda script, timeout: calls.append((script, timeout)) or _Completed())

    client = TestClient(storage_host_helper_app.app)
    response = client.post(
        "/v1/write-file",
        json={
            "path": "/home/hostuser/.config/test.conf",
            "content_b64": "YQ==",
            "mode": "0644",
            "overwrite": True,
            "owner": "hostuser",
            "group": "hostuser",
        },
    )

    assert response.status_code == 200
    assert response.json()["written"] is True
    assert calls and "base64 -d > /home/hostuser/.config/test.conf" in calls[0][0]
    assert "chown hostuser:hostuser /home/hostuser/.config/test.conf" in calls[0][0]


def test_storage_host_helper_ensure_symlink_uses_host_shell(monkeypatch):
    calls = []

    class _Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(storage_host_helper_app, "_run_host_shell", lambda script, timeout: calls.append((script, timeout)) or _Completed())

    client = TestClient(storage_host_helper_app.app)
    response = client.post(
        "/v1/ensure-symlink",
        json={
            "target": "/data/services/containers",
            "link_path": "/DATA/AppData/TRION/containers",
            "replace": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert calls
    assert "ln -s /data/services/containers /DATA/AppData/TRION/containers" in calls[0][0]


def test_storage_host_helper_systemctl_user_wraps_runuser(monkeypatch):
    calls = []

    class _Completed:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr(storage_host_helper_app, "_run_host_command", lambda cmd, timeout: calls.append((cmd, timeout)) or _Completed())

    client = TestClient(storage_host_helper_app.app)
    response = client.post(
        "/v1/systemctl-user",
        json={
            "user": "danny",
            "runtime_dir": "/run/user/1000",
            "args": ["daemon-reload"],
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert calls == [([
        "runuser",
        "-u",
        "danny",
        "--",
        "env",
        "XDG_RUNTIME_DIR=/run/user/1000",
        "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus",
        "systemctl",
        "--user",
        "daemon-reload",
    ], 30)]


def test_storage_host_helper_path_exists_uses_test(monkeypatch):
    calls = []

    class _Completed:
        def __init__(self, returncode):
            self.returncode = returncode
            self.stdout = ""
            self.stderr = ""

    monkeypatch.setattr(storage_host_helper_app, "_run_host_command", lambda cmd, timeout: calls.append((cmd, timeout)) or _Completed(0))

    client = TestClient(storage_host_helper_app.app)
    response = client.post("/v1/path-exists", json={"path": "/usr/bin/sunshine"})

    assert response.status_code == 200
    assert response.json()["exists"] is True
    assert calls == [(["test", "-e", "/usr/bin/sunshine"], 5)]


def test_storage_host_helper_install_deb_url_runs_download_and_install(monkeypatch):
    calls = []

    class _Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(storage_host_helper_app, "_run_host_shell", lambda script, timeout: calls.append(("shell", script, timeout)) or _Completed())
    monkeypatch.setattr(storage_host_helper_app, "_run_host_command", lambda cmd, timeout: calls.append(("cmd", cmd, timeout)) or _Completed())

    client = TestClient(storage_host_helper_app.app)
    response = client.post(
        "/v1/install-deb-url",
        json={
            "url": "https://example.invalid/sunshine.deb",
            "package_name": "sunshine",
            "binary_path": "/usr/bin/sunshine",
            "allow_downgrade": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    shell_script = calls[0][1]
    assert "curl -LfsS" in shell_script
    assert "dpkg -i" in shell_script
    assert calls[1] == ("cmd", ["test", "-x", "/usr/bin/sunshine"], 5)


def test_storage_host_helper_apt_install_installs_missing_packages(monkeypatch):
    calls = []

    class _Completed:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake_shell(script, timeout):
        calls.append((script, timeout))
        return _Completed()

    monkeypatch.setattr(storage_host_helper_app, "_run_host_shell", _fake_shell)

    client = TestClient(storage_host_helper_app.app)
    response = client.post(
        "/v1/apt-install",
        json={
            "packages": ["openbox", "xterm"],
            "update_cache": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["installed"] == ["openbox", "xterm"]
    assert "apt-get update" in calls[0][0]
    assert "apt-get install -y $missing" in calls[0][0]
    assert "dpkg-query -W -f='${Status}' \"$pkg\"" in calls[0][0]


def test_storage_host_helper_create_partition_retries_kernel_busy_parted(monkeypatch):
    calls = []
    busy_error = (
        "Error: Partition(s) 1 on /dev/sdd have been written, but we have been unable "
        "to inform the kernel of the change, probably because it/they are in use."
    )

    class _Completed:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    busy_once = {"mklabel": True}
    fuser_busy_once = {"seen": False}

    def _fake_run(cmd, timeout):
        calls.append((list(cmd), timeout))
        if cmd[:3] == ["lsblk", "-rno", "NAME"]:
            return _Completed(stdout="sdd\nsdd1\n")
        if cmd[:2] == ["findmnt", "-rn"]:
            return _Completed(returncode=1, stdout="")
        if cmd[:2] == ["wipefs", "-a"]:
            return _Completed()
        if cmd[:2] == ["partx", "-d"]:
            return _Completed()
        if cmd[:2] == ["udevadm", "settle"]:
            return _Completed()
        if cmd[:2] == ["blockdev", "--rereadpt"]:
            return _Completed()
        if cmd[:2] == ["partprobe", "/dev/sdd"]:
            return _Completed()
        if cmd[:2] == ["partx", "-u"]:
            return _Completed()
        if cmd[:2] == ["fuser", "-v"]:
            if not fuser_busy_once["seen"]:
                fuser_busy_once["seen"] = True
                return _Completed(
                    returncode=0,
                    stderr="/dev/sdd:            root      f.... (udev-worker)",
                )
            return _Completed(returncode=1, stdout="", stderr="")
        if cmd[:4] == ["parted", "-s", "/dev/sdd", "mklabel"] and busy_once["mklabel"]:
            busy_once["mklabel"] = False
            return _Completed(returncode=1, stderr=busy_error)
        if cmd[:3] == ["parted", "-s", "/dev/sdd"]:
            return _Completed()
        if cmd[:3] == ["test", "-b", "/dev/sdd1"]:
            return _Completed()
        if cmd and cmd[0] == "mkfs.ext4":
            return _Completed()
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(storage_host_helper_app, "_run_host_command", _fake_run)

    client = TestClient(storage_host_helper_app.app)
    response = client.post(
        "/v1/create-partition",
        json={
            "device": "/dev/sdd",
            "table_type": "gpt",
            "dry_run": False,
            "partitions": [{"label": "gaming", "filesystem": "ext4", "size_gib": 500}],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert any(cmd[:4] == ["parted", "-s", "/dev/sdd", "mklabel"] for cmd, _ in calls)
    assert any(cmd[:2] == ["blockdev", "--rereadpt"] for cmd, _ in calls)
    assert any(cmd[:2] == ["partx", "-u"] for cmd, _ in calls)
    assert any(cmd and cmd[0] == "mkfs.ext4" for cmd, _ in calls)


def test_storage_host_helper_create_partition_blocks_non_udev_busy_detail(monkeypatch):
    busy_error = (
        "Error: Partition(s) 1 on /dev/sdd have been written, but we have been unable "
        "to inform the kernel of the change, probably because it/they are in use."
    )

    class _Completed:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake_run(cmd, timeout):
        if cmd[:3] == ["lsblk", "-rno", "NAME"]:
            return _Completed(stdout="sdd\nsdd1\n")
        if cmd[:2] == ["findmnt", "-rn"]:
            return _Completed(returncode=1, stdout="")
        if cmd[:2] in (["wipefs", "-a"], ["partx", "-d"], ["udevadm", "settle"], ["blockdev", "--rereadpt"], ["partprobe", "/dev/sdd"], ["partx", "-u"]):
            return _Completed()
        if cmd[:2] == ["fuser", "-v"]:
            return _Completed(returncode=0, stderr="/dev/sdd: root f.... (qemu-system-x86_64)")
        if cmd[:4] == ["parted", "-s", "/dev/sdd", "mklabel"]:
            return _Completed(returncode=1, stderr=busy_error)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(storage_host_helper_app, "_run_host_command", _fake_run)

    client = TestClient(storage_host_helper_app.app)
    response = client.post(
        "/v1/create-partition",
        json={
            "device": "/dev/sdd",
            "table_type": "gpt",
            "dry_run": False,
            "partitions": [{"label": "gaming", "filesystem": "ext4", "size_gib": 500}],
        },
    )

    assert response.status_code == 409
    assert "device still busy before repartition" in response.json()["detail"]
    assert "qemu-system-x86_64" in response.json()["detail"]


def test_storage_host_helper_create_partition_retries_mkfs_busy_for_udev(monkeypatch):
    calls = []

    class _Completed:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    mkfs_busy_once = {"seen": False}
    fuser_sdd1_busy_once = {"seen": False}

    def _fake_run(cmd, timeout):
        calls.append((list(cmd), timeout))
        if cmd[:3] == ["lsblk", "-rno", "NAME"]:
            return _Completed(stdout="sdd\nsdd1\n")
        if cmd[:2] == ["findmnt", "-rn"]:
            return _Completed(returncode=1, stdout="")
        if cmd[:2] in (["wipefs", "-a"], ["partx", "-d"], ["udevadm", "settle"], ["blockdev", "--rereadpt"], ["partprobe", "/dev/sdd"], ["partx", "-u"]):
            return _Completed()
        if cmd[:2] == ["fuser", "-v"]:
            device = cmd[-1]
            if device == "/dev/sdd1" and not fuser_sdd1_busy_once["seen"]:
                fuser_sdd1_busy_once["seen"] = True
                return _Completed(returncode=0, stderr="/dev/sdd1:            root      f.... (udev-worker)")
            return _Completed(returncode=1, stdout="", stderr="")
        if cmd[:3] == ["test", "-b", "/dev/sdd1"]:
            return _Completed()
        if cmd[:4] == ["parted", "-s", "/dev/sdd", "mklabel"]:
            return _Completed()
        if cmd[:4] == ["parted", "-s", "/dev/sdd", "mkpart"]:
            return _Completed()
        if cmd and cmd[0] == "mkfs.ext4":
            if not mkfs_busy_once["seen"]:
                mkfs_busy_once["seen"] = True
                return _Completed(returncode=1, stderr="/dev/sdd1 is apparently in use by the system; will not make a filesystem here!")
            return _Completed()
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(storage_host_helper_app, "_run_host_command", _fake_run)

    client = TestClient(storage_host_helper_app.app)
    response = client.post(
        "/v1/create-partition",
        json={
            "device": "/dev/sdd",
            "table_type": "gpt",
            "dry_run": False,
            "partitions": [{"label": "games", "filesystem": "ext4", "size_gib": 500}],
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    mkfs_calls = [cmd for cmd, _ in calls if cmd and cmd[0] == "mkfs.ext4"]
    assert len(mkfs_calls) == 2


def test_storage_host_helper_remove_paths_uses_rm_f(monkeypatch):
    calls = []

    class _Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(storage_host_helper_app, "_run_host_shell", lambda script, timeout: calls.append((script, timeout)) or _Completed())

    client = TestClient(storage_host_helper_app.app)
    response = client.post(
        "/v1/remove-paths",
        json={
            "paths": ["/home/hostuser/.local/bin/gaming-station-steam.sh", "/home/hostuser/.config/systemd/user/sunshine-host.service"],
            "missing_ok": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert "rm -f /home/hostuser/.local/bin/gaming-station-steam.sh /home/hostuser/.config/systemd/user/sunshine-host.service" in calls[0][0]
