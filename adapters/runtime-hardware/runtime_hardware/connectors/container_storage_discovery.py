from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from runtime_hardware.models import HardwareResource
from utils.service_endpoint_resolver import candidate_service_endpoints


_BROKER_ASSET_SOURCE_KINDS = {"service_dir", "existing_path", "import"}
_BROKER_OUTSIDE_MANAGED_PATH_KINDS = {"existing_path", "import"}


def _slug_token(raw: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", str(raw or "").strip().lower()).strip("-")
    return value[:64] or "storage"


def _default_mount_ref_container_path(asset_id: str, asset: Dict[str, Any]) -> str:
    explicit = str((asset or {}).get("default_container_path") or "").strip()
    if explicit.startswith("/"):
        return explicit
    return f"/storage/{_slug_token(asset_id)}"


def _admin_api_base_urls() -> List[str]:
    return candidate_service_endpoints(
        configured=str(os.environ.get("ADMIN_API_URL", "")).strip(),
        port=8200,
        scheme="http",
        service_name=os.environ.get("ADMIN_API_SERVICE_NAME", "jarvis-admin-api").strip(),
        prefer_container_service=True,
        include_gateway=True,
        include_host_docker=True,
        include_loopback=True,
        include_localhost=True,
    )


def _fetch_admin_api_json(path: str, params: Dict[str, Any] | None = None, timeout: float = 8.0) -> Dict[str, Any]:
    query = urllib_parse.urlencode(
        {
            str(key): str(value)
            for key, value in dict(params or {}).items()
            if str(key or "").strip()
        }
    )
    normalized_path = str(path or "").strip()
    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"
    suffix = normalized_path if not query else f"{normalized_path}?{query}"

    last_error: Exception | None = None
    for base_url in _admin_api_base_urls():
        url = f"{base_url}{suffix}"
        try:
            with urllib_request.urlopen(url, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            return dict(payload or {}) if isinstance(payload, dict) else {}
        except Exception as exc:
            last_error = exc
            continue
    raise RuntimeError(f"admin_api_unreachable:{last_error}" if last_error else "admin_api_unreachable")


def _normalize_broker_risk_level(raw: str) -> str:
    value = str(raw or "").strip().lower()
    if value == "critical":
        return "high"
    if value == "safe":
        return "low"
    return "medium"


def _storage_broker_disk_index() -> Dict[str, Dict[str, Any]]:
    try:
        payload = _fetch_admin_api_json("/api/storage-broker/disks")
    except Exception:
        return {}

    index: Dict[str, Dict[str, Any]] = {}
    for raw in list(payload.get("disks") or []):
        disk = dict(raw or {})
        disk_id = str(disk.get("id") or "").strip()
        device = str(disk.get("device") or "").strip()
        disk_type = str(disk.get("disk_type") or "").strip().lower()
        if not disk_id or not device.startswith("/dev/") or disk_type not in {"disk", "part"}:
            continue
        index[disk_id] = {
            "disk_id": disk_id,
            "device": device,
            "label": str(disk.get("label") or disk_id).strip() or disk_id,
            "disk_type": disk_type,
            "filesystem": str(disk.get("filesystem") or ""),
            "policy_state": str(disk.get("policy_state") or "").strip() or "blocked",
            "zone": str(disk.get("zone") or "").strip() or "unzoned",
            "risk_level": str(disk.get("risk_level") or ""),
            "managed": bool(disk.get("managed")),
            "read_only": bool(disk.get("read_only")),
            "allowed_operations": list(disk.get("allowed_operations") or []),
            "mountpoint": str(disk.get("mountpoint") or ""),
            "mountpoints": list(disk.get("mountpoints") or []),
            "notes": list(disk.get("notes") or []),
            "is_removable": bool(disk.get("is_removable")),
            "size_bytes": int(disk.get("size_bytes") or 0),
            "available_bytes": int(disk.get("available_bytes") or 0),
            "is_external": bool(disk.get("is_external")),
            "is_system": bool(disk.get("is_system")),
        }
    return index


def _storage_broker_managed_paths() -> List[str]:
    try:
        payload = _fetch_admin_api_json("/api/storage-broker/managed-paths")
    except Exception:
        return []

    values = payload.get("managed_paths") if isinstance(payload, dict) else []
    result: List[str] = []
    seen: set[str] = set()
    for raw in list(values or []):
        path = str(raw or "").strip()
        if not path.startswith("/") or path in seen:
            continue
        seen.add(path)
        result.append(path.rstrip("/") or "/")
    return result


def _path_within_managed_paths(path: str, managed_paths: List[str]) -> bool:
    candidate = str(path or "").strip().rstrip("/") or "/"
    if not managed_paths:
        return True
    for base in managed_paths:
        normalized = str(base or "").strip().rstrip("/") or "/"
        if candidate == normalized or candidate.startswith(f"{normalized}/"):
            return True
    return False


def _is_storage_broker_asset(asset: Dict[str, Any]) -> bool:
    source_kind = str((asset or {}).get("source_kind") or "").strip().lower()
    return source_kind in _BROKER_ASSET_SOURCE_KINDS


def _allow_broker_asset_outside_managed_paths(asset: Dict[str, Any]) -> bool:
    source_kind = str((asset or {}).get("source_kind") or "").strip().lower()
    return source_kind in _BROKER_OUTSIDE_MANAGED_PATH_KINDS


def discover_storage_broker_block_resources() -> List[HardwareResource]:
    disk_index = _storage_broker_disk_index()
    resources: List[HardwareResource] = []
    for disk in disk_index.values():
        device = str(disk.get("device") or "").strip()
        disk_id = str(disk.get("disk_id") or "").strip()
        disk_type = str(disk.get("disk_type") or "").strip().lower()
        policy_state = str(disk.get("policy_state") or "").strip() or "blocked"
        zone = str(disk.get("zone") or "").strip() or "unzoned"
        capabilities = ["block", f"zone:{zone}", f"policy:{policy_state}"]
        if bool(disk.get("is_removable")):
            capabilities.append("removable")
        else:
            capabilities.append("fixed")
        if bool(disk.get("managed")):
            capabilities.append("managed")
        if bool(disk.get("read_only")):
            capabilities.append("read_only")
        resources.append(
            HardwareResource(
                id=f"container::block_device_ref::{device}",
                kind="block_device_ref",
                source_connector="container",
                label=str(disk.get("label") or disk_id).strip() or disk_id,
                host_path=device,
                capabilities=capabilities,
                risk_level=_normalize_broker_risk_level(str(disk.get("risk_level") or "")),
                metadata={
                    "storage_source": "storage_broker",
                    "disk_id": disk_id,
                    "disk_type": disk_type,
                    "filesystem": str(disk.get("filesystem") or ""),
                    "mountpoint": str(disk.get("mountpoint") or ""),
                    "mountpoints": list(disk.get("mountpoints") or []),
                    "policy_state": policy_state,
                    "zone": zone,
                    "managed": bool(disk.get("managed")),
                    "is_system": bool(disk.get("is_system")),
                    "is_external": bool(disk.get("is_external")),
                    "allowed_operations": list(disk.get("allowed_operations") or []),
                    "notes": list(disk.get("notes") or []),
                    "size_bytes": int(disk.get("size_bytes") or 0),
                    "available_bytes": int(disk.get("available_bytes") or 0),
                },
            )
        )
    return resources


def discover_storage_asset_mount_refs() -> List[HardwareResource]:
    try:
        payload = _fetch_admin_api_json("/api/commander/storage/assets", {"published_only": "true"})
    except Exception:
        return []

    resources: List[HardwareResource] = []
    assets = dict(payload.get("assets") or {})
    disk_index = _storage_broker_disk_index()
    managed_paths = _storage_broker_managed_paths()
    for asset_id, raw in assets.items():
        asset = dict(raw or {})
        path = str(asset.get("path") or "").strip()
        normalized_asset_id = str(asset.get("id") or asset_id).strip()
        if not normalized_asset_id or not path.startswith("/"):
            continue
        broker_managed = _is_storage_broker_asset(asset)
        if not _path_within_managed_paths(path, managed_paths) and not _allow_broker_asset_outside_managed_paths(asset):
            continue
        source_disk_id = str(asset.get("source_disk_id") or "").strip()
        source_disk = dict(disk_index.get(source_disk_id) or {})
        default_mode = str(asset.get("default_mode") or "ro").strip().lower() or "ro"
        zone = str(asset.get("zone") or "").strip() or "managed_services"
        policy_state = str(asset.get("policy_state") or "").strip() or "managed_rw"
        default_container_path = _default_mount_ref_container_path(normalized_asset_id, asset)
        capabilities = ["mount_ref", f"mode:{default_mode}", f"zone:{zone}", f"policy:{policy_state}"]
        if bool(asset.get("published_to_commander")):
            capabilities.append("published")
        if broker_managed:
            capabilities.append("storage_broker")
        for usage in list(asset.get("allowed_for") or []):
            item = str(usage or "").strip().lower()
            if item:
                capabilities.append(f"usage:{item}")
        resources.append(
            HardwareResource(
                id=f"container::mount_ref::{normalized_asset_id}",
                kind="mount_ref",
                source_connector="container",
                label=str(asset.get("label") or normalized_asset_id).strip() or normalized_asset_id,
                host_path=path,
                capabilities=capabilities,
                risk_level="medium" if default_mode == "rw" else "low",
                metadata={
                    "storage_source": "storage_asset",
                    "asset_id": normalized_asset_id,
                    "path": path,
                    "zone": zone,
                    "policy_state": policy_state,
                    "default_mode": default_mode,
                    "default_container_path": default_container_path,
                    "allowed_for": list(asset.get("allowed_for") or []),
                    "source_disk_id": source_disk_id,
                    "source_disk_label": str(source_disk.get("label") or ""),
                    "source_disk_device": str(source_disk.get("device") or ""),
                    "source_kind": str(asset.get("source_kind") or ""),
                    "broker_managed": broker_managed,
                    "published_to_commander": bool(asset.get("published_to_commander")),
                    "filesystem": str(source_disk.get("filesystem") or ""),
                    "size_bytes": int(source_disk.get("size_bytes") or 0),
                    "available_bytes": int(source_disk.get("available_bytes") or 0),
                    "is_external": bool(source_disk.get("is_external")),
                    "is_system": bool(source_disk.get("is_system")),
                },
            )
        )
    return resources
