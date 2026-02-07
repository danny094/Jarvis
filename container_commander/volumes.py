"""
Container Commander — Volume & Snapshot Manager
═══════════════════════════════════════════════════
Named Volumes for workspace persistence + Tarball snapshots.

Volume Naming: trion_ws_{blueprint_id}_{timestamp}
Snapshot Dir:  /app/data/snapshots/ (configurable via SNAPSHOT_DIR)

Lifecycle:
  1. start_container → creates Named Volume → mounts at /workspace
  2. Container runs → writes to /workspace
  3. stop_container → Volume persists (data survives restart)
  4. snapshot_create → tar.gz of volume contents with timestamp
  5. resume_container → re-mount existing volume
  6. snapshot_restore → extract tarball into new volume
  7. volume_cleanup → remove orphaned volumes
"""

import os
import io
import tarfile
import logging
from datetime import datetime
from typing import Optional, List, Dict

import docker
from docker.errors import NotFound, APIError

logger = logging.getLogger(__name__)

TRION_LABEL = "trion.managed"
SNAPSHOT_DIR = os.environ.get("SNAPSHOT_DIR", "/app/data/snapshots")


def _get_client():
    from .engine import get_client
    return get_client()


# ── Volume CRUD ───────────────────────────────────────────

def create_volume(blueprint_id: str, session_id: Optional[str] = None) -> str:
    """Create a named volume for a blueprint workspace."""
    client = _get_client()
    ts = session_id or str(int(datetime.utcnow().timestamp()))
    name = f"trion_ws_{blueprint_id}_{ts}"

    client.volumes.create(
        name=name,
        driver="local",
        labels={
            TRION_LABEL: "true",
            "trion.blueprint": blueprint_id,
            "trion.created": datetime.utcnow().isoformat(),
        }
    )
    logger.info(f"[Volumes] Created: {name}")
    return name


def list_volumes(blueprint_id: Optional[str] = None) -> List[Dict]:
    """List all TRION workspace volumes."""
    client = _get_client()
    try:
        vols = client.volumes.list(filters={"label": TRION_LABEL})
        result = []
        for v in vols:
            bp = v.attrs.get("Labels", {}).get("trion.blueprint", "")
            if blueprint_id and bp != blueprint_id:
                continue

            # Get size via docker system df (approximate)
            created = v.attrs.get("Labels", {}).get("trion.created", "")
            result.append({
                "name": v.name,
                "blueprint_id": bp,
                "created_at": created or v.attrs.get("CreatedAt", ""),
                "driver": v.attrs.get("Driver", "local"),
                "mountpoint": v.attrs.get("Mountpoint", ""),
            })
        return sorted(result, key=lambda x: x["created_at"], reverse=True)
    except Exception as e:
        logger.error(f"[Volumes] List failed: {e}")
        return []


def get_volume(volume_name: str) -> Optional[Dict]:
    """Get details of a specific volume."""
    client = _get_client()
    try:
        v = client.volumes.get(volume_name)
        labels = v.attrs.get("Labels", {})
        return {
            "name": v.name,
            "blueprint_id": labels.get("trion.blueprint", ""),
            "created_at": labels.get("trion.created", v.attrs.get("CreatedAt", "")),
            "driver": v.attrs.get("Driver", "local"),
            "mountpoint": v.attrs.get("Mountpoint", ""),
            "snapshots": list_snapshots(volume_name),
        }
    except NotFound:
        return None
    except Exception as e:
        logger.error(f"[Volumes] Get '{volume_name}' failed: {e}")
        return None


def remove_volume(volume_name: str, force: bool = False) -> bool:
    """Remove a volume. Fails if a container is using it (unless force=True)."""
    client = _get_client()
    try:
        v = client.volumes.get(volume_name)
        v.remove(force=force)
        logger.info(f"[Volumes] Removed: {volume_name}")
        return True
    except NotFound:
        return False
    except APIError as e:
        if "volume is in use" in str(e).lower():
            logger.warning(f"[Volumes] Cannot remove {volume_name}: in use by a container")
            if force:
                v.remove(force=True)
                return True
        logger.error(f"[Volumes] Remove '{volume_name}' failed: {e}")
        return False


def find_latest_volume(blueprint_id: str) -> Optional[str]:
    """Find the most recent volume for a blueprint (for resume)."""
    vols = list_volumes(blueprint_id=blueprint_id)
    if vols:
        return vols[0]["name"]  # Already sorted by created_at DESC
    return None


def cleanup_orphaned_volumes(dry_run: bool = True) -> List[str]:
    """
    Find and optionally remove volumes not attached to any container.
    Returns list of orphaned volume names.
    """
    client = _get_client()
    orphaned = []
    try:
        # Get all running container volume names
        active_volumes = set()
        for c in client.containers.list(all=True):
            for m in c.attrs.get("Mounts", []):
                if m.get("Name"):
                    active_volumes.add(m["Name"])

        # Check TRION volumes
        for v in client.volumes.list(filters={"label": TRION_LABEL}):
            if v.name not in active_volumes:
                orphaned.append(v.name)
                if not dry_run:
                    v.remove()
                    logger.info(f"[Volumes] Cleaned orphan: {v.name}")

    except Exception as e:
        logger.error(f"[Volumes] Cleanup failed: {e}")

    return orphaned


# ── Snapshot (Tarball) ────────────────────────────────────

def create_snapshot(volume_name: str, tag: Optional[str] = None) -> Optional[str]:
    """
    Create a tarball snapshot of a volume's contents.

    Uses a temporary alpine container to read the volume and stream
    a tar archive back. Saves to SNAPSHOT_DIR.

    Returns: snapshot filename or None on failure.
    """
    client = _get_client()

    # Verify volume exists
    try:
        client.volumes.get(volume_name)
    except NotFound:
        logger.error(f"[Snapshot] Volume '{volume_name}' not found")
        return None

    # Build filename
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    tag_part = f"_{tag}" if tag else ""
    filename = f"{volume_name}{tag_part}_{ts}.tar.gz"
    filepath = os.path.join(SNAPSHOT_DIR, filename)
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)

    try:
        # Spin up a temporary container to tar the volume
        container = client.containers.run(
            "alpine:latest",
            command="sh -c 'mkdir -p /backup && tar czf /backup/snapshot.tar.gz -C /workspace .'",
            volumes={
                volume_name: {"bind": "/workspace", "mode": "ro"},
            },
            detach=True,
            remove=False,
            labels={TRION_LABEL: "true", "trion.temp": "snapshot"},
        )

        # Wait for completion
        result = container.wait(timeout=120)
        exit_code = result.get("StatusCode", -1)

        if exit_code != 0:
            logs = container.logs().decode("utf-8", errors="replace")
            logger.error(f"[Snapshot] Tar failed (exit {exit_code}): {logs}")
            container.remove(force=True)
            return None

        # Extract the tar from the container
        bits, stat = container.get_archive("/backup/snapshot.tar.gz")
        
        # The archive from get_archive is a tar containing our tar.gz
        # We need to extract the inner file
        raw = b"".join(bits)
        outer_tar = tarfile.open(fileobj=io.BytesIO(raw), mode="r")
        inner_member = outer_tar.getmembers()[0]
        inner_file = outer_tar.extractfile(inner_member)
        
        with open(filepath, "wb") as f:
            f.write(inner_file.read())

        container.remove(force=True)

        size_mb = os.path.getsize(filepath) / (1024 * 1024)
        logger.info(f"[Snapshot] Created: {filename} ({size_mb:.1f} MB)")

        from .blueprint_store import log_action
        log_action("", volume_name, "snapshot_create", filename)

        return filename

    except Exception as e:
        logger.error(f"[Snapshot] Create failed: {e}")
        return None


def restore_snapshot(snapshot_filename: str, target_volume: Optional[str] = None) -> Optional[str]:
    """
    Restore a snapshot tarball into a (new or existing) volume.

    If target_volume is None, creates a new volume derived from the filename.
    Returns: volume name or None on failure.
    """
    client = _get_client()
    filepath = os.path.join(SNAPSHOT_DIR, snapshot_filename)

    if not os.path.exists(filepath):
        logger.error(f"[Snapshot] File not found: {filepath}")
        return None

    # Create or reuse target volume
    if not target_volume:
        # Derive name from snapshot filename: trion_ws_python-sandbox_1234_20260206_120000.tar.gz
        base = snapshot_filename.rsplit("_", 2)[0] if "_" in snapshot_filename else "restored"
        ts = str(int(datetime.utcnow().timestamp()))
        target_volume = f"{base}_restored_{ts}"

    try:
        client.volumes.get(target_volume)
    except NotFound:
        client.volumes.create(
            name=target_volume,
            driver="local",
            labels={
                TRION_LABEL: "true",
                "trion.restored_from": snapshot_filename,
                "trion.created": datetime.utcnow().isoformat(),
            }
        )

    try:
        # Create temp container, copy tar in, extract
        container = client.containers.create(
            "alpine:latest",
            command="tar xzf /backup/snapshot.tar.gz -C /workspace",
            volumes={
                target_volume: {"bind": "/workspace", "mode": "rw"},
            },
            labels={TRION_LABEL: "true", "trion.temp": "restore"},
        )

        # Upload the tarball into the container
        with open(filepath, "rb") as f:
            tar_data = f.read()

        # Wrap in a tar for put_archive
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w") as tar:
            info = tarfile.TarInfo(name="snapshot.tar.gz")
            info.size = len(tar_data)
            tar.addfile(info, io.BytesIO(tar_data))
        tar_stream.seek(0)

        container.put_archive("/backup", tar_stream.read())
        container.start()
        result = container.wait(timeout=120)
        container.remove(force=True)

        if result.get("StatusCode", -1) != 0:
            logger.error(f"[Snapshot] Restore extraction failed")
            return None

        logger.info(f"[Snapshot] Restored '{snapshot_filename}' → volume '{target_volume}'")

        from .blueprint_store import log_action
        log_action("", target_volume, "snapshot_restore", snapshot_filename)

        return target_volume

    except Exception as e:
        logger.error(f"[Snapshot] Restore failed: {e}")
        return None


def list_snapshots(volume_name: Optional[str] = None) -> List[Dict]:
    """List all snapshots, optionally filtered by volume name prefix."""
    if not os.path.exists(SNAPSHOT_DIR):
        return []

    result = []
    for f in sorted(os.listdir(SNAPSHOT_DIR), reverse=True):
        if not f.endswith(".tar.gz"):
            continue
        if volume_name and not f.startswith(volume_name):
            continue

        filepath = os.path.join(SNAPSHOT_DIR, f)
        stat = os.stat(filepath)
        result.append({
            "filename": f,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })

    return result


def delete_snapshot(filename: str) -> bool:
    """Delete a snapshot file."""
    filepath = os.path.join(SNAPSHOT_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
        logger.info(f"[Snapshot] Deleted: {filename}")
        return True
    return False
