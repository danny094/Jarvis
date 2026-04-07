"""
Container Commander — Storage Asset Registry
===========================================
Shared catalog for Storage Manager paths that may be published to Container Commander.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional


_LOCK = threading.Lock()
ASSETS_PATH = os.environ.get("COMMANDER_STORAGE_ASSETS_PATH", "/app/data/storage_assets.json")
_ALLOWED_MODES = {"ro", "rw"}
_ALLOWED_USAGE = {"appdata", "media", "backup", "workspace", "games"}
_ALLOWED_SOURCE_KINDS = {"manual", "service_dir", "existing_path", "import"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_payload() -> dict:
    return {"assets": {}}


def _load() -> dict:
    if not os.path.exists(ASSETS_PATH):
        return _default_payload()
    try:
        with open(ASSETS_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict) and isinstance(payload.get("assets"), dict):
            return payload
    except Exception:
        pass
    return _default_payload()


def _save(payload: dict) -> None:
    os.makedirs(os.path.dirname(ASSETS_PATH), exist_ok=True)
    tmp = f"{ASSETS_PATH}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=True, indent=2)
    os.replace(tmp, ASSETS_PATH)


def _normalize_allowed_for(values: List[str]) -> List[str]:
    normalized: List[str] = []
    seen = set()
    for raw in list(values or []):
        item = str(raw or "").strip().lower()
        if not item or item not in _ALLOWED_USAGE or item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized


def _normalize_asset(asset_id: str, data: dict, existing: Optional[dict] = None) -> dict:
    aid = str(asset_id or "").strip()
    if not aid:
        raise ValueError("asset id is required")
    raw_path = str((data or {}).get("path", "")).strip()
    if not raw_path:
        raise ValueError("asset path is required")
    path = os.path.abspath(raw_path)
    label = str((data or {}).get("label", "")).strip() or os.path.basename(path.rstrip("/")) or aid
    default_mode = str((data or {}).get("default_mode", "ro")).strip().lower() or "ro"
    if default_mode not in _ALLOWED_MODES:
        raise ValueError(f"invalid default_mode '{default_mode}'")
    source_kind = str((data or {}).get("source_kind", "manual")).strip().lower() or "manual"
    if source_kind not in _ALLOWED_SOURCE_KINDS:
        raise ValueError(f"invalid source_kind '{source_kind}'")
    allowed_for = _normalize_allowed_for((data or {}).get("allowed_for", []))
    now = _now_iso()
    created_at = (existing or {}).get("created_at") or now
    return {
        "id": aid,
        "label": label,
        "path": path,
        "zone": str((data or {}).get("zone", (existing or {}).get("zone", "managed_services"))).strip() or "managed_services",
        "policy_state": str((data or {}).get("policy_state", (existing or {}).get("policy_state", "managed_rw"))).strip() or "managed_rw",
        "published_to_commander": bool((data or {}).get("published_to_commander", False)),
        "default_mode": default_mode,
        "allowed_for": allowed_for,
        "source_disk_id": str((data or {}).get("source_disk_id", (existing or {}).get("source_disk_id", ""))).strip() or None,
        "source_kind": source_kind,
        "notes": str((data or {}).get("notes", "")).strip(),
        "created_at": created_at,
        "updated_at": now,
    }


def list_assets(*, published_only: bool = False) -> Dict[str, dict]:
    with _LOCK:
        assets = dict(_load().get("assets", {}))
    if not published_only:
        return assets
    return {
        aid: dict(asset)
        for aid, asset in assets.items()
        if bool((asset or {}).get("published_to_commander"))
    }


def get_asset(asset_id: str) -> dict | None:
    assets = list_assets()
    return assets.get(str(asset_id or "").strip())


def upsert_asset(asset_id: str, data: dict) -> dict:
    with _LOCK:
        payload = _load()
        assets = payload.setdefault("assets", {})
        existing = dict(assets.get(str(asset_id or "").strip(), {}) or {})
        asset = _normalize_asset(asset_id, data or {}, existing=existing or None)
        assets[asset["id"]] = asset
        _save(payload)
        return dict(asset)


def delete_asset(asset_id: str) -> bool:
    aid = str(asset_id or "").strip()
    if not aid:
        return False
    with _LOCK:
        payload = _load()
        assets = payload.setdefault("assets", {})
        existed = aid in assets
        if existed:
            assets.pop(aid, None)
            _save(payload)
        return existed
