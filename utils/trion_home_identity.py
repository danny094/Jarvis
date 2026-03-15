"""
Shared TRION home identity helpers.

Single source of truth for:
- home_identity.json bootstrap/loading
- deterministic health/status evaluation
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

IDENTITY_PATH_ENV = "TRION_HOME_IDENTITY_PATH"
DEFAULT_IDENTITY_PATH = "/trion-home/config/home_identity.json"


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def default_home_identity() -> Dict[str, Any]:
    return {
        "container_id": "trion-home",
        "role": "primary_memory",
        "home_path": "/trion-home",
        "workspace_path": "/trion-home/workspace",
        "capabilities": {
            "auto_remember": True,
            "importance_threshold": 0.72,
            "categories": ["user_preference", "project_fact", "todo"],
            "forced_keywords": ["merk dir", "vergiss nicht", "wichtig", "merke"],
            "max_note_size_kb": 10,
            "redact_patterns": ["token", "secret", "password", "api_key", "Bearer"],
        },
        "allowed_actions": [
            "read_notes",
            "write_notes",
            "summarize_notes",
            "manage_index",
        ],
        "identity_check_on_start": True,
        "version": "1.0",
    }


def _identity_path(identity_path: Optional[str] = None) -> Path:
    raw = (
        str(identity_path).strip()
        if identity_path is not None
        else str(os.environ.get(IDENTITY_PATH_ENV, "")).strip()
    )
    return Path(raw or DEFAULT_IDENTITY_PATH)


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in (override or {}).items():
        if (
            isinstance(value, dict)
            and isinstance(merged.get(key), dict)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_home_identity(
    *,
    identity_path: Optional[str] = None,
    create_if_missing: bool = True,
) -> Dict[str, Any]:
    """
    Load home identity from disk.
    If create_if_missing=True: bootstrap default file when absent.
    """
    path = _identity_path(identity_path)
    base = default_home_identity()

    if not path.exists():
        if not create_if_missing:
            return base
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(base, ensure_ascii=True, indent=2), encoding="utf-8")
        return base

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return base
        return _deep_merge(base, raw)
    except Exception:
        # Fail-open with deterministic default so runtime can continue safely.
        return base


def evaluate_home_status(
    containers: Iterable[Any],
    *,
    identity: Optional[Dict[str, Any]] = None,
    identity_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Evaluate Home-Container status from identity + known container list.
    Returns: connected | degraded | offline
    """
    home_identity = identity or load_home_identity(identity_path=identity_path, create_if_missing=True)
    home_blueprint_id = str(home_identity.get("container_id") or "trion-home").strip() or "trion-home"

    known = []
    home_running = []
    for c in containers or []:
        c_id = str(getattr(c, "container_id", "") or "").strip()
        bp_id = str(getattr(c, "blueprint_id", "") or "").strip()
        status_raw = getattr(c, "status", "")
        status = getattr(status_raw, "value", status_raw)
        status = str(status or "").strip() or "unknown"
        row = {
            "container_id": c_id,
            "blueprint_id": bp_id,
            "status": status,
            "name": str(getattr(c, "name", "") or ""),
        }
        known.append(row)
        if bp_id == home_blueprint_id and status == "running":
            home_running.append(row)

    status = "offline"
    error_code = ""
    checks = {
        "identity_loaded": bool(home_identity),
        "home_container_expected": home_blueprint_id,
        "running_home_count": len(home_running),
    }
    if len(home_running) == 1:
        status = "connected"
    elif len(home_running) > 1:
        status = "degraded"
        error_code = "home_container_ambiguous"
    elif any(row["blueprint_id"] == home_blueprint_id for row in known):
        status = "degraded"
        error_code = "home_container_not_running"
    else:
        error_code = "home_container_missing"

    out = {
        "status": status,
        "error_code": error_code,
        "identity_path": str(_identity_path(identity_path)),
        "identity": home_identity,
        "home_container_id": home_running[0]["container_id"] if len(home_running) == 1 else "",
        "known_containers": known,
        "checks": checks,
        "checked_at": _utc_now_iso(),
    }
    return out
