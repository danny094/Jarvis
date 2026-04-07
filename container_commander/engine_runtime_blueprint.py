"""
Internal helpers for runtime blueprint composition and pre-start execution.

This module exists to shrink `engine.py` without changing the external
function names that current contracts and tests import from that module.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any, Callable, Dict, List, Optional

try:
    from docker.errors import ContainerError
except Exception:  # pragma: no cover - import fallback for source-mocked tests
    ContainerError = Exception

from .models import Blueprint, MountDef


def normalize_runtime_mount_overrides(raw_mounts: Optional[List[Dict[str, Any]]]) -> List[MountDef]:
    mounts: List[MountDef] = []
    for item in list(raw_mounts or []):
        if not isinstance(item, dict):
            raise RuntimeError("invalid_mount_override_entry: expected object")
        asset_id = str(item.get("asset_id", "") or "").strip()
        host = str(item.get("host", "")).strip()
        container = str(item.get("container", "")).strip()
        mount_type = str(item.get("type", "bind") or "bind").strip().lower()
        raw_mode = str(item.get("mode", "") or "").strip().lower()
        mode = raw_mode or "rw"
        if not container or not container.startswith("/"):
            raise RuntimeError(f"invalid_mount_override_container: '{container or '?'}'")
        if mount_type not in {"bind", "volume"}:
            raise RuntimeError(f"invalid_mount_override_type: '{mount_type}'")
        if asset_id and mount_type != "bind":
            raise RuntimeError(f"invalid_mount_override_asset_type: '{mount_type}'")
        if asset_id:
            from .storage_assets import get_asset

            asset = get_asset(asset_id)
            if not asset:
                raise RuntimeError(f"storage_asset_not_found: '{asset_id}'")
            if not bool((asset or {}).get("published_to_commander")):
                raise RuntimeError(f"storage_asset_not_published: '{asset_id}'")
            asset_path = os.path.abspath(str((asset or {}).get("path", "")).strip())
            if not asset_path:
                raise RuntimeError(f"storage_asset_invalid_path: '{asset_id}'")
            if host and os.path.abspath(host) != asset_path:
                raise RuntimeError(f"storage_asset_host_mismatch: '{asset_id}'")
            host = asset_path
            asset_mode = str((asset or {}).get("default_mode", "ro") or "ro").strip().lower()
            if asset_mode not in {"ro", "rw"}:
                asset_mode = "ro"
            if not raw_mode:
                mode = asset_mode
            if asset_mode == "ro" and mode == "rw":
                raise RuntimeError(f"storage_asset_read_only: '{asset_id}'")
        if not host:
            raise RuntimeError("invalid_mount_override_host_empty")
        if mode not in {"ro", "rw"}:
            raise RuntimeError(f"invalid_mount_override_mode: '{mode}'")
        mounts.append(
            MountDef(
                host=host,
                container=container,
                type=mount_type,
                mode=mode,
                asset_id=asset_id or None,
            )
        )
    return mounts


def normalize_runtime_device_overrides(raw_devices: Optional[List[str]]) -> List[str]:
    devices: List[str] = []
    seen = set()
    for raw in list(raw_devices or []):
        value = str(raw or "").strip()
        if not value:
            continue
        if any(ch.isspace() for ch in value):
            raise RuntimeError(f"invalid_device_override_whitespace: '{value}'")
        host = value.split(":", 1)[0].strip()
        if not host.startswith("/dev/") or ".." in host:
            raise RuntimeError(f"invalid_device_override_host: '{value}'")
        if value in seen:
            continue
        seen.add(value)
        devices.append(value)
    return devices


def run_pre_start_exec(
    bp: Blueprint,
    image_tag: str,
    env_vars: Dict[str, str],
    *,
    get_client: Callable[[], Any],
) -> None:
    spec = getattr(bp, "pre_start_exec", None)
    if not spec:
        return

    command = str(getattr(spec, "command", "") or "").strip()
    if not command:
        return

    volumes: Dict[str, Dict[str, str]] = {}
    for mount in list(getattr(bp, "mounts", []) or []):
        mount_type = str(getattr(mount, "type", "bind") or "bind").strip().lower()
        host_path = mount.host if mount_type == "volume" else os.path.abspath(mount.host)
        volumes[host_path] = {"bind": mount.container, "mode": mount.mode}

    run_kwargs: Dict[str, Any] = {
        "image": image_tag,
        "entrypoint": ["/bin/sh", "-lc"],
        "command": [command],
        "environment": dict(env_vars or {}),
        "volumes": volumes,
        "network": "none",
        "remove": True,
        "detach": False,
        "stdin_open": False,
        "tty": False,
    }

    user = str(getattr(spec, "user", "") or "").strip()
    if user:
        run_kwargs["user"] = user
    if bp.runtime:
        run_kwargs["runtime"] = bp.runtime
    if bp.devices:
        run_kwargs["devices"] = list(bp.devices)
    if bp.cap_add:
        run_kwargs["cap_add"] = list(bp.cap_add)
    if bp.security_opt:
        run_kwargs["security_opt"] = list(bp.security_opt)
    if bp.cap_drop:
        run_kwargs["cap_drop"] = list(bp.cap_drop)
    if bp.privileged:
        run_kwargs["privileged"] = True
    if bp.shm_size:
        run_kwargs["shm_size"] = bp.shm_size
    if bp.ipc_mode:
        run_kwargs["ipc_mode"] = bp.ipc_mode

    try:
        get_client().containers.run(**run_kwargs)
    except ContainerError as exc:
        logs = ""
        try:
            raw = exc.stderr or exc.stdout or b""
            logs = raw.decode("utf-8", errors="replace").strip()
        except Exception:
            logs = str(exc)
        raise RuntimeError(f"pre_start_exec_failed: {logs or exc}") from exc


def slug_scope_token(raw: str) -> str:
    token = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(raw or "").strip())
    token = "-".join(part for part in token.split("-") if part)
    return token[:48] or "item"


def auto_scope_name_for_mounts(bp: Blueprint, roots: List[dict], runtime_mount_overrides: List[MountDef]) -> str:
    asset_ids = sorted(
        {
            slug_scope_token(getattr(m, "asset_id", "") or "")
            for m in list(runtime_mount_overrides or [])
            if str(getattr(m, "asset_id", "") or "").strip()
        }
    )
    digest_src = "|".join(f"{r['path']}:{r['mode']}" for r in roots)
    digest = hashlib.sha1(digest_src.encode("utf-8")).hexdigest()[:12]
    bp_token = slug_scope_token(getattr(bp, "id", "") or "blueprint")
    if asset_ids:
        asset_token = "-".join(asset_ids[:2])
        if len(asset_ids) > 2:
            asset_token = f"{asset_token}-plus{len(asset_ids) - 2}"
        return f"deploy_auto_asset_{bp_token}_{asset_token}_{digest}"
    return f"deploy_auto_{bp_token}_{digest}"


def auto_scope_metadata(bp: Blueprint, runtime_mount_overrides: List[MountDef]) -> dict:
    asset_ids = sorted(
        {
            str(getattr(m, "asset_id", "") or "").strip()
            for m in list(runtime_mount_overrides or [])
            if str(getattr(m, "asset_id", "") or "").strip()
        }
    )
    metadata = {
        "origin": "runtime_auto_scope",
        "blueprint_id": str(getattr(bp, "id", "") or "").strip(),
        "auto_generated": True,
    }
    if asset_ids:
        metadata["origin"] = "storage_asset_auto_scope"
        metadata["asset_ids"] = asset_ids
    return metadata


def runtime_mount_payloads(runtime_mount_overrides: List[MountDef]) -> List[dict]:
    return [mount.model_dump() for mount in list(runtime_mount_overrides or [])]


def runtime_mount_asset_ids(runtime_mount_overrides: List[MountDef]) -> List[str]:
    return sorted(
        {
            str(getattr(m, "asset_id", "") or "").strip()
            for m in list(runtime_mount_overrides or [])
            if str(getattr(m, "asset_id", "") or "").strip()
        }
    )


def compose_runtime_blueprint(
    bp: Blueprint,
    runtime_mount_overrides: List[MountDef],
    runtime_device_overrides: List[str],
    storage_scope_override: str = "",
    force_auto_scope: bool = False,
) -> Blueprint:
    from .storage_scope import get_scope, upsert_scope

    effective = bp.model_copy(deep=True)
    bound_container_paths = {
        str(getattr(mount, "container", "") or "").strip()
        for mount in list(runtime_mount_overrides or [])
        if str(getattr(mount, "type", "bind") or "bind").strip().lower() == "bind"
    }
    bound_host_paths = {
        os.path.abspath(str(getattr(mount, "host", "") or "").strip())
        for mount in list(runtime_mount_overrides or [])
        if str(getattr(mount, "type", "bind") or "bind").strip().lower() == "bind"
        and str(getattr(mount, "host", "") or "").strip()
    }
    if runtime_mount_overrides:
        effective.mounts = list(effective.mounts) + list(runtime_mount_overrides)
    if effective.devices and (bound_container_paths or bound_host_paths):
        filtered_devices: List[str] = []
        for raw in list(effective.devices or []):
            item = str(raw or "").strip()
            if not item:
                continue
            host_path, container_path = (item.split(":", 1) + [""])[:2]
            host_path = os.path.abspath(host_path.strip()) if host_path.strip() else ""
            container_path = (container_path.strip() or host_path)
            if container_path in bound_container_paths or (host_path and host_path in bound_host_paths):
                continue
            filtered_devices.append(item)
        effective.devices = filtered_devices
    if runtime_device_overrides:
        merged_devices = list(effective.devices or []) + list(runtime_device_overrides)
        deduped: List[str] = []
        seen = set()
        for dev in merged_devices:
            item = str(dev or "").strip()
            if not item or item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        effective.devices = deduped
    if storage_scope_override:
        effective.storage_scope = storage_scope_override

    if runtime_mount_overrides and (force_auto_scope or not str(effective.storage_scope or "").strip()):
        roots_by_path: Dict[str, str] = {}
        for mount in list(effective.mounts or []):
            mount_type = str(getattr(mount, "type", "bind") or "bind").strip().lower()
            if mount_type == "volume":
                continue
            host_abs = os.path.abspath(str(getattr(mount, "host", "") or "").strip())
            if not host_abs:
                continue
            mode = str(getattr(mount, "mode", "rw") or "rw").strip().lower()
            prev = roots_by_path.get(host_abs, "ro")
            roots_by_path[host_abs] = "rw" if mode == "rw" or prev == "rw" else "ro"
        roots = [{"path": path, "mode": roots_by_path[path]} for path in sorted(roots_by_path.keys())]
        if roots:
            auto_scope_name = auto_scope_name_for_mounts(bp, roots, runtime_mount_overrides)
            scope_metadata = auto_scope_metadata(bp, runtime_mount_overrides)
            scope = get_scope(auto_scope_name)
            if not scope or dict(scope.get("metadata", {}) or {}) != scope_metadata:
                upsert_scope(
                    name=auto_scope_name,
                    roots=roots,
                    approved_by="system:auto",
                    metadata=scope_metadata,
                )
            effective.storage_scope = auto_scope_name
    return effective
