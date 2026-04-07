"""
Gaming-station helpers for Container Commander MCP tools.
"""

from __future__ import annotations

import os
from base64 import b64encode
from shlex import quote
from textwrap import dedent
from typing import List


def compute_gaming_override_resources():
    """
    Derive a quota-compatible resource profile for gaming requests.
    This keeps request_container deterministic even when default gaming
    blueprint resources exceed current commander quotas.
    """
    from .engine import get_quota
    from .models import ResourceLimits

    try:
        quota = get_quota()
        max_mem = int(getattr(quota, "max_total_memory_mb", 0) or 0)
        used_mem = float(getattr(quota, "memory_used_mb", 0) or 0.0)
        max_cpu = float(getattr(quota, "max_total_cpu", 0) or 0.0)
        used_cpu = float(getattr(quota, "cpu_used", 0) or 0.0)
    except Exception:
        return None

    if max_mem <= 0 or max_cpu <= 0:
        return None

    mem_headroom = max(0, int(max_mem - used_mem) - 256)
    cpu_headroom = max(0.0, max_cpu - used_cpu - 0.25)

    if mem_headroom < 512 or cpu_headroom < 0.5:
        return None

    mem_limit_mb = min(1536, mem_headroom)
    cpu_limit = min(1.5, cpu_headroom)
    swap_mb = max(1024, min(mem_limit_mb * 2, 4096))

    return ResourceLimits(
        cpu_limit=f"{cpu_limit:.2f}".rstrip("0").rstrip("."),
        memory_limit=f"{int(mem_limit_mb)}m",
        memory_swap=f"{int(swap_mb)}m",
        timeout_seconds=0,
        pids_limit=512,
    )


def is_path_within_scope(path: str, roots: List[dict]) -> bool:
    try:
        host_path = os.path.abspath(str(path or "").strip())
    except Exception:
        return False
    if not host_path:
        return False
    for root in list(roots or []):
        root_path = os.path.abspath(str((root or {}).get("path", "")).strip())
        if not root_path:
            continue
        try:
            if os.path.commonpath([host_path, root_path]) == root_path:
                return True
        except Exception:
            continue
    return False


def mount_signature(mount) -> tuple[str, str, str, str, str]:
    return (
        str(getattr(mount, "host", "") or "").strip(),
        str(getattr(mount, "container", "") or "").strip(),
        str(getattr(mount, "type", "bind") or "bind").strip().lower(),
        str(getattr(mount, "mode", "rw") or "rw").strip().lower(),
        str(getattr(mount, "asset_id", "") or "").strip(),
    )


def resolve_gaming_station_storage_profile(mount_ctor):
    from .storage_assets import get_asset
    from .storage_scope import get_scope

    fallback_mounts = [
        mount_ctor(host="gaming_steam_config", container="/config", type="volume", mode="rw"),
        mount_ctor(host="gaming_steam_data", container="/data", type="volume", mode="rw"),
    ]

    config_asset = get_asset("gaming-station-config")
    data_asset = get_asset("gaming-station-data")
    if not data_asset:
        return {"mounts": fallback_mounts, "storage_scope": ""}

    scope_name = ""
    for candidate in ("gaming-station", "gaming"):
        scope = get_scope(candidate)
        roots = list((scope or {}).get("roots", []) or [])
        if not roots:
            continue
        data_ok = is_path_within_scope(data_asset.get("path", ""), roots)
        config_ok = not config_asset or is_path_within_scope(config_asset.get("path", ""), roots)
        if data_ok and config_ok:
            scope_name = candidate
            break

    if not scope_name:
        return {"mounts": fallback_mounts, "storage_scope": ""}

    mounts = []
    if config_asset and str(config_asset.get("path", "")).strip():
        mounts.append(
            mount_ctor(
                host=str(config_asset.get("path", "")).strip(),
                container="/config",
                type="bind",
                mode=str(config_asset.get("default_mode", "rw")).strip().lower() or "rw",
                asset_id=str(config_asset.get("id", "")).strip() or None,
            )
        )
    else:
        mounts.append(mount_ctor(host="gaming_steam_config", container="/config", type="volume", mode="rw"))

    mounts.append(
        mount_ctor(
            host=str(data_asset.get("path", "")).strip(),
            container="/data",
            type="bind",
            mode=str(data_asset.get("default_mode", "rw")).strip().lower() or "rw",
            asset_id=str(data_asset.get("id", "")).strip() or None,
        )
    )
    return {"mounts": mounts, "storage_scope": scope_name}


def resolve_gaming_station_games_mount(mount_ctor):
    from .storage_assets import get_asset, list_assets

    candidate_ids = ("gaming-station-games", "games", "sb-games")
    candidates = []
    seen_ids: set[str] = set()

    for asset_id in candidate_ids:
        asset = get_asset(asset_id)
        if not asset:
            continue
        normalized_id = str(asset.get("id") or asset_id).strip() or asset_id
        if normalized_id in seen_ids:
            continue
        seen_ids.add(normalized_id)
        candidates.append(dict(asset))

    for asset_id, asset in sorted(dict(list_assets(published_only=True) or {}).items()):
        normalized_id = str((asset or {}).get("id") or asset_id).strip() or str(asset_id).strip()
        if not normalized_id or normalized_id in seen_ids:
            continue
        allowed_for = {
            str(item or "").strip().lower()
            for item in list((asset or {}).get("allowed_for") or [])
            if str(item or "").strip()
        }
        if "games" not in allowed_for:
            continue
        seen_ids.add(normalized_id)
        candidates.append(dict(asset or {}))

    for asset in candidates:
        host_path = str(asset.get("path", "")).strip()
        asset_id = str(asset.get("id", "")).strip()
        if not host_path.startswith("/") or not asset_id:
            continue
        mode = str(asset.get("default_mode", "rw")).strip().lower() or "rw"
        if mode not in {"ro", "rw"}:
            mode = "rw"
        return mount_ctor(
            host=host_path,
            container="/games",
            type="bind",
            mode=mode,
            asset_id=asset_id,
        )
    return None


def resolve_gaming_station_games_intents(intent_ctor):
    from .storage_assets import get_asset, list_assets

    candidate_ids = ("gaming-station-games", "games", "sb-games")
    candidates = []
    seen_ids: set[str] = set()

    for asset_id in candidate_ids:
        asset = get_asset(asset_id)
        if not asset:
            continue
        normalized_id = str(asset.get("id") or asset_id).strip() or asset_id
        if normalized_id in seen_ids:
            continue
        seen_ids.add(normalized_id)
        candidates.append(dict(asset))

    for asset_id, asset in sorted(dict(list_assets(published_only=True) or {}).items()):
        normalized_id = str((asset or {}).get("id") or asset_id).strip() or str(asset_id).strip()
        if not normalized_id or normalized_id in seen_ids:
            continue
        allowed_for = {
            str(item or "").strip().lower()
            for item in list((asset or {}).get("allowed_for") or [])
            if str(item or "").strip()
        }
        if "games" not in allowed_for:
            continue
        seen_ids.add(normalized_id)
        candidates.append(dict(asset or {}))

    for asset in candidates:
        host_path = str(asset.get("path", "")).strip()
        asset_id = str(asset.get("id", "")).strip()
        if not host_path.startswith("/") or not asset_id:
            continue
        mode = str(asset.get("default_mode", "rw")).strip().lower() or "rw"
        if mode not in {"ro", "rw"}:
            mode = "rw"
        return [
            intent_ctor(
                resource_id=f"container::mount_ref::{asset_id}",
                target_type="container",
                attachment_mode="attach",
                policy={"container_path": "/games", "mode": mode},
                requested_by="gaming-station",
            )
        ]
    return []


def merge_scope_roots(*groups: List[dict]) -> List[dict]:
    merged: dict[str, str] = {}
    for group in groups:
        for root in list(group or []):
            path = os.path.abspath(str((root or {}).get("path", "")).strip())
            if not path:
                continue
            mode = str((root or {}).get("mode", "rw")).strip().lower() or "rw"
            prev = merged.get(path, "ro")
            merged[path] = "rw" if mode == "rw" or prev == "rw" else "ro"
    return [{"path": path, "mode": merged[path]} for path in sorted(merged.keys())]


def build_gaming_station_data_submounts(base_mounts, mount_ctor):
    """Attach persistent Steam/user-data mounts for both bind- and volume-backed /data."""
    data_mount = next(
        (
            mount
            for mount in list(base_mounts or [])
            if str(getattr(mount, "container", "") or "").strip() == "/data"
        ),
        None,
    )
    if data_mount is None:
        return []

    data_type = str(getattr(data_mount, "type", "bind") or "bind").strip().lower() or "bind"
    if data_type == "bind":
        data_host = os.path.abspath(str(getattr(data_mount, "host", "") or "").strip())
        if not data_host:
            return []
        steam_home_host = os.path.join(data_host, "steam-home")
        userdata_host = os.path.join(data_host, "userdata")
        try:
            os.makedirs(steam_home_host, exist_ok=True)
            os.makedirs(userdata_host, exist_ok=True)
        except PermissionError:
            pass
        return [
            mount_ctor(host=userdata_host, container="/home/default/.local/share", type="bind", mode="rw"),
            mount_ctor(host=steam_home_host, container="/home/default/.steam", type="bind", mode="rw"),
        ]

    if data_type == "volume":
        return [
            mount_ctor(host="gaming_user_data", container="/home/default/.local/share", type="volume", mode="rw"),
            mount_ctor(host="gaming_steam_home", container="/home/default/.steam", type="volume", mode="rw"),
        ]

    return []


def strip_block_margin(text: str, margin: str = "        ") -> str:
    """Remove one fixed left margin while preserving nested indentation and here-doc content."""
    return "".join(
        line[len(margin):] if line.startswith(margin) else line
        for line in text.splitlines(keepends=True)
    )


def resolve_gaming_station_primary_profile(mount_ctor):
    """Primary-mode profile: self-contained container, no host X11/Pulse mounts."""
    from .storage_scope import get_scope, upsert_scope

    base = resolve_gaming_station_storage_profile(mount_ctor)
    merged_mounts = list(base["mounts"] or []) + build_gaming_station_data_submounts(base.get("mounts") or [], mount_ctor)

    bind_roots = []
    for mount in merged_mounts:
        if str(getattr(mount, "type", "bind") or "bind").strip().lower() != "bind":
            continue
        bind_roots.append(
            {
                "path": os.path.abspath(str(getattr(mount, "host", "") or "").strip()),
                "mode": str(getattr(mount, "mode", "rw") or "rw").strip().lower() or "rw",
            }
        )

    scope_name = "gaming-station"
    existing_scope = get_scope(scope_name) or {}
    merged_roots = merge_scope_roots(existing_scope.get("roots", []), bind_roots)
    upsert_scope(
        name=scope_name,
        roots=merged_roots,
        approved_by="system:auto",
        metadata={"origin": "gaming_station_primary", "blueprint_id": "gaming-station"},
    )
    return {"mounts": merged_mounts, "storage_scope": scope_name}


def resolve_gaming_station_host_bridge_profile(mount_ctor):
    """Preferred host-bridge profile: Sunshine on host, Steam on host X11/Pulse."""
    from .storage_scope import get_scope, upsert_scope

    base = resolve_gaming_station_storage_profile(mount_ctor)
    merged_mounts = list(base.get("mounts") or [])
    merged_mounts.extend(build_gaming_station_data_submounts(base.get("mounts") or [], mount_ctor))
    merged_mounts.extend([
        mount_ctor(host="/dev/input", container="/dev/input", type="bind", mode="rw"),
        mount_ctor(host="/tmp/.X11-unix", container="/tmp/.X11-unix", type="bind", mode="rw"),
        mount_ctor(host="/run/user/1000/pulse", container="/tmp/host-pulse", type="bind", mode="rw"),
    ])
    bind_roots = []
    for mount in merged_mounts:
        if str(getattr(mount, "type", "bind") or "bind").strip().lower() != "bind":
            continue
        bind_roots.append(
            {
                "path": os.path.abspath(str(getattr(mount, "host", "") or "").strip()),
                "mode": str(getattr(mount, "mode", "rw") or "rw").strip().lower() or "rw",
            }
        )

    scope_name = "gaming-station-host-bridge"
    existing_scope = get_scope(scope_name) or {}
    merged_roots = merge_scope_roots(existing_scope.get("roots", []), bind_roots)
    upsert_scope(
        name=scope_name,
        roots=merged_roots,
        approved_by="system:auto",
        metadata={"origin": "gaming_station_host_bridge", "blueprint_id": "gaming-station"},
    )
    return {"mounts": merged_mounts, "storage_scope": scope_name}


def gaming_station_dockerfile(base_image: str) -> str:
    """
    Build a derived Steam Headless image for host-display bridging:
    Steam runs against the host X11/Pulse stack while Sunshine stays on host.
    """
    start_steam_host_bridge = strip_block_margin(
        """\
        #!/usr/bin/env bash
        set -euo pipefail
        source /usr/bin/common-functions.sh

        export USER_HOME="${USER_HOME:-/home/${USER:-default}}"
        export XDG_CACHE_HOME="${USER_HOME}/.cache"
        export XDG_CONFIG_HOME="${USER_HOME}/.config"
        export XDG_DATA_HOME="${USER_HOME}/.local/share"

        mkdir -p "${XDG_CACHE_HOME}" "${XDG_CONFIG_HOME}" "${XDG_DATA_HOME}"
        wait_for_x

        apply_game_compat_patches() {
            local game_root script_path tmp

            game_root="${USER_HOME}/.steam/steam/steamapps/common/7 Days To Die"
            script_path="${game_root}/7DaysToDie.sh"
            [ -d "${game_root}" ] || return 0
            [ -f "${script_path}" ] || return 0

            tmp="$(mktemp)"
            cat > "${tmp}" <<'EOF'
        #!/bin/sh

        unset LD_PRELOAD
        unset ENABLE_VK_LAYER_VALVE_steam_overlay_1

        exec ./7DaysToDie.x86_64 -force-glcore -disablenativeinput -nogs "$@"
        EOF
            install -m 0777 "${tmp}" "${script_path}"
            rm -f "${tmp}"
        }

        bootstrap_steam_installation() {
            local steam_script steam_config steam_dir needed url sha256 deb_version archive_tmp got

            steam_script="/usr/games/steam"
            steam_config="${USER_HOME}/.steam"
            mkdir -p "${steam_config}"

            if [ -L "${steam_config}/steam" ]; then
                steam_dir="$(readlink -e -q "${steam_config}/steam" || true)"
            elif [ -L "${steam_config}/root" ]; then
                steam_dir="$(readlink -e -q "${steam_config}/root" || true)"
            elif [ -d "${steam_config}/steam" ] && ! [ -L "${steam_config}/steam" ]; then
                steam_dir="${USER_HOME}/.steam"
            else
                steam_dir="${steam_config}/debian-installation"
            fi

            mkdir -p "${steam_dir}"
            ln -fns "${steam_dir}" "${steam_config}/steam"
            ln -fns "${steam_dir}" "${steam_config}/root"

            for needed in \\
                steam.sh \\
                ubuntu12_32/steam \\
                ubuntu12_32/steam-runtime/run.sh \\
                ubuntu12_32/steam-runtime/setup.sh
            do
                [ -x "${steam_dir}/${needed}" ] || break
                needed=""
            done

            [ -n "${needed:-}" ] || return 0

            eval "$(
                python3 - <<'PY'
        import pathlib, re, shlex

        text = pathlib.Path("/usr/games/steam").read_text(encoding="utf-8")
        values = {}
        for key in ("version", "deb_version", "sha256", "url"):
            match = re.search(rf'^{key}="([^"]+)"', text, re.MULTILINE)
            if not match:
                raise SystemExit(f"missing {key} in /usr/games/steam")
            values[key] = match.group(1)

        for key in ("deb_version", "url"):
            values[key] = re.sub(r"\\$\\{([^}]+)\\}", lambda m: values.get(m.group(1), m.group(0)), values[key])

        for key in ("deb_version", "sha256", "url"):
            print(f"{key.upper()}={shlex.quote(values[key])}")
PY
            )"

            mkdir -p "${steam_dir}/deb-installer"
            archive_tmp="${steam_dir}/deb-installer/bootstrap.tar.gz.$$"
            curl -L --fail --retry 5 --retry-delay 2 -o "${archive_tmp}" "${URL}"
            got="$(sha256sum -b "${archive_tmp}")"
            if [ "${got%% *}" != "${SHA256}" ]; then
                echo "steam bootstrap sha256 verification failed" >&2
                echo "Expected: ${SHA256}" >&2
                echo "Got:      ${got}" >&2
                rm -f "${archive_tmp}"
                exit 1
            fi

            tar \\
                -C "${steam_dir}/deb-installer" \\
                -zxf "${archive_tmp}" \\
                steam-launcher/bootstraplinux_ubuntu12_32.tar.xz
            mv \\
                "${steam_dir}/deb-installer/steam-launcher/bootstraplinux_ubuntu12_32.tar.xz" \\
                "${steam_dir}/bootstrap.tar.xz"
            rm -f "${archive_tmp}"
            tar -C "${steam_dir}" -xf "${steam_dir}/bootstrap.tar.xz"
            printf '%s\\n' "${DEB_VERSION}" > "${steam_dir}/deb-installer/version"
        }

        if [ -n "${PULSE_SERVER:-}" ] && [ "${PULSE_SERVER#unix:}" != "${PULSE_SERVER}" ]; then
            pulse_socket="${PULSE_SERVER#unix:}"
            for _ in $(seq 1 30); do
                [ -S "${pulse_socket}" ] && break
                sleep 1
            done
        fi

        export GTK_A11Y=none
        ulimit -n "${TRION_NOFILE_LIMIT:-65535}" 2>/dev/null || true
        bootstrap_steam_installation
        wait_for_desktop
        apply_game_compat_patches
        exec /usr/games/steam -gamepadui ${STEAM_ARGS:-}
        """
    ).lstrip()
    start_desktop_host_bridge = dedent(
        """\
        #!/usr/bin/env bash
        set -euo pipefail
        source /usr/bin/common-functions.sh

        _term() {
            kill -TERM "${desktop_pid:-}" 2>/dev/null || true
        }
        trap _term SIGTERM SIGINT

        rm -f /tmp/.started-desktop
        rm -fv /tmp/.dbus-desktop-session.env
        export_desktop_dbus_session
        export XDG_CACHE_HOME="${USER_HOME:?}/.cache"
        export XDG_CONFIG_HOME="${USER_HOME:?}/.config"
        export XDG_DATA_HOME="${USER_HOME:?}/.local/share"

        mkdir -p "${XDG_CACHE_HOME}" "${XDG_CONFIG_HOME}" "${XDG_DATA_HOME}"
        wait_for_x

        # Skip first-run Flatpak installers in host-bridge mode; they block the
        # visible desktop behind an xterm before the session is usable.
        touch /tmp/.desktop-apps-updated

        echo "**** Starting minimal host-bridge window manager ****"
        xsetroot -solid "#101418" >/dev/null 2>&1 || true
        xfwm4 --compositor=off &
        desktop_pid=$!
        touch /tmp/.started-desktop

        wait "${desktop_pid}"
        """
    ).lstrip()
    configure_host_bridge = dedent(
        """\
        #!/usr/bin/env bash
        set -euo pipefail

        if [ "${TRION_HOST_DISPLAY_BRIDGE:-false}" != "true" ]; then
            exit 0
        fi

        for file in \
            /etc/supervisor.d/accounts-daemon.ini \
            /etc/supervisor.d/polkit.ini \
            /etc/supervisor.d/xorg.ini \
            /etc/supervisor.d/xvfb.ini \
            /etc/supervisor.d/sunshine.ini \
            /etc/supervisor.d/vnc.ini \
            /etc/supervisor.d/vnc-audio.ini \
            /etc/supervisor.d/desktop.ini \
            /etc/supervisor.d/neko.ini \
            /etc/supervisor.d/wol-power-manager.ini \
            /etc/supervisor.d/pulseaudio.ini
        do
            [ -f "${file}" ] || continue
            sed -i 's|^autostart.*=.*$|autostart=false|' "${file}"
        done

        sed -i 's|^autostart.*=.*$|autostart=true|' /etc/supervisor.d/desktop.ini
        sed -i 's|^command=.*$|command=/usr/local/bin/start-desktop-host-bridge.sh|' /etc/supervisor.d/desktop.ini
        sed -i 's|^autostart.*=.*$|autostart=true|' /etc/supervisor.d/steam.ini
        sed -i 's|^command=.*$|command=/usr/local/bin/start-steam-host-bridge.sh|' /etc/supervisor.d/steam.ini
        sed -i 's|^environment=.*$|environment=HOME="/home/%(ENV_USER)s",USER="%(ENV_USER)s",DISPLAY="%(ENV_DISPLAY)s",PULSE_SERVER="%(ENV_PULSE_SERVER)s"|' /etc/supervisor.d/steam.ini
        """
    ).lstrip()
    fix_streaming_perms = dedent(
        """\
        #!/usr/bin/env bash
        set -euo pipefail

        user_name="${USER:-default}"
        if [ -z "${user_name}" ] || [ "${user_name}" = "root" ]; then
            user_name="default"
        fi
        user_home="${USER_HOME:-/home/${user_name}}"

        for grp in video render input; do
            if getent group "${grp}" >/dev/null 2>&1; then
                usermod -aG "${grp}" "${user_name}" 2>/dev/null || true
            fi
        done

        mkdir -p "${user_home}/.cache" "${user_home}/.config" "${user_home}/.local/share"
        chown "${user_name}:${user_name}" "${user_home}" 2>/dev/null || true
        chown -R "${user_name}:${user_name}" "${user_home}/.cache" "${user_home}/.config" "${user_home}/.local" 2>/dev/null || true

        if [ -d /dev/dri ]; then
            for card in /dev/dri/card*; do
                [ -e "${card}" ] || continue
                chgrp video "${card}" 2>/dev/null || true
                chmod 660 "${card}" 2>/dev/null || true
            done
            for render in /dev/dri/renderD*; do
                [ -e "${render}" ] || continue
                if getent group render >/dev/null 2>&1; then
                    chgrp render "${render}" 2>/dev/null || true
                else
                    chgrp video "${render}" 2>/dev/null || true
                fi
                chmod 660 "${render}" 2>/dev/null || true
            done
        fi

        if [ -e /dev/uinput ]; then
            chown "${user_name}:${user_name}" /dev/uinput 2>/dev/null || true
            chmod 660 /dev/uinput 2>/dev/null || true
        fi
        """
    ).lstrip()
    patch_flatpak_init = dedent(
        '''\
from pathlib import Path

path = Path("/etc/cont-init.d/80-configure_flatpak.sh")
text = path.read_text(encoding="utf-8")
old = """if [ "X${NVIDIA_VISIBLE_DEVICES:-}" != "X" ]; then
    # Fix some flatpak quirks (not sure what is happening here) for NVIDIA containers
    mount -t proc none /proc
    flatpak list
    print_step_header "Flatpak configured for running inside a Docker container"
else
    print_step_header "Flatpak already configured for running inside a Docker container"
fi
"""
new = """if [ "X${NVIDIA_VISIBLE_DEVICES:-}" != "X" ]; then
    # Fix some flatpak quirks (not sure what is happening here) for NVIDIA containers
    if mount -t proc none /proc 2>/dev/null; then
        flatpak list
        print_step_header "Flatpak configured for running inside a Docker container"
    else
        print_step_header "Skipping Flatpak proc remount in unprivileged container"
    fi
else
    print_step_header "Flatpak already configured for running inside a Docker container"
fi
"""
if old not in text:
    raise SystemExit("unexpected flatpak init layout")
path.write_text(text.replace(old, new), encoding="utf-8")
'''
    )
    start_steam_host_bridge_b64 = b64encode(start_steam_host_bridge.encode("utf-8")).decode("ascii")
    start_desktop_host_bridge_b64 = b64encode(start_desktop_host_bridge.encode("utf-8")).decode("ascii")
    configure_host_bridge_b64 = b64encode(configure_host_bridge.encode("utf-8")).decode("ascii")
    fix_streaming_perms_b64 = b64encode(fix_streaming_perms.encode("utf-8")).decode("ascii")
    patch_flatpak_init_b64 = b64encode(patch_flatpak_init.encode("utf-8")).decode("ascii")
    gpu_driver_guard = dedent(
        """\
        if [ "${TRION_HOST_DISPLAY_BRIDGE:-false}" = "true" ]; then
            print_header "Skipping internal GPU driver install in host-display bridge mode"
            echo -e "\\e[34mDONE\\e[0m"
            return 0 2>/dev/null || true
        fi

        """
    ).lstrip()
    gpu_driver_guard_b64 = b64encode(gpu_driver_guard.encode("utf-8")).decode("ascii")
    return dedent(
        f"""
        FROM {base_image}

        RUN python3 -c {quote(f"from pathlib import Path; import base64; Path('/usr/local/bin/start-steam-host-bridge.sh').write_bytes(base64.b64decode('{start_steam_host_bridge_b64}')); Path('/usr/local/bin/start-steam-host-bridge.sh').chmod(0o755)")}
        RUN python3 -c {quote(f"from pathlib import Path; import base64; Path('/usr/local/bin/start-desktop-host-bridge.sh').write_bytes(base64.b64decode('{start_desktop_host_bridge_b64}')); Path('/usr/local/bin/start-desktop-host-bridge.sh').chmod(0o755)")}
        RUN python3 -c {quote(f"from pathlib import Path; import base64; Path('/etc/cont-init.d/93-configure_host_bridge.sh').write_bytes(base64.b64decode('{configure_host_bridge_b64}')); Path('/etc/cont-init.d/93-configure_host_bridge.sh').chmod(0o755)")}
        RUN python3 -c {quote(f"from pathlib import Path; import base64; Path('/etc/cont-init.d/92-fix_streaming_perms.sh').write_bytes(base64.b64decode('{fix_streaming_perms_b64}')); Path('/etc/cont-init.d/92-fix_streaming_perms.sh').chmod(0o755)")}
        RUN python3 -c {quote(f"import base64; exec(base64.b64decode('{patch_flatpak_init_b64}').decode('utf-8'))")}
        RUN python3 -c {quote(f"from pathlib import Path; import base64; p=Path('/etc/cont-init.d/60-configure_gpu_driver.sh'); p.write_bytes(base64.b64decode('{gpu_driver_guard_b64}') + p.read_bytes())")}
        """
    ).strip()


def gaming_station_primary_dockerfile(base_image: str) -> str:
    """
    Minimal derived image for primary mode: Sunshine runs inside the container.
    Adds streaming permission fixes plus a dumb-udev input classification patch;
    the image's built-in supervisord handles Xvfb, Sunshine, and Steam
    automatically with MODE=primary.
    """
    patch_dumb_udev_input_classification = dedent(
        """\
from pathlib import Path
import dumb_udev.service

path = Path(dumb_udev.service.__file__)
text = path.read_text(encoding="utf-8")
if "ID_INPUT_MOUSE=1\\\\n" in text and "ID_INPUT_KEYBOARD=1\\\\n" in text:
    raise SystemExit(0)
start_marker = "def build_data_content(dev: pyudev.Device):"
end_marker = "            return file_content\\n"
try:
    start = text.index(start_marker)
    end = text.index(end_marker, start) + len(end_marker)
except ValueError as exc:
    raise SystemExit(f"unexpected dumb-udev source layout: {path}") from exc
replacement = '''def build_data_content(dev: pyudev.Device):
            # Classify Sunshine passthrough devices so libudev/Xorg can match them.
            time_now = time.time()
            init_usec = int(time_now * 1_000)
            input_properties = ["E:ID_INPUT_JOYSTICK=1\\\\n"]
            source_device = dev.parent if dev.device_node is not None and dev.parent is not None else dev
            name = str(source_device.get("NAME", "")).strip('"')
            if name == "Keyboard passthrough":
                input_properties = [
                    "E:ID_INPUT_KEY=1\\\\n",
                    "E:ID_INPUT_KEYBOARD=1\\\\n",
                ]
            elif name.startswith("Mouse passthrough"):
                input_properties = ["E:ID_INPUT_MOUSE=1\\\\n"]
            elif name == "Touch passthrough":
                input_properties = ["E:ID_INPUT_TOUCHSCREEN=1\\\\n"]
            elif name == "Pen passthrough":
                input_properties = ["E:ID_INPUT_TABLET=1\\\\n"]
            file_content = [
                f"I:{init_usec}\\\\n",
                "E:ID_INPUT=1\\\\n",
                *input_properties,
                "E:ID_SERIAL=noserial\\\\n",
                "G:seat\\\\n",
            ]
            if dev.device_node is not None:
                file_content.append("G:uaccess\\\\n")
            return file_content
'''
path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")
"""
    )
    patch_steam_launcher_no_prompt = dedent(
        '''\
from pathlib import Path
import re

path = Path("/usr/games/steam")
text = path.read_text(encoding="utf-8")
pattern = re.compile(
    r'if \\[ -n "\\$new_installation" \\]; then\\n'
    r'(?:(?:    .*?)\\n)+?'
    r'fi\\n\\n'
    r'if \\[ "\\$installed" != "\\$deb_version" \\] \\|\\| \\[ -n "\\$new_installation" \\]; then\\n',
    re.S,
)
replacement = """if [ -n "$new_installation" ]; then
    echo "steam: auto-accepting bootstrap installation into $STEAMDIR" >&2
fi

if [ "$installed" != "$deb_version" ] || [ -n "$new_installation" ]; then
"""
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise SystemExit("unexpected /usr/games/steam installer layout")
path.write_text(text, encoding="utf-8")
'''
    )
    fix_streaming_perms = dedent(
        """\
        #!/usr/bin/env bash
        set -euo pipefail

        user_name="${USER:-default}"
        if [ -z "${user_name}" ] || [ "${user_name}" = "root" ]; then
            user_name="default"
        fi
        user_home="${USER_HOME:-/home/${user_name}}"

        for grp in video render input; do
            if getent group "${grp}" >/dev/null 2>&1; then
                usermod -aG "${grp}" "${user_name}" 2>/dev/null || true
            fi
        done

        mkdir -p "${user_home}/.cache" "${user_home}/.config" "${user_home}/.local/share"
        chown "${user_name}:${user_name}" "${user_home}" 2>/dev/null || true
        chown -R "${user_name}:${user_name}" "${user_home}/.cache" "${user_home}/.config" "${user_home}/.local" 2>/dev/null || true

        if [ -d /dev/dri ]; then
            for card in /dev/dri/card*; do
                [ -e "${card}" ] || continue
                chgrp video "${card}" 2>/dev/null || true
                chmod 660 "${card}" 2>/dev/null || true
            done
            for render in /dev/dri/renderD*; do
                [ -e "${render}" ] || continue
                if getent group render >/dev/null 2>&1; then
                    chgrp render "${render}" 2>/dev/null || true
                else
                    chgrp video "${render}" 2>/dev/null || true
                fi
                chmod 660 "${render}" 2>/dev/null || true
            done
        fi

        if [ -e /dev/uinput ]; then
            chown "${user_name}:${user_name}" /dev/uinput 2>/dev/null || true
            chmod 660 /dev/uinput 2>/dev/null || true
        fi
        """
    ).lstrip()
    fix_xorg_input_hotplug = dedent(
        """\
        #!/usr/bin/env bash
        set -euo pipefail

        python3 - <<'PY'
from pathlib import Path
import re

xorg_conf = Path("/etc/X11/xorg.conf")
if xorg_conf.exists():
    text = xorg_conf.read_text(encoding="utf-8")
    text = text.replace('    InputDevice    "Keyboard0" "CoreKeyboard"\\n', "")
    text = text.replace('    InputDevice    "Mouse0" "CorePointer"\\n', "")
    text = re.sub(
        r'Section "InputDevice"\\n.*?EndSection\\n\\n',
        "",
        text,
        flags=re.S,
    )
    server_flags = '''Section "ServerFlags"
    Option "AutoAddGPU" "false"
    Option "AutoAddDevices" "true"
    Option "AutoEnableDevices" "true"
EndSection
'''
    if 'Section "ServerFlags"' in text:
        text = re.sub(r'Section "ServerFlags"\\n(?:    .*\\n)*?EndSection\\n?', server_flags, text, count=1, flags=re.S)
    else:
        if not text.endswith("\\n"):
            text += "\\n"
        text += "\\n" + server_flags
    xorg_conf.write_text(text, encoding="utf-8")

ignore_conf = Path("/etc/X11/xorg.conf.d/92-trion-ignore-virtual-touch.conf")
ignore_conf.parent.mkdir(parents=True, exist_ok=True)
ignore_conf.write_text(
    '''Section "InputClass"
    Identifier "Ignore Sunshine touch passthrough"
    MatchProduct "Touch passthrough"
    Option "Ignore" "true"
EndSection

Section "InputClass"
    Identifier "Ignore Sunshine pen passthrough"
    MatchProduct "Pen passthrough"
    Option "Ignore" "true"
EndSection

Section "InputClass"
    Identifier "Ignore controller touchpad"
    MatchProduct "Wireless Controller Touchpad"
    Option "Ignore" "true"
EndSection
''',
    encoding="utf-8",
)
PY
        """
    ).lstrip()
    patch_udev_runtime_bootstrap = dedent(
        '''\
from pathlib import Path

path = Path("/etc/cont-init.d/30-configure_udev.sh")
text = path.read_text(encoding="utf-8")
needle = """# Configure dbus
print_header "Configure udevd"

"""
insert = """# Configure dbus
print_header "Configure udevd"

# The primary gaming path now runs privileged. Ensure the runtime directories
# exist before the udev capability checks, otherwise the image falls back to
# dumb-udev only because /run/udev is missing during cont-init.
mkdir -p /run/udev /run/udev/data /dev/input
chmod 0755 /run/udev /run/udev/data /dev/input 2>/dev/null || true

"""
if needle not in text:
    raise SystemExit("unexpected udev init layout")
path.write_text(text.replace(needle, insert, 1), encoding="utf-8")
'''
    )
    patch_sunshine_input_udev_rules = dedent(
        '''\
from pathlib import Path

rules_path = Path("/usr/lib/udev/rules.d/99-trion-sunshine-input.rules")
rules_path.write_text(
    """# Keep Sunshine passthrough input devices visible to Xorg on their event nodes.
ACTION==\\"remove\\", GOTO=\\"trion_sunshine_input_end\\"
SUBSYSTEM!=\\"input\\", GOTO=\\"trion_sunshine_input_end\\"
KERNEL!=\\"event*\\", GOTO=\\"trion_sunshine_input_end\\"

ATTRS{name}==\\"Mouse passthrough\\", ENV{ID_INPUT}=\\"1\\", ENV{ID_INPUT_MOUSE}=\\"1\\", ENV{ID_SEAT}=\\"seat0\\", TAG+=\\"seat\\"
ATTRS{name}==\\"Mouse passthrough (absolute)\\", ENV{ID_INPUT}=\\"1\\", ENV{ID_INPUT_MOUSE}=\\"1\\", ENV{ID_SEAT}=\\"seat0\\", TAG+=\\"seat\\"
ATTRS{name}==\\"Keyboard passthrough\\", ENV{ID_INPUT}=\\"1\\", ENV{ID_INPUT_KEY}=\\"1\\", ENV{ID_INPUT_KEYBOARD}=\\"1\\", ENV{ID_SEAT}=\\"seat0\\", TAG+=\\"seat\\", TAG-=\\"power-switch\\"

LABEL=\\"trion_sunshine_input_end\\"
""",
    encoding="utf-8",
)
'''
    )
    patch_flatpak_init = dedent(
        '''\
from pathlib import Path

path = Path("/etc/cont-init.d/80-configure_flatpak.sh")
text = path.read_text(encoding="utf-8")
old = """if [ "X${NVIDIA_VISIBLE_DEVICES:-}" != "X" ]; then
    # Fix some flatpak quirks (not sure what is happening here) for NVIDIA containers
    mount -t proc none /proc
    flatpak list
    print_step_header "Flatpak configured for running inside a Docker container"
else
    print_step_header "Flatpak already configured for running inside a Docker container"
fi
"""
new = """if [ "X${NVIDIA_VISIBLE_DEVICES:-}" != "X" ]; then
    # Fix some flatpak quirks (not sure what is happening here) for NVIDIA containers
    if mount -t proc none /proc 2>/dev/null; then
        flatpak list
        print_step_header "Flatpak configured for running inside a Docker container"
    else
        print_step_header "Skipping Flatpak proc remount in unprivileged container"
    fi
else
    print_step_header "Flatpak already configured for running inside a Docker container"
fi
"""
if old not in text:
    raise SystemExit("unexpected flatpak init layout")
path.write_text(text.replace(old, new), encoding="utf-8")
'''
    )
    patch_desktop_startup = dedent(
        '''\
from pathlib import Path

path = Path("/usr/bin/start-desktop.sh")
text = path.read_text(encoding="utf-8")
old = """# EXECUTE PROCESS:
# Wait for the X server to start
wait_for_x
# Install/Upgrade user apps
if [[ ! -f /tmp/.desktop-apps-updated ]]; then
    xterm -geometry 200x50+0+0 -ls -e /bin/bash -c "
        source /usr/bin/install_firefox.sh;
        source /usr/bin/install_protonup.sh;
        sleep 1;
    "
    touch /tmp/.desktop-apps-updated
fi

# Run the desktop environment
echo "**** Starting Xfce4 ****"
/usr/bin/startxfce4 &
desktop_pid=$!
touch /tmp/.started-desktop
"""
new = """# EXECUTE PROCESS:
# Wait for the X server to start
wait_for_x

# Run the desktop environment first so dependents (e.g. Sunshine) do not block
echo "**** Starting Xfce4 ****"
/usr/bin/startxfce4 &
desktop_pid=$!
touch /tmp/.started-desktop

# Install/Upgrade user apps in the background after the desktop is live
if [[ ! -f /tmp/.desktop-apps-updated ]]; then
    xterm -geometry 200x50+0+0 -ls -e /bin/bash -c "
        source /usr/bin/install_firefox.sh;
        source /usr/bin/install_protonup.sh;
        sleep 1;
    " &
    touch /tmp/.desktop-apps-updated
fi
"""
if old not in text:
    raise SystemExit("unexpected desktop startup layout")
path.write_text(text.replace(old, new), encoding="utf-8")
'''
    )
    patch_sunshine_pairing_paths = dedent(
        '''\
from pathlib import Path

path = Path("/usr/bin/start-sunshine.sh")
text = path.read_text(encoding="utf-8")
needle = """if [ ! -f "${USER_HOME:?}/.config/sunshine/sunshine_state.json" ]; then
    echo "{}" > "${USER_HOME:?}/.config/sunshine/sunshine_state.json"
fi
"""
insert = """if [ ! -f "${USER_HOME:?}/.config/sunshine/sunshine_state.json" ]; then
    echo "{}" > "${USER_HOME:?}/.config/sunshine/sunshine_state.json"
fi
python3 - <<'PY'
from pathlib import Path
cfg = Path(f"{Path.home()}/.config/sunshine/sunshine.conf")
text = cfg.read_text(encoding="utf-8")
required = {
    "cert": f"{Path.home()}/.config/sunshine/credentials/cacert.pem",
    "pkey": f"{Path.home()}/.config/sunshine/credentials/cakey.pem",
}
for key, value in required.items():
    active = f"{key} = {value}"
    commented = f"# {key} = /dir/{'cert.pem' if key == 'cert' else 'pkey.pem'}"
    if active in text:
        continue
    if commented in text:
        text = text.replace(commented, active, 1)
    else:
        text += "\\\\n" + active + "\\\\n"
cfg.write_text(text, encoding="utf-8")
PY
"""
if needle not in text:
    raise SystemExit("unexpected sunshine startup layout")
path.write_text(text.replace(needle, insert), encoding="utf-8")
'''
    )
    patch_sunshine_primary_defaults = dedent(
        '''\
from pathlib import Path

path = Path("/templates/sunshine/sunshine.conf")
text = path.read_text(encoding="utf-8")

replacements = {
    "# hevc_mode = 2": "hevc_mode = 2",
    "# av1_mode = 0": "av1_mode = 1",
    "# qp = 28": "qp = 20",
    "# encoder = software": "encoder = nvenc",
    "# fec_percentage = 20": "fec_percentage = 0",
    "min_log_level = info": "min_log_level = 2",
}
for old, new in replacements.items():
    if old in text:
        text = text.replace(old, new)

text = text.replace("channels = 2\\n", "")
path.write_text(text, encoding="utf-8")
'''
    )
    patch_dumb_udev_input_classification_b64 = b64encode(
        patch_dumb_udev_input_classification.encode("utf-8")
    ).decode("ascii")
    patch_steam_launcher_no_prompt_b64 = b64encode(
        patch_steam_launcher_no_prompt.encode("utf-8")
    ).decode("ascii")
    fix_streaming_perms_b64 = b64encode(fix_streaming_perms.encode("utf-8")).decode("ascii")
    fix_xorg_input_hotplug_b64 = b64encode(fix_xorg_input_hotplug.encode("utf-8")).decode("ascii")
    patch_udev_runtime_bootstrap_b64 = b64encode(patch_udev_runtime_bootstrap.encode("utf-8")).decode("ascii")
    patch_sunshine_input_udev_rules_b64 = b64encode(
        patch_sunshine_input_udev_rules.encode("utf-8")
    ).decode("ascii")
    patch_flatpak_init_b64 = b64encode(patch_flatpak_init.encode("utf-8")).decode("ascii")
    patch_desktop_startup_b64 = b64encode(patch_desktop_startup.encode("utf-8")).decode("ascii")
    patch_sunshine_pairing_paths_b64 = b64encode(patch_sunshine_pairing_paths.encode("utf-8")).decode("ascii")
    patch_sunshine_primary_defaults_b64 = b64encode(patch_sunshine_primary_defaults.encode("utf-8")).decode("ascii")
    return dedent(
        f"""
        FROM {base_image}

        RUN apt-get update && apt-get install -y --no-install-recommends libcap2-bin \
            && rm -rf /var/lib/apt/lists/* \
            && setcap cap_net_admin+ep "$(realpath /usr/bin/sunshine)"

        RUN python3 -c {quote(f"import base64; exec(base64.b64decode('{patch_steam_launcher_no_prompt_b64}').decode('utf-8'))")}
        RUN python3 -c {quote(f"import base64; exec(base64.b64decode('{patch_dumb_udev_input_classification_b64}').decode('utf-8'))")}
        RUN python3 -c {quote(f"from pathlib import Path; import base64; Path('/etc/cont-init.d/92-fix_streaming_perms.sh').write_bytes(base64.b64decode('{fix_streaming_perms_b64}')); Path('/etc/cont-init.d/92-fix_streaming_perms.sh').chmod(0o755)")}
        RUN python3 -c {quote(f"from pathlib import Path; import base64; Path('/etc/cont-init.d/71-fix_xorg_input_hotplug.sh').write_bytes(base64.b64decode('{fix_xorg_input_hotplug_b64}')); Path('/etc/cont-init.d/71-fix_xorg_input_hotplug.sh').chmod(0o755)")}
        RUN python3 -c {quote(f"import base64; exec(base64.b64decode('{patch_udev_runtime_bootstrap_b64}').decode('utf-8'))")}
        RUN python3 -c {quote(f"import base64; exec(base64.b64decode('{patch_sunshine_input_udev_rules_b64}').decode('utf-8'))")}
        RUN python3 -c {quote(f"import base64; exec(base64.b64decode('{patch_flatpak_init_b64}').decode('utf-8'))")}
        RUN python3 -c {quote(f"import base64; exec(base64.b64decode('{patch_sunshine_primary_defaults_b64}').decode('utf-8'))")}
        RUN python3 -c {quote(f"import base64; exec(base64.b64decode('{patch_desktop_startup_b64}').decode('utf-8'))")}
        RUN python3 -c {quote(f"import base64; exec(base64.b64decode('{patch_sunshine_pairing_paths_b64}').decode('utf-8'))")}
        """
    ).strip()


def ensure_gaming_station_blueprint() -> None:
    """
    Ensure a deterministic host-bridge gaming blueprint exists.
    Sunshine remains on the host; the container only carries Steam/app state.
    """
    from .blueprint_store import get_blueprint, create_blueprint, update_blueprint
    from .models import Blueprint, ResourceLimits, MountDef, NetworkMode, HardwareIntent

    blueprint_id = "gaming-station"
    image_ref = "josh5/steam-headless:latest"
    create_dockerfile = gaming_station_dockerfile(image_ref)
    create_desired_ports: list[str] = []
    create_desired_healthcheck: dict = {}
    desired_devices = ["/dev/dri", "/dev/uinput"]
    existing = get_blueprint(blueprint_id)
    if existing:
        existing_env = dict(getattr(existing, "environment", {}) or {})
        dockerfile = gaming_station_dockerfile(image_ref)
        desired_ports: list[str] = []
        desired_healthcheck: dict = {}
        storage_profile = resolve_gaming_station_host_bridge_profile(MountDef)
        desired_hardware_intents = resolve_gaming_station_games_intents(HardwareIntent)
        updates: dict = {}
        legacy_image = str(existing.image or "").strip().lower()
        if legacy_image in {
            "ghcr.io/linuxserver/steam-headless:latest",
            "lscr.io/linuxserver/steam-headless:latest",
        }:
            updates["image"] = ""
            updates["dockerfile"] = dockerfile
            updates["image_digest"] = ""
        if str(existing.image or "").strip() or str(existing.dockerfile or "").strip() != dockerfile:
            updates["image"] = ""
            updates["dockerfile"] = dockerfile
            updates["image_digest"] = ""
        host_bridge_keys = {"MODE", "DISPLAY", "TRION_HOST_DISPLAY_BRIDGE", "PULSE_SERVER", "ENABLE_SUNSHINE", "TRION_GAMING_LEGACY_PRIMARY"}
        if (
            existing_env.get("NVIDIA_VISIBLE_DEVICES") != "all"
            or existing_env.get("NVIDIA_DRIVER_CAPABILITIES") != "all"
            or existing_env.get("MODE") != "secondary"
            or existing_env.get("DISPLAY") != ":0"
            or existing_env.get("TRION_HOST_DISPLAY_BRIDGE") != "true"
            or existing_env.get("PULSE_SERVER") != "unix:/tmp/host-pulse/native"
            or existing_env.get("ENABLE_SUNSHINE", "false").strip().lower() != "false"
            or "TRION_GAMING_LEGACY_PRIMARY" in existing_env
            or existing_env.get("STEAM_ARGS", None) != ""
        ):
            base_env = {key: value for key, value in existing_env.items() if key not in host_bridge_keys}
            updates["environment"] = {
                **base_env,
                "NVIDIA_VISIBLE_DEVICES": "all",
                "NVIDIA_DRIVER_CAPABILITIES": "all",
                "MODE": "secondary",
                "DISPLAY": ":0",
                "TRION_HOST_DISPLAY_BRIDGE": "true",
                "PULSE_SERVER": "unix:/tmp/host-pulse/native",
                "ENABLE_SUNSHINE": "false",
                "STEAM_ARGS": "",
            }
        desired_caps = ["NET_ADMIN", "SYS_ADMIN", "SYS_NICE"]
        merged_caps = list(existing.cap_add or [])
        missing_caps = [cap for cap in desired_caps if cap not in merged_caps]
        if missing_caps:
            updates["cap_add"] = merged_caps + missing_caps
        desired_security_opt = ["seccomp=unconfined", "apparmor=unconfined"]
        current_security_opt = list(existing.security_opt or [])
        missing_security_opt = [opt for opt in desired_security_opt if opt not in current_security_opt]
        if missing_security_opt:
            updates["security_opt"] = current_security_opt + missing_security_opt
        if list(existing.ports or []) != desired_ports:
            updates["ports"] = list(desired_ports)
        if dict(existing.healthcheck or {}) != desired_healthcheck:
            updates["healthcheck"] = dict(desired_healthcheck)
        if str(getattr(existing, "ipc_mode", "") or "").strip().lower() != "host":
            updates["ipc_mode"] = "host"
        existing_resources = existing.resources
        desired_resources = ResourceLimits(
            memory_limit="16g",
            memory_swap="24g",
            cpu_limit="6.0",
            timeout_seconds=0,
            pids_limit=512,
        )
        has_resource_shape = all(
            hasattr(existing_resources, field)
            and isinstance(getattr(existing_resources, field), (str, int, float))
            for field in ("memory_limit", "memory_swap", "cpu_limit", "pids_limit")
        )
        if has_resource_shape and (
            str(getattr(existing_resources, "memory_limit", "") or "").strip().lower()
            != str(desired_resources.memory_limit).strip().lower()
            or str(getattr(existing_resources, "memory_swap", "") or "").strip().lower()
            != str(desired_resources.memory_swap).strip().lower()
            or str(getattr(existing_resources, "cpu_limit", "") or "").strip().lower()
            != str(desired_resources.cpu_limit).strip().lower()
            or int(getattr(existing_resources, "pids_limit", 0) or 0) != int(desired_resources.pids_limit or 0)
        ):
            updates["resources"] = desired_resources.model_dump()
        if not bool(getattr(existing, "privileged", False)):
            updates["privileged"] = True
        current_signature = [mount_signature(mount) for mount in list(existing.mounts or [])]
        desired_signature = [mount_signature(mount) for mount in list(storage_profile["mounts"] or [])]
        if current_signature != desired_signature:
            updates["mounts"] = [mount.model_dump() for mount in storage_profile["mounts"]]
        if list(existing.devices or []) != desired_devices:
            updates["devices"] = list(desired_devices)
        current_hardware_intents = [intent.model_dump() for intent in list(existing.hardware_intents or [])]
        desired_hardware_intent_payloads = [intent.model_dump() for intent in list(desired_hardware_intents or [])]
        if current_hardware_intents != desired_hardware_intent_payloads:
            updates["hardware_intents"] = desired_hardware_intent_payloads
        if str(existing.storage_scope or "").strip() != str(storage_profile["storage_scope"] or "").strip():
            updates["storage_scope"] = str(storage_profile["storage_scope"] or "").strip()
        if updates:
            update_blueprint(blueprint_id, updates)
        return

    create_storage_profile = resolve_gaming_station_host_bridge_profile(MountDef)
    create_hardware_intents = resolve_gaming_station_games_intents(HardwareIntent)
    blueprint = Blueprint(
        id=blueprint_id,
        name="Gaming Station (Steam Headless + Sunshine)",
        description="GPU gaming container with Sunshine on the host and Steam in the container. Preferred host-display bridge profile.",
        dockerfile=create_dockerfile,
        image="",
        image_digest="",
        resources=ResourceLimits(memory_limit="16g", memory_swap="24g", cpu_limit="6.0", timeout_seconds=0, pids_limit=512),
        mounts=create_storage_profile["mounts"],
        storage_scope=str(create_storage_profile["storage_scope"] or "").strip(),
        network=NetworkMode.FULL,
        ports=create_desired_ports,
        runtime="nvidia",
        devices=list(desired_devices),
        hardware_intents=create_hardware_intents,
        environment={
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
            "ENABLE_SUNSHINE": "false",
            "NVIDIA_VISIBLE_DEVICES": "all",
            "NVIDIA_DRIVER_CAPABILITIES": "all",
            "DISPLAY_SIZEW": "1920",
            "DISPLAY_SIZEH": "1080",
            "DISPLAY_REFRESH": "120",
            "ENABLE_EVDEV_INPUTS": "true",
        },
        cap_add=["NET_ADMIN", "SYS_ADMIN", "SYS_NICE"],
        security_opt=["seccomp=unconfined", "apparmor=unconfined"],
        privileged=True,
        ipc_mode="host",
        healthcheck=create_desired_healthcheck,
        tags=["gaming", "steam", "sunshine", "gpu", "nvidia"],
        icon="🎮",
    )
    create_blueprint(blueprint)
