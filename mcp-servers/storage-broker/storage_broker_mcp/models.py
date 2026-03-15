"""
Storage Broker — Data Models
═══════════════════════════════
Pydantic models for disks, mounts, zones, policies, and audit entries.
"""

from __future__ import annotations
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


# ── Zone & Policy Enums ───────────────────────────────────

VALID_ZONES = frozenset({
    "system",            # OS, boot, kernel — always blocked
    "managed_services",  # TRION services and MCP containers
    "backup",            # Backup targets only
    "external",          # USB / external drives
    "docker_runtime",    # /var/lib/docker — special handling
    "unzoned",           # Not yet classified
})

VALID_POLICY_STATES = frozenset({"blocked", "read_only", "managed_rw"})
VALID_RISK_LEVELS    = frozenset({"critical", "caution", "safe"})

# Paths that are ALWAYS blocked — immutable, not overrideable by user
IMMUTABLE_BLOCKED_MOUNTS = frozenset({
    "/", "/boot", "/boot/efi", "/etc", "/usr",
    "/proc", "/sys", "/dev", "/run",
    "/var/lib/docker",
})

IMMUTABLE_BLOCKED_PREFIXES = (
    "/proc/", "/sys/", "/dev/", "/run/",
    "/boot/", "/etc/", "/usr/",
)

# Ops allowed per zone
ZONE_CAPABILITIES: Dict[str, List[str]] = {
    "system":           [],
    "managed_services": ["create_directory", "set_permissions", "assign_to_container", "create_service_storage"],
    "backup":           ["create_directory", "create_service_storage"],
    "external":         ["create_directory"],
    "docker_runtime":   [],
    "unzoned":          [],
}


# ── Core Models ───────────────────────────────────────────

class DiskInfo(BaseModel):
    """Full representation of a discovered disk/partition."""
    id: str                          # e.g. "sdb1"
    device: str                      # e.g. "/dev/sdb1"
    uuid: str = ""
    label: str = ""
    filesystem: str = ""
    size_bytes: int = 0
    available_bytes: int = 0
    mountpoint: str = ""             # Primary mountpoint (or "")
    mountpoints: List[str] = Field(default_factory=list)
    disk_type: str = ""              # disk | part | rom | loop
    is_system: bool = False
    is_external: bool = False
    is_removable: bool = False
    read_only: bool = False
    # Policy (filled by policy layer)
    policy_state: str = "blocked"    # blocked | read_only | managed_rw
    zone: str = "unzoned"
    risk_level: str = "caution"      # critical | caution | safe
    managed: bool = False
    allowed_operations: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class MountInfo(BaseModel):
    """A single mountpoint entry."""
    device: str
    mountpoint: str
    filesystem: str = ""
    options: str = ""
    is_system: bool = False
    policy_state: str = "read_only"
    zone: str = "unzoned"


class StorageSummary(BaseModel):
    """High-level overview returned by storage_get_summary."""
    total_disks: int = 0
    total_mounts: int = 0
    managed_rw_count: int = 0
    read_only_count: int = 0
    blocked_count: int = 0
    total_size_bytes: int = 0
    total_available_bytes: int = 0
    zones: Dict[str, int] = Field(default_factory=dict)   # zone → disk count
    managed_paths: List[str] = Field(default_factory=list)


class PolicyConfig(BaseModel):
    """Current policy configuration."""
    external_default_policy: str = "read_only"  # policy for unknown external
    unknown_mount_default: str = "blocked"
    dry_run_default: bool = True
    blacklist_extra: List[str] = Field(default_factory=list)  # user-added blocked paths
    zone_overrides: Dict[str, str] = Field(default_factory=dict)  # device_id → zone
    policy_overrides: Dict[str, str] = Field(default_factory=dict)  # device_id → policy_state


class ValidationResult(BaseModel):
    """Result of validate_path."""
    path: str
    real_path: str = ""
    valid: bool = False
    policy_state: str = "blocked"
    zone: str = "unzoned"
    reason: str = ""
    allowed_operations: List[str] = Field(default_factory=list)


class ProvisionResult(BaseModel):
    """Result of create_service_dir."""
    service_name: str
    zone: str
    profile: str
    dry_run: bool = True
    target_base: str = ""
    paths_to_create: List[str] = Field(default_factory=list)
    created: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    ok: bool = False


class OperationResult(BaseModel):
    """Result of mount/format operations."""
    operation: str
    device: str
    dry_run: bool = True
    preview: str = ""
    executed: bool = False
    ok: bool = False
    error: str = ""
    audit_id: Optional[int] = None


class AuditEntry(BaseModel):
    """One audit log record."""
    id: Optional[int] = None
    operation: str
    target: str
    actor: str = "trion"
    dry_run: bool = True
    before_state: str = ""
    after_state: str = ""
    result: str = ""
    error: str = ""
    created_at: str = ""
