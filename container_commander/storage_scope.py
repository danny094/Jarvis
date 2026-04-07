"""
Container Commander — Storage Scope Manager
==========================================
Human-approved host path scopes for bind mounts.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

_LOCK = threading.Lock()
SCOPES_PATH = os.environ.get("COMMANDER_STORAGE_SCOPES_PATH", "/app/data/storage_scopes.json")
_RUNTIME_BIND_PREFIXES = (
    "/dev",
    "/proc",
    "/sys",
    "/run/udev",
    "/run/dbus",
    "/run/user",
    "/var/run/dbus",
    "/tmp/.X11-unix",
)


def _default_payload() -> dict:
    return {"scopes": {}}


def _load() -> dict:
    if not os.path.exists(SCOPES_PATH):
        return _default_payload()
    try:
        with open(SCOPES_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict) and isinstance(payload.get("scopes"), dict):
            return payload
    except Exception:
        pass
    return _default_payload()


def _save(payload: dict) -> None:
    os.makedirs(os.path.dirname(SCOPES_PATH), exist_ok=True)
    tmp = f"{SCOPES_PATH}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=True, indent=2)
    os.replace(tmp, SCOPES_PATH)


def list_scopes() -> Dict[str, dict]:
    with _LOCK:
        return dict(_load().get("scopes", {}))


def get_scope(name: str) -> dict | None:
    scopes = list_scopes()
    return scopes.get(str(name or "").strip())


def upsert_scope(name: str, roots: List[dict], approved_by: str = "user", metadata: dict | None = None) -> dict:
    scope_name = str(name or "").strip()
    if not scope_name:
        raise ValueError("scope name is required")
    normalized_roots: List[dict] = []
    for root in list(roots or []):
        path = os.path.abspath(str((root or {}).get("path", "")).strip())
        mode = str((root or {}).get("mode", "rw")).strip().lower() or "rw"
        if mode not in {"ro", "rw"}:
            raise ValueError(f"invalid scope mode '{mode}' for path {path}")
        if not path:
            raise ValueError("scope root path is required")
        normalized_roots.append({"path": path, "mode": mode})
    if not normalized_roots:
        raise ValueError("at least one scope root is required")
    normalized_metadata: Dict[str, Any] = {}
    if isinstance(metadata, dict):
        for key, value in metadata.items():
            meta_key = str(key or "").strip()
            if not meta_key:
                continue
            normalized_metadata[meta_key] = value

    with _LOCK:
        payload = _load()
        scopes = payload.setdefault("scopes", {})
        existing = dict(scopes.get(scope_name, {}) or {})
        scopes[scope_name] = {
            "name": scope_name,
            "roots": normalized_roots,
            "approved_by": str(approved_by or "user"),
            "approved_at": datetime.utcnow().isoformat() + "Z",
            "metadata": normalized_metadata,
        }
        created_at = str(existing.get("created_at", "")).strip()
        scopes[scope_name]["created_at"] = created_at or scopes[scope_name]["approved_at"]
        _save(payload)
        return dict(scopes[scope_name])


def delete_scope(name: str) -> bool:
    scope_name = str(name or "").strip()
    if not scope_name:
        return False
    with _LOCK:
        payload = _load()
        scopes = payload.setdefault("scopes", {})
        existed = scope_name in scopes
        if existed:
            scopes.pop(scope_name, None)
            _save(payload)
        return existed


def _is_within(path: str, root: str) -> bool:
    try:
        p = os.path.abspath(path)
        r = os.path.abspath(root)
        return os.path.commonpath([p, r]) == r
    except Exception:
        return False


def _runtime_bind_prefix(path: str) -> Optional[str]:
    normalized = os.path.abspath(str(path or "").strip())
    if not normalized.startswith("/"):
        return None
    for prefix in _RUNTIME_BIND_PREFIXES:
        candidate = os.path.abspath(prefix)
        if normalized == candidate or normalized.startswith(f"{candidate}/"):
            return candidate
    return None


def _is_runtime_system_bind(mount: Any) -> bool:
    """
    Storage scopes govern persistent host data, not transient runtime interfaces.

    Allow bind mounts for system/runtime namespaces only when they stay in the
    same namespace and path inside the container. This keeps the exception narrow
    while allowing dynamic hardware/runtime surfaces like /dev/input and
    /run/udev/data to bypass storage-scope checks.
    """

    mount_type = str(getattr(mount, "type", "bind") or "bind").strip().lower()
    if mount_type != "bind":
        return False
    if str(getattr(mount, "asset_id", "") or "").strip():
        return False

    host_raw = str(getattr(mount, "host", "") or "").strip()
    container_raw = str(getattr(mount, "container", "") or "").strip()
    if not host_raw or not container_raw:
        return False
    if not host_raw.startswith("/") or not container_raw.startswith("/"):
        return False

    host_abs = os.path.abspath(host_raw)
    container_abs = os.path.abspath(container_raw)
    host_prefix = _runtime_bind_prefix(host_abs)
    if not host_prefix:
        return False
    return container_abs == host_abs


def validate_blueprint_mounts(bp) -> Tuple[bool, str]:
    """
    Validate bind-mount host paths against scope policy.
    - If bp.storage_scope is set: every bind mount must be inside one of that scope's roots.
    - If empty: only project-local paths and /tmp are allowed.
    """
    mounts = list(getattr(bp, "mounts", []) or [])
    if not mounts:
        return True, "ok"

    scope_name = str(getattr(bp, "storage_scope", "") or "").strip()
    allowed_roots: List[dict]
    if scope_name:
        scope = get_scope(scope_name)
        if not scope:
            return False, f"storage_scope_missing: '{scope_name}'"
        allowed_roots = list(scope.get("roots", []) or [])
        if not allowed_roots:
            return False, f"storage_scope_empty: '{scope_name}'"
    else:
        allowed_roots = [
            {"path": os.path.abspath(os.getcwd()), "mode": "rw"},
            {"path": "/tmp", "mode": "rw"},
        ]

    for mount in mounts:
        mount_type = str(getattr(mount, "type", "bind") or "bind").strip().lower()
        if mount_type == "volume":
            continue
        if _is_runtime_system_bind(mount):
            continue
        host_raw = str(getattr(mount, "host", "") or "").strip()
        if not host_raw:
            return False, "invalid_mount_host_empty"
        host_abs = os.path.abspath(host_raw)
        mount_mode = str(getattr(mount, "mode", "rw") or "rw").strip().lower()
        matched = False
        for root in allowed_roots:
            root_path = os.path.abspath(str((root or {}).get("path", "")).strip())
            root_mode = str((root or {}).get("mode", "rw")).strip().lower()
            if not root_path:
                continue
            if _is_within(host_abs, root_path):
                if root_mode == "ro" and mount_mode == "rw":
                    return (
                        False,
                        f"storage_scope_mode_violation: mount '{host_abs}' wants rw but scope root '{root_path}' is ro",
                    )
                matched = True
                break
        if not matched:
            if scope_name:
                return (
                    False,
                    f"storage_scope_violation: mount '{host_abs}' is outside scope '{scope_name}'",
                )
            return (
                False,
                f"storage_scope_required: mount '{host_abs}' needs an approved storage_scope",
            )
    return True, "ok"
