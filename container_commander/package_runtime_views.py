"""
Package runtime views
=====================

Dynamic package-side runtime mounts and environment enrichment that should not
live directly inside the generic engine orchestration path.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
from typing import Any, Dict, List, Tuple

from .models import Blueprint


_BROKER_SOURCE_KINDS = {"service_dir", "existing_path", "import"}


def _slug_token(raw: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", str(raw or "").strip().lower()).strip("-")
    return value[:64] or "storage"


def _list_broker_assets(*, published_only: bool, source_kinds: set[str]) -> List[Dict[str, Any]]:
    from .storage_assets import list_assets

    assets = list_assets(published_only=published_only)
    items: List[Dict[str, Any]] = []
    for _asset_id, raw in sorted(dict(assets or {}).items()):
        asset = dict(raw or {})
        asset_id = str(asset.get("id") or _asset_id).strip()
        path = os.path.abspath(str(asset.get("path") or "").strip())
        source_kind = str(asset.get("source_kind") or "").strip().lower()
        if not asset_id or not path.startswith("/"):
            continue
        if source_kind not in source_kinds:
            continue
        items.append(asset)
    items.sort(key=lambda item: (str(item.get("label") or "").lower(), str(item.get("path") or "").lower()))
    return items


def _filestash_connections_payload(
    *,
    assets: List[Dict[str, Any]],
    container_root: str,
    label_prefix: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    mount_overrides: List[Dict[str, Any]] = []
    connections: List[Dict[str, Any]] = []
    seen_targets: set[str] = set()
    for asset in assets:
        asset_id = str(asset.get("id") or "").strip()
        if not asset_id:
            continue
        token = _slug_token(asset_id)
        target = posixpath.join(container_root, token)
        if target in seen_targets:
            continue
        seen_targets.add(target)
        mount_overrides.append(
            {
                "asset_id": asset_id,
                "container": target,
                "type": "bind",
                "mode": str(asset.get("default_mode") or "ro").strip().lower() or "ro",
            }
        )
        label = str(asset.get("label") or asset_id).strip() or asset_id
        connections.append(
            {
                "label": f"{label_prefix}{label}",
                "type": "local",
                "path": target,
                "password": "",
                "trion_managed": True,
                "storage_asset_id": asset_id,
                "source_kind": str(asset.get("source_kind") or "").strip(),
            }
        )
    return mount_overrides, connections


def apply_package_runtime_views(
    blueprint_id: str,
    bp: Blueprint,
    manifest: Dict[str, Any] | None,
) -> Tuple[Blueprint, List[Dict[str, Any]]]:
    package_manifest = dict(manifest or {})
    runtime_views = package_manifest.get("runtime_storage_views")
    if not isinstance(runtime_views, dict):
        return bp, []

    broker_assets_cfg = runtime_views.get("broker_assets")
    if not isinstance(broker_assets_cfg, dict) or broker_assets_cfg.get("enabled") is False:
        return bp, []

    container_root = str(broker_assets_cfg.get("container_root") or "/srv/storage-broker").strip()
    if not container_root.startswith("/"):
        container_root = "/srv/storage-broker"
    published_only = bool(broker_assets_cfg.get("published_only", True))
    source_kinds = {
        str(item or "").strip().lower()
        for item in list(broker_assets_cfg.get("source_kinds") or [])
        if str(item or "").strip()
    } or set(_BROKER_SOURCE_KINDS)
    assets = _list_broker_assets(published_only=published_only, source_kinds=source_kinds)
    if not assets:
        return bp, []

    connection_mode = str(broker_assets_cfg.get("connection_mode") or "").strip().lower()
    label_prefix = str(broker_assets_cfg.get("label_prefix") or "TRION / ").strip()
    mount_overrides, filestash_connections = _filestash_connections_payload(
        assets=assets,
        container_root=container_root,
        label_prefix=(f"{label_prefix} " if label_prefix and not label_prefix.endswith(" ") else label_prefix),
    )

    effective = bp.model_copy(deep=True)
    if connection_mode == "filestash_local":
        env = dict(effective.environment or {})
        env["TRION_FILESTASH_CONNECTIONS_JSON"] = json.dumps(filestash_connections, ensure_ascii=True, separators=(",", ":"))
        env["TRION_FILESTASH_STORAGE_ROOT"] = container_root
        effective.environment = env

    return effective, mount_overrides
