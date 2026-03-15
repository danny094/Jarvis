import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from .common import exception_response

router = APIRouter()


def _managed_path_catalog(paths: list[str]) -> list[dict]:
    catalog = []
    seen = set()
    for raw in list(paths or []):
        p = os.path.abspath(str(raw or "").strip())
        if not p or p in seen:
            continue
        seen.add(p)
        base = os.path.basename(p.rstrip("/")) or p
        catalog.append(
            {
                "id": f"mp:{base}:{len(catalog) + 1}",
                "label": base,
                "path": p,
                "source": "storage_broker",
            }
        )
    catalog.sort(key=lambda item: item["path"])
    return catalog


def _extend_catalog_with_scopes(catalog: list[dict]) -> list[dict]:
    try:
        from container_commander.storage_scope import list_scopes

        scopes = list_scopes()
    except Exception:
        return catalog

    seen = {str(item.get("path", "")).strip() for item in list(catalog or [])}
    out = list(catalog or [])
    for scope_name, scope in dict(scopes or {}).items():
        roots = list((scope or {}).get("roots", []) or [])
        for idx, root in enumerate(roots, start=1):
            path = os.path.abspath(str((root or {}).get("path", "")).strip())
            if not path or path in seen:
                continue
            seen.add(path)
            out.append(
                {
                    "id": f"scope:{scope_name}:{idx}",
                    "label": f"{scope_name}",
                    "path": path,
                    "source": "storage_scope",
                }
            )
    out.sort(key=lambda item: item["path"])
    return out


@router.get("/volumes")
async def api_list_volumes(blueprint_id: Optional[str] = None):
    """List all TRION workspace volumes."""
    try:
        from container_commander.volumes import list_volumes

        vols = list_volumes(blueprint_id=blueprint_id)
        return {"volumes": vols, "count": len(vols)}
    except Exception as e:
        return exception_response(e)


@router.get("/volumes/{volume_name}")
async def api_get_volume(volume_name: str):
    """Get details of a specific volume including its snapshots."""
    try:
        from container_commander.volumes import get_volume

        vol = get_volume(volume_name)
        if not vol:
            return exception_response(
                HTTPException(404, f"Volume '{volume_name}' not found"),
                error_code="not_found",
                details={"volume_name": volume_name},
            )
        return vol
    except Exception as e:
        return exception_response(e)


@router.delete("/volumes/{volume_name}")
async def api_remove_volume(volume_name: str, force: bool = False):
    """Remove a workspace volume."""
    try:
        from container_commander.volumes import remove_volume

        removed = remove_volume(volume_name, force=force)
        if not removed:
            return exception_response(
                HTTPException(404, f"Volume '{volume_name}' not found or in use"),
                error_code="not_found",
                details={"removed": False, "volume": volume_name},
            )
        return {"removed": True, "volume": volume_name}
    except Exception as e:
        return exception_response(e)


@router.post("/volumes/cleanup")
async def api_cleanup_volumes(dry_run: bool = True):
    """Find and optionally remove orphaned volumes."""
    try:
        from container_commander.volumes import cleanup_orphaned_volumes

        orphaned = cleanup_orphaned_volumes(dry_run=dry_run)
        return {"orphaned": orphaned, "count": len(orphaned), "dry_run": dry_run}
    except Exception as e:
        return exception_response(e)


@router.get("/snapshots")
async def api_list_snapshots(volume_name: Optional[str] = None):
    """List all snapshots, optionally filtered by volume."""
    try:
        from container_commander.volumes import list_snapshots

        snaps = list_snapshots(volume_name=volume_name)
        return {"snapshots": snaps, "count": len(snaps)}
    except Exception as e:
        return exception_response(e)


@router.post("/snapshots/create")
async def api_create_snapshot(request: Request):
    """Create a tarball snapshot of a volume."""
    try:
        from container_commander.volumes import create_snapshot

        data = await request.json()
        volume_name = data.get("volume_name", "")
        tag = data.get("tag", "")
        if not volume_name:
            return exception_response(
                HTTPException(400, "'volume_name' is required"),
                error_code="bad_request",
                details={"created": False},
            )
        filename = create_snapshot(volume_name, tag=tag or None)
        if not filename:
            return exception_response(
                RuntimeError("Snapshot failed"),
                error_code="snapshot_failed",
                details={"created": False},
            )
        return {"created": True, "filename": filename}
    except Exception as e:
        return exception_response(e)


@router.post("/snapshots/restore")
async def api_restore_snapshot(request: Request):
    """Restore a snapshot into a new or existing volume."""
    try:
        from container_commander.volumes import restore_snapshot

        data = await request.json()
        filename = data.get("filename", "")
        target = data.get("target_volume")
        if not filename:
            return exception_response(
                HTTPException(400, "'filename' is required"),
                error_code="bad_request",
                details={"restored": False},
            )
        vol_name = restore_snapshot(filename, target_volume=target)
        if not vol_name:
            return exception_response(
                RuntimeError("Restore failed"),
                error_code="restore_failed",
                details={"restored": False},
            )
        return {"restored": True, "volume": vol_name}
    except Exception as e:
        return exception_response(e)


@router.delete("/snapshots/{filename}")
async def api_delete_snapshot(filename: str):
    """Delete a snapshot file."""
    try:
        from container_commander.volumes import delete_snapshot

        deleted = delete_snapshot(filename)
        if not deleted:
            return exception_response(
                HTTPException(404, f"Snapshot '{filename}' not found"),
                error_code="not_found",
                details={"deleted": False, "filename": filename},
            )
        return {"deleted": True, "filename": filename}
    except Exception as e:
        return exception_response(e)


@router.get("/networks")
async def api_list_networks():
    """List all TRION-managed Docker networks."""
    try:
        from container_commander.network import list_networks

        nets = list_networks()
        return {"networks": nets, "count": len(nets)}
    except Exception as e:
        return exception_response(e)


@router.get("/networks/{container_id}/info")
async def api_network_info(container_id: str):
    """Get network details for a specific container."""
    try:
        from container_commander.network import get_network_info

        info = get_network_info(container_id)
        if info is None:
            return exception_response(
                HTTPException(404, "Container not found"),
                error_code="not_found",
                details={"container_id": container_id},
            )
        return {"container_id": container_id, "networks": info}
    except Exception as e:
        return exception_response(e)


@router.post("/networks/cleanup")
async def api_cleanup_networks():
    """Remove empty isolated TRION networks."""
    try:
        from container_commander.network import cleanup_networks

        removed = cleanup_networks()
        return {"removed": removed, "count": len(removed)}
    except Exception as e:
        return exception_response(e)


@router.get("/storage/scopes")
async def api_list_storage_scopes():
    """List all approved storage scopes."""
    try:
        from container_commander.storage_scope import list_scopes

        scopes = list_scopes()
        return {"scopes": scopes, "count": len(scopes)}
    except Exception as e:
        return exception_response(e)


@router.get("/storage/managed-paths")
async def api_list_storage_managed_paths():
    """
    List Storage-Broker managed paths as a UI-friendly catalog for deploy pickers.
    Returns both raw paths and normalized catalog items.
    """
    try:
        from storage_broker_routes import _mcp_call  # lazy import: optional service

        payload = await _mcp_call("storage_list_managed_paths")
        raw_paths = payload.get("managed_paths", []) if isinstance(payload, dict) else []
        normalized = _managed_path_catalog(raw_paths if isinstance(raw_paths, list) else [])
        normalized = _extend_catalog_with_scopes(normalized)
        return {"managed_paths": [item["path"] for item in normalized], "catalog": normalized, "count": len(normalized)}
    except Exception as e:
        return exception_response(e)


@router.get("/storage/scopes/{scope_name}")
async def api_get_storage_scope(scope_name: str):
    """Get one storage scope."""
    try:
        from container_commander.storage_scope import get_scope

        scope = get_scope(scope_name)
        if not scope:
            return exception_response(
                HTTPException(404, f"Storage scope '{scope_name}' not found"),
                error_code="not_found",
                details={"scope_name": scope_name},
            )
        return {"scope": scope}
    except Exception as e:
        return exception_response(e)


@router.post("/storage/scopes")
async def api_upsert_storage_scope(request: Request):
    """Create or update an approved storage scope."""
    try:
        from container_commander.storage_scope import upsert_scope

        data = await request.json()
        name = str(data.get("name", "")).strip()
        roots = data.get("roots", [])
        approved_by = str(data.get("approved_by", "user")).strip() or "user"
        scope = upsert_scope(name=name, roots=roots, approved_by=approved_by)
        return {"stored": True, "scope": scope}
    except Exception as e:
        return exception_response(e)


@router.delete("/storage/scopes/{scope_name}")
async def api_delete_storage_scope(scope_name: str):
    """Delete a storage scope."""
    try:
        from container_commander.storage_scope import delete_scope

        deleted = delete_scope(scope_name)
        if not deleted:
            return exception_response(
                HTTPException(404, f"Storage scope '{scope_name}' not found"),
                error_code="not_found",
                details={"scope_name": scope_name, "deleted": False},
            )
        return {"deleted": True, "scope_name": scope_name}
    except Exception as e:
        return exception_response(e)
