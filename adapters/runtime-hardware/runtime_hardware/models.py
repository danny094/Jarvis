from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


ResourceKind = Literal["input", "usb", "device", "gpu_access", "block_device_ref", "mount_ref"]
PlanActionKind = Literal["live_attach", "live_detach", "stage_for_recreate", "reject", "unsupported"]


class ConnectorInfo(BaseModel):
    id: str
    label: str
    enabled: bool = True
    resource_kinds: List[ResourceKind] = Field(default_factory=list)


class RuntimeCapability(BaseModel):
    connector: str
    resource_kind: ResourceKind
    discover: bool = True
    attach_live: bool = False
    detach_live: bool = False
    stage_supported: bool = True
    requires_privileged: bool = False
    requires_restart: bool = True
    notes: str = ""


class HardwareResource(BaseModel):
    id: str
    kind: ResourceKind
    source_connector: str
    label: str
    host_path: str = ""
    vendor: str = ""
    product: str = ""
    serial: str = ""
    capabilities: List[str] = Field(default_factory=list)
    risk_level: str = "medium"
    availability_state: str = "available"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AttachmentIntent(BaseModel):
    resource_id: str
    target_type: str
    target_id: str
    attachment_mode: str = "attach"
    policy: Dict[str, Any] = Field(default_factory=dict)
    requested_by: str = ""


class PlanRequest(BaseModel):
    target_type: str
    target_id: str
    connector: str = "container"
    intents: List[AttachmentIntent] = Field(default_factory=list)


class PlanAction(BaseModel):
    resource_id: str
    action: PlanActionKind
    supported: bool = False
    requires_restart: bool = False
    requires_approval: bool = False
    explanation: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AttachmentPlan(BaseModel):
    target_type: str
    target_id: str
    connector: str
    actions: List[PlanAction] = Field(default_factory=list)
    summary: str = ""


class AttachedResource(BaseModel):
    kind: str
    value: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AttachmentState(BaseModel):
    target_type: str
    target_id: str
    exists: bool
    connector: str
    attached_resources: List[AttachedResource] = Field(default_factory=list)
    staged_resources: List[AttachedResource] = Field(default_factory=list)
    runtime: Dict[str, Any] = Field(default_factory=dict)


class ValidateRequest(BaseModel):
    target_type: str
    target_id: str
    connector: str = "container"
    resource_ids: List[str] = Field(default_factory=list)


class ValidateResult(BaseModel):
    target_type: str
    target_id: str
    connector: str
    valid: bool
    issues: List[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    service: str
    status: str
    connectors: List[str] = Field(default_factory=list)
    config_dir: str = ""
    state_dir: str = ""
