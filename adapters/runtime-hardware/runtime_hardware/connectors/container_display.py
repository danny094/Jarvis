from __future__ import annotations

import os
import re
from typing import Dict, Iterable, List

from runtime_hardware.models import HardwareResource


_TECHNICAL_BLOCK_PREFIXES = ("dm-", "loop", "ram", "zram", "md")
_MIN_SIMPLE_BLOCK_PARTITION_SIZE_BYTES = 1024 * 1024 * 1024
_GENERIC_INPUT_LABELS = {
    "mouse passthrough",
    "mouse passthrough (absolute)",
    "keyboard passthrough",
    "power button",
}


def enrich_container_resources_for_simple_display(resources: List[HardwareResource]) -> List[HardwareResource]:
    for resource in resources:
        _apply_base_display_metadata(resource)
    _apply_input_grouping(resources)
    return resources


def _apply_base_display_metadata(resource: HardwareResource) -> None:
    metadata = dict(resource.metadata or {})
    technical_label = str(metadata.get("technical_label") or resource.label or "").strip()
    host_path = str(resource.host_path or "").strip()

    metadata["technical_label"] = technical_label
    metadata["display_name"] = _display_name_for_resource(resource)
    metadata["display_badges"] = _display_badges_for_resource(resource)
    metadata["display_secondary"] = _display_secondary_for_resource(resource)
    metadata["simple_visibility"] = _simple_visibility_for_resource(resource)
    metadata["simple_select_resource_ids"] = [resource.id]
    metadata["simple_group_id"] = resource.id
    metadata["simple_group_label"] = str(metadata["display_name"])
    metadata["simple_group_member_ids"] = [resource.id]
    metadata["technical_summary"] = technical_label or host_path
    resource.metadata = metadata


def _apply_input_grouping(resources: List[HardwareResource]) -> None:
    grouped: Dict[str, List[HardwareResource]] = {}
    for resource in resources:
        if str(resource.kind) != "input":
            continue
        metadata = dict(resource.metadata or {})
        if str(metadata.get("simple_visibility") or "").strip().lower() == "hidden":
            continue
        key = _input_group_key(resource)
        grouped.setdefault(key, []).append(resource)

    for group_key, members in grouped.items():
        if not members:
            continue
        if len(members) == 1:
            member = members[0]
            metadata = dict(member.metadata or {})
            metadata["simple_group_id"] = group_key
            metadata["simple_group_label"] = metadata.get("display_name") or member.label
            metadata["simple_group_member_ids"] = [member.id]
            metadata["simple_select_resource_ids"] = [member.id]
            member.metadata = metadata
            continue

        members.sort(key=_input_group_sort_key)
        primary = members[0]
        member_ids = [item.id for item in members]
        channels = sorted(
            {
                _input_channel_label(item)
                for item in members
                if _input_channel_label(item)
            }
        )
        channel_hint = ", ".join(channels[:3])
        for index, member in enumerate(members):
            metadata = dict(member.metadata or {})
            metadata["simple_group_id"] = group_key
            metadata["simple_group_label"] = metadata.get("display_name") or primary.label
            metadata["simple_group_member_ids"] = list(member_ids)
            metadata["simple_select_resource_ids"] = list(member_ids)
            metadata["simple_group_primary"] = index == 0
            if index > 0:
                metadata["simple_visibility"] = "hidden"
            member.metadata = metadata

        primary_metadata = dict(primary.metadata or {})
        if channel_hint:
            secondary = str(primary_metadata.get("display_secondary") or "").strip()
            parts = [part for part in [secondary, f"Kanaele: {channel_hint}"] if part]
            primary_metadata["display_secondary"] = " · ".join(parts)
        primary_metadata["simple_visibility"] = "visible"
        primary.metadata = primary_metadata


def _display_name_for_resource(resource: HardwareResource) -> str:
    if str(resource.kind) == "block_device_ref":
        return _block_display_name(resource)
    if str(resource.kind) == "input":
        return _input_display_name(resource)
    if str(resource.kind) == "usb":
        return _usb_display_name(resource)
    if str(resource.kind) == "device":
        return _device_display_name(resource)
    if str(resource.kind) == "mount_ref":
        label = str(resource.label or "").strip()
        return label or "Managed Storage"
    return str(resource.label or resource.host_path or "Hardware").strip() or "Hardware"


def _display_badges_for_resource(resource: HardwareResource) -> List[str]:
    badges: List[str] = []
    metadata = dict(resource.metadata or {})
    kind = str(resource.kind or "").strip()
    role = _input_role(resource) if kind == "input" else ""
    if kind == "input" and role:
        badges.append(_title_case(role))
    elif kind == "usb":
        badges.append("USB")
        usb_role = _usb_role(resource)
        if usb_role:
            badges.append(_title_case(usb_role))
    elif kind == "block_device_ref":
        disk_type = str(metadata.get("disk_type") or "").strip().lower()
        if disk_type == "part":
            badges.append("Partition")
        elif disk_type == "disk":
            badges.append("Datentraeger")
    elif kind == "mount_ref":
        badges.append("Storage")

    if _is_system_resource(resource):
        badges.append("Systemkritisch")
    elif _is_external_resource(resource):
        badges.append("Extern")
    elif _is_internal_resource(resource):
        badges.append("Intern")

    if kind == "block_device_ref":
        policy_state = str(metadata.get("policy_state") or "").strip().lower()
        if policy_state == "managed_rw":
            badges.append("Managed")
        elif policy_state == "read_only":
            badges.append("Read-only")
    return badges


def _display_secondary_for_resource(resource: HardwareResource) -> str:
    metadata = dict(resource.metadata or {})
    kind = str(resource.kind or "").strip()
    parts: List[str] = []

    if kind == "input":
        vendor_product = _vendor_product(resource)
        if vendor_product and vendor_product != metadata.get("display_name"):
            parts.append(vendor_product)
        technical = str(metadata.get("technical_label") or "").strip()
        if technical and technical.lower() not in _GENERIC_INPUT_LABELS and technical != metadata.get("display_name"):
            parts.append(technical)
        return " · ".join(_unique(parts))

    if kind == "usb":
        vendor_product = _vendor_product(resource)
        if vendor_product:
            parts.append(vendor_product)
        technical = str(metadata.get("technical_label") or "").strip()
        if technical and technical != metadata.get("display_name"):
            parts.append(technical)
        return " · ".join(_unique(parts))

    if kind == "block_device_ref":
        filesystem = str(metadata.get("filesystem") or "").strip().upper()
        if filesystem:
            parts.append(filesystem)
        size_label = _format_size_label(int(metadata.get("size_bytes") or metadata.get("size_bytes_estimate") or 0))
        if size_label:
            parts.append(size_label)
        mountpoint = str(metadata.get("mountpoint") or "").strip()
        if mountpoint:
            parts.append(mountpoint)
        elif resource.host_path:
            parts.append(str(resource.host_path))
        return " · ".join(_unique(parts))

    if kind == "mount_ref":
        source_disk_label = str(metadata.get("source_disk_label") or "").strip()
        if source_disk_label:
            parts.append(source_disk_label)
        filesystem = str(metadata.get("filesystem") or "").strip().upper()
        if filesystem:
            parts.append(filesystem)
        size_label = _format_size_label(int(metadata.get("size_bytes") or 0))
        if size_label:
            parts.append(size_label)
        available_label = _format_available_label(int(metadata.get("available_bytes") or 0))
        if available_label:
            parts.append(available_label)
        if resource.host_path:
            parts.append(str(resource.host_path))
        policy_state = str(metadata.get("policy_state") or "").strip()
        if policy_state:
            parts.append(policy_state)
        return " · ".join(_unique(parts))

    vendor_product = _vendor_product(resource)
    if vendor_product:
        parts.append(vendor_product)
    if resource.host_path:
        parts.append(str(resource.host_path))
    return " · ".join(_unique(parts))


def _simple_visibility_for_resource(resource: HardwareResource) -> str:
    metadata = dict(resource.metadata or {})
    kind = str(resource.kind or "").strip()
    technical_label = str(metadata.get("technical_label") or resource.label or "").strip().lower()
    host_base = os.path.basename(str(resource.host_path or "").strip())

    if kind == "input":
        if _should_hide_input_from_simple(resource):
            return "hidden"
    if kind == "block_device_ref":
        if _is_system_resource(resource):
            return "hidden"
        if _is_technical_block_name(host_base) or _is_technical_block_name(technical_label):
            return "hidden"
        if str(metadata.get("storage_source") or "").strip() != "storage_broker":
            return "hidden"
        disk_type = str(metadata.get("disk_type") or "").strip().lower()
        size_bytes = int(metadata.get("size_bytes") or metadata.get("size_bytes_estimate") or 0)
        if disk_type == "part" and size_bytes > 0 and size_bytes < _MIN_SIMPLE_BLOCK_PARTITION_SIZE_BYTES:
            return "hidden"
        if disk_type == "disk" and not _is_external_resource(resource):
            return "hidden"
    if kind == "usb":
        if _is_usb_hub(resource):
            return "hidden"
    return "visible"


def _input_group_key(resource: HardwareResource) -> str:
    metadata = dict(resource.metadata or {})
    sysfs_group = _normalized_input_group_path(str(metadata.get("input_device_path") or "").strip())
    if sysfs_group:
        return f"input::{sysfs_group}"
    role = _input_role(resource) or "input"
    vendor_product = _vendor_product(resource).lower()
    display_name = str(metadata.get("display_name") or resource.label or resource.host_path or "").strip().lower()
    path_hint = _normalized_input_group_path(_path_hints(resource))
    if path_hint:
        return f"input::{role}::{path_hint}"
    return f"input::{role}::{vendor_product}::{display_name}"


def _input_group_sort_key(resource: HardwareResource) -> tuple[int, int, str]:
    host_path = str(resource.host_path or "")
    caps = set(str(item).lower() for item in list(resource.capabilities or []))
    return (
        0 if host_path.startswith("/dev/input/event") else 1,
        0 if "keyboard" in caps or "mouse" in caps or "joystick" in caps else 1,
        host_path,
    )


def _input_display_name(resource: HardwareResource) -> str:
    metadata = dict(resource.metadata or {})
    vendor_product = _vendor_product(resource)
    role = _input_role(resource)
    technical = str(metadata.get("technical_label") or resource.label or "").strip()
    normalized_technical = technical.lower()

    if vendor_product:
        return vendor_product
    if role == "power":
        return "Power Button"
    if _is_monitor_audio_input(technical):
        if "nvidia" in _normalize_lookup_text(technical):
            return "Monitor-Audio (NVIDIA)"
        return "Monitor-Audio"
    if normalized_technical in _GENERIC_INPUT_LABELS or not technical:
        if role == "keyboard":
            return "Tastatur"
        if role == "mouse":
            return "Maus"
        if role == "touchpad":
            return "Touchpad"
        if role == "joystick":
            return "Gamepad / Controller"
        return "Eingabegeraet"
    return technical


def _usb_display_name(resource: HardwareResource) -> str:
    metadata = dict(resource.metadata or {})
    vendor_product = _vendor_product(resource)
    technical = str(metadata.get("technical_label") or resource.label or "").strip()
    normalized = technical.lower()

    if vendor_product:
        return vendor_product
    role = _usb_role(resource)
    if role == "kamera":
        return "USB-Kamera"
    if role == "audio":
        return "USB-Audiogeraet"
    if role == "bluetooth":
        return "Bluetooth-Adapter"
    if role == "empfaenger":
        return "USB-Empfaenger"
    if role == "controller":
        return "USB-Controller"
    if role == "speicher":
        return "USB-Speicher"
    if role == "hub":
        return "USB-Hub"
    return technical or "USB-Geraet"


def _device_display_name(resource: HardwareResource) -> str:
    host_path = str(resource.host_path or "").strip().lower()
    if host_path.startswith("/dev/dri/"):
        base = os.path.basename(host_path)
        if base.startswith("render"):
            return "GPU Render-Zugriff"
        if base.startswith("card"):
            return "GPU Device"
    if host_path == "/dev/kvm":
        return "KVM Virtualisierung"
    if host_path == "/dev/uinput":
        return "Virtuelles Input-Device"
    if host_path == "/dev/vfio/vfio":
        return "VFIO Zugriff"
    return str(resource.label or resource.host_path or "Device").strip() or "Device"


def _block_display_name(resource: HardwareResource) -> str:
    metadata = dict(resource.metadata or {})
    label = str(resource.label or "").strip()
    disk_type = str(metadata.get("disk_type") or "").strip().lower()
    technical = str(metadata.get("technical_label") or label or "").strip()
    mountpoint = str(metadata.get("mountpoint") or "").strip()
    policy_state = str(metadata.get("policy_state") or "").strip().lower()
    partition_index = _block_partition_index(resource)

    if label and not _is_raw_block_device_name(label) and not _is_technical_block_name(label):
        return label
    if disk_type == "part":
        if mountpoint == "/data":
            return "Service-Speicher"
        if mountpoint and mountpoint not in {"/", "/home"}:
            return f"Speicherpfad {mountpoint}"
        if _is_external_resource(resource):
            return f"Externe Partition {partition_index}" if partition_index else "Externe Partition"
        if policy_state == "managed_rw":
            return f"Managed Partition {partition_index}" if partition_index else "Managed Partition"
        if policy_state == "read_only":
            return f"Read-only Partition {partition_index}" if partition_index else "Read-only Partition"
        return f"Interne Partition {partition_index}" if partition_index else "Interne Partition"
    if disk_type == "disk":
        if _is_external_resource(resource):
            return "Externer Datentraeger"
        if policy_state == "managed_rw":
            return "Managed Datentraeger"
        return "Interner Datentraeger"
    if _is_external_resource(resource):
        return "Externes Block-Device"
    return technical or "Block-Device"


def _input_role(resource: HardwareResource) -> str:
    caps = {str(item).lower() for item in list(resource.capabilities or [])}
    technical = str(dict(resource.metadata or {}).get("technical_label") or resource.label or "").strip().lower()
    if "keyboard" in caps:
        return "keyboard"
    if "mouse" in caps:
        return "mouse"
    if "touchpad" in caps:
        return "touchpad"
    if "joystick" in caps:
        return "joystick"
    if "power button" in technical:
        return "power"
    return "input"


def _input_channel_label(resource: HardwareResource) -> str:
    technical = str(dict(resource.metadata or {}).get("technical_label") or resource.label or "").strip().lower()
    host_path = str(resource.host_path or "").strip().lower()
    if "absolute" in technical:
        return "absolute"
    if host_path.startswith("/dev/input/js"):
        return "joystick"
    if host_path.startswith("/dev/input/event"):
        return "event"
    return ""


def _vendor_product(resource: HardwareResource) -> str:
    vendor = str(resource.vendor or "").strip()
    product = str(resource.product or "").strip()
    if vendor and product:
        return f"{vendor} {product}".strip()
    return product or vendor


def _usb_role(resource: HardwareResource) -> str:
    metadata = dict(resource.metadata or {})
    technical = " ".join(
        [
            str(metadata.get("technical_label") or ""),
            str(resource.label or ""),
            str(resource.vendor or ""),
            str(resource.product or ""),
            str(metadata.get("ID_USB_DRIVER") or ""),
            str(metadata.get("ID_USB_INTERFACES") or ""),
        ]
    ).strip().lower()
    normalized = _normalize_lookup_text(technical)
    if _contains_lookup_term(normalized, "root hub") or _contains_lookup_term(normalized, "usb hub") or _contains_lookup_term(normalized, "hub"):
        return "hub"
    if any(_contains_lookup_term(normalized, token) for token in ("camera", "webcam", "facetime", "uvc")):
        return "kamera"
    if any(_contains_lookup_term(normalized, token) for token in ("audio", "headset", "microphone", "speaker", "sound")):
        return "audio"
    if _contains_lookup_term(normalized, "bluetooth") or _contains_lookup_term(normalized, "bluetooth radio"):
        return "bluetooth"
    if any(_contains_lookup_term(normalized, token) for token in ("receiver", "dongle", "transceiver")):
        return "empfaenger"
    if any(_contains_lookup_term(normalized, token) for token in ("controller", "gamepad", "joystick")):
        return "controller"
    if any(_contains_lookup_term(normalized, token) for token in ("storage", "flash", "mass storage", "disk", "ssd", "drive", "sata bridge", "sata")):
        return "speicher"
    if any(_contains_lookup_term(normalized, token) for token in ("keyboard", "mouse")):
        return "eingabe"
    return ""


def _is_technical_block_name(value: str) -> bool:
    item = str(value or "").strip().lower()
    if not item:
        return False
    return item.startswith(_TECHNICAL_BLOCK_PREFIXES)


def _is_raw_block_device_name(value: str) -> bool:
    item = str(value or "").strip().lower()
    if not item:
        return False
    patterns = (
        r"^sd[a-z]+\d*$",
        r"^vd[a-z]+\d*$",
        r"^xvd[a-z]+\d*$",
        r"^nvme\d+n\d+(p\d+)?$",
        r"^mmcblk\d+(p\d+)?$",
    )
    return any(re.match(pattern, item) for pattern in patterns)


def _block_partition_index(resource: HardwareResource) -> str:
    candidates = [
        str(resource.host_path or "").strip().lower(),
        str(resource.label or "").strip().lower(),
        str(dict(resource.metadata or {}).get("disk_id") or "").strip().lower(),
    ]
    patterns = (
        r"^/dev/sd[a-z]+(\d+)$",
        r"^/dev/vd[a-z]+(\d+)$",
        r"^/dev/xvd[a-z]+(\d+)$",
        r"^/dev/nvme\d+n\d+p(\d+)$",
        r"^/dev/mmcblk\d+p(\d+)$",
        r"^sd[a-z]+(\d+)$",
        r"^vd[a-z]+(\d+)$",
        r"^xvd[a-z]+(\d+)$",
        r"^nvme\d+n\d+p(\d+)$",
        r"^mmcblk\d+p(\d+)$",
    )
    for candidate in candidates:
        for pattern in patterns:
            match = re.match(pattern, candidate)
            if match:
                return str(match.group(1) or "").strip()
    return ""


def _is_system_resource(resource: HardwareResource) -> bool:
    metadata = dict(resource.metadata or {})
    return bool(metadata.get("is_system")) or "systemkritisch" in [str(item).strip().lower() for item in metadata.get("display_badges") or []]


def _is_external_resource(resource: HardwareResource) -> bool:
    metadata = dict(resource.metadata or {})
    if metadata.get("is_external") is True:
        return True
    technical = str(metadata.get("technical_label") or resource.label or "").strip().lower()
    if str(resource.kind) == "usb":
        role = _usb_role(resource)
        if role == "hub":
            return False
        if any(token in technical for token in ("bluetooth", "webcam", "camera", "fingerprint", "integrated", "internal", "built-in", "builtin")):
            return False
        if _path_hints(resource).find("platform-") >= 0:
            return False
        return True
    if str(resource.kind) == "input":
        if _is_internal_resource(resource):
            return False
        return str(metadata.get("ID_BUS") or "").strip().lower() == "usb"
    if str(resource.kind) == "block_device_ref":
        return "removable" in list(resource.capabilities or [])
    return False


def _is_internal_resource(resource: HardwareResource) -> bool:
    metadata = dict(resource.metadata or {})
    if metadata.get("is_external") is True:
        return False
    technical = str(metadata.get("technical_label") or resource.label or "").strip().lower()
    path_hints = _path_hints(resource)
    if str(resource.kind) == "device":
        return True
    if str(resource.kind) == "block_device_ref":
        return bool(metadata.get("is_system")) or "fixed" in list(resource.capabilities or [])
    if str(resource.kind) == "usb":
        if _usb_role(resource) == "hub":
            return True
        if any(token in technical for token in ("bluetooth", "webcam", "camera", "fingerprint", "integrated", "internal", "built-in", "builtin")):
            return True
    if any(token in technical for token in ("power button", "touchpad", "at translated", "laptop", "internal")):
        return True
    if "platform-" in path_hints or "pci-" in path_hints:
        return True
    return False


def _is_usb_hub(resource: HardwareResource) -> bool:
    return str(resource.kind) == "usb" and _usb_role(resource) == "hub"


def _path_hints(resource: HardwareResource) -> str:
    metadata = dict(resource.metadata or {})
    return " ".join(
        [
            str(metadata.get("ID_PATH") or ""),
            str(metadata.get("ID_PATH_TAG") or ""),
            str(metadata.get("input_device_path") or ""),
        ]
    ).lower()


def _format_size_label(size_bytes: int) -> str:
    if size_bytes <= 0:
        return ""
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    value = float(size_bytes)
    unit_index = 0
    while value >= 1024.0 and unit_index < len(units) - 1:
        value /= 1024.0
        unit_index += 1
    if unit_index == 0:
        return f"{int(value)} {units[unit_index]}"
    return f"{value:.1f} {units[unit_index]}"


def _format_available_label(size_bytes: int) -> str:
    label = _format_size_label(size_bytes)
    if not label:
        return ""
    return f"{label} frei"


def _should_hide_input_from_simple(resource: HardwareResource) -> bool:
    role = _input_role(resource)
    technical = str(dict(resource.metadata or {}).get("technical_label") or resource.label or "").strip().lower()
    normalized = _normalize_lookup_text(technical)
    if role == "power":
        return True
    if _is_monitor_audio_input(technical):
        return True
    if any(
        _contains_lookup_term(normalized, token)
        for token in ("hd audio", "video bus", "front mic", "rear mic", "line out", "front headphone", "monitor audio")
    ):
        return True
    return False


def _is_monitor_audio_input(value: str) -> bool:
    normalized = _normalize_lookup_text(value)
    if not normalized:
        return False
    if _contains_lookup_term(normalized, "monitor audio"):
        return True
    if _contains_lookup_term(normalized, "hdmi dp") and (
        _contains_lookup_term(normalized, "hd audio")
        or _contains_lookup_term(normalized, "hda")
        or _contains_lookup_term(normalized, "nvidia")
        or _contains_lookup_term(normalized, "pcm")
    ):
        return True
    return False


def _normalized_input_group_path(value: str) -> str:
    item = str(value or "").strip().lower()
    if not item:
        return ""
    normalized = re.sub(r"/device$", "", item)
    normalized = re.sub(r"/input\d+(?:/.*)?$", "", normalized)
    normalized = re.sub(r"-event(?:-[a-z0-9]+)?$", "", normalized)
    normalized = re.sub(r"-mouse$", "", normalized)
    return normalized.strip()


def _normalize_lookup_text(value: str) -> str:
    return " ".join(part for part in re.split(r"[^a-z0-9]+", str(value or "").lower()) if part)


def _contains_lookup_term(normalized_text: str, term: str) -> bool:
    text = f" {str(normalized_text or '').strip()} "
    needle = f" {_normalize_lookup_text(term)} "
    return bool(needle.strip()) and needle in text


def _title_case(value: str) -> str:
    item = str(value or "").strip()
    if not item:
        return ""
    return item[:1].upper() + item[1:]


def _unique(items: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for item in items:
        normalized = str(item or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
