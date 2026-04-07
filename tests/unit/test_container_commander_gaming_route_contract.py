from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_engine_has_runtime_preflight_and_connection_resolver_contract():
    src = _read("container_commander/engine.py")
    assert "def _blueprint_image_tag" in src
    assert 'fingerprint = hashlib.sha256(dockerfile.encode("utf-8")).hexdigest()[:12]' in src
    assert 'return f"trion/{blueprint.id}:{fingerprint}"' in src
    assert "def _validate_runtime_preflight" in src
    assert "nvidia_runtime_unavailable" in src
    assert "runtime_ok, runtime_reason = _validate_runtime_preflight(client, bp.runtime)" in src
    assert "def _extract_port_details" in src
    assert "def _build_connection_info" in src
    assert "def _infer_access_link_meta" in src
    assert "\"access_links\": access_links" in src
    assert "\"connection\": connection" in src
    assert "def _merge_host_companion_access_info(" in src
    assert "from .host_companions import get_host_companion_access_links" in src
    assert "\"service_name\": str(link.get(\"service_name\", \"\")).strip()" in src


def test_mcp_request_container_returns_connection_and_auto_gaming_blueprint():
    src = _read("container_commander/mcp_tools.py")
    gaming_src = _read("container_commander/mcp_tools_gaming.py")
    assert "def _ensure_gaming_station_blueprint" in src
    assert "def _gaming_station_dockerfile" in src
    assert "def _compute_gaming_override_resources" in src
    assert "if blueprint_id in {\"gaming-station\", \"steam-headless\", \"gaming_station\"}:" in src
    assert "_ensure_gaming_station_blueprint()" in src
    assert "override_resources=override_resources" in src
    assert "\"connection\": details.get(\"connection\", {})" in src
    assert "image_ref = \"josh5/steam-headless:latest\"" in src
    assert "dockerfile = _gaming_station_dockerfile(image_ref)" in src
    assert "dockerfile=dockerfile" in src
    assert "image=\"\"" in src
    assert "command=/usr/local/bin/start-steam-host-bridge.sh" in src
    assert "/etc/cont-init.d/93-configure_host_bridge.sh" in src
    assert "/etc/cont-init.d/92-fix_streaming_perms.sh" in src
    assert "/etc/cont-init.d/60-configure_gpu_driver.sh" in src
    assert 'Skipping internal GPU driver install in host-display bridge mode' in src
    assert 'return 0 2>/dev/null || true' in src
    assert "bootstrap_steam_installation()" in src
    assert 'text = pathlib.Path("/usr/games/steam").read_text(encoding="utf-8")' in src
    assert 'for key in ("version", "deb_version", "sha256", "url"):' in src
    assert 'values[key] = re.sub(r"\\\\$\\\\{([^}]+)\\\\}", lambda m: values.get(m.group(1), m.group(0)), values[key])' in src
    assert 'curl -L --fail --retry 5 --retry-delay 2 -o "${archive_tmp}" "${URL}"' in src
    assert "\"/tmp/.X11-unix\"" in src
    assert "\"/run/user/1000/pulse\"" in src
    assert 'steam_home_host = os.path.join(data_host, "steam-home")' in src
    assert 'os.makedirs(steam_home_host, exist_ok=True)' in src
    assert 'container="/home/default/.steam"' in src
    assert 'exec /usr/games/steam -gamepadui ${STEAM_ARGS:-}' in gaming_src
    assert 'echo "**** Starting minimal host-bridge window manager ****"' in gaming_src
    assert 'xfwm4 --compositor=off &' in gaming_src
    assert 'resource_id=f"container::mount_ref::{asset_id}"' in gaming_src
    assert 'policy={"container_path": "/games", "mode": mode}' in gaming_src
    assert 'requested_by="gaming-station"' in gaming_src
    assert "runtime=\"nvidia\"" in src
    assert "\"STEAM_USER\": \"vault://STEAM_USERNAME\"" in src
    assert "\"STEAM_PASS\": \"vault://STEAM_PASSWORD\"" in src
    assert "\"STEAM_ARGS\": \"\"" in src
    assert "\"MODE\": \"secondary\"" in src
    assert "\"DISPLAY\": \":0\"" in src
    assert "\"TRION_HOST_DISPLAY_BRIDGE\": \"true\"" in src
    assert "\"PULSE_SERVER\": \"unix:/tmp/host-pulse/native\"" in src
    assert "\"NVIDIA_VISIBLE_DEVICES\": \"all\"" in src
    assert "\"NVIDIA_DRIVER_CAPABILITIES\": \"all\"" in src
    assert "\"ENABLE_SUNSHINE\": \"false\"" in src
    assert "desired_ports: list[str] = []" in src
    assert "desired_healthcheck: dict = {}" in src
    assert "cap_add=[\"NET_ADMIN\", \"SYS_ADMIN\", \"SYS_NICE\"]" in src
    assert "security_opt=[\"seccomp=unconfined\", \"apparmor=unconfined\"]" in src
    assert "privileged=True" in src
    assert "ipc_mode=\"host\"" in src
    assert "\"access_links\": [" in _read("marketplace/packages/gaming-station/package.json")


def test_primary_gaming_dockerfile_patches_dumb_udev_input_classification():
    src = _read("container_commander/mcp_tools_gaming.py")
    assert 'unexpected /usr/games/steam installer layout' in src
    assert 'steam: auto-accepting bootstrap installation into $STEAMDIR' in src
    assert '/etc/cont-init.d/71-fix_xorg_input_hotplug.sh' in src
    assert 'Option "AutoAddDevices" "true"' in src
    assert 'Option "AutoEnableDevices" "true"' in src
    assert 'Ignore Sunshine touch passthrough' in src
    assert 'Ignore Sunshine pen passthrough' in src
    assert 'Ignore controller touchpad' in src
    assert "/etc/supervisor.d/accounts-daemon.ini" in src
    assert "/etc/supervisor.d/polkit.ini" in src
    assert 'unexpected desktop startup layout' in src
    assert 'unexpected sunshine startup layout' in src
    assert 'encoder = nvenc' in src
    assert 'hevc_mode = 2' in src
    assert 'av1_mode = 1' in src
    assert 'qp = 20' in src
    assert 'fec_percentage = 0' in src
    assert 'min_log_level = 2' in src
    assert 'channels = 2' in src
    assert 'credentials/cacert.pem' in src
    assert 'credentials/cakey.pem' in src
    assert 'Install/Upgrade user apps in the background after the desktop is live' in src
    assert '" &' in src
    assert 'touch /tmp/.desktop-apps-updated' in src
    assert "unexpected flatpak init layout" in src
    assert "mount -t proc none /proc 2>/dev/null" in src
    assert "Skipping Flatpak proc remount in unprivileged container" in src
    assert "/etc/cont-init.d/80-configure_flatpak.sh" in src
    assert "unexpected udev init layout" in src
    assert "mkdir -p /run/udev /run/udev/data /dev/input" in src
    assert "/usr/lib/udev/rules.d/99-trion-sunshine-input.rules" in src
    assert 'ATTRS{name}==\\\\"Mouse passthrough\\\\"' in src
    assert 'ATTRS{name}==\\\\"Mouse passthrough (absolute)\\\\"' in src
    assert 'ATTRS{name}==\\\\"Keyboard passthrough\\\\"' in src
    assert 'ENV{ID_SEAT}=\\\\"seat0\\\\"' in src
    assert 'TAG+=\\\\"seat\\\\"' in src
    assert 'TAG-=\\\\"power-switch\\\\"' in src
    assert 'input_properties = ["E:ID_INPUT_JOYSTICK=1' in src
    assert "dumb_udev.service.__file__" in src
    assert 'name == "Keyboard passthrough"' in src
    assert "source_device = dev.parent if dev.device_node is not None and dev.parent is not None else dev" in src
    assert 'name.startswith("Mouse passthrough")' in src
    assert "ID_INPUT_MOUSE=1" in src
    assert "ID_INPUT_KEYBOARD=1" in src
    assert "ID_INPUT_TOUCHSCREEN=1" in src
    assert "ID_INPUT_TABLET=1" in src
    assert "unexpected dumb-udev source layout" in src


def test_ensure_gaming_blueprint_patches_existing_missing_nvidia_caps():
    """
    Regression guard: _ensure_gaming_station_blueprint() must patch an existing
    blueprint that lacks NVIDIA_VISIBLE_DEVICES / NVIDIA_DRIVER_CAPABILITIES so
    that the container-internal GPU driver installer never runs (exit_code=32 fix).
    """
    import sys
    from unittest.mock import MagicMock, patch, call

    sys.modules.pop("container_commander.blueprint_store", None)

    existing = MagicMock()
    existing.image = "josh5/steam-headless:latest"
    existing.dockerfile = ""
    existing.cap_add = []
    existing.hardware_intents = []
    existing.environment = {
        "TZ": "UTC",
        "PUID": "1000",
        "PGID": "1000",
        "STEAM_USER": "vault://STEAM_USERNAME",
        "STEAM_PASS": "vault://STEAM_PASSWORD",
    }

    with (
        patch("container_commander.blueprint_store.get_blueprint", return_value=existing) as mock_get,
        patch("container_commander.blueprint_store.update_blueprint") as mock_update,
        patch("container_commander.blueprint_store.create_blueprint") as mock_create,
        patch("container_commander.storage_assets.get_asset", return_value=None),
        patch("container_commander.storage_assets.list_assets", return_value={}),
        patch("container_commander.storage_scope.get_scope", return_value=None),
        patch("container_commander.storage_scope.upsert_scope") as mock_scope_upsert,
    ):
        from container_commander.mcp_tools import _ensure_gaming_station_blueprint

        _ensure_gaming_station_blueprint()

        mock_get.assert_called_once_with("gaming-station")
        mock_create.assert_not_called()
        mock_scope_upsert.assert_called_once()

        assert mock_update.call_count == 1
        update_payload = mock_update.call_args[0][1]
        updated_env = update_payload["environment"]
        assert update_payload["image"] == ""
        assert "start-steam-host-bridge.sh" in update_payload["dockerfile"]
        assert updated_env["NVIDIA_VISIBLE_DEVICES"] == "all"
        assert updated_env["NVIDIA_DRIVER_CAPABILITIES"] == "all"
        assert updated_env["MODE"] == "secondary"
        assert updated_env["DISPLAY"] == ":0"
        assert updated_env["TRION_HOST_DISPLAY_BRIDGE"] == "true"
        assert updated_env["PULSE_SERVER"] == "unix:/tmp/host-pulse/native"
        assert updated_env["ENABLE_SUNSHINE"] == "false"
        assert updated_env["STEAM_ARGS"] == ""
        assert updated_env["STEAM_USER"] == "vault://STEAM_USERNAME"
        assert updated_env["TZ"] == "UTC"
        assert "SYS_ADMIN" in update_payload["cap_add"]


def test_ensure_gaming_blueprint_no_update_when_nvidia_caps_already_set():
    """No spurious update_blueprint calls when caps are already correct."""
    import sys
    from unittest.mock import MagicMock, patch
    from container_commander.models import MountDef

    sys.modules.pop("container_commander.blueprint_store", None)

    existing = MagicMock()
    existing.image = ""
    existing.dockerfile = "dummy"
    existing.cap_add = ["NET_ADMIN", "SYS_ADMIN", "SYS_NICE"]
    existing.security_opt = ["seccomp=unconfined", "apparmor=unconfined"]
    existing.hardware_intents = []
    existing.environment = {
        "TZ": "UTC",
        "PUID": "1000",
        "PGID": "1000",
        "STEAM_USER": "vault://STEAM_USERNAME",
        "STEAM_PASS": "vault://STEAM_PASSWORD",
        "STEAM_ARGS": "",
        "MODE": "secondary",
        "DISPLAY": ":0",
        "TRION_HOST_DISPLAY_BRIDGE": "true",
        "PULSE_SERVER": "unix:/tmp/host-pulse/native",
        "NVIDIA_VISIBLE_DEVICES": "all",
        "NVIDIA_DRIVER_CAPABILITIES": "all",
        "ENABLE_SUNSHINE": "false",
    }
    existing.mounts = [
        MountDef(host="gaming_steam_config", container="/config", type="volume", mode="rw"),
        MountDef(host="gaming_steam_data", container="/data", type="volume", mode="rw"),
        MountDef(host="gaming_user_data", container="/home/default/.local/share", type="volume", mode="rw"),
        MountDef(host="gaming_steam_home", container="/home/default/.steam", type="volume", mode="rw"),
        MountDef(host="/dev/input", container="/dev/input", type="bind", mode="rw"),
        MountDef(host="/tmp/.X11-unix", container="/tmp/.X11-unix", type="bind", mode="rw"),
        MountDef(host="/run/user/1000/pulse", container="/tmp/host-pulse", type="bind", mode="rw"),
    ]
    existing.devices = ["/dev/dri", "/dev/uinput"]
    existing.storage_scope = "gaming-station-host-bridge"
    existing.ipc_mode = "host"
    existing.ports = []
    existing.healthcheck = {}

    with (
        patch("container_commander.blueprint_store.get_blueprint", return_value=existing),
        patch("container_commander.blueprint_store.update_blueprint") as mock_update,
        patch("container_commander.blueprint_store.create_blueprint") as mock_create,
        patch("container_commander.storage_assets.get_asset", return_value=None),
        patch("container_commander.storage_assets.list_assets", return_value={}),
        patch("container_commander.storage_scope.get_scope", return_value={"roots": [{"path": "/tmp/.X11-unix", "mode": "rw"}]}),
        patch("container_commander.storage_scope.upsert_scope") as mock_scope_upsert,
    ):
        from container_commander.mcp_tools import _ensure_gaming_station_blueprint, _gaming_station_dockerfile

        existing.dockerfile = _gaming_station_dockerfile("josh5/steam-headless:latest")

        _ensure_gaming_station_blueprint()

        mock_create.assert_not_called()
        mock_update.assert_not_called()
        mock_scope_upsert.assert_called_once()


def test_ensure_gaming_blueprint_creates_host_bridge_profile_by_default():
    import sys
    from unittest.mock import patch

    sys.modules.pop("container_commander.blueprint_store", None)

    captured = {}

    with (
        patch("container_commander.blueprint_store.get_blueprint", return_value=None),
        patch("container_commander.blueprint_store.update_blueprint") as mock_update,
        patch("container_commander.blueprint_store.create_blueprint", side_effect=lambda bp: captured.setdefault("bp", bp)),
        patch(
            "container_commander.storage_assets.get_asset",
            side_effect=lambda asset_id: {"id": asset_id, "path": "/data/services/gaming-station/data", "default_mode": "rw"}
            if asset_id == "gaming-station-data"
            else {"id": asset_id, "path": "/data/services/gaming-station/config", "default_mode": "rw"}
            if asset_id == "gaming-station-config"
            else None,
        ),
        patch(
            "container_commander.storage_assets.list_assets",
            return_value={
                "games-library": {
                    "id": "games-library",
                    "path": "/mnt/games/services/gaming-station-games/data",
                    "default_mode": "rw",
                    "published_to_commander": True,
                    "allowed_for": ["games"],
                }
            },
        ),
        patch("container_commander.storage_scope.get_scope", return_value={"roots": [{"path": "/data/services/gaming-station", "mode": "rw"}]}),
        patch("container_commander.storage_scope.upsert_scope") as mock_scope_upsert,
    ):
        from container_commander.mcp_tools import _ensure_gaming_station_blueprint

        _ensure_gaming_station_blueprint()

    bp = captured["bp"]
    assert bp.environment["MODE"] == "secondary"
    assert bp.environment["DISPLAY"] == ":0"
    assert bp.environment["TRION_HOST_DISPLAY_BRIDGE"] == "true"
    assert bp.environment["PULSE_SERVER"] == "unix:/tmp/host-pulse/native"
    assert bp.environment["ENABLE_SUNSHINE"] == "false"
    assert bp.ports == []
    assert bp.storage_scope == "gaming-station-host-bridge"
    assert any(m.container == "/tmp/.X11-unix" for m in bp.mounts)
    assert any(m.container == "/tmp/host-pulse" for m in bp.mounts)
    assert any(m.container == "/home/default/.steam" for m in bp.mounts)
    assert any(m.container == "/home/default/.local/share" for m in bp.mounts)
    assert not any(m.container == "/games" for m in bp.mounts)
    assert len(bp.hardware_intents) == 1
    assert bp.hardware_intents[0].resource_id == "container::mount_ref::games-library"
    assert bp.hardware_intents[0].policy == {"container_path": "/games", "mode": "rw"}
    assert "start-steam-host-bridge.sh" in bp.dockerfile
    mock_update.assert_not_called()
    mock_scope_upsert.assert_called_once()


def test_host_bridge_profile_keeps_steam_and_userdata_mounts():
    from container_commander.mcp_tools_gaming import resolve_gaming_station_host_bridge_profile
    from container_commander.models import MountDef
    from unittest.mock import patch

    with patch(
        "container_commander.storage_assets.get_asset",
        side_effect=lambda asset_id: {"id": asset_id, "path": "/data/services/gaming-station/data", "default_mode": "rw"}
        if asset_id == "gaming-station-data"
        else {"id": asset_id, "path": "/data/services/gaming-station/config", "default_mode": "rw"},
    ), patch(
        "container_commander.storage_scope.get_scope",
        side_effect=lambda name: {"roots": [{"path": "/data/services/gaming-station", "mode": "rw"}]} if name in {"gaming-station", "gaming-station-host-bridge"} else None,
    ), patch("container_commander.storage_scope.upsert_scope") as mock_scope_upsert:
        profile = resolve_gaming_station_host_bridge_profile(MountDef)

    mounts = profile["mounts"]
    assert any(m.container == "/home/default/.steam" for m in mounts)
    assert any(m.container == "/home/default/.local/share" for m in mounts)
    assert any(m.container == "/tmp/.X11-unix" for m in mounts)
    assert any(m.container == "/tmp/host-pulse" for m in mounts)
    assert profile["storage_scope"] == "gaming-station-host-bridge"
    mock_scope_upsert.assert_called_once()


def test_host_bridge_profile_keeps_games_out_of_static_mounts():
    from container_commander.mcp_tools_gaming import resolve_gaming_station_host_bridge_profile
    from container_commander.models import MountDef
    from unittest.mock import patch

    def fake_get_asset(asset_id):
        if asset_id == "gaming-station-data":
            return {"id": asset_id, "path": "/data/services/gaming-station/data", "default_mode": "rw"}
        if asset_id == "gaming-station-config":
            return {"id": asset_id, "path": "/data/services/gaming-station/config", "default_mode": "rw"}
        return None

    with patch(
        "container_commander.storage_assets.get_asset",
        side_effect=fake_get_asset,
    ), patch(
        "container_commander.storage_scope.get_scope",
        side_effect=lambda name: {"roots": [{"path": "/data/services/gaming-station", "mode": "rw"}]} if name in {"gaming-station", "gaming-station-host-bridge"} else None,
    ), patch("container_commander.storage_scope.upsert_scope") as mock_scope_upsert:
        profile = resolve_gaming_station_host_bridge_profile(MountDef)

    mounts = profile["mounts"]
    assert not any(m.container == "/games" for m in mounts)
    mock_scope_upsert.assert_called_once()


def test_host_bridge_profile_adds_persistent_volume_mounts_when_storage_assets_are_missing():
    from container_commander.mcp_tools_gaming import resolve_gaming_station_host_bridge_profile
    from container_commander.models import MountDef
    from unittest.mock import patch

    with patch(
        "container_commander.storage_assets.get_asset",
        return_value=None,
    ), patch(
        "container_commander.storage_scope.get_scope",
        side_effect=lambda name: {"roots": [{"path": "/tmp/.X11-unix", "mode": "rw"}]} if name == "gaming-station-host-bridge" else None,
    ), patch("container_commander.storage_scope.upsert_scope") as mock_scope_upsert:
        profile = resolve_gaming_station_host_bridge_profile(MountDef)

    mounts = profile["mounts"]
    assert any(m.container == "/config" and m.type == "volume" for m in mounts)
    assert any(m.container == "/data" and m.type == "volume" for m in mounts)
    assert any(m.container == "/home/default/.steam" and m.type == "volume" for m in mounts)
    assert any(m.container == "/home/default/.local/share" and m.type == "volume" for m in mounts)
    mock_scope_upsert.assert_called_once()


def test_resolve_gaming_station_games_intents_prefers_published_games_asset():
    from container_commander.mcp_tools_gaming import resolve_gaming_station_games_intents
    from container_commander.models import HardwareIntent
    from unittest.mock import patch

    with patch(
        "container_commander.storage_assets.get_asset",
        return_value=None,
    ), patch(
        "container_commander.storage_assets.list_assets",
        return_value={
            "games-library": {
                "id": "games-library",
                "path": "/mnt/games",
                "default_mode": "rw",
                "published_to_commander": True,
                "allowed_for": ["games"],
            }
        },
    ):
        intents = resolve_gaming_station_games_intents(HardwareIntent)

    assert len(intents) == 1
    assert intents[0].resource_id == "container::mount_ref::games-library"
    assert intents[0].policy == {"container_path": "/games", "mode": "rw"}
    assert intents[0].requested_by == "gaming-station"


def test_host_bridge_dockerfile_writes_unindented_start_script():
    from container_commander.mcp_tools_gaming import gaming_station_dockerfile
    import base64
    import os
    import re
    import subprocess
    import tempfile

    dockerfile = gaming_station_dockerfile("josh5/steam-headless:latest")
    match = re.search(
        r"Path\('\"'\"'/usr/local/bin/start-steam-host-bridge\.sh'\"'\"'\)\.write_bytes\(base64\.b64decode\('\"'\"'([^']+)'\"'\"'\)\)",
        dockerfile,
    )
    assert match, "start-steam-host-bridge payload missing"
    script = base64.b64decode(match.group(1)).decode("utf-8")
    lines = script.splitlines()
    assert lines[0] == "#!/usr/bin/env bash"
    assert lines[1] == "set -euo pipefail"
    assert "<<'EOF'" in script
    assert "\nEOF\n" in script
    assert 'if not match:\n        raise SystemExit(f"missing {key} in /usr/games/steam")' in script
    assert "for needed in \\\n        steam.sh \\\n" in script
    with tempfile.NamedTemporaryFile("w", delete=False) as handle:
        handle.write(script)
        script_path = handle.name
    try:
        subprocess.run(["bash", "-n", script_path], check=True, capture_output=True, text=True)
    finally:
        os.unlink(script_path)


def test_orchestrator_build_tool_args_has_gaming_fallbacks():
    src = _read("core/orchestrator.py")
    assert "if any(tok in lower for tok in (\"steam-headless\", \"sunshine\", \"gaming station\", \"gaming-station\", \"zocken\", \"moonlight\")):" in src
    assert "return {\"blueprint_id\": \"gaming-station\"}" in src
    assert "elif tool_name == \"blueprint_create\":" in src
    assert "\"id\": \"gaming-station\"" in src
    assert "\"image\": \"josh5/steam-headless:latest\"" in src


def test_gaming_blueprint_prefers_published_storage_assets_when_available():
    src = _read("container_commander/mcp_tools.py")
    assert 'get_asset("gaming-station-config")' in src
    assert 'get_asset("gaming-station-data")' in src
    assert 'for candidate in ("gaming-station", "gaming"):' in src
    assert 'def _resolve_gaming_station_host_bridge_profile' in src
    assert 'host="/tmp/.X11-unix"' in src
    assert 'host="/run/user/1000/pulse"' in src
    assert 'container="/home/default/.steam"' in src
    assert 'updates["storage_scope"] = str(storage_profile["storage_scope"] or "").strip()' in src
    assert 'updates["mounts"] = [mount.model_dump() for mount in storage_profile["mounts"]]' in src
    assert 'memory_swap="16g"' in src
    assert 'updates["ports"] = list(desired_ports)' in src
    assert 'updates["healthcheck"] = dict(desired_healthcheck)' in src
