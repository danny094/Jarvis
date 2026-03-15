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
from typing import Dict, List, Tuple

_LOCK = threading.Lock()
SCOPES_PATH = os.environ.get("COMMANDER_STORAGE_SCOPES_PATH", "/app/data/storage_scopes.json")


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


def upsert_scope(name: str, roots: List[dict], approved_by: str = "user") -> dict:
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

    with _LOCK:
        payload = _load()
        scopes = payload.setdefault("scopes", {})
        scopes[scope_name] = {
            "name": scope_name,
            "roots": normalized_roots,
            "approved_by": str(approved_by or "user"),
            "approved_at": datetime.utcnow().isoformat() + "Z",
        }
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
