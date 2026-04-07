from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from container_commander import host_companions


def test_ensure_host_companion_materializes_files_and_enables_service(monkeypatch, tmp_path):
    expected_home = "/home/hostuser"
    package_root = tmp_path / "packages" / "gaming-station"
    (package_root / "host" / "bin").mkdir(parents=True)
    (package_root / "host" / "config" / "sunshine").mkdir(parents=True)
    (package_root / "host" / "systemd-user").mkdir(parents=True)
    (package_root / "host" / "etc" / "X11" / "edid").mkdir(parents=True)

    (package_root / "package.json").write_text(
        '{"id":"gaming-station","package_type":"composite_addon","host_companion":{"id":"sunshine-host-bridge","host_packages":{"apt":["openbox"]},"binary_bootstrap":{"binary_path":"/usr/bin/sunshine","deb_url":"https://example.invalid/sunshine.deb","package_name":"sunshine"}}}',
        encoding="utf-8",
    )
    (package_root / "host" / "bin" / "start-host-sunshine-session.sh").write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    (package_root / "host" / "bin" / "host-sunshine-xsession.sh").write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    (package_root / "host" / "bin" / "gaming-station-steam.sh").write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    (package_root / "host" / "bin" / "sunshine-host-prepare.sh").write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    (package_root / "host" / "config" / "sunshine" / "sunshine.conf").write_text("port = 47989\n", encoding="utf-8")
    (package_root / "host" / "config" / "sunshine" / "apps.json").write_text('{"apps":[]}', encoding="utf-8")
    (package_root / "host" / "systemd-user" / "sunshine-host.service").write_text(
        "Environment=SUNSHINE_BIN={{SUNSHINE_BIN}}\n",
        encoding="utf-8",
    )
    (package_root / "host" / "etc" / "X11" / "90-sunshine-headless.conf").write_text(
        'BusID "{{XORG_BUS_ID}}"\nOption "ConnectedMonitor" "{{XORG_OUTPUT_NAME}}"\n',
        encoding="utf-8",
    )
    (package_root / "host" / "etc" / "X11" / "Xwrapper.config").write_text("allowed_users=anybody\n", encoding="utf-8")
    (package_root / "host" / "etc" / "X11" / "edid" / "monitor-1080p.bin.hex").write_text("00 ff", encoding="utf-8")

    monkeypatch.setattr(host_companions, "MARKETPLACE_DIR", tmp_path / "market")
    monkeypatch.setattr(host_companions, "LOCAL_PACKAGE_DIR", tmp_path / "packages")
    monkeypatch.setattr(host_companions, "HOST_COMPANION_USER", "hostuser")
    monkeypatch.setattr(host_companions, "HOST_COMPANION_UID", 1000)
    monkeypatch.setattr(host_companions, "HOST_COMPANION_GID", 1000)
    monkeypatch.setattr(host_companions, "HOST_COMPANION_HOME", expected_home)

    calls = []

    def _fake_post(path, payload, timeout=30):
        calls.append((path, payload))
        if path == "/v1/path-exists":
            return {"ok": True, "exists": False}
        if path == "/v1/apt-install":
            return {"ok": True, "installed": ["openbox"]}
        if path == "/v1/install-deb-url":
            return {"ok": True, "binary_exists": True}
        if path == "/v1/systemctl-user" and payload.get("args") == ["is-active", "sunshine-host.service"]:
            return {"ok": False, "returncode": 3}
        if path == "/v1/write-file":
            return {"ok": True, "written": True}
        return {"ok": True}

    monkeypatch.setattr(host_companions, "_helper_post_json", _fake_post)

    result = host_companions.ensure_host_companion("gaming-station", overwrite=False)

    assert result["installed"] is True
    assert result["packages"][0]["installed"] == ["openbox"]
    assert ("/v1/apt-install", {"packages": ["openbox"], "update_cache": True}) in calls
    assert ("/v1/path-exists", {"path": "/usr/bin/sunshine"}) in calls
    assert any(path == "/v1/install-deb-url" for path, _ in calls)
    write_targets = [payload["path"] for path, payload in calls if path == "/v1/write-file"]
    assert f"{expected_home}/.config/systemd/user/sunshine-host.service" in write_targets
    assert "/etc/X11/edid/monitor-1080p.bin" in write_targets
    service_payload = next(payload for path, payload in calls if path == "/v1/write-file" and payload["path"] == f"{expected_home}/.config/systemd/user/sunshine-host.service")
    assert service_payload["owner"] == "1000"
    assert service_payload["group"] == "1000"
    systemctl_args = [payload["args"] for path, payload in calls if path == "/v1/systemctl-user"]
    assert ["daemon-reload"] in systemctl_args
    assert ["enable", "sunshine-host.service"] in systemctl_args
    assert ["start", "sunshine-host.service"] in systemctl_args


def test_default_render_vars_prefers_appimage_path_when_no_service_exists(monkeypatch):
    monkeypatch.setattr(host_companions, "HOST_COMPANION_USER", "hostuser")
    monkeypatch.setattr(host_companions, "HOST_COMPANION_HOME", "/home/hostuser")
    monkeypatch.setattr(host_companions, "_extract_service_env", lambda path, key: "")
    monkeypatch.setattr(host_companions, "_extract_xorg_bus_id", lambda path: "")
    monkeypatch.setattr(host_companions, "_extract_xorg_option", lambda path, key: "")

    result = host_companions._default_render_vars()

    assert result["SUNSHINE_BIN"] == "/home/hostuser/.local/opt/sunshine/sunshine.AppImage"
    assert result["XORG_BUS_ID"] == "PCI:1:0:0"
    assert result["XORG_OUTPUT_NAME"] == "TV-1"


def test_gaming_station_host_xsession_bootstraps_appimage():
    script = (
        ROOT
        / "marketplace"
        / "packages"
        / "gaming-station"
        / "host"
        / "bin"
        / "host-sunshine-xsession.sh"
    ).read_text(encoding="utf-8")

    assert "ensure_sunshine_bin()" in script
    assert "https://github.com/LizardByte/Sunshine/releases/latest/download/sunshine.AppImage" in script
    assert 'sunshine_bin="$(ensure_sunshine_bin)"' in script


def test_get_package_manifest_prefers_installed_marketplace_package(monkeypatch, tmp_path):
    market_pkg = tmp_path / "market" / "packages" / "gaming-station"
    local_pkg = tmp_path / "local" / "gaming-station"
    market_pkg.mkdir(parents=True)
    local_pkg.mkdir(parents=True)
    (market_pkg / "package.json").write_text('{"id":"gaming-station","version":"2"}', encoding="utf-8")
    (local_pkg / "package.json").write_text('{"id":"gaming-station","version":"1"}', encoding="utf-8")

    monkeypatch.setattr(host_companions, "MARKETPLACE_DIR", tmp_path / "market")
    monkeypatch.setattr(host_companions, "LOCAL_PACKAGE_DIR", tmp_path / "local")

    manifest = host_companions.get_package_manifest("gaming-station")

    assert manifest["version"] == "2"


def test_shadow_package_materializes_parallel_targets_without_enabling_service(monkeypatch, tmp_path):
    expected_home = "/home/hostuser"
    package_root = tmp_path / "packages" / "gaming-station-shadow"
    (package_root / "host" / "bin").mkdir(parents=True)
    (package_root / "host" / "config" / "sunshine").mkdir(parents=True)
    (package_root / "host" / "systemd-user").mkdir(parents=True)
    (package_root / "host" / "etc" / "X11" / "edid").mkdir(parents=True)

    (package_root / "package.json").write_text(
        '{"id":"gaming-station-shadow","package_type":"composite_addon","host_companion":{"id":"sunshine-host-shadow","auto_enable":false,"auto_start":false,"install_targets":{"service_name":"sunshine-host-shadow.service","start_script_name":"start-host-sunshine-shadow-session.sh","xsession_script_name":"host-sunshine-shadow-xsession.sh","steam_script_name":"gaming-station-shadow-steam.sh","prepare_script_path":"/usr/local/bin/sunshine-host-shadow-prepare.sh","xorg_conf_path":"/etc/X11/xorg.conf.d/90-sunshine-headless-shadow.conf","xwrapper_path":"/etc/X11/Xwrapper-shadow.config","edid_path":"/etc/X11/edid/monitor-1080p-shadow.bin"},"binary_bootstrap":{"binary_path":"/usr/bin/sunshine","deb_url":"https://example.invalid/sunshine.deb","package_name":"sunshine"}}}',
        encoding="utf-8",
    )
    for rel, text in {
        "host/bin/start-host-sunshine-session.sh": "#!/bin/sh\nexec true\n",
        "host/bin/host-sunshine-xsession.sh": "#!/bin/sh\nexec true\n",
        "host/bin/gaming-station-steam.sh": "#!/bin/sh\nexec true\n",
        "host/bin/sunshine-host-prepare.sh": "#!/bin/sh\nexec true\n",
        "host/config/sunshine/sunshine.conf": "port = 47989\n",
        "host/config/sunshine/apps.json": '{"apps":[]}',
        "host/systemd-user/sunshine-host.service": "ExecStart={{HOST_START_SCRIPT_PATH}}\n",
        "host/etc/X11/90-sunshine-headless.conf": 'BusID "{{XORG_BUS_ID}}"\n',
        "host/etc/X11/Xwrapper.config": "allowed_users=anybody\n",
        "host/etc/X11/edid/monitor-1080p.bin.hex": "00 ff",
    }.items():
        target = package_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    monkeypatch.setattr(host_companions, "MARKETPLACE_DIR", tmp_path / "market")
    monkeypatch.setattr(host_companions, "LOCAL_PACKAGE_DIR", tmp_path / "packages")
    monkeypatch.setattr(host_companions, "HOST_COMPANION_USER", "hostuser")
    monkeypatch.setattr(host_companions, "HOST_COMPANION_UID", 1000)
    monkeypatch.setattr(host_companions, "HOST_COMPANION_GID", 1000)
    monkeypatch.setattr(host_companions, "HOST_COMPANION_HOME", expected_home)

    calls = []

    def _fake_post(path, payload, timeout=30):
        calls.append((path, payload))
        if path == "/v1/path-exists":
            return {"ok": True, "exists": True}
        if path == "/v1/write-file":
            return {"ok": True, "written": True}
        return {"ok": True}

    monkeypatch.setattr(host_companions, "_helper_post_json", _fake_post)

    result = host_companions.ensure_host_companion("gaming-station-shadow", overwrite=False)

    assert result["installed"] is True
    write_targets = [payload["path"] for path, payload in calls if path == "/v1/write-file"]
    assert f"{expected_home}/.config/systemd/user/sunshine-host-shadow.service" in write_targets
    assert "/etc/X11/xorg.conf.d/90-sunshine-headless-shadow.conf" in write_targets
    shadow_service_payload = next(payload for path, payload in calls if path == "/v1/write-file" and payload["path"] == f"{expected_home}/.config/systemd/user/sunshine-host-shadow.service")
    assert shadow_service_payload["owner"] == "1000"
    assert shadow_service_payload["group"] == "1000"
    systemctl_args = [payload["args"] for path, payload in calls if path == "/v1/systemctl-user"]
    assert ["daemon-reload"] in systemctl_args
    assert ["enable", "sunshine-host-shadow.service"] not in systemctl_args
    assert ["start", "sunshine-host-shadow.service"] not in systemctl_args


def test_ensure_package_storage_scope_upserts_declared_scope(monkeypatch, tmp_path):
    package_root = tmp_path / "packages" / "gaming-station"
    package_root.mkdir(parents=True)
    (package_root / "package.json").write_text(
        '{"id":"gaming-station","storage":{"scope":{"name":"gaming-station-host-bridge","roots":[{"path":"/data/services/gaming-station/config","mode":"rw"},{"path":"/data/services/gaming-station/data","mode":"rw"}]}}}',
        encoding="utf-8",
    )

    monkeypatch.setattr(host_companions, "MARKETPLACE_DIR", tmp_path / "market")
    monkeypatch.setattr(host_companions, "LOCAL_PACKAGE_DIR", tmp_path / "packages")

    calls = {}

    def _fake_get_scope(name):
        calls["get_scope"] = name
        return None

    def _fake_upsert_scope(name, roots, approved_by="user", metadata=None):
        calls["upsert"] = {
            "name": name,
            "roots": roots,
            "approved_by": approved_by,
            "metadata": metadata,
        }
        return {"name": name, "roots": roots}

    monkeypatch.setattr("container_commander.storage_scope.get_scope", _fake_get_scope)
    monkeypatch.setattr("container_commander.storage_scope.upsert_scope", _fake_upsert_scope)

    result = host_companions.ensure_package_storage_scope("gaming-station")

    assert result["installed"] is True
    assert result["scope"] == "gaming-station-host-bridge"
    assert calls["get_scope"] == "gaming-station-host-bridge"
    assert calls["upsert"]["approved_by"] == "system:package"
    assert calls["upsert"]["metadata"]["origin"] == "package_storage_scope"


def test_ensure_package_storage_scope_skips_when_blueprint_scope_mismatches(monkeypatch, tmp_path):
    package_root = tmp_path / "packages" / "gaming-station"
    package_root.mkdir(parents=True)
    (package_root / "package.json").write_text(
        '{"id":"gaming-station","storage":{"scope":{"name":"gaming-station-host-bridge","roots":[{"path":"/data/services/gaming-station/config","mode":"rw"}]}}}',
        encoding="utf-8",
    )

    monkeypatch.setattr(host_companions, "MARKETPLACE_DIR", tmp_path / "market")
    monkeypatch.setattr(host_companions, "LOCAL_PACKAGE_DIR", tmp_path / "packages")

    class _Bp:
        storage_scope = "different-scope"

    result = host_companions.ensure_package_storage_scope("gaming-station", blueprint=_Bp())

    assert result["installed"] is False
    assert result["reason"] == "scope_name_mismatch"


def test_ensure_package_storage_scope_merges_declared_and_blueprint_bind_roots(monkeypatch, tmp_path):
    package_root = tmp_path / "packages" / "gaming-station"
    package_root.mkdir(parents=True)
    (package_root / "package.json").write_text(
        '{"id":"gaming-station","storage":{"scope":{"name":"gaming-station-host-bridge","roots":[{"path":"/data/services/gaming-station/config","mode":"rw"},{"path":"/data/services/gaming-station/data","mode":"rw"}]}}}',
        encoding="utf-8",
    )

    monkeypatch.setattr(host_companions, "MARKETPLACE_DIR", tmp_path / "market")
    monkeypatch.setattr(host_companions, "LOCAL_PACKAGE_DIR", tmp_path / "packages")

    calls = {}

    def _fake_get_scope(name):
        calls["get_scope"] = name
        return None

    def _fake_upsert_scope(name, roots, approved_by="user", metadata=None):
        calls["upsert"] = {
            "name": name,
            "roots": roots,
            "approved_by": approved_by,
            "metadata": metadata,
        }
        return {"name": name, "roots": roots}

    monkeypatch.setattr("container_commander.storage_scope.get_scope", _fake_get_scope)
    monkeypatch.setattr("container_commander.storage_scope.upsert_scope", _fake_upsert_scope)

    class _Mount:
        type = "bind"
        host = "/mnt/games/services/gaming-station-games/data"
        container = "/games"
        mode = "rw"
        asset_id = "gaming-station-games"

    class _RuntimeBind:
        type = "bind"
        host = "/tmp/.X11-unix"
        container = "/tmp/.X11-unix"
        mode = "rw"
        asset_id = ""

    class _Bp:
        storage_scope = "gaming-station-host-bridge"
        mounts = [_Mount(), _RuntimeBind()]

    result = host_companions.ensure_package_storage_scope("gaming-station", blueprint=_Bp())

    assert result["installed"] is True
    assert calls["get_scope"] == "gaming-station-host-bridge"
    assert calls["upsert"]["roots"] == [
        {"path": "/data/services/gaming-station/config", "mode": "rw"},
        {"path": "/data/services/gaming-station/data", "mode": "rw"},
        {"path": "/mnt/games/services/gaming-station-games/data", "mode": "rw"},
    ]


def test_run_package_postchecks_validates_host_and_container_state(monkeypatch, tmp_path):
    package_root = tmp_path / "packages" / "gaming-station"
    package_root.mkdir(parents=True)
    (package_root / "package.json").write_text(
        '{"id":"gaming-station","host_companion":{"install_targets":{"service_name":"sunshine-host.service"},"auto_enable":true,"auto_start":true},"postchecks":["host_sunshine_service_enabled","host_xorg_ready","container_display_bridge_ready","steam_home_persistent","user_data_persistent"]}',
        encoding="utf-8",
    )

    monkeypatch.setattr(host_companions, "MARKETPLACE_DIR", tmp_path / "market")
    monkeypatch.setattr(host_companions, "LOCAL_PACKAGE_DIR", tmp_path / "packages")

    calls = []

    def _fake_post(path, payload, timeout=30):
        calls.append((path, payload))
        if path == "/v1/systemctl-user":
            return {"ok": True, "returncode": 0}
        if path == "/v1/path-exists":
            return {"ok": True, "exists": True}
        return {"ok": True}

    class _Container:
        attrs = {
            "Mounts": [
                {"Destination": "/tmp/.X11-unix", "Source": "/tmp/.X11-unix", "Mode": "rw"},
                {"Destination": "/tmp/host-pulse", "Source": "/run/user/1000/pulse", "Mode": "rw"},
                {"Destination": "/home/default/.steam", "Source": "/data/services/gaming-station/data/steam-home", "Mode": "rw"},
                {"Destination": "/home/default/.local/share", "Source": "/data/services/gaming-station/data/userdata", "Mode": "rw"},
            ],
            "Config": {
                "Env": [
                    "DISPLAY=:0",
                    "TRION_HOST_DISPLAY_BRIDGE=true",
                    "PULSE_SERVER=unix:/tmp/host-pulse/native",
                ]
            },
        }

        def reload(self):
            return None

    monkeypatch.setattr(host_companions, "_helper_post_json", _fake_post)

    result = host_companions.run_package_postchecks("gaming-station", container=_Container())

    assert result["ok"] is True
    assert [item["name"] for item in result["checks"]] == [
        "host_sunshine_service_enabled",
        "host_xorg_ready",
        "container_display_bridge_ready",
        "steam_home_persistent",
        "user_data_persistent",
    ]
    assert any(path == "/v1/systemctl-user" and payload["args"] == ["is-enabled", "sunshine-host.service"] for path, payload in calls)
    assert any(path == "/v1/systemctl-user" and payload["args"] == ["is-active", "sunshine-host.service"] for path, payload in calls)
    assert ("/v1/path-exists", {"path": "/tmp/.X11-unix/X0"}) in calls


def test_repair_host_companion_overwrites_and_rechecks(monkeypatch):
    calls = []

    def _fake_manifest(package_id):
        assert package_id == "gaming-station"
        return {
            "id": "gaming-station",
            "package_type": "composite_addon",
            "postchecks": ["host_xorg_ready"],
        }

    def _fake_ensure(package_id, overwrite=False):
        calls.append(("ensure", package_id, overwrite))
        return {"installed": True, "package_id": package_id}

    def _fake_scope(package_id, blueprint=None, manifest=None):
        calls.append(("scope", package_id))
        return {"installed": True, "scope": "gaming-station-host-bridge"}

    def _fake_postchecks(package_id, blueprint=None, container=None, manifest=None):
        calls.append(("postchecks", package_id))
        return {"ok": True, "checks": [{"name": "host_xorg_ready", "ok": True}]}

    monkeypatch.setattr(host_companions, "get_package_manifest", _fake_manifest)
    monkeypatch.setattr(host_companions, "ensure_host_companion", _fake_ensure)
    monkeypatch.setattr(host_companions, "ensure_package_storage_scope", _fake_scope)
    monkeypatch.setattr(host_companions, "run_package_postchecks", _fake_postchecks)

    result = host_companions.repair_host_companion("gaming-station")

    assert result["repaired"] is True
    assert ("ensure", "gaming-station", True) in calls
    assert ("scope", "gaming-station") in calls
    assert ("postchecks", "gaming-station") in calls


def test_check_host_companion_returns_postcheck_state(monkeypatch):
    monkeypatch.setattr(host_companions, "get_package_manifest", lambda package_id: {"id": package_id, "postchecks": ["host_xorg_ready"]})
    monkeypatch.setattr(host_companions, "ensure_package_storage_scope", lambda package_id, blueprint=None, manifest=None: {"installed": True})
    monkeypatch.setattr(
        host_companions,
        "run_package_postchecks",
        lambda package_id, blueprint=None, container=None, manifest=None: {"ok": False, "checks": [{"name": "host_xorg_ready", "ok": False}]},
    )

    result = host_companions.check_host_companion("gaming-station")

    assert result["ok"] is False
    assert result["postchecks"]["checks"][0]["name"] == "host_xorg_ready"


def test_run_package_postchecks_accepts_explicit_volume_mounts_for_gaming_persistence(monkeypatch):
    calls = []

    def _fake_manifest(package_id):
        assert package_id == "gaming-station"
        return {
            "id": "gaming-station",
            "package_type": "composite_addon",
            "host_companion": {"install_targets": {"service_name": "sunshine-host.service"}, "auto_enable": True, "auto_start": True},
            "postchecks": [
                "host_sunshine_service_enabled",
                "host_xorg_ready",
                "container_display_bridge_ready",
                "steam_home_persistent",
                "user_data_persistent",
            ],
        }

    def _fake_post(path, payload, timeout=30):
        calls.append((path, payload))
        if path == "/v1/systemctl-user":
            return {"ok": True}
        if path == "/v1/path-exists":
            return {"exists": True}
        raise AssertionError(f"unexpected helper call: {path}")

    class _Container:
        attrs = {
            "Mounts": [
                {"Destination": "/tmp/.X11-unix", "Source": "/tmp/.X11-unix", "Mode": "rw"},
                {"Destination": "/tmp/host-pulse", "Source": "/run/user/1000/pulse", "Mode": "rw"},
                {"Destination": "/home/default/.steam", "Source": "/var/lib/docker/volumes/gaming_steam_home/_data", "Mode": "rw"},
                {"Destination": "/home/default/.local/share", "Source": "/var/lib/docker/volumes/gaming_user_data/_data", "Mode": "rw"},
            ],
            "Config": {
                "Env": [
                    "DISPLAY=:0",
                    "TRION_HOST_DISPLAY_BRIDGE=true",
                    "PULSE_SERVER=unix:/tmp/host-pulse/native",
                ]
            },
        }

        def reload(self):
            return None

    monkeypatch.setattr(host_companions, "get_package_manifest", _fake_manifest)
    monkeypatch.setattr(host_companions, "_helper_post_json", _fake_post)

    result = host_companions.run_package_postchecks("gaming-station", container=_Container())

    assert result["ok"] is True
    assert any(check["name"] == "steam_home_persistent" and check["ok"] is True for check in result["checks"])
    assert any(check["name"] == "user_data_persistent" and check["ok"] is True for check in result["checks"])


def test_uninstall_host_companion_stops_service_and_removes_files(monkeypatch, tmp_path):
    expected_home = "/home/hostuser"
    package_root = tmp_path / "packages" / "gaming-station"
    (package_root / "host" / "bin").mkdir(parents=True)
    (package_root / "host" / "systemd-user").mkdir(parents=True)
    (package_root / "package.json").write_text(
        '{"id":"gaming-station","host_companion":{"install_targets":{"service_name":"sunshine-host.service"}}}',
        encoding="utf-8",
    )
    (package_root / "host" / "bin" / "gaming-station-steam.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (package_root / "host" / "systemd-user" / "sunshine-host.service").write_text("[Service]\n", encoding="utf-8")

    monkeypatch.setattr(host_companions, "MARKETPLACE_DIR", tmp_path / "market")
    monkeypatch.setattr(host_companions, "LOCAL_PACKAGE_DIR", tmp_path / "packages")
    monkeypatch.setattr(host_companions, "HOST_COMPANION_USER", "hostuser")
    monkeypatch.setattr(host_companions, "HOST_COMPANION_UID", 1000)
    monkeypatch.setattr(host_companions, "HOST_COMPANION_GID", 1000)
    monkeypatch.setattr(host_companions, "HOST_COMPANION_HOME", expected_home)

    calls = []

    def _fake_post(path, payload, timeout=30):
        calls.append((path, payload))
        return {"ok": True, "paths": payload.get("paths", [])}

    monkeypatch.setattr(host_companions, "_helper_post_json", _fake_post)

    result = host_companions.uninstall_host_companion("gaming-station")

    assert result["uninstalled"] is True
    assert any(path == "/v1/systemctl-user" and payload["args"] == ["stop", "sunshine-host.service"] for path, payload in calls)
    assert any(path == "/v1/systemctl-user" and payload["args"] == ["disable", "sunshine-host.service"] for path, payload in calls)
    remove_payload = next(payload for path, payload in calls if path == "/v1/remove-paths")
    assert f"{expected_home}/.local/bin/gaming-station-steam.sh" in remove_payload["paths"]
    assert f"{expected_home}/.config/systemd/user/sunshine-host.service" in remove_payload["paths"]
