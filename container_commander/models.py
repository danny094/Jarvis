"""
Container Commander — Blueprint YAML Schema + Pydantic Models
═══════════════════════════════════════════════════════════════
Defines the data structures for:
- Blueprint: Container template (Dockerfile, resources, secrets, system_prompt)
- ContainerInstance: Running container state
- SecretRef: Reference to an encrypted secret (never exposes value)
- ResourceLimits: CPU, RAM, swap, timeout constraints
"""

from __future__ import annotations
from typing import Optional, List, Dict
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime


# ── Enums ──────────────────────────────────────────────────

class NetworkMode(str, Enum):
    NONE = "none"          # No network (pure sandbox)
    INTERNAL = "internal"  # TRION-internal only
    BRIDGE = "bridge"      # Host network access
    FULL = "full"          # Internet (requires user approval)


class ContainerStatus(str, Enum):
    READY = "ready"        # Blueprint exists, no container running
    BUILDING = "building"  # Image is being built
    RUNNING = "running"    # Container is active
    STOPPED = "stopped"    # Container exited
    ERROR = "error"        # Build or runtime error


class SecretScope(str, Enum):
    GLOBAL = "global"          # Available to all blueprints
    BLUEPRINT = "blueprint"    # Tied to a specific blueprint


# ── Resource Limits ────────────────────────────────────────

class ResourceLimits(BaseModel):
    """Hard resource constraints for a container."""
    cpu_limit: str = Field(default="1.0", description="CPU cores (e.g. '0.5', '2.0')")
    memory_limit: str = Field(default="512m", description="RAM limit (e.g. '256m', '2g')")
    memory_swap: str = Field(default="1g", description="Swap limit")
    timeout_seconds: int = Field(default=300, description="Auto-kill TTL in seconds")
    pids_limit: int = Field(default=100, description="Max processes inside container")


# ── Mount Definition ───────────────────────────────────────

class MountDef(BaseModel):
    """Volume mount: host path → container path."""
    host: str = Field(..., description="Host path (relative to project root)")
    container: str = Field(..., description="Container mount path")
    mode: str = Field(default="rw", description="ro or rw")


# ── Secret Reference ──────────────────────────────────────

class SecretRequirement(BaseModel):
    """A secret that a blueprint needs (declared in YAML)."""
    name: str = Field(..., description="Environment variable name (e.g. OPENAI_API_KEY)")
    description: str = Field(default="", description="What this secret is used for")
    optional: bool = Field(default=False, description="Container can run without it")


class SecretEntry(BaseModel):
    """A stored secret (value is NEVER exposed to KI)."""
    id: Optional[int] = None
    name: str
    scope: SecretScope = SecretScope.GLOBAL
    blueprint_id: Optional[str] = None
    created_at: Optional[str] = None
    expires_at: Optional[str] = None
    # Note: encrypted_value is never in this model — only in DB


class SecretRef(BaseModel):
    """Reference to a secret (what the KI sees — no value!)."""
    name: str
    scope: str
    blueprint_id: Optional[str] = None
    exists: bool = True


# ── Blueprint ─────────────────────────────────────────────

class Blueprint(BaseModel):
    """
    Container Blueprint — the template for spinning up containers.
    Loaded from YAML files or stored in SQLite.
    """
    id: str = Field(..., description="Unique identifier (e.g. 'python-sandbox')")
    name: str = Field(..., description="Display name")
    description: str = Field(default="", description="What this blueprint is for")
    extends: Optional[str] = Field(default=None, description="Parent blueprint ID for inheritance")
    
    # Container definition
    dockerfile: str = Field(default="", description="Dockerfile content or path")
    image: Optional[str] = Field(default=None, description="Pre-built image (alternative to dockerfile)")
    image_digest: Optional[str] = Field(
        default=None,
        description=(
            "Optional pinned image digest (sha256:...) for trust verification. "
            "If set: start_container() fails if resolved digest doesn't match (fail closed). "
            "If None: start allowed with warning (opt-in, backwards compatible)."
        )
    )
    
    # KI context
    system_prompt: str = Field(default="", description="System prompt for KI when using this container")
    
    # Resources
    resources: ResourceLimits = Field(default_factory=ResourceLimits)
    
    # Secrets
    secrets_required: List[SecretRequirement] = Field(default_factory=list)
    
    # Mounts
    mounts: List[MountDef] = Field(default_factory=list)
    
    # Network
    network: NetworkMode = Field(default=NetworkMode.INTERNAL)
    
    # Exec Policy
    allowed_exec: List[str] = Field(
        default_factory=list,
        description=(
            "Allowlist of permitted command prefixes for exec_in_container. "
            "Empty = no restriction. E.g. ['python', 'pip', 'sh']"
        )
    )

    # Metadata
    tags: List[str] = Field(default_factory=list)
    icon: str = Field(default="📦", description="Emoji icon for UI")
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ── Container Instance ────────────────────────────────────

class ContainerInstance(BaseModel):
    """A running (or stopped) container instance."""
    container_id: str
    blueprint_id: str
    name: str
    status: ContainerStatus = ContainerStatus.READY
    
    # Runtime stats
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    memory_limit_mb: float = 512.0
    network_rx_bytes: int = 0
    network_tx_bytes: int = 0
    
    # Timing
    started_at: Optional[str] = None
    runtime_seconds: int = 0
    ttl_remaining: int = 0
    
    # Efficiency
    efficiency_score: float = 1.0  # 0.0-1.0
    efficiency_level: str = "green"  # green/yellow/red
    
    # Volume
    volume_name: Optional[str] = None
    has_snapshot: bool = False
    cpu_limit_alloc: float = 1.0  # CPU cores allocated to this container
    network_info: Dict = Field(default_factory=dict)  # Network isolation details

    # Session tracking (set at start, persisted in Docker labels)
    session_id: str = ""  # conversation_id that started this container


# ── Quota ─────────────────────────────────────────────────

class SessionQuota(BaseModel):
    """Resource budget for the KI per session."""
    max_containers: int = Field(default=2, description="Max simultaneous containers")
    max_total_memory_mb: int = Field(default=2048, description="Total RAM budget")
    max_total_cpu: float = Field(default=2.0, description="Total CPU budget")
    containers_used: int = 0
    memory_used_mb: int = 0
    cpu_used: float = 0.0


# ── API Request/Response Models ───────────────────────────

class DeployRequest(BaseModel):
    """Request to deploy a container from a blueprint."""
    blueprint_id: str
    override_resources: Optional[ResourceLimits] = None
    environment: Dict[str, str] = Field(default_factory=dict)


class ExecRequest(BaseModel):
    """Request to execute a command in a running container."""
    container_id: str
    command: str
    timeout: int = Field(default=30, description="Exec timeout in seconds")


class BlueprintCreateRequest(BaseModel):
    """Request to create a new blueprint."""
    id: str
    name: str
    description: str = ""
    dockerfile: str = ""
    image: Optional[str] = None
    system_prompt: str = ""
    resources: Optional[ResourceLimits] = None
    secrets_required: List[SecretRequirement] = Field(default_factory=list)
    mounts: List[MountDef] = Field(default_factory=list)
    network: NetworkMode = NetworkMode.INTERNAL
    tags: List[str] = Field(default_factory=list)
    icon: str = "📦"
    extends: Optional[str] = None


class SecretStoreRequest(BaseModel):
    """Request to store a new secret."""
    name: str
    value: str  # Only in request — never stored in plaintext
    scope: SecretScope = SecretScope.GLOBAL
    blueprint_id: Optional[str] = None
    expires_at: Optional[str] = None
