"""
Container Commander — Host Companion Installer
═══════════════════════════════════════════════
Materializes optional marketplace package files onto the host for hybrid
blueprints such as gaming-station (container + host runtime companion).
"""

from __future__ import annotations

import base64
import getpass
import json
import logging
import os
import pwd
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen


logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE_DIR = Path(os.environ.get("MARKETPLACE_DIR", "/app/data/marketplace"))
LOCAL_PACKAGE_DIR = REPO_ROOT / "marketplace" / "packages"
HOST_HELPER_URL = str(os.environ.get("STORAGE_HOST_HELPER_URL", "http://storage-host-helper:8090") or "").strip().rstrip("/")


def _default_host_companion_user() -> str:
    explicit = str(os.environ.get("HOST_COMPANION_USER", "") or "").strip()
    if explicit:
        return explicit
    for candidate in (os.environ.get("SUDO_USER"), os.environ.get("USER")):
        value = str(candidate or "").strip()
        if value:
            return value
    try:
        value = str(getpass.getuser() or "").strip()
        if value:
            return value
    except Exception:
        pass
    return "hostuser"


def _default_host_companion_uid() -> int:
    explicit = str(os.environ.get("HOST_COMPANION_UID", "") or "").strip()
    if explicit.isdigit():
        return int(explicit)
    try:
        return int(os.getuid())
    except Exception:
        return 1000


def _default_host_companion_home(user: str) -> str:
    explicit = str(os.environ.get("HOST_COMPANION_HOME", "") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    try:
        return str(Path(pwd.getpwnam(user).pw_dir))
    except Exception:
        if user == "root":
            return "/root"
        return f"/home/{user}"


HOST_COMPANION_USER = _default_host_companion_user()
HOST_COMPANION_UID = _default_host_companion_uid()
HOST_COMPANION_GID = int(str(os.environ.get("HOST_COMPANION_GID", str(HOST_COMPANION_UID)) or str(HOST_COMPANION_UID)))
HOST_COMPANION_HOME = _default_host_companion_home(HOST_COMPANION_USER)


def _package_root(package_id: str) -> Optional[Path]:
    for base in (MARKETPLACE_DIR / "packages", LOCAL_PACKAGE_DIR):
        candidate = base / package_id
        if candidate.exists():
            return candidate
    return None


def get_package_manifest(package_id: str) -> Optional[Dict]:
    root = _package_root(package_id)
    if not root:
        return None
    manifest = root / "package.json"
    if not manifest.exists():
        return None
    try:
        return json.loads(manifest.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[HostCompanion] Failed to parse package manifest for %s: %s", package_id, exc)
        return None


def get_host_companion_access_links(package_id: str) -> List[Dict[str, str]]:
    manifest = get_package_manifest(package_id)
    if not manifest:
        return []
    host_companion = manifest.get("host_companion") if isinstance(manifest.get("host_companion"), dict) else {}
    raw_links = host_companion.get("access_links") if isinstance(host_companion.get("access_links"), list) else []
    links: List[Dict[str, str]] = []
    for item in raw_links:
        if not isinstance(item, dict):
            continue
        host_port = str(item.get("host_port", "")).strip()
        container_port = str(item.get("container_port", "")).strip()
        if not host_port or not container_port:
            continue
        links.append(
            {
                "host_ip": str(item.get("host_ip", "0.0.0.0")).strip() or "0.0.0.0",
                "host_port": host_port,
                "container_port": container_port,
                "service_name": str(item.get("service_name", "")).strip(),
                "access_label": str(item.get("access_label", "Open")).strip() or "Open",
                "access_scheme": str(item.get("access_scheme", "")).strip(),
                "access_path": str(item.get("access_path", "/")).strip() or "/",
                "access_kind": str(item.get("access_kind", "")).strip(),
            }
        )
    return links


def get_package_storage_scope(package_id: str, manifest: Optional[Dict] = None) -> Optional[Dict]:
    if manifest is None:
        manifest = get_package_manifest(package_id)
    if not isinstance(manifest, dict):
        return None
    storage = manifest.get("storage") if isinstance(manifest.get("storage"), dict) else {}
    scope = storage.get("scope") if isinstance(storage.get("scope"), dict) else {}
    name = str(scope.get("name", "")).strip()
    raw_roots = list(scope.get("roots") or [])
    roots: List[Dict[str, str]] = []
    for item in raw_roots:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "")).strip()
        mode = str(item.get("mode", "rw")).strip().lower() or "rw"
        if not path or mode not in {"ro", "rw"}:
            continue
        roots.append({"path": path, "mode": mode})
    if not name or not roots:
        return None
    return {
        "name": name,
        "roots": roots,
        "metadata": {
            "origin": "package_storage_scope",
            "package_id": str(package_id or "").strip(),
        },
    }


def get_package_postchecks(package_id: str, manifest: Optional[Dict] = None) -> List[str]:
    if manifest is None:
        manifest = get_package_manifest(package_id)
    if not isinstance(manifest, dict):
        return []
    return [str(item or "").strip() for item in list(manifest.get("postchecks") or []) if str(item or "").strip()]


def _get_advisory_checks(manifest: Dict) -> List[str]:
    """Return postcheck names that are advisory (warning-only, do not block ok)."""
    host_companion = manifest.get("host_companion") if isinstance(manifest.get("host_companion"), dict) else {}
    streaming_backend = host_companion.get("streaming_backend") if isinstance(host_companion.get("streaming_backend"), dict) else {}
    if bool(streaming_backend.get("advisory_only", False)):
        return ["sunshine_binary_available", "host_sunshine_service_enabled"]
    return []


def _merge_scope_roots(*groups: List[Dict[str, str]]) -> List[Dict[str, str]]:
    merged: Dict[str, str] = {}
    for group in groups:
        for root in list(group or []):
            path = os.path.abspath(str((root or {}).get("path", "")).strip())
            mode = str((root or {}).get("mode", "rw")).strip().lower() or "rw"
            if not path or mode not in {"ro", "rw"}:
                continue
            previous = merged.get(path, "ro")
            merged[path] = "rw" if mode == "rw" or previous == "rw" else "ro"
    return [{"path": path, "mode": merged[path]} for path in sorted(merged.keys())]


def _blueprint_scope_roots(blueprint) -> List[Dict[str, str]]:
    if blueprint is None:
        return []

    from .storage_scope import _is_runtime_system_bind

    roots: List[Dict[str, str]] = []
    for mount in list(getattr(blueprint, "mounts", []) or []):
        mount_type = str(getattr(mount, "type", "bind") or "bind").strip().lower()
        if mount_type != "bind" or _is_runtime_system_bind(mount):
            continue
        host_path = os.path.abspath(str(getattr(mount, "host", "") or "").strip())
        mode = str(getattr(mount, "mode", "rw") or "rw").strip().lower() or "rw"
        if not host_path.startswith("/") or mode not in {"ro", "rw"}:
            continue
        roots.append({"path": host_path, "mode": mode})
    return roots


def ensure_package_storage_scope(package_id: str, blueprint=None, manifest: Optional[Dict] = None) -> Dict:
    declared = get_package_storage_scope(package_id, manifest=manifest)
    if not declared:
        return {"installed": False, "reason": "scope_not_declared", "package_id": package_id}

    scope_name = str(declared["name"]).strip()
    blueprint_scope = str(getattr(blueprint, "storage_scope", "") or "").strip()
    if blueprint_scope and blueprint_scope != scope_name:
        return {
            "installed": False,
            "reason": "scope_name_mismatch",
            "package_id": package_id,
            "declared_scope": scope_name,
            "blueprint_scope": blueprint_scope,
        }

    from .storage_scope import get_scope, upsert_scope

    effective_roots = _merge_scope_roots(declared["roots"], _blueprint_scope_roots(blueprint))
    existing = get_scope(scope_name)
    existing_roots = list((existing or {}).get("roots") or [])
    if existing and existing_roots == effective_roots:
        return {
            "installed": True,
            "package_id": package_id,
            "scope": scope_name,
            "roots": effective_roots,
            "changed": False,
        }

    scope = upsert_scope(
        name=scope_name,
        roots=effective_roots,
        approved_by="system:package",
        metadata=declared.get("metadata") or {},
    )
    return {
        "installed": True,
        "package_id": package_id,
        "scope": scope_name,
        "roots": list(scope.get("roots") or []),
        "changed": True,
    }


def _read_existing_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception:
        return ""


def _extract_service_env(path: str, key: str) -> str:
    text = _read_existing_text(path)
    for line in text.splitlines():
        if line.startswith(f"Environment={key}="):
            return line.split("=", 1)[1].split("=", 1)[1].strip()
    return ""


def _extract_xorg_option(path: str, option_name: str) -> str:
    text = _read_existing_text(path)
    pattern = re.compile(rf'Option\s+"{re.escape(option_name)}"\s+"([^"]+)"')
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def _extract_xorg_bus_id(path: str) -> str:
    text = _read_existing_text(path)
    pattern = re.compile(r'BusID\s+"([^"]+)"')
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def _default_render_vars() -> Dict[str, str]:
    service_path = f"{HOST_COMPANION_HOME}/.config/systemd/user/sunshine-host.service"
    xorg_path = "/etc/X11/xorg.conf.d/90-sunshine-headless.conf"
    default_sunshine_bin = f"{HOST_COMPANION_HOME}/.local/opt/sunshine/sunshine.AppImage"
    return {
        "SUNSHINE_BIN": _extract_service_env(service_path, "SUNSHINE_BIN") or default_sunshine_bin,
        "XORG_BUS_ID": _extract_xorg_bus_id(xorg_path) or "PCI:1:0:0",
        "XORG_OUTPUT_NAME": _extract_xorg_option(xorg_path, "ConnectedMonitor") or "TV-1",
        "XRANDR_OUTPUT_NAME": "HDMI-0",
        "HOST_COMPANION_USER": HOST_COMPANION_USER,
    }


def _install_targets(manifest: Dict) -> Dict[str, str | bool]:
    host_companion = manifest.get("host_companion") if isinstance(manifest.get("host_companion"), dict) else {}
    raw = host_companion.get("install_targets") if isinstance(host_companion.get("install_targets"), dict) else {}
    home = HOST_COMPANION_HOME
    defaults: Dict[str, str | bool] = {
        "service_name": "sunshine-host.service",
        "start_script_name": "start-host-sunshine-session.sh",
        "xsession_script_name": "host-sunshine-xsession.sh",
        "steam_script_name": "gaming-station-steam.sh",
        "prepare_script_path": "/usr/local/bin/sunshine-host-prepare.sh",
        "sunshine_config_path": f"{home}/.config/sunshine/host-test/sunshine.conf",
        "sunshine_apps_path": f"{home}/.config/sunshine/apps.json",
        "sunshine_log_path": f"{home}/.local/state/sunshine-host.log",
        "xorg_conf_path": "/etc/X11/xorg.conf.d/90-sunshine-headless.conf",
        "xwrapper_path": "/etc/X11/Xwrapper.config",
        "edid_path": "/etc/X11/edid/monitor-1080p.bin",
        "auto_enable": bool(host_companion.get("auto_enable", True)),
        "auto_start": bool(host_companion.get("auto_start", True)),
    }
    merged = {**defaults, **raw}
    merged["service_path"] = f"{home}/.config/systemd/user/{merged['service_name']}"
    merged["start_script_path"] = f"{home}/.local/bin/{merged['start_script_name']}"
    merged["xsession_script_path"] = f"{home}/.local/bin/{merged['xsession_script_name']}"
    merged["steam_script_path"] = f"{home}/.local/bin/{merged['steam_script_name']}"
    return merged


def _render_text(template: str, variables: Dict[str, str]) -> str:
    rendered = str(template)
    for key, value in (variables or {}).items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
    return rendered


def _container_mount_lookup(container: Any) -> Dict[str, Dict[str, str]]:
    mounts: Dict[str, Dict[str, str]] = {}
    attrs = getattr(container, "attrs", {}) or {}
    for item in list(attrs.get("Mounts") or []):
        if not isinstance(item, dict):
            continue
        destination = str(item.get("Destination", "")).strip()
        source = str(item.get("Source", "")).strip()
        mode = str(item.get("Mode", "")).strip().lower() or "rw"
        if destination:
            mounts[destination] = {"source": source, "mode": mode}
    return mounts


def _container_env_lookup(container: Any) -> Dict[str, str]:
    env_map: Dict[str, str] = {}
    attrs = getattr(container, "attrs", {}) or {}
    env_list = list((((attrs.get("Config") or {}).get("Env")) or []))
    for item in env_list:
        if not isinstance(item, str) or "=" not in item:
            continue
        key, value = item.split("=", 1)
        env_map[key] = value
    return env_map


def _is_explicit_persistent_mount(mount: Dict[str, str], expected_source: str = "") -> bool:
    source = str((mount or {}).get("source", "")).strip()
    if not source:
        return False
    if expected_source and source == expected_source:
        return True
    return True


def run_package_postchecks(package_id: str, blueprint=None, container: Any = None, manifest: Optional[Dict] = None) -> Dict:
    manifest = manifest if isinstance(manifest, dict) else get_package_manifest(package_id)
    if not isinstance(manifest, dict):
        return {"ok": False, "package_id": package_id, "reason": "package_not_found", "checks": []}

    requested = get_package_postchecks(package_id, manifest=manifest)
    if not requested:
        return {"ok": True, "package_id": package_id, "checks": []}

    install_targets = _install_targets(manifest)
    host_companion = manifest.get("host_companion") if isinstance(manifest.get("host_companion"), dict) else {}
    runtime_dir = f"/run/user/{HOST_COMPANION_UID}"
    checks: List[Dict[str, Any]] = []

    if container is not None and hasattr(container, "reload"):
        try:
            container.reload()
        except Exception:
            pass

    container_mounts = _container_mount_lookup(container) if container is not None else {}
    container_env = _container_env_lookup(container) if container is not None else {}

    for name in requested:
        ok = True
        detail: Dict[str, Any] = {}

        if name == "host_sunshine_service_enabled":
            service_name = str(install_targets["service_name"])
            enabled = _helper_post_json(
                "/v1/systemctl-user",
                {"user": HOST_COMPANION_USER, "runtime_dir": runtime_dir, "args": ["is-enabled", service_name], "check": False},
            )
            active = _helper_post_json(
                "/v1/systemctl-user",
                {"user": HOST_COMPANION_USER, "runtime_dir": runtime_dir, "args": ["is-active", service_name], "check": False},
            )
            expected_enabled = bool(install_targets["auto_enable"])
            expected_active = bool(install_targets["auto_start"])
            enabled_ok = bool(enabled.get("ok")) if expected_enabled else True
            active_ok = bool(active.get("ok")) if expected_active else True
            ok = enabled_ok and active_ok
            detail = {
                "service": service_name,
                "enabled": bool(enabled.get("ok")),
                "active": bool(active.get("ok")),
                "expected_enabled": expected_enabled,
                "expected_active": expected_active,
            }
        elif name == "host_xorg_ready":
            x_socket = _helper_post_json("/v1/path-exists", {"path": "/tmp/.X11-unix/X0"})
            ok = bool(x_socket.get("exists", False))
            detail = {"path": "/tmp/.X11-unix/X0", "exists": ok}
        elif name == "container_display_bridge_ready":
            required_mounts = {
                "/tmp/.X11-unix": "/tmp/.X11-unix",
                "/tmp/host-pulse": "/run/user/1000/pulse",
            }
            required_env = {
                "DISPLAY": ":0",
                "TRION_HOST_DISPLAY_BRIDGE": "true",
                "PULSE_SERVER": "unix:/tmp/host-pulse/native",
            }
            if not container_mounts:
                ok = False
                detail = {"reason": "container_missing"}
            else:
                mounts_ok = all(container_mounts.get(dst, {}).get("source") == src for dst, src in required_mounts.items())
                env_ok = all(container_env.get(key, "") == value for key, value in required_env.items())
                ok = mounts_ok and env_ok
                detail = {
                    "mounts_ok": mounts_ok,
                    "env_ok": env_ok,
                    "mounts": container_mounts,
                    "env": {key: container_env.get(key, "") for key in required_env},
                }
        elif name == "steam_home_persistent":
            expected_source = "/data/services/gaming-station/data/steam-home"
            mount = container_mounts.get("/home/default/.steam", {})
            ok = _is_explicit_persistent_mount(mount, expected_source=expected_source)
            detail = {
                "destination": "/home/default/.steam",
                "source": mount.get("source", ""),
                "accepted_legacy_source": expected_source,
            }
        elif name == "user_data_persistent":
            expected_source = "/data/services/gaming-station/data/userdata"
            mount = container_mounts.get("/home/default/.local/share", {})
            ok = _is_explicit_persistent_mount(mount, expected_source=expected_source)
            detail = {
                "destination": "/home/default/.local/share",
                "source": mount.get("source", ""),
                "accepted_legacy_source": expected_source,
            }
        elif name == "sunshine_binary_available":
            host_companion = manifest.get("host_companion") if isinstance(manifest.get("host_companion"), dict) else {}
            bb = host_companion.get("binary_bootstrap") if isinstance(host_companion.get("binary_bootstrap"), dict) else {}
            binary_path = str(bb.get("binary_path", "/usr/bin/sunshine")).strip() or "/usr/bin/sunshine"
            path_state = _helper_post_json("/v1/path-exists", {"path": binary_path})
            ok = bool(path_state.get("exists", False))
            detail = {
                "binary_path": binary_path,
                "found": ok,
                "advisory": True,
                "message": (
                    None if ok
                    else f"Sunshine Binary nicht gefunden unter {binary_path}. "
                         "Moonlight-Streaming nicht verfuegbar bis Sunshine installiert wird."
                ),
            }
        else:
            ok = False
            detail = {"reason": "unknown_postcheck"}

        checks.append({"name": name, "ok": ok, "detail": detail})

    advisory_names = set(_get_advisory_checks(manifest))
    hard_checks = [c for c in checks if c["name"] not in advisory_names]
    warnings = [c for c in checks if c["name"] in advisory_names and not c.get("ok")]

    return {
        "ok": all(bool(c.get("ok")) for c in hard_checks),
        "warnings": warnings,
        "package_id": package_id,
        "checks": checks,
    }


def check_host_companion(package_id: str, blueprint=None, container: Any = None, manifest: Optional[Dict] = None) -> Dict:
    manifest = manifest if isinstance(manifest, dict) else get_package_manifest(package_id)
    if not isinstance(manifest, dict):
        return {"ok": False, "package_id": package_id, "reason": "package_not_found"}

    storage_scope = ensure_package_storage_scope(package_id, blueprint=blueprint, manifest=manifest)
    postchecks = run_package_postchecks(package_id, blueprint=blueprint, container=container, manifest=manifest)
    return {
        "ok": bool(postchecks.get("ok")),
        "package_id": package_id,
        "storage_scope": storage_scope,
        "postchecks": postchecks,
    }


def _helper_post_json(path: str, payload: Dict, timeout: int = 30) -> Dict:
    if not HOST_HELPER_URL:
        raise RuntimeError("storage-host-helper not configured")
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        f"{HOST_HELPER_URL}{path}",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"host-helper {path} failed: {exc.code} {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"host-helper {path} unreachable: {exc}") from exc


def _target_for_relative(rel_path: str, install_targets: Dict[str, str | bool]) -> Optional[Dict[str, str]]:
    rel = rel_path.replace("\\", "/").strip("/")
    home_owner = str(HOST_COMPANION_UID)
    home_group = str(HOST_COMPANION_GID)
    mapping = {
        "host/bin/start-host-sunshine-session.sh": {"path": str(install_targets["start_script_path"]), "mode": "0755", "binary": "false", "owner": home_owner, "group": home_group},
        "host/bin/host-sunshine-xsession.sh": {"path": str(install_targets["xsession_script_path"]), "mode": "0755", "binary": "false", "owner": home_owner, "group": home_group},
        "host/bin/gaming-station-steam.sh": {"path": str(install_targets["steam_script_path"]), "mode": "0755", "binary": "false", "owner": home_owner, "group": home_group},
        "host/bin/sunshine-host-prepare.sh": {"path": str(install_targets["prepare_script_path"]), "mode": "0755", "binary": "false", "owner": "root", "group": "root"},
        "host/systemd-user/sunshine-host.service": {"path": str(install_targets["service_path"]), "mode": "0644", "binary": "false", "owner": home_owner, "group": home_group},
        "host/config/sunshine/sunshine.conf": {"path": str(install_targets["sunshine_config_path"]), "mode": "0644", "binary": "false", "owner": home_owner, "group": home_group},
        "host/config/sunshine/apps.json": {"path": str(install_targets["sunshine_apps_path"]), "mode": "0644", "binary": "false", "owner": home_owner, "group": home_group},
        "host/etc/X11/90-sunshine-headless.conf": {"path": str(install_targets["xorg_conf_path"]), "mode": "0644", "binary": "false", "owner": "root", "group": "root"},
        "host/etc/X11/Xwrapper.config": {"path": str(install_targets["xwrapper_path"]), "mode": "0644", "binary": "false", "owner": "root", "group": "root"},
        "host/etc/X11/edid/monitor-1080p.bin.hex": {"path": str(install_targets["edid_path"]), "mode": "0644", "binary": "hex", "owner": "root", "group": "root"},
    }
    return mapping.get(rel)


def _materialized_targets(root: Path, install_targets: Dict[str, str | bool]) -> List[str]:
    targets: List[str] = []
    for source in sorted(root.rglob("*")):
        if not source.is_file():
            continue
        rel = source.relative_to(root).as_posix()
        if rel == "package.json" or rel == "README.md":
            continue
        target = _target_for_relative(rel, install_targets)
        if target and str(target.get("path", "")).strip():
            targets.append(str(target["path"]))
    return targets


def ensure_host_companion(package_id: str, overwrite: bool = False) -> Dict:
    manifest = get_package_manifest(package_id)
    if not manifest:
        return {"installed": False, "reason": "package_not_found", "package_id": package_id}

    root = _package_root(package_id)
    assert root is not None
    install_targets = _install_targets(manifest)
    variables = {
        **_default_render_vars(),
        "HOST_START_SCRIPT_PATH": str(install_targets["start_script_path"]),
        "HOST_XSESSION_SCRIPT_PATH": str(install_targets["xsession_script_path"]),
        "HOST_PREP_SCRIPT_PATH": str(install_targets["prepare_script_path"]),
        "GAMING_STATION_STEAM_SCRIPT_PATH": str(install_targets["steam_script_path"]),
        "SUNSHINE_CONFIG_PATH": str(install_targets["sunshine_config_path"]),
        "SUNSHINE_APPS_PATH": str(install_targets["sunshine_apps_path"]),
        "SUNSHINE_LOG_PATH": str(install_targets["sunshine_log_path"]),
    }
    host_companion = manifest.get("host_companion") if isinstance(manifest.get("host_companion"), dict) else {}
    host_packages = host_companion.get("host_packages") if isinstance(host_companion.get("host_packages"), dict) else {}
    apt_packages = [str(pkg or "").strip() for pkg in list(host_packages.get("apt") or []) if str(pkg or "").strip()]
    binary_bootstrap = host_companion.get("binary_bootstrap") if isinstance(host_companion.get("binary_bootstrap"), dict) else {}
    written: List[Dict[str, str]] = []
    package_results: List[Dict[str, object]] = []

    if apt_packages:
        apt_result = _helper_post_json(
            "/v1/apt-install",
            {
                "packages": apt_packages,
                "update_cache": True,
            },
            timeout=300,
        )
        package_results.append(
            {
                "kind": "apt",
                "requested": apt_packages,
                "installed": list(apt_result.get("installed") or []),
            }
        )

    streaming_backend = host_companion.get("streaming_backend") if isinstance(host_companion.get("streaming_backend"), dict) else {}
    sb_auto_install = bool(streaming_backend.get("auto_install", True))

    if binary_bootstrap and sb_auto_install:
        binary_path = str(binary_bootstrap.get("binary_path", "")).strip()
        path_state = _helper_post_json("/v1/path-exists", {"path": binary_path}) if binary_path else {"exists": False}
        if binary_path and not bool(path_state.get("exists", False)):
            _helper_post_json(
                "/v1/install-deb-url",
                {
                    "url": str(binary_bootstrap.get("deb_url", "")).strip(),
                    "package_name": str(binary_bootstrap.get("package_name", "sunshine")).strip(),
                    "binary_path": binary_path,
                    "allow_downgrade": True,
                },
                timeout=300,
            )
    elif binary_bootstrap and not sb_auto_install:
        logger.info("[HostCompanion] Skipping binary_bootstrap for %s: streaming_backend.auto_install=false", package_id)

    for source in sorted(root.rglob("*")):
        if not source.is_file():
            continue
        rel = source.relative_to(root).as_posix()
        if rel == "package.json" or rel == "README.md":
            continue
        target = _target_for_relative(rel, install_targets)
        if not target:
            continue

        content = source.read_bytes()
        mode = target["mode"]
        if target["binary"] == "false":
            rendered = _render_text(content.decode("utf-8"), variables).encode("utf-8")
        elif target["binary"] == "hex":
            rendered = bytes.fromhex(_render_text(content.decode("utf-8"), variables).strip())
        else:
            rendered = content

        result = _helper_post_json(
            "/v1/write-file",
            {
                "path": target["path"],
                "content_b64": base64.b64encode(rendered).decode("ascii"),
                "mode": mode,
                "overwrite": bool(overwrite),
                "owner": target.get("owner", ""),
                "group": target.get("group", ""),
            },
        )
        written.append(
            {
                "source": rel,
                "target": target["path"],
                "written": str(bool(result.get("written", False))).lower(),
            }
        )

    service_name = str(install_targets["service_name"])
    runtime_dir = f"/run/user/{HOST_COMPANION_UID}"
    _helper_post_json("/v1/systemctl-user", {"user": HOST_COMPANION_USER, "runtime_dir": runtime_dir, "args": ["daemon-reload"]})
    if bool(install_targets["auto_enable"]):
        _helper_post_json("/v1/systemctl-user", {"user": HOST_COMPANION_USER, "runtime_dir": runtime_dir, "args": ["enable", service_name]})

    if bool(install_targets["auto_start"]):
        active = _helper_post_json(
            "/v1/systemctl-user",
            {"user": HOST_COMPANION_USER, "runtime_dir": runtime_dir, "args": ["is-active", service_name], "check": False},
        )
        if not bool(active.get("ok")):
            _helper_post_json("/v1/systemctl-user", {"user": HOST_COMPANION_USER, "runtime_dir": runtime_dir, "args": ["start", service_name]})

    result: Dict[str, Any] = {
        "installed": True,
        "package_id": package_id,
        "package_type": str(manifest.get("package_type", "composite_addon")).strip() or "composite_addon",
        "packages": package_results,
        "files": written,
        "service": service_name,
    }
    if binary_bootstrap and not sb_auto_install:
        result["streaming_backend_skipped"] = True
        result["streaming_backend_reason"] = "auto_install=false"
    return result


def repair_host_companion(package_id: str, blueprint=None, container: Any = None) -> Dict:
    manifest = get_package_manifest(package_id)
    if not isinstance(manifest, dict):
        return {"repaired": False, "package_id": package_id, "reason": "package_not_found"}

    install_result = ensure_host_companion(package_id, overwrite=True)
    storage_scope = ensure_package_storage_scope(package_id, blueprint=blueprint, manifest=manifest)
    postchecks = run_package_postchecks(package_id, blueprint=blueprint, container=container, manifest=manifest)
    return {
        "repaired": bool(postchecks.get("ok")),
        "package_id": package_id,
        "install": install_result,
        "storage_scope": storage_scope,
        "postchecks": postchecks,
    }


def uninstall_host_companion(package_id: str) -> Dict:
    manifest = get_package_manifest(package_id)
    if not isinstance(manifest, dict):
        return {"uninstalled": False, "package_id": package_id, "reason": "package_not_found"}

    root = _package_root(package_id)
    assert root is not None
    install_targets = _install_targets(manifest)
    service_name = str(install_targets["service_name"])
    runtime_dir = f"/run/user/{HOST_COMPANION_UID}"

    stop_result = _helper_post_json(
        "/v1/systemctl-user",
        {"user": HOST_COMPANION_USER, "runtime_dir": runtime_dir, "args": ["stop", service_name], "check": False},
    )
    disable_result = _helper_post_json(
        "/v1/systemctl-user",
        {"user": HOST_COMPANION_USER, "runtime_dir": runtime_dir, "args": ["disable", service_name], "check": False},
    )

    targets = _materialized_targets(root, install_targets)
    remove_result = {"ok": True, "paths": []}
    if targets:
        remove_result = _helper_post_json(
            "/v1/remove-paths",
            {"paths": targets, "missing_ok": True},
        )

    _helper_post_json("/v1/systemctl-user", {"user": HOST_COMPANION_USER, "runtime_dir": runtime_dir, "args": ["daemon-reload"]})

    return {
        "uninstalled": True,
        "package_id": package_id,
        "service": service_name,
        "service_stop": stop_result,
        "service_disable": disable_result,
        "removed_paths": list(remove_result.get("paths") or []),
        "notes": [
            "storage under /data is intentionally preserved",
            "host packages are intentionally not removed",
        ],
    }
