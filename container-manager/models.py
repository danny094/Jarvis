# models.py
"""
Pydantic Models für Container-Manager API.

Alle Request/Response Models an einem Ort.
"""

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from dataclasses import dataclass, field


# ============================================================
# API REQUEST MODELS
# ============================================================

class ContainerStartRequest(BaseModel):
    """Request zum Starten eines Containers."""
    container_name: str = Field(..., description="Name des Containers aus der Registry")
    code: Optional[str] = Field(None, description="Code zum Ausführen")
    command: Optional[str] = Field(None, description="Alternativer Befehl")
    timeout: Optional[int] = Field(60, ge=1, le=300, description="Timeout in Sekunden")
    language: Optional[str] = Field("python", description="Programmiersprache")
    keep_alive: bool = Field(False, description="Container nach Ausführung behalten")
    ttl_seconds: Optional[int] = Field(300, ge=60, le=3600, description="Session TTL")
    enable_ttyd: bool = Field(False, description="Live Terminal aktivieren")


class ContainerExecRequest(BaseModel):
    """Request zur Ausführung in laufendem Container."""
    container_id: str = Field(..., description="Container ID")
    command: str = Field(..., description="Auszuführender Befehl")
    timeout: Optional[int] = Field(30, ge=1, le=300, description="Timeout in Sekunden")


class ContainerStopRequest(BaseModel):
    """Request zum Stoppen eines Containers."""
    container_id: str = Field(..., description="Container ID")


class SessionExtendRequest(BaseModel):
    """Request zur Verlängerung einer Session."""
    session_id: str = Field(..., description="Session ID")
    extend_seconds: int = Field(300, ge=60, le=3600, description="Verlängerung in Sekunden")


class UserSandboxStartRequest(BaseModel):
    """Request zum Starten der User-Sandbox."""
    container_name: str = Field("code-sandbox", description="Container Name")
    preferred_model: Optional[str] = Field(None, description="Bevorzugtes Code-Model")


class UserSandboxStopRequest(BaseModel):
    """Request zum Stoppen der User-Sandbox."""
    force: bool = Field(False, description="Force Kill")


# ============================================================
# INTERNAL DATA MODELS
# ============================================================

@dataclass
class ExecutionResult:
    """Ergebnis einer Code-Ausführung."""
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }
    
    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass
class SessionInfo:
    """Session-Informationen für persistente Container."""
    session_id: str
    container_id: str
    container_name: str
    started_at: str
    last_activity: str
    persistent: bool = False
    ttl_seconds: Optional[int] = None
    ttyd_enabled: bool = False
    ttyd_port: Optional[str] = None
    ttyd_url: Optional[str] = None
    owner: str = "system"  # "user" oder "system"
    preferred_model: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "container_id": self.container_id,
            "container_name": self.container_name,
            "started_at": self.started_at,
            "last_activity": self.last_activity,
            "persistent": self.persistent,
            "ttl_seconds": self.ttl_seconds,
            "ttyd_enabled": self.ttyd_enabled,
            "ttyd_port": self.ttyd_port,
            "ttyd_url": self.ttyd_url,
            "owner": self.owner,
            "preferred_model": self.preferred_model,
        }


@dataclass
class ContainerConfig:
    """Konfiguration eines Containers aus der Registry."""
    name: str
    description: str = ""
    image: str = ""
    build_context: Optional[str] = None
    triggers: List[str] = field(default_factory=list)
    security: Dict[str, Any] = field(default_factory=dict)
    resources: Dict[str, Any] = field(default_factory=dict)
    mounts: List[Dict[str, Any]] = field(default_factory=list)
    
    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "ContainerConfig":
        return cls(
            name=name,
            description=data.get("description", ""),
            image=data.get("image", f"jarvis-{name}:latest"),
            build_context=data.get("build_context"),
            triggers=data.get("triggers", []),
            security=data.get("security", {}),
            resources=data.get("resources", {}),
            mounts=data.get("mounts", []),
        )
