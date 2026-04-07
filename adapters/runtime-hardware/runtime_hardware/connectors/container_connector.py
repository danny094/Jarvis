from __future__ import annotations

import json
import os
import stat
from glob import glob
from pathlib import Path
from typing import Any, Dict, List

try:
    import docker
except Exception:  # pragma: no cover - local/dev environments may not ship docker SDK
    docker = None

from runtime_hardware.models import (
    AttachedResource,
    AttachmentIntent,
    AttachmentState,
    ConnectorInfo,
    HardwareResource,
    RuntimeCapability,
    ValidateResult,
)
from runtime_hardware.planner import build_plan

from .base import RuntimeConnector
from .container_display import enrich_container_resources_for_simple_display
from .container_storage_discovery import (
    discover_storage_asset_mount_refs,
    discover_storage_broker_block_resources,
)


def _parse_udev_properties(device_path: str) -> Dict[str, str]:
    try:
        st = os.stat(device_path)
    except Exception:
        return {}
    if not stat.S_ISCHR(st.st_mode) and not stat.S_ISBLK(st.st_mode):
        return {}
    major_num = os.major(st.st_rdev)
    minor_num = os.minor(st.st_rdev)
    data_path = Path(f"/run/udev/data/c{major_num}:{minor_num}")
    if not data_path.exists():
        return {}
    props: Dict[str, str] = {}
    try:
        for raw_line in data_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if raw_line.startswith("E:") and "=" in raw_line[2:]:
                key, value = raw_line[2:].split("=", 1)
                props[key.strip()] = value.strip()
    except Exception:
        return {}
    return props


def _read_sysfs_input_name(device_path: str) -> str:
    path = Path(device_path)
    base_name = path.name
    if not base_name:
        return ""
    candidates = [
        Path("/sys/class/input") / base_name / "device" / "name",
        Path("/sys/class/input") / base_name / "name",
    ]
    for candidate in candidates:
        try:
            if candidate.exists():
                value = candidate.read_text(encoding="utf-8", errors="replace").strip()
                if value:
                    return value
        except Exception:
            continue
    return ""


def _read_sysfs_input_device_path(device_path: str) -> str:
    path = Path(device_path)
    base_name = path.name
    if not base_name:
        return ""
    candidate = Path("/sys/class/input") / base_name / "device"
    try:
        if candidate.exists():
            return str(candidate.resolve())
    except Exception:
        return ""
    return ""


def _resource_from_device(path: str) -> HardwareResource | None:
    props = _parse_udev_properties(path)
    lower = path.lower()
    kind = "device"
    capabilities: List[str] = []
    label = os.path.basename(path)
    risk = "medium"

    if lower.startswith("/dev/input/"):
        kind = "input"
        if props.get("ID_INPUT_KEYBOARD") == "1":
            capabilities.append("keyboard")
        if props.get("ID_INPUT_MOUSE") == "1":
            capabilities.append("mouse")
        if props.get("ID_INPUT_TOUCHPAD") == "1":
            capabilities.append("touchpad")
        if props.get("ID_INPUT_JOYSTICK") == "1":
            capabilities.append("joystick")
        sysfs_name = _read_sysfs_input_name(path)
        input_device_path = _read_sysfs_input_device_path(path)
        label = props.get("NAME") or sysfs_name or props.get("ID_MODEL_FROM_DATABASE") or label
        risk = "high"
    elif lower.startswith("/dev/bus/usb/"):
        kind = "usb"
        label = props.get("ID_MODEL_FROM_DATABASE") or label
        risk = "high"
    elif lower.startswith("/dev/dri/"):
        kind = "device"
        capabilities.append("gpu")
        risk = "high"
    elif lower in {"/dev/kvm", "/dev/vfio/vfio", "/dev/uinput"}:
        kind = "device"
        capabilities.append("special")
        risk = "high"

    vendor = props.get("ID_VENDOR_FROM_DATABASE") or props.get("ID_VENDOR", "")
    product = props.get("ID_MODEL_FROM_DATABASE") or props.get("ID_MODEL", "")
    serial = props.get("ID_SERIAL_SHORT") or props.get("ID_SERIAL", "")
    resource_id = f"container::{kind}::{path}"
    return HardwareResource(
        id=resource_id,
        kind=kind,  # type: ignore[arg-type]
        source_connector="container",
        label=str(label).strip() or os.path.basename(path),
        host_path=path,
        vendor=str(vendor),
        product=str(product),
        serial=str(serial),
        capabilities=capabilities,
        risk_level=risk,
        metadata={
            **{k: v for k, v in props.items() if k.startswith("ID_")},
            "technical_label": str(label).strip() or os.path.basename(path),
            **({"sysfs_input_name": sysfs_name} if lower.startswith("/dev/input/") and sysfs_name else {}),
            **({"input_device_path": input_device_path} if lower.startswith("/dev/input/") and input_device_path else {}),
        },
    )


def _discover_device_resources() -> List[HardwareResource]:
    candidates: List[str] = []
    candidates.extend(sorted(glob("/dev/input/event*")))
    candidates.extend(sorted(glob("/dev/input/js*")))
    candidates.extend(sorted(glob("/dev/bus/usb/*/*")))
    candidates.extend(sorted(glob("/dev/dri/*")))
    for extra in ("/dev/kvm", "/dev/uinput", "/dev/vfio/vfio"):
        if os.path.exists(extra):
            candidates.append(extra)
    resources: List[HardwareResource] = []
    seen: set[str] = set()
    for path in candidates:
        if path in seen or not os.path.exists(path):
            continue
        seen.add(path)
        resource = _resource_from_device(path)
        if resource is not None:
            resources.append(resource)
    return resources


def _discover_block_resources() -> List[HardwareResource]:
    resources: List[HardwareResource] = []
    for sys_path in sorted(Path("/sys/class/block").glob("*")):
        name = sys_path.name
        dev_path = f"/dev/{name}"
        if not os.path.exists(dev_path):
            continue
        removable = ""
        try:
            removable = (sys_path / "removable").read_text(encoding="utf-8").strip()
        except Exception:
            removable = ""
        size_sectors = 0
        try:
            size_sectors = int((sys_path / "size").read_text(encoding="utf-8").strip() or "0")
        except Exception:
            size_sectors = 0
        resources.append(
            HardwareResource(
                id=f"container::block_device_ref::{dev_path}",
                kind="block_device_ref",
                source_connector="container",
                label=name,
                host_path=dev_path,
                capabilities=["block", "removable" if removable == "1" else "fixed"],
                risk_level="high",
                metadata={
                    "sys_path": str(sys_path),
                    "device_name": name,
                    "removable": removable == "1",
                    "size_bytes_estimate": size_sectors * 512,
                },
            )
        )
    return resources


class ContainerConnector(RuntimeConnector):
    def __init__(self) -> None:
        self._client: Any = None

    def _docker(self):
        if docker is None:
            raise RuntimeError("docker_sdk_unavailable")
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    def info(self) -> ConnectorInfo:
        return ConnectorInfo(
            id="container",
            label="Container Runtime",
            enabled=True,
            resource_kinds=["input", "usb", "device", "gpu_access", "block_device_ref", "mount_ref"],
        )

    def get_capabilities(self) -> List[RuntimeCapability]:
        return [
            RuntimeCapability(
                connector="container",
                resource_kind="input",
                attach_live=False,
                detach_live=False,
                stage_supported=True,
                requires_privileged=False,
                requires_restart=True,
                notes="input devices are staged for recreate in v0",
            ),
            RuntimeCapability(
                connector="container",
                resource_kind="usb",
                attach_live=False,
                detach_live=False,
                stage_supported=True,
                requires_privileged=False,
                requires_restart=True,
                notes="usb passthrough is recreate-based in v0",
            ),
            RuntimeCapability(
                connector="container",
                resource_kind="device",
                attach_live=False,
                detach_live=False,
                stage_supported=True,
                requires_privileged=False,
                requires_restart=True,
                notes="device passthrough is recreate-based in v0",
            ),
            RuntimeCapability(
                connector="container",
                resource_kind="gpu_access",
                attach_live=False,
                detach_live=False,
                stage_supported=False,
                requires_privileged=True,
                requires_restart=True,
                notes="gpu capability is discovery-only in v0",
            ),
            RuntimeCapability(
                connector="container",
                resource_kind="block_device_ref",
                attach_live=False,
                detach_live=False,
                stage_supported=True,
                requires_privileged=True,
                requires_restart=True,
                notes="block devices require recreate and storage review in v0",
            ),
            RuntimeCapability(
                connector="container",
                resource_kind="mount_ref",
                attach_live=False,
                detach_live=False,
                stage_supported=True,
                requires_privileged=False,
                requires_restart=True,
                notes="mount refs require storage-broker materialization in v1",
            ),
        ]

    def list_resources(self) -> List[HardwareResource]:
        resource_index: Dict[str, HardwareResource] = {}
        for resource in _discover_device_resources():
            resource_index[resource.id] = resource
        for resource in _discover_block_resources():
            resource_index[resource.id] = resource
        for resource in discover_storage_broker_block_resources():
            resource_index[resource.id] = resource
        for resource in discover_storage_asset_mount_refs():
            resource_index[resource.id] = resource
        resources = list(resource_index.values())
        resources = enrich_container_resources_for_simple_display(resources)
        resources.sort(key=lambda item: (item.kind, item.host_path, item.label, item.id))
        return resources

    def resource_index(self) -> Dict[str, HardwareResource]:
        return {resource.id: resource for resource in self.list_resources()}

    def get_target_state(self, *, target_type: str, target_id: str) -> AttachmentState:
        if target_type == "blueprint":
            return AttachmentState(
                target_type=target_type,
                target_id=target_id,
                exists=True,
                connector="container",
                runtime={"mode": "blueprint_preview"},
            )
        if target_type != "container":
            return AttachmentState(
                target_type=target_type,
                target_id=target_id,
                exists=False,
                connector="container",
                runtime={"error": f"unsupported_target_type:{target_type}"},
            )
        try:
            container = self._docker().containers.get(target_id)
        except Exception as exc:
            return AttachmentState(
                target_type=target_type,
                target_id=target_id,
                exists=False,
                connector="container",
                runtime={"error": f"container_lookup_failed:{exc}"},
            )

        attrs: Dict[str, Any] = dict(container.attrs or {})
        host_config = attrs.get("HostConfig") or {}
        devices = list(host_config.get("Devices") or [])
        mounts = list(attrs.get("Mounts") or [])
        attached = [
            AttachedResource(
                kind="device",
                value=str(item.get("PathOnHost") or ""),
                metadata={
                    "container_path": str(item.get("PathInContainer") or ""),
                    "permissions": str(item.get("CgroupPermissions") or ""),
                },
            )
            for item in devices
        ]
        attached.extend(
            AttachedResource(
                kind="mount",
                value=str(item.get("Source") or ""),
                metadata={
                    "target": str(item.get("Destination") or ""),
                    "mode": str(item.get("Mode") or ""),
                    "rw": bool(item.get("RW")),
                },
            )
            for item in mounts
        )
        return AttachmentState(
            target_type="container",
            target_id=container.id,
            exists=True,
            connector="container",
            attached_resources=attached,
            runtime={
                "name": str(attrs.get("Name") or "").lstrip("/"),
                "image": str(((attrs.get("Config") or {}).get("Image")) or ""),
                "running": bool((attrs.get("State") or {}).get("Running")),
                "status": str((attrs.get("State") or {}).get("Status") or ""),
                "privileged": bool(host_config.get("Privileged")),
                "cap_add": list(host_config.get("CapAdd") or []),
            },
        )

    def plan(self, *, target_type: str, target_id: str, intents: List[AttachmentIntent]):
        capabilities = {item.resource_kind: item for item in self.get_capabilities()}
        return build_plan(
            connector="container",
            target_type=target_type,
            target_id=target_id,
            intents=intents,
            resources=self.resource_index(),
            capabilities=capabilities,
        )

    def validate(self, *, target_type: str, target_id: str, resource_ids: List[str]) -> ValidateResult:
        issues: List[str] = []
        if target_type != "blueprint":
            state = self.get_target_state(target_type=target_type, target_id=target_id)
            if not state.exists:
                issues.append(f"target_not_found:{target_id}")
        resource_index = self.resource_index()
        for resource_id in resource_ids:
            if resource_id not in resource_index:
                issues.append(f"resource_not_found:{resource_id}")
        return ValidateResult(
            target_type=target_type,
            target_id=target_id,
            connector="container",
            valid=not issues,
            issues=issues,
        )
