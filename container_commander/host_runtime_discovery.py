"""
Read-only host runtime discovery for packages that depend on host services
without being allowed to materialize or mutate them.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


logger = logging.getLogger(__name__)

HOST_HELPER_URL = str(os.environ.get("STORAGE_HOST_HELPER_URL", "http://storage-host-helper:8090") or "").strip().rstrip("/")
from .host_companions import HOST_COMPANION_HOME, HOST_COMPANION_UID, HOST_COMPANION_USER


def _helper_post_json(path: str, payload: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
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
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"host-helper {path} failed: {exc.code} {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"host-helper {path} unreachable: {exc.reason}") from exc


def get_package_host_runtime_requirements(package_id: str, manifest: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    if manifest is None:
        from .host_companions import get_package_manifest

        manifest = get_package_manifest(package_id)
    if not isinstance(manifest, dict):
        return {}

    raw = manifest.get("host_runtime_requirements")
    if not isinstance(raw, dict):
        return {}

    normalized: Dict[str, Dict[str, Any]] = {}
    for runtime_name, item in raw.items():
        if not isinstance(item, dict):
            continue
        runtime_key = str(runtime_name or "").strip().lower()
        if not runtime_key:
            continue
        normalized[runtime_key] = {
            "required": bool(item.get("required", False)),
            "systemd_user_units": [
                str(unit or "").strip()
                for unit in list(item.get("systemd_user_units") or [])
                if str(unit or "").strip()
            ],
            "systemd_user_globs": [
                str(pattern or "").strip()
                for pattern in list(item.get("systemd_user_globs") or [])
                if str(pattern or "").strip()
            ],
            "binary_candidates": [
                str(path or "").strip()
                for path in list(item.get("binary_candidates") or [])
                if str(path or "").strip()
            ],
            "message_when_found": str(item.get("message_when_found", "")).strip(),
            "message_when_missing": str(item.get("message_when_missing", "")).strip(),
        }
    return normalized


def _systemctl_user(args: List[str], check: bool = False) -> Dict[str, Any]:
    runtime_dir = f"/run/user/{HOST_COMPANION_UID}"
    return _helper_post_json(
        "/v1/systemctl-user",
        {
            "user": HOST_COMPANION_USER,
            "runtime_dir": runtime_dir,
            "args": list(args or []),
            "check": bool(check),
        },
    )


def _path_exists(path: str) -> bool:
    try:
        result = _helper_post_json("/v1/path-exists", {"path": path})
    except Exception:
        return False
    return bool(result.get("exists", False))


def _parse_unit_names(stdout: str) -> List[str]:
    names: List[str] = []
    for raw_line in str(stdout or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        name = line.split()[0].strip()
        if name.endswith(".service"):
            names.append(name)
    return names


def _parse_service_show(stdout: str) -> Dict[str, str]:
    data: Dict[str, str] = {}
    for raw_line in str(stdout or "").splitlines():
        if "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def _extract_exec_path(exec_start: str) -> str:
    match = re.search(r"path=([^ ;]+)", str(exec_start or ""))
    if match:
        return match.group(1).strip()
    match = re.search(r"argv\[\]=([^ ;]+)", str(exec_start or ""))
    if match:
        return match.group(1).strip()
    return ""


def _discover_sunshine_runtime(requirement: Dict[str, Any]) -> Dict[str, Any]:
    configured_units = [
        str(unit or "").strip()
        for unit in list(requirement.get("systemd_user_units") or [])
        if str(unit or "").strip()
    ]
    unit_globs = [
        str(pattern or "").strip()
        for pattern in list(requirement.get("systemd_user_globs") or [])
        if str(pattern or "").strip()
    ]
    binary_candidates = [
        str(path or "").strip()
        for path in list(requirement.get("binary_candidates") or [])
        if str(path or "").strip()
    ]
    default_appimage = f"{HOST_COMPANION_HOME}/.local/opt/sunshine/sunshine.AppImage"
    if default_appimage not in binary_candidates:
        binary_candidates.insert(0, default_appimage)

    discovered_units: List[str] = []
    for pattern in unit_globs:
        for args in (
            ["list-units", pattern, "--all", "--plain", "--no-legend"],
            ["list-unit-files", pattern, "--plain", "--no-legend"],
        ):
            try:
                result = _systemctl_user(args, check=False)
            except Exception:
                continue
            discovered_units.extend(_parse_unit_names(result.get("stdout", "")))

    ordered_units: List[str] = []
    for unit in configured_units + discovered_units:
        if unit and unit not in ordered_units:
            ordered_units.append(unit)

    inactive_units: List[Dict[str, str]] = []
    for unit in ordered_units:
        try:
            active = _systemctl_user(["is-active", unit], check=False)
            show = _systemctl_user(
                ["show", "--property=ExecStart", "--property=FragmentPath", "--property=UnitFileState", unit],
                check=False,
            )
        except Exception as exc:
            logger.debug("[HostRuntime] Failed to inspect unit %s: %s", unit, exc)
            continue
        show_data = _parse_service_show(show.get("stdout", ""))
        exec_path = _extract_exec_path(show_data.get("ExecStart", ""))
        unit_state = str(show_data.get("UnitFileState", "")).strip()
        fragment_path = str(show_data.get("FragmentPath", "")).strip()
        if bool(active.get("ok")):
            return {
                "found": True,
                "status": "active_service",
                "service_name": unit,
                "binary_path": exec_path,
                "unit_file_state": unit_state,
                "fragment_path": fragment_path,
                "binary_candidates_found": [path for path in binary_candidates if _path_exists(path)],
                "inactive_services": inactive_units,
            }
        inactive_units.append(
            {
                "service_name": unit,
                "binary_path": exec_path,
                "unit_file_state": unit_state,
                "fragment_path": fragment_path,
            }
        )

    binaries_found = [path for path in binary_candidates if _path_exists(path)]
    return {
        "found": False,
        "status": "not_found",
        "service_name": "",
        "binary_path": binaries_found[0] if binaries_found else "",
        "unit_file_state": "",
        "fragment_path": "",
        "binary_candidates_found": binaries_found,
        "inactive_services": inactive_units,
    }


def run_package_host_runtime_checks(package_id: str, manifest: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    requirements = get_package_host_runtime_requirements(package_id, manifest=manifest)
    if not requirements:
        return {"ok": True, "package_id": package_id, "checks": [], "warnings": [], "infos": []}

    checks: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    infos: List[Dict[str, Any]] = []

    for runtime_name, requirement in requirements.items():
        if runtime_name == "sunshine":
            discovery = _discover_sunshine_runtime(requirement)
            found = bool(discovery.get("found"))
            required = bool(requirement.get("required", False))
            message = (
                str(requirement.get("message_when_found", "")).strip() or "Sunshine auf dem Host gefunden"
                if found
                else str(requirement.get("message_when_missing", "")).strip() or "Sunshine auf dem Host nicht gefunden"
            )
            detail = {
                **discovery,
                "required": required,
                "message": message,
            }
            check = {
                "name": "host_runtime_sunshine",
                "ok": found,
                "detail": detail,
            }
        else:
            check = {
                "name": f"host_runtime_{runtime_name}",
                "ok": False,
                "detail": {
                    "required": bool(requirement.get("required", False)),
                    "message": f"Unbekannte Host-Runtime-Anforderung: {runtime_name}",
                    "reason": "unknown_runtime_requirement",
                },
            }

        checks.append(check)
        if bool(check.get("ok")):
            infos.append(check)
        elif bool(check["detail"].get("required", False)):
            pass
        else:
            warnings.append(check)

    required_failures = [
        item for item in checks if not bool(item.get("ok")) and bool((item.get("detail") or {}).get("required", False))
    ]
    return {
        "ok": not required_failures,
        "package_id": package_id,
        "checks": checks,
        "warnings": warnings,
        "infos": infos,
    }
