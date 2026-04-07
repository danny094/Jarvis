"""
Storage Broker — Policy Layer
══════════════════════════════
Manages zones, policy_state, blacklists, and capability matrix.
State persisted in /app/data/storage_policy.json.

Single Source of Truth for what TRION is allowed to do on each disk.
Immutable blocked paths (system) can NEVER be overridden.
"""

import json
import os
import threading
import logging
from typing import List, Optional, Dict
from .models import (
    DiskInfo, PolicyConfig, ValidationResult, ZONE_CAPABILITIES,
    VALID_ZONES, VALID_POLICY_STATES,
    IMMUTABLE_BLOCKED_MOUNTS, IMMUTABLE_BLOCKED_PREFIXES,
)

log = logging.getLogger(__name__)

POLICY_PATH = os.environ.get("STORAGE_POLICY_PATH", "/app/data/storage_policy.json")
_LOCK = threading.Lock()


def _is_system_disk_id(disk_id: str) -> bool:
    try:
        from .discovery import list_disks
        disks = list_disks()
        hit = next((d for d in disks if str(d.id) == str(disk_id)), None)
        return bool(hit and hit.is_system)
    except Exception:
        return False


# ── Persistence ───────────────────────────────────────────

def _default_config() -> dict:
    return {
        "external_default_policy": "read_only",
        "unknown_mount_default": "blocked",
        "dry_run_default": True,
        "blacklist_extra": [],
        "managed_bases": [],
        "zone_overrides": {},
        "policy_overrides": {},
    }


def _load() -> dict:
    if not os.path.exists(POLICY_PATH):
        return _default_config()
    try:
        with open(POLICY_PATH, "r") as f:
            data = json.load(f)
        cfg = _default_config()
        cfg.update({k: v for k, v in data.items() if k in cfg})
        return cfg
    except Exception as e:
        log.warning(f"[Policy] Load failed: {e} — using defaults")
        return _default_config()


def _save(cfg: dict):
    os.makedirs(os.path.dirname(POLICY_PATH), exist_ok=True)
    tmp = POLICY_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, POLICY_PATH)


# ── Immutability Check ────────────────────────────────────

def _is_immutably_blocked_mount(mountpoint: str) -> bool:
    if mountpoint in IMMUTABLE_BLOCKED_MOUNTS:
        return True
    return any(mountpoint.startswith(p) for p in IMMUTABLE_BLOCKED_PREFIXES)


def _is_immutably_blocked_path(path: str) -> bool:
    """Also check raw paths, not just mountpoints."""
    real = _safe_realpath(path)
    if real in IMMUTABLE_BLOCKED_MOUNTS:
        return True
    return any(real.startswith(p) for p in IMMUTABLE_BLOCKED_PREFIXES)


def _safe_realpath(path: str) -> str:
    try:
        return os.path.realpath(path)
    except Exception:
        return path


# ── Public API ────────────────────────────────────────────

def get_policy() -> PolicyConfig:
    with _LOCK:
        return PolicyConfig(**_load())


def set_policy(updates: dict) -> PolicyConfig:
    allowed_keys = {
        "external_default_policy", "unknown_mount_default",
        "dry_run_default", "blacklist_extra", "managed_bases",
    }
    with _LOCK:
        cfg = _load()
        for k, v in updates.items():
            if k in allowed_keys:
                cfg[k] = v
        _save(cfg)
        return PolicyConfig(**cfg)


def set_disk_zone(disk_id: str, zone: str) -> bool:
    if zone not in VALID_ZONES:
        raise ValueError(f"Invalid zone '{zone}'. Valid: {sorted(VALID_ZONES)}")
    if _is_system_disk_id(disk_id):
        raise ValueError(f"System disk '{disk_id}' cannot be reassigned to zone '{zone}'")
    with _LOCK:
        cfg = _load()
        cfg.setdefault("zone_overrides", {})[disk_id] = zone
        _save(cfg)
    return True


def set_disk_policy(disk_id: str, policy_state: str) -> bool:
    if policy_state not in VALID_POLICY_STATES:
        raise ValueError(f"Invalid policy_state '{policy_state}'. Valid: {sorted(VALID_POLICY_STATES)}")
    if _is_system_disk_id(disk_id):
        raise ValueError(f"System disk '{disk_id}' cannot be changed to policy '{policy_state}'")
    with _LOCK:
        cfg = _load()
        cfg.setdefault("policy_overrides", {})[disk_id] = policy_state
        _save(cfg)
    return True


def get_blocked_paths() -> List[str]:
    """Return full blacklist: immutable + user-defined."""
    with _LOCK:
        cfg = _load()
    extra = [_safe_realpath(p) for p in cfg.get("blacklist_extra", [])]
    return sorted(IMMUTABLE_BLOCKED_MOUNTS) + extra


def add_blacklist_path(path: str) -> bool:
    real = _safe_realpath(path)
    with _LOCK:
        cfg = _load()
        bl = cfg.setdefault("blacklist_extra", [])
        if real not in bl:
            bl.append(real)
        _save(cfg)
    return True


def remove_blacklist_path(path: str) -> bool:
    real = _safe_realpath(path)
    with _LOCK:
        cfg = _load()
        bl = cfg.setdefault("blacklist_extra", [])
        if real in bl:
            bl.remove(real)
            _save(cfg)
            return True
    return False


# ── Disk Enrichment ───────────────────────────────────────

def enrich_disk(disk: DiskInfo) -> DiskInfo:
    """Apply policy overrides to a DiskInfo object."""
    with _LOCK:
        cfg = _load()

    zone_overrides   = cfg.get("zone_overrides", {})
    policy_overrides = cfg.get("policy_overrides", {})
    blacklist_extra  = [_safe_realpath(p) for p in cfg.get("blacklist_extra", [])]
    ext_default      = cfg.get("external_default_policy", "read_only")

    # Check immutable block first (system disks)
    for mp in disk.mountpoints + [disk.mountpoint]:
        if mp and _is_immutably_blocked_mount(mp):
            disk.is_system = True
            disk.policy_state = "blocked"
            disk.zone = "system"
            disk.risk_level = "critical"
            disk.managed = False
            disk.allowed_operations = []
            disk.notes = list(set(disk.notes + ["immutably blocked — system disk"]))
            return disk

    # System disks detected by discovery heuristics are always hard-blocked.
    # User overrides must never downgrade this.
    if disk.is_system:
        disk.policy_state = "blocked"
        disk.zone = "system"
        disk.risk_level = "critical"
        disk.managed = False
        disk.allowed_operations = []
        disk.notes = list(set(disk.notes + ["heuristically detected system disk"]))
        return disk

    # Check user blacklist
    real_mp = _safe_realpath(disk.mountpoint) if disk.mountpoint else ""
    if real_mp and real_mp in blacklist_extra:
        disk.policy_state = "blocked"
        disk.zone = disk.zone or "unzoned"
        disk.risk_level = "caution"
        disk.managed = False
        disk.allowed_operations = []
        return disk

    # Apply zone override
    if disk.id in zone_overrides:
        disk.zone = zone_overrides[disk.id]
    elif disk.is_system:
        disk.zone = "system"
    elif disk.is_external:
        disk.zone = "external"

    # Apply policy override
    if disk.id in policy_overrides:
        disk.policy_state = policy_overrides[disk.id]
    elif disk.is_system:
        disk.policy_state = "blocked"
    elif disk.is_external:
        disk.policy_state = ext_default
    else:
        disk.policy_state = disk.policy_state  # keep discovery default

    # Risk level
    if disk.policy_state == "blocked" or disk.is_system:
        disk.risk_level = "critical"
    elif disk.policy_state == "read_only" or disk.is_external:
        disk.risk_level = "caution"
    else:
        disk.risk_level = "safe"

    # Managed flag + capabilities
    disk.managed = disk.policy_state == "managed_rw"
    disk.allowed_operations = list(ZONE_CAPABILITIES.get(disk.zone, []))

    return disk


def enrich_disks(disks: List[DiskInfo]) -> List[DiskInfo]:
    return [enrich_disk(d) for d in disks]


# ── Path Validation ───────────────────────────────────────

def validate_path(path: str) -> ValidationResult:
    """
    Validate a target path against policy.
    Returns ValidationResult with valid=True only if path is in a managed_rw zone.
    Always uses realpath to prevent path-escape attacks.
    """
    if not path:
        return ValidationResult(path=path, valid=False, reason="empty path")

    real = _safe_realpath(path)

    # Symlink escape check
    if real != os.path.abspath(path):
        pass  # realpath resolved — that's fine, we use real

    # Immutable block check
    if _is_immutably_blocked_path(real):
        return ValidationResult(
            path=path, real_path=real,
            valid=False, policy_state="blocked", zone="system",
            reason="immutably blocked system path",
        )

    # Blacklist check
    with _LOCK:
        cfg = _load()
    blacklist = [_safe_realpath(p) for p in cfg.get("blacklist_extra", [])]
    if any(real == b or real.startswith(b + "/") for b in blacklist):
        return ValidationResult(
            path=path, real_path=real,
            valid=False, policy_state="blocked",
            reason="path is in user blacklist",
        )

    # Find matching managed scope from persisted policy config first, then env fallbacks.
    with _LOCK:
        cfg = _load()
    config_bases = [_safe_realpath(p) for p in cfg.get("managed_bases", []) if p]
    env_bases = [
        _safe_realpath(p)
        for p in os.environ.get("STORAGE_MANAGED_BASES", "").split(":")
        if p.strip()
    ]
    managed_bases = list(dict.fromkeys(config_bases + env_bases))
    for base in managed_bases:
        if real == base or real.startswith(base + "/"):
            return ValidationResult(
                path=path, real_path=real,
                valid=True, policy_state="managed_rw",
                zone="managed_services",
                reason="path is within managed zone",
                allowed_operations=list(ZONE_CAPABILITIES["managed_services"]),
            )

    return ValidationResult(
        path=path, real_path=real,
        valid=False, policy_state="read_only",
        reason="path is not in any managed zone — assign zone first",
    )
