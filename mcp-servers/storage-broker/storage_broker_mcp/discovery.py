"""
Storage Broker — Discovery Layer
══════════════════════════════════
Reads disk/mount information from the host via:
  - lsblk -J  (JSON, util-linux)
  - mounts file (defaults to /proc/mounts, overridable via STORAGE_MOUNTS_PATH)
  - df -B1  (available space)

No root required. Container needs /proc and /sys/block mounted read-only.
"""

import json
import os
import subprocess
import logging
from typing import List, Dict, Optional

from .models import (
    DiskInfo, MountInfo,
    IMMUTABLE_BLOCKED_MOUNTS, IMMUTABLE_BLOCKED_PREFIXES,
)

log = logging.getLogger(__name__)

# ── System detection ──────────────────────────────────────

# Mountpoints that identify a disk as a system disk
_SYSTEM_MOUNTS = frozenset({
    "/", "/boot", "/boot/efi", "/usr", "/var",
    "/etc", "/home", "/opt", "/proc", "/sys", "/dev",
})

# lsblk columns we need
_LSBLK_COLS = "NAME,PATH,UUID,LABEL,PARTLABEL,FSTYPE,SIZE,MOUNTPOINTS,RM,RO,TYPE"
_MOUNTS_PATH = os.environ.get("STORAGE_MOUNTS_PATH", "/proc/mounts")
_MOUNTS_FALLBACK_PATHS = [
    p.strip()
    for p in str(
        os.environ.get(
            "STORAGE_MOUNTS_FALLBACKS",
            "/host/proc/1/mounts:/proc/1/mounts:/etc/mtab",
        )
    ).split(":")
    if p.strip()
]


def _run(cmd: List[str], timeout: int = 10) -> Optional[str]:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode == 0:
            return result.stdout
        log.debug(f"[Discovery] {cmd[0]} exited {result.returncode}: {result.stderr[:200]}")
    except Exception as e:
        log.debug(f"[Discovery] {cmd[0]} failed: {e}")
    return None


def _parse_lsblk() -> List[Dict]:
    """Run lsblk -J and return flat list of block device dicts."""
    raw = _run(["lsblk", "-J", "-b", "-o", _LSBLK_COLS])
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []

    # Filesystem types that are never real user storage
    _SKIP_FS = frozenset({"squashfs", "tmpfs", "devtmpfs", "sysfs", "proc",
                           "cgroup", "cgroup2", "pstore", "efivarfs",
                           "bpf", "tracefs", "hugetlbfs", "mqueue", "debugfs",
                           "securityfs", "fusectl", "fuse.snapfuse"})

    flat: List[Dict] = []

    def _walk(devices, parent_type=""):
        for dev in (devices or []):
            t = str(dev.get("type", "") or "")
            fs = str(dev.get("fstype", "") or "")

            # Skip loop devices entirely — snap/squashfs clutter
            if t == "loop":
                continue
            # Skip optical drives and ram disks
            if t in ("rom", "ram"):
                continue
            # Skip virtual/pseudo filesystems
            if fs in _SKIP_FS:
                continue

            # Normalise mountpoints: lsblk returns list or null
            mpts = dev.get("mountpoints") or []
            if isinstance(mpts, str):
                mpts = [mpts] if mpts else []
            mpts = [m for m in mpts if m]

            flat.append({
                "name": dev.get("name", ""),
                "path": dev.get("path", "") or f"/dev/{dev.get('name','')}",
                "uuid": dev.get("uuid", "") or "",
                "label": dev.get("label", "") or dev.get("partlabel", "") or "",
                "partlabel": dev.get("partlabel", "") or "",
                "fstype": fs,
                "size": int(dev.get("size", 0) or 0),
                "mountpoints": mpts,
                "removable": str(dev.get("rm", "0")) in ("1", "true"),
                "ro": str(dev.get("ro", "0")) in ("1", "true"),
                "type": t,
            })
            _walk(dev.get("children", []), t)

    _walk(data.get("blockdevices", []))
    return flat


def _device_symlink_name_map(directory: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    try:
        entries = os.listdir(directory)
    except Exception:
        return result

    for entry in entries:
        link_path = os.path.join(directory, entry)
        try:
            real = os.path.realpath(link_path)
        except Exception:
            continue
        if real.startswith("/dev/") and real not in result:
            result[real] = entry
    return result


def _blkid_info(device: str) -> Dict[str, str]:
    raw = _run(["blkid", "-o", "export", str(device or "").strip()])
    if not raw:
        return {}

    props: Dict[str, str] = {}
    for line in raw.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = str(key or "").strip()
        if key:
            props[key] = str(value or "").strip()
    return props


def _enrich_device_metadata(raw_devs: List[Dict]) -> List[Dict]:
    by_label = _device_symlink_name_map("/dev/disk/by-label")
    by_partlabel = _device_symlink_name_map("/dev/disk/by-partlabel")

    enriched: List[Dict] = []
    for dev in list(raw_devs or []):
        item = dict(dev or {})
        device = str(item.get("path") or "").strip()
        if device.startswith("/dev/"):
            partlabel = str(item.get("partlabel") or "").strip() or by_partlabel.get(device, "")
            label = str(item.get("label") or "").strip() or by_label.get(device, "") or partlabel
            fstype = str(item.get("fstype") or "").strip()
            uuid = str(item.get("uuid") or "").strip()

            if not uuid or not fstype or not label:
                blkid = _blkid_info(device)
                uuid = uuid or str(blkid.get("UUID") or "").strip()
                fstype = fstype or str(blkid.get("TYPE") or "").strip()
                label = label or str(blkid.get("LABEL") or "").strip() or partlabel

            item["partlabel"] = partlabel
            item["label"] = label
            item["fstype"] = fstype
            item["uuid"] = uuid
        enriched.append(item)
    return enriched


def _read_mount_lines(path: str) -> List[str]:
    try:
        with open(path, "r") as f:
            return [line.strip() for line in f if line.strip()]
    except Exception:
        return []


def _looks_like_proc_self_bind(lines: List[str], mount_path: str) -> bool:
    """
    Detect broken bind mounts like:
        proc /host/proc_mounts proc ...
    """
    target = str(mount_path or "").strip()
    if not target:
        return False
    for line in lines[:80]:
        parts = line.split()
        if len(parts) < 3:
            continue
        if parts[0] == "proc" and parts[1] == target and parts[2] == "proc":
            return True
    return False


def _parse_mount_map(lines: List[str]) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        device, mountpoint = parts[0], parts[1]
        if not device.startswith("/dev/"):
            continue
        result.setdefault(device, []).append(mountpoint)
    return result


def _host_mount_map() -> Dict[str, List[str]]:
    """
    Parse STORAGE_MOUNTS_PATH (host /proc/mounts) and return
    {device_path: [mountpoint, ...]} so we can cross-reference
    lsblk output with actual host mountpoints.
    """
    lines = _read_mount_lines(_MOUNTS_PATH)
    if lines and not _looks_like_proc_self_bind(lines, _MOUNTS_PATH):
        return _parse_mount_map(lines)

    # Fallbacks for environments where /proc/mounts bind resolves to proc itself.
    for path in _MOUNTS_FALLBACK_PATHS:
        lines = _read_mount_lines(path)
        if not lines:
            continue
        if _looks_like_proc_self_bind(lines, path):
            continue
        parsed = _parse_mount_map(lines)
        if parsed:
            log.info(f"[Discovery] using mount fallback source: {path}")
            return parsed

    log.warning("[Discovery] no usable mount source found; continuing without host mount mapping")
    return {}


def _df_map() -> Dict[str, int]:
    """Return {mountpoint: available_bytes} via df."""
    raw = _run(["df", "-B1", "--output=target,avail"])
    result: Dict[str, int] = {}
    if not raw:
        return result
    for line in raw.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            try:
                result[parts[0]] = int(parts[1])
            except ValueError:
                pass
    return result


def _live_mount_targets(device: str) -> List[str]:
    """
    Ask findmnt for current live targets of a specific device.
    This helps suppress stale lsblk mountpoints after an unmount.
    """
    dev = str(device or "").strip()
    if not dev:
        return []
    raw = _run(["findmnt", "-rn", "-S", dev, "-o", "TARGET"])
    if not raw:
        return []
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _resolved_mountpoints(dev: Dict, host_mounts: Dict[str, List[str]]) -> List[str]:
    """
    Reconcile lsblk mountpoints with stronger sources.

    Priority:
      1. host /proc mount map when present
      2. live findmnt targets
      3. lsblk mountpoints only when confirmed by one of the above

    This prevents the UI from staying in a stale "mounted" state after a device
    has already been unmounted.
    """
    device = str(dev.get("path") or "").strip()
    lsblk_mpts = dev.get("mountpoints") or []
    if isinstance(lsblk_mpts, str):
        lsblk_mpts = [lsblk_mpts] if lsblk_mpts else []
    lsblk_mpts = [m for m in lsblk_mpts if m]

    host_mpts = [m for m in host_mounts.get(device, []) if m]
    if host_mpts:
        return list(dict.fromkeys(host_mpts))

    live_mpts = _live_mount_targets(device)
    if live_mpts:
        return list(dict.fromkeys(live_mpts))

    return []


# Filesystem types that indicate a system/OS disk partition
_SYSTEM_FS = frozenset({"LVM2_member", "zfs_member"})
# Filesystem types that clearly indicate non-system user data
_DATA_ONLY_FS = frozenset({"ntfs", "exfat"})


def _is_system(mountpoints: List[str]) -> bool:
    for mp in mountpoints:
        if mp in _SYSTEM_MOUNTS:
            return True
        for prefix in ("/proc/", "/sys/", "/dev/"):
            if mp.startswith(prefix):
                return True
    return False


def _build_system_disk_set(raw_devs: List[Dict], host_mounts: Optional[Dict[str, List[str]]] = None) -> set:
    """
    Determine which disk names are system disks via filesystem heuristics.
    A disk is system if it or any of its direct partitions has a system FS
    (e.g. LVM2_member) AND none of its partitions are data-only (ntfs/exfat).

    Returns a set of device names (e.g. {'sda', 'sda1', 'sda2', 'sda3'}).
    """
    # Group partitions by parent disk prefix
    disk_names = {d["name"] for d in raw_devs if d["type"] == "disk"}
    system_disks: set = set()

    host_mounts = host_mounts or {}

    def _merged_mounts(dev: Dict) -> List[str]:
        lsblk_mpts = dev.get("mountpoints") or []
        if isinstance(lsblk_mpts, str):
            lsblk_mpts = [lsblk_mpts] if lsblk_mpts else []
        host_mpts = host_mounts.get(str(dev.get("path") or ""), [])
        return [m for m in list(dict.fromkeys(list(lsblk_mpts) + list(host_mpts))) if m]

    for disk_name in disk_names:
        # Use the lsblk tree structure from raw JSON to find real children,
        # falling back to prefix matching only when no other disk_name is a
        # longer prefix (prevents nvme0n1 absorbing nvme0n10, nvme0n11, etc.)
        other_disks = disk_names - {disk_name}
        children = [
            d for d in raw_devs
            if d["name"] != disk_name
            and d["name"].startswith(disk_name)
            and not any(d["name"].startswith(other) for other in other_disks)
        ]
        child_fs = {c["fstype"] for c in children}

        # If any partition has system mountpoints, treat the whole disk as system.
        child_mounts = [m for c in children for m in _merged_mounts(c)]
        if _is_system(child_mounts):
            system_disks.add(disk_name)
            for c in children:
                system_disks.add(c["name"])
            continue

        # If any child has a system FS indicator → system disk
        if child_fs & _SYSTEM_FS:
            system_disks.add(disk_name)
            for c in children:
                system_disks.add(c["name"])
            continue

        # If disk itself has system FS
        this_fs = next((d["fstype"] for d in raw_devs if d["name"] == disk_name), "")
        if this_fs in _SYSTEM_FS:
            system_disks.add(disk_name)
            for c in children:
                system_disks.add(c["name"])

    return system_disks


def _is_external(dev: Dict) -> bool:
    return bool(dev.get("removable"))


def list_disks() -> List[DiskInfo]:
    """
    Discover all block devices visible to the container.
    Mountpoints are cross-referenced from the host /proc/mounts file
    because lsblk inside the container sees the container namespace.
    Policy fields are left at defaults here — policy.py enriches them.
    """
    df          = _df_map()
    raw_devs    = _enrich_device_metadata(_parse_lsblk())
    host_mounts = _host_mount_map()
    system_set  = _build_system_disk_set(raw_devs, host_mounts)  # heuristic system detection
    disks: List[DiskInfo] = []

    for dev in raw_devs:
        # Reconcile mount state against stronger live sources so lsblk cannot keep
        # a partition artificially "mounted" in the UI after an unmount.
        mpts = _resolved_mountpoints(dev, host_mounts)

        primary_mp = mpts[0] if mpts else ""
        avail      = df.get(primary_mp, 0) if primary_mp else 0
        # System = detected by mountpoints OR by filesystem heuristic
        system   = _is_system(mpts) or dev["name"] in system_set
        external = _is_external(dev)

        notes: List[str] = []
        if system:
            notes.append("system disk")
        if external:
            notes.append("removable/external")
        if dev["ro"]:
            notes.append("hardware read-only")

        disks.append(DiskInfo(
            id=dev["name"],
            device=dev["path"],
            uuid=dev["uuid"],
            label=dev["label"],
            partlabel=dev.get("partlabel", ""),
            filesystem=dev["fstype"],
            size_bytes=dev["size"],
            available_bytes=avail,
            mountpoint=primary_mp,
            mountpoints=mpts,
            disk_type=dev["type"],
            is_system=system,
            is_external=external,
            is_removable=dev["removable"],
            read_only=dev["ro"],
            # defaults — policy.py will override
            policy_state="blocked" if system else "read_only",
            zone="system" if system else ("external" if external else "unzoned"),
            risk_level="critical" if system else ("caution" if external else "caution"),
            managed=False,
            allowed_operations=[],
            notes=notes,
        ))

    return disks


def list_mounts() -> List[MountInfo]:
    """Read mounts file and return structured mount list."""
    mounts: List[MountInfo] = []
    try:
        with open(_MOUNTS_PATH, "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 4:
                    continue
                device, mountpoint, fstype, options = parts[0], parts[1], parts[2], parts[3]
                system = mountpoint in _SYSTEM_MOUNTS or any(
                    mountpoint.startswith(p) for p in IMMUTABLE_BLOCKED_PREFIXES
                )
                mounts.append(MountInfo(
                    device=device,
                    mountpoint=mountpoint,
                    filesystem=fstype,
                    options=options,
                    is_system=system,
                    policy_state="blocked" if system else "read_only",
                    zone="system" if system else "unzoned",
                ))
    except Exception as e:
        log.warning(f"[Discovery] mounts read failed ({_MOUNTS_PATH}): {e}")
    return mounts
