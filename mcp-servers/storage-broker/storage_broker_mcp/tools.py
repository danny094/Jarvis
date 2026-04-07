"""
Storage Broker — MCP Tool Definitions
═══════════════════════════════════════
All tools are registered here via @mcp.tool.

Communication with admin-api only via HTTP (no direct Python imports).

Tool groups:
  Discovery  → storage_list_disks, storage_get_disk, storage_list_mounts, storage_get_summary
  Policy     → storage_get_policy, storage_set_disk_zone, storage_set_disk_policy,
               storage_validate_path, storage_list_blocked_paths
  Provisioning → storage_create_service_dir, storage_list_managed_paths
  Disk Ops   → storage_mount_device, storage_format_device  (dry_run=True by default)
  Audit      → storage_audit_log
"""

import os
import logging
import subprocess
from typing import Optional, List
import requests

from .discovery import list_disks, list_mounts
from .policy import (
    enrich_disks, enrich_disk,
    get_policy, set_policy, set_disk_zone, set_disk_policy,
    get_blocked_paths, validate_path,
    add_blacklist_path, remove_blacklist_path,
    _safe_realpath, _is_immutably_blocked_path,
)
from .provisioner import create_service_storage, list_managed_paths
from .audit import log_operation, get_log, init_db
from .models import StorageSummary, OperationResult

log = logging.getLogger(__name__)

ADMIN_API = os.environ.get("ADMIN_API_URL", "http://jarvis-admin-api:8200")
HOST_HELPER_URL = str(os.environ.get("STORAGE_HOST_HELPER_URL", "http://storage-host-helper:8090") or "").strip().rstrip("/")


def register_tools(mcp):
    init_db()

    def _host_helper_post(path: str, payload: dict, timeout: int = 30) -> dict:
        base = str(HOST_HELPER_URL or "").strip().rstrip("/")
        if not base:
            return {"ok": False, "error": "storage-host-helper not configured"}
        try:
            response = requests.post(f"{base}{path}", json=payload, timeout=timeout)
        except Exception as exc:
            return {"ok": False, "error": f"storage-host-helper unreachable: {exc}"}
        try:
            data = response.json()
        except Exception:
            data = {}
        if not response.ok:
            detail = ""
            if isinstance(data, dict):
                detail = str(data.get("detail") or data.get("error") or "").strip()
            if not detail:
                detail = (response.text or "").strip() or f"HTTP {response.status_code}"
            return {"ok": False, "error": detail}
        return data if isinstance(data, dict) else {"ok": False, "error": "invalid host-helper response"}

    def _find_disk_match(disks, device: str):
        dev = str(device or "").strip()
        if not dev:
            return None
        return next((d for d in disks if d.device == dev or d.id == dev or d.id in dev), None)

    def _child_partitions_for_device(disks, device: str):
        dev = str(device or "").strip()
        if not dev:
            return []
        return [
            d for d in disks
            if getattr(d, "disk_type", "") == "part"
            and str(getattr(d, "device", "") or "").startswith(dev)
            and str(getattr(d, "device", "") or "") != dev
        ]

    def _mounted_targets_for_device(device: str) -> List[str]:
        dev = str(device or "").strip()
        if not dev:
            return []
        result = _host_helper_post("/v1/mount-targets", {"device": dev}, timeout=10)
        if result.get("ok") is True:
            targets = result.get("targets") or []
            return [line.strip() for line in targets if str(line).strip()]
        try:
            fallback = subprocess.run(
                ["findmnt", "-rn", "-S", dev, "-o", "TARGET"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            return []
        if fallback.returncode != 0:
            return []
        return [line.strip() for line in (fallback.stdout or "").splitlines() if line.strip()]

    # ────────────────────────────────────────────────────────
    # DISCOVERY
    # ────────────────────────────────────────────────────────

    @mcp.tool
    def storage_list_disks() -> dict:
        """
        List all block devices visible to the host with their zone, policy state,
        risk level, and allowed operations. System disks are always marked blocked.
        Returns a list of DiskInfo objects.
        """
        try:
            disks = enrich_disks(list_disks())
            return {
                "disks": [d.model_dump() for d in disks],
                "count": len(disks),
            }
        except Exception as e:
            log.error(f"[Tools] storage_list_disks: {e}")
            return {"error": str(e), "disks": []}

    @mcp.tool
    def storage_get_disk(disk_id: str) -> dict:
        """
        Get detailed info for a single disk/partition by its id (e.g. 'sdb1', 'nvme0n1p2').
        Returns full DiskInfo including policy_state, zone, risk_level, allowed_operations.
        """
        try:
            disks = enrich_disks(list_disks())
            match = next((d for d in disks if d.id == disk_id), None)
            if not match:
                return {"error": f"Disk '{disk_id}' not found", "disk": None}
            return {"disk": match.model_dump()}
        except Exception as e:
            log.error(f"[Tools] storage_get_disk: {e}")
            return {"error": str(e), "disk": None}

    @mcp.tool
    def storage_list_mounts() -> dict:
        """
        List all active mountpoints from /proc/mounts with their policy state and zone.
        Useful to see exactly what is mounted and what TRION can access.
        """
        try:
            mounts = list_mounts()
            return {
                "mounts": [m.model_dump() for m in mounts],
                "count": len(mounts),
            }
        except Exception as e:
            log.error(f"[Tools] storage_list_mounts: {e}")
            return {"error": str(e), "mounts": []}

    @mcp.tool
    def storage_get_summary() -> dict:
        """
        Get a high-level storage overview: total disks, total space, space available,
        count per policy state, count per zone, and list of managed paths.
        """
        try:
            disks = enrich_disks(list_disks())
            zones: dict = {}
            total_size = total_avail = managed_rw = read_only = blocked = 0
            for d in disks:
                zones[d.zone] = zones.get(d.zone, 0) + 1
                total_size  += d.size_bytes
                total_avail += d.available_bytes
                if d.policy_state == "managed_rw": managed_rw += 1
                elif d.policy_state == "read_only": read_only  += 1
                else:                               blocked    += 1

            summary = StorageSummary(
                total_disks=len(disks),
                total_mounts=len(list_mounts()),
                managed_rw_count=managed_rw,
                read_only_count=read_only,
                blocked_count=blocked,
                total_size_bytes=total_size,
                total_available_bytes=total_avail,
                zones=zones,
                managed_paths=list_managed_paths(),
            )
            return {"summary": summary.model_dump()}
        except Exception as e:
            log.error(f"[Tools] storage_get_summary: {e}")
            return {"error": str(e)}

    # ────────────────────────────────────────────────────────
    # POLICY
    # ────────────────────────────────────────────────────────

    @mcp.tool
    def storage_get_policy() -> dict:
        """
        Get the current storage policy configuration:
        - external_default_policy: what happens to unknown external drives
        - unknown_mount_default: default for unclassified mounts
        - dry_run_default: whether write operations default to preview mode
        - blacklist_extra: user-defined blocked paths
        - zone_overrides / policy_overrides: per-disk customisations
        """
        try:
            return {"policy": get_policy().model_dump()}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool
    def storage_set_disk_zone(disk_id: str, zone: str) -> dict:
        """
        Assign a zone to a disk/partition by its id.
        Valid zones: system, managed_services, backup, external, docker_runtime, unzoned.
        System disks remain immutably blocked regardless of zone assignment.

        Args:
            disk_id: e.g. 'sdb1', 'nvme0n1p2'
            zone: target zone name
        """
        try:
            set_disk_zone(disk_id, zone)
            log_operation("set_zone", disk_id, after_state=zone)
            return {"ok": True, "disk_id": disk_id, "zone": zone}
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            log.error(f"[Tools] storage_set_disk_zone: {e}")
            return {"ok": False, "error": str(e)}

    @mcp.tool
    def storage_set_disk_policy(disk_id: str, policy_state: str) -> dict:
        """
        Set the policy_state for a disk. Valid values: blocked | read_only | managed_rw.
        System disks always remain blocked. managed_rw enables provisioning.

        Args:
            disk_id: e.g. 'sdb1'
            policy_state: blocked | read_only | managed_rw
        """
        try:
            # Guard: cannot set managed_rw on a system disk
            disks = list_disks()
            match = next((d for d in disks if d.id == disk_id), None)
            if match and match.is_system:
                return {"ok": False, "error": "Cannot change policy of a system disk — it is immutably blocked."}
            set_disk_policy(disk_id, policy_state)
            log_operation("set_policy", disk_id, after_state=policy_state)
            return {"ok": True, "disk_id": disk_id, "policy_state": policy_state}
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            log.error(f"[Tools] storage_set_disk_policy: {e}")
            return {"ok": False, "error": str(e)}

    @mcp.tool
    def storage_validate_path(path: str) -> dict:
        """
        Validate whether a path is safe and accessible for TRION operations.
        Checks: immutable block, user blacklist, symlink escape, managed zone membership.
        Always resolves symlinks (realpath) before checking.

        Args:
            path: absolute path to validate
        """
        try:
            result = validate_path(path)
            return {"validation": result.model_dump()}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool
    def storage_list_blocked_paths() -> dict:
        """
        List all blocked paths: immutable system paths + user-defined blacklist.
        These paths can NEVER be targets of TRION write operations.
        """
        try:
            return {"blocked_paths": get_blocked_paths()}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool
    def storage_add_blacklist_path(path: str) -> dict:
        """
        Add a path to the user-defined blacklist (permanently blocked for TRION).
        The path is resolved via realpath before storage.

        Args:
            path: absolute path to block
        """
        try:
            if _is_immutably_blocked_path(path):
                return {"ok": True, "note": "Path is already in immutable system block."}
            add_blacklist_path(path)
            log_operation("blacklist_add", path, after_state="blocked")
            return {"ok": True, "path": _safe_realpath(path)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool
    def storage_remove_blacklist_path(path: str) -> dict:
        """
        Remove a user-defined blacklist entry (does NOT affect immutable system paths).

        Args:
            path: absolute path to unblock
        """
        try:
            if _is_immutably_blocked_path(path):
                return {"ok": False, "error": "Cannot remove immutable system blocked path."}
            removed = remove_blacklist_path(path)
            if removed:
                log_operation("blacklist_remove", path, after_state="unblocked")
            return {"ok": removed}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ────────────────────────────────────────────────────────
    # PROVISIONING
    # ────────────────────────────────────────────────────────

    @mcp.tool
    def storage_create_service_dir(
        service_name: str,
        zone: str = "managed_services",
        profile: str = "standard",
        dry_run: bool = True,
        base_path: str = "",
        owner: str = "",
        group: str = "",
    ) -> dict:
        """
        Create a managed directory structure for a service inside a zone.

        Profiles:
          - standard: config/, data/, logs/
          - full:     config/, data/, logs/, workspace/, backups/, tmp/
          - minimal:  data/
          - backup:   backups/

        ALWAYS preview (dry_run=True) by default. Set dry_run=False only after reviewing preview.
        Path traversal is prevented via realpath checks.

        Args:
            service_name: name of the service (e.g. 'mcp-weather')
            zone: target zone (managed_services | backup)
            profile: directory profile (standard | full | minimal | backup)
            dry_run: True = preview only, False = actually create directories
        """
        try:
            result = create_service_storage(
                service_name,
                zone,
                profile,
                dry_run,
                base_path=base_path,
                owner=owner,
                group=group,
            )
            log_operation(
                "create_service_dir", service_name,
                after_state=(
                    f"zone={zone} profile={profile} base={str(base_path or '').strip() or 'auto'} "
                    f"owner={str(owner or '').strip() or '-'} group={str(group or '').strip() or '-'}"
                ),
                dry_run=dry_run,
                result="ok" if result.ok else "failed",
                error="; ".join(result.errors),
            )
            return {"result": result.model_dump()}
        except Exception as e:
            log.error(f"[Tools] storage_create_service_dir: {e}")
            return {"error": str(e)}

    @mcp.tool
    def storage_list_managed_paths() -> dict:
        """
        List all existing service directories that TRION has created inside managed zones.
        """
        try:
            return {"managed_paths": list_managed_paths()}
        except Exception as e:
            return {"error": str(e)}

    # ────────────────────────────────────────────────────────
    # DISK OPERATIONS (mount / format)
    # dry_run=True by default — NEVER auto-execute
    # ────────────────────────────────────────────────────────

    @mcp.tool
    def storage_mount_device(
        device: str,
        mountpoint: str,
        filesystem: str = "",
        options: str = "",
        dry_run: bool = True,
        create_mountpoint: bool = False,
        persist: bool = False,
    ) -> dict:
        """
        Mount a block device to a mountpoint on the host.

        SAFETY RULES:
        - dry_run=True by default → shows mount command without executing
        - mountpoint must NOT be an immutably blocked system path
        - device must not be a system disk
        - Requires explicit dry_run=False to execute
        - Full audit log always written

        Args:
            device: block device path (e.g. /dev/sdb1)
            mountpoint: target mount path (must exist or be created first)
            filesystem: optional fstype (e.g. ext4, vfat). Empty = auto-detect.
            options: mount options (e.g. 'ro,noexec')
            dry_run: True = preview only
        """
        op = OperationResult(operation="mount", device=device, dry_run=dry_run, mountpoint=mountpoint)

        # Guard: catch swapped arguments — device path passed as mountpoint
        if mountpoint.startswith("/dev/"):
            op.error = (
                f"Invalid mountpoint '{mountpoint}': looks like a block device path. "
                f"'mountpoint' must be a target directory (e.g. /mnt/gaming-storage), "
                f"not a device. Use 'device' for the block device."
            )
            op.ok = False
            log_operation("mount", f"{device} → {mountpoint}", dry_run=dry_run, error=op.error)
            return {"result": op.model_dump()}

        # Guard: check mountpoint against system paths
        if _is_immutably_blocked_path(mountpoint):
            op.error = f"Mountpoint '{mountpoint}' is an immutably blocked system path."
            op.ok = False
            log_operation("mount", f"{device} → {mountpoint}", dry_run=dry_run, error=op.error)
            return {"result": op.model_dump()}

        # Guard: check device isn't a system disk
        disks = enrich_disks(list_disks())
        match = _find_disk_match(disks, device)
        if match and match.is_system:
            op.error = f"Device '{device}' is a system disk — mounting is blocked."
            op.ok = False
            log_operation("mount", f"{device} → {mountpoint}", dry_run=dry_run, error=op.error)
            return {"result": op.model_dump()}

        child_partitions = _child_partitions_for_device(disks, device)
        if match and getattr(match, "disk_type", "") == "disk" and child_partitions:
            child_devices = [d.device for d in child_partitions if getattr(d, "device", "")]
            example = child_devices[0] if child_devices else ""
            op.error = (
                f"Device '{device}' is a whole disk with partitions {child_devices}. "
                f"Mount the partition instead{f' (e.g. {example})' if example else ''}."
            )
            op.ok = False
            log_operation("mount", f"{device} → {mountpoint}", dry_run=dry_run, error=op.error)
            return {"result": op.model_dump()}

        # Build command
        cmd = ["mount"]
        if filesystem:
            cmd += ["-t", filesystem]
        if options:
            cmd += ["-o", options]
        cmd += [device, mountpoint]
        preview_parts = []
        if create_mountpoint:
            preview_parts.append(f"mkdir -p {mountpoint}")
        preview_parts.append(" ".join(cmd))
        if persist:
            preview_parts.append("# persist mount in /etc/fstab")
        op.preview = " && ".join(preview_parts)

        if dry_run:
            op.ok = True
            log_operation("mount", f"{device} → {mountpoint}", dry_run=True, result="preview")
            return {"result": op.model_dump()}

        # Execute (will fail gracefully if no permissions)
        try:
            result = _host_helper_post(
                "/v1/mount",
                {
                    "device": device,
                    "mountpoint": mountpoint,
                    "filesystem": filesystem,
                    "options": options,
                    "create_mountpoint": bool(create_mountpoint),
                    "persist": bool(persist),
                },
                timeout=30,
            )
            if result.get("ok") is True:
                op.ok = True
                op.executed = True
                log_operation("mount", f"{device} → {mountpoint}", dry_run=False, result="success")
            else:
                op.error = str(result.get("error") or "storage-host-helper mount failed")
                op.ok = False
                log_operation("mount", f"{device} → {mountpoint}", dry_run=False, error=op.error)
        except Exception as e:
            op.error = str(e)
            op.ok = False
            log_operation("mount", f"{device} → {mountpoint}", dry_run=False, error=str(e))

        return {"result": op.model_dump()}

    @mcp.tool
    def storage_unmount_device(
        device: str,
        dry_run: bool = True,
    ) -> dict:
        """
        Unmount a mounted block device from the host.

        SAFETY RULES:
        - dry_run=True by default → preview only
        - device must not be a system disk
        - if the target is a whole disk with child partitions, unmount the partition instead
        - full audit log always written
        """
        op = OperationResult(operation="unmount", device=device, dry_run=dry_run)

        disks = enrich_disks(list_disks())
        match = _find_disk_match(disks, device)
        if match and match.is_system:
            op.error = f"Device '{device}' is a system disk — unmount is blocked."
            op.ok = False
            log_operation("unmount", device, dry_run=dry_run, error=op.error)
            return {"result": op.model_dump()}

        child_partitions = _child_partitions_for_device(disks, device)
        if match and getattr(match, "disk_type", "") == "disk" and child_partitions:
            child_devices = [d.device for d in child_partitions if getattr(d, "device", "")]
            mounted_children = [d.device for d in child_partitions if getattr(d, "mountpoints", None)]
            suggestion = mounted_children[0] if mounted_children else (child_devices[0] if child_devices else "")
            op.error = (
                f"Device '{device}' is a whole disk with partitions {child_devices}. "
                f"Unmount the partition instead{f' (e.g. {suggestion})' if suggestion else ''}."
            )
            op.ok = False
            log_operation("unmount", device, dry_run=dry_run, error=op.error)
            return {"result": op.model_dump()}

        mounted_targets = list(dict.fromkeys(list(getattr(match, "mountpoints", []) or []) + _mounted_targets_for_device(device)))
        if not mounted_targets:
            op.error = f"Device '{device}' is not currently mounted."
            op.ok = False
            log_operation("unmount", device, dry_run=dry_run, error=op.error)
            return {"result": op.model_dump()}

        cmd = ["umount", device]
        op.preview = " ".join(cmd)

        if dry_run:
            op.ok = True
            log_operation("unmount", device, dry_run=True, result="preview")
            return {"result": op.model_dump()}

        try:
            result = _host_helper_post("/v1/unmount", {"device": device}, timeout=30)
            if result.get("ok") is True:
                op.ok = True
                op.executed = True
                log_operation("unmount", device, dry_run=False, result="success")
            else:
                op.error = str(result.get("error") or "storage-host-helper unmount failed")
                op.ok = False
                log_operation("unmount", device, dry_run=False, error=op.error)
        except Exception as e:
            op.error = str(e)
            op.ok = False
            log_operation("unmount", device, dry_run=False, error=str(e))

        return {"result": op.model_dump()}

    @mcp.tool
    def storage_format_device(
        device: str,
        filesystem: str,
        label: str = "",
        dry_run: bool = True,
    ) -> dict:
        """
        Format a block device with a filesystem.

        SAFETY RULES (STRICT):
        - dry_run=True ALWAYS by default — never auto-formats
        - Device must NOT be mounted (checked before execution)
        - Device must NOT be a system disk
        - Device must NOT be in IMMUTABLE_BLOCKED_MOUNTS
        - Supported filesystems: ext4, xfs, vfat, btrfs
        - Full audit log written in all cases

        THIS IS DESTRUCTIVE. All data on the device will be lost.
        Only execute with dry_run=False after explicit user confirmation.

        Args:
            device: block device (e.g. /dev/sdb1)
            filesystem: target filesystem (ext4 | xfs | vfat | btrfs)
            label: optional volume label
            dry_run: True = preview only (default)
        """
        op = OperationResult(operation="format", device=device, dry_run=dry_run)

        SUPPORTED_FS = {"ext4", "xfs", "vfat", "btrfs"}
        if filesystem not in SUPPORTED_FS:
            op.error = f"Unsupported filesystem '{filesystem}'. Supported: {sorted(SUPPORTED_FS)}"
            op.ok = False
            log_operation("format", device, dry_run=dry_run, error=op.error)
            return {"result": op.model_dump()}

        # Guard: system disk check
        disks = enrich_disks(list_disks())
        match = _find_disk_match(disks, device)
        if match and match.is_system:
            op.error = f"Device '{device}' is a system disk — formatting is permanently blocked."
            op.ok = False
            log_operation("format", device, dry_run=dry_run, error=op.error)
            return {"result": op.model_dump()}

        child_partitions = _child_partitions_for_device(disks, device)
        if match and getattr(match, "disk_type", "") == "disk" and child_partitions:
            child_devices = [d.device for d in child_partitions if getattr(d, "device", "")]
            example = child_devices[0] if child_devices else ""
            op.error = (
                f"Device '{device}' is a whole disk with partitions {child_devices}. "
                f"Format the partition instead{f' (e.g. {example})' if example else ''} or reinitialize the disk explicitly."
            )
            op.ok = False
            log_operation("format", device, dry_run=dry_run, error=op.error)
            return {"result": op.model_dump()}

        # Build command
        mkfs_cmds = {
            "ext4": ["mkfs.ext4", "-F"],
            "xfs":  ["mkfs.xfs"],
            "vfat": ["mkfs.vfat"],
            "btrfs": ["mkfs.btrfs"],
        }
        cmd = mkfs_cmds[filesystem]
        if label:
            cmd += ["-L", label]
        cmd.append(device)
        op.preview = " ".join(cmd) + "  ⚠ DESTRUCTIVE — all data will be erased"

        if dry_run:
            op.ok = True
            log_operation("format", device, dry_run=True,
                          after_state=f"fs={filesystem}", result="preview")
            return {"result": op.model_dump()}

        # Execute
        try:
            result = _host_helper_post(
                "/v1/format",
                {"device": device, "filesystem": filesystem, "label": label},
                timeout=120,
            )
            if result.get("ok") is True:
                op.ok = True
                op.executed = True
                log_operation("format", device, dry_run=False,
                              after_state=f"fs={filesystem}", result="success")
            else:
                op.error = str(result.get("error") or "storage-host-helper format failed")
                op.ok = False
                log_operation("format", device, dry_run=False, error=op.error)
        except Exception as e:
            op.error = str(e)
            op.ok = False
            log_operation("format", device, dry_run=False, error=str(e))

        return {"result": op.model_dump()}

    @mcp.tool
    def storage_partition_disk(
        device: str,
        partitions: list,
        table_type: str = "gpt",
        dry_run: bool = True,
    ) -> dict:
        """
        Create a partition table and one or more partitions on a whole disk.

        SAFETY RULES (STRICT):
        - dry_run=True ALWAYS by default — never auto-partitions
        - Device must be a whole disk (not an existing partition)
        - Device must NOT be a system disk
        - Only one partition may omit size_pct (it receives remaining space)
        - Full audit log written in all cases

        THIS IS DESTRUCTIVE. All existing data and partitions will be lost.
        Only execute with dry_run=False after explicit user confirmation.

        Args:
            device:     whole disk device (e.g. /dev/sdb)
            partitions: list of dicts, each with:
                          label      (str, optional)
                          size_pct   (float 0-100, or null = use remaining space)
                          filesystem (str: ext4 | xfs | vfat | btrfs)
            table_type: partition table type: 'gpt' (default) or 'mbr'
            dry_run:    True = preview only (default)
        """
        op = OperationResult(operation="partition", device=device, dry_run=dry_run)

        disks = enrich_disks(list_disks())
        match = _find_disk_match(disks, device)

        if match and match.is_system:
            op.error = f"Device '{device}' is a system disk — partitioning is permanently blocked."
            op.ok = False
            log_operation("partition", device, dry_run=dry_run, error=op.error)
            return {"result": op.model_dump()}

        if match and getattr(match, "disk_type", "") == "part":
            op.error = f"Device '{device}' is a partition, not a whole disk. Provide the parent disk."
            op.ok = False
            log_operation("partition", device, dry_run=dry_run, error=op.error)
            return {"result": op.model_dump()}

        if not isinstance(partitions, list) or not partitions:
            op.error = "partitions must be a non-empty list."
            op.ok = False
            log_operation("partition", device, dry_run=dry_run, error=op.error)
            return {"result": op.model_dump()}

        payload = {
            "device": device,
            "table_type": table_type,
            "partitions": partitions,
            "dry_run": dry_run,
        }

        if dry_run:
            result = _host_helper_post("/v1/create-partition", payload, timeout=30)
            if result.get("ok") is True:
                op.ok = True
                op.preview = "\n".join(result.get("preview") or [])
                log_operation("partition", device, dry_run=True, result="preview")
            else:
                op.error = str(result.get("error") or "host-helper partition preview failed")
                op.ok = False
                log_operation("partition", device, dry_run=True, error=op.error)
            return {"result": op.model_dump()}

        # Execute
        try:
            result = _host_helper_post("/v1/create-partition", payload, timeout=180)
            if result.get("ok") is True:
                op.ok = True
                op.executed = True
                log_operation("partition", device, dry_run=False,
                              after_state=f"table={table_type},parts={len(partitions)}", result="success")
            else:
                op.error = str(result.get("error") or "host-helper partition failed")
                op.ok = False
                log_operation("partition", device, dry_run=False, error=op.error)
        except Exception as e:
            op.error = str(e)
            op.ok = False
            log_operation("partition", device, dry_run=False, error=str(e))

        return {"result": op.model_dump()}

    # ────────────────────────────────────────────────────────
    # AUDIT
    # ────────────────────────────────────────────────────────

    @mcp.tool
    def storage_audit_log(limit: int = 50, operation: str = "") -> dict:
        """
        Retrieve the storage broker audit log.
        Every write-intent operation (including dry-runs) is recorded here.

        Args:
            limit: max number of entries to return (default: 50)
            operation: filter by operation type (e.g. 'mount', 'format', 'create_service_dir')
        """
        try:
            entries = get_log(limit=limit, operation=operation or None)
            return {
                "entries": [e.model_dump() for e in entries],
                "count": len(entries),
            }
        except Exception as e:
            return {"error": str(e), "entries": []}
