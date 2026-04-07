"""
Internal helpers for port parsing and user-facing connection metadata.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
from utils.service_endpoint_resolver import resolve_public_endpoint_host


def infer_service_name(container_port: str, blueprint_id: str = "", image_ref: str = "") -> str:
    """Return a compact service label for a port mapping when it is recognizable."""
    raw_port = str(container_port or "").strip().lower()
    if not raw_port:
        return ""
    if "/" in raw_port:
        port_text, proto = raw_port.rsplit("/", 1)
    else:
        port_text, proto = raw_port, "tcp"
    try:
        port_num = int(port_text)
    except Exception:
        return ""

    lower_bp = str(blueprint_id or "").strip().lower()
    lower_image = str(image_ref or "").strip().lower()
    if (
        lower_bp in {"gaming-station", "steam-headless", "gaming_station"}
        or "steam-headless" in lower_image
        or "sunshine" in lower_image
    ):
        sunshine_names = {
            (8083, "tcp"): "Desktop GUI (noVNC)",
            (47984, "tcp"): "Sunshine HTTPS",
            (47989, "tcp"): "Sunshine HTTP",
            (47990, "tcp"): "Sunshine Web UI",
            (48010, "tcp"): "Sunshine RTSP",
            (47998, "udp"): "Sunshine Video",
            (47999, "udp"): "Sunshine Control",
            (48000, "udp"): "Sunshine Audio",
            (48002, "udp"): "Sunshine Mic",
        }
        if (port_num, proto) in sunshine_names:
            return sunshine_names[(port_num, proto)]
        if proto == "udp" and 48100 <= port_num <= 48110:
            return "Game Stream UDP"

    well_known = {
        (22, "tcp"): "SSH",
        (53, "tcp"): "DNS",
        (53, "udp"): "DNS",
        (80, "tcp"): "HTTP",
        (81, "tcp"): "Web UI",
        (110, "tcp"): "POP3",
        (123, "udp"): "NTP",
        (143, "tcp"): "IMAP",
        (443, "tcp"): "HTTPS",
        (445, "tcp"): "SMB",
        (465, "tcp"): "SMTP TLS",
        (587, "tcp"): "SMTP",
        (993, "tcp"): "IMAPS",
        (995, "tcp"): "POP3S",
        (1433, "tcp"): "SQL Server",
        (1521, "tcp"): "Oracle DB",
        (1883, "tcp"): "MQTT",
        (2375, "tcp"): "Docker API",
        (3000, "tcp"): "Web App",
        (3306, "tcp"): "MySQL",
        (3389, "tcp"): "RDP",
        (3478, "udp"): "STUN/TURN",
        (5000, "tcp"): "Registry/API",
        (5432, "tcp"): "PostgreSQL",
        (5672, "tcp"): "RabbitMQ",
        (5900, "tcp"): "VNC",
        (6080, "tcp"): "noVNC",
        (6379, "tcp"): "Redis",
        (7860, "tcp"): "Gradio",
        (8000, "tcp"): "HTTP API",
        (8006, "tcp"): "Web UI",
        (8080, "tcp"): "Web UI",
        (8081, "tcp"): "Admin UI",
        (8123, "tcp"): "Home Assistant",
        (8443, "tcp"): "HTTPS Admin",
        (8501, "tcp"): "Streamlit",
        (9000, "tcp"): "Web Console",
        (9090, "tcp"): "Metrics UI",
        (9443, "tcp"): "HTTPS UI",
        (11434, "tcp"): "Ollama API",
        (27017, "tcp"): "MongoDB",
    }
    return well_known.get((port_num, proto), "")


def infer_access_link_meta(container_port: str, blueprint_id: str = "", image_ref: str = "") -> Dict[str, str]:
    """Return browser-openable access metadata for known web-facing services."""
    raw_port = str(container_port or "").strip().lower()
    if not raw_port:
        return {}
    if "/" in raw_port:
        port_text, proto = raw_port.rsplit("/", 1)
    else:
        port_text, proto = raw_port, "tcp"
    try:
        port_num = int(port_text)
    except Exception:
        return {}

    lower_bp = str(blueprint_id or "").strip().lower()
    lower_image = str(image_ref or "").strip().lower()
    if (
        proto == "tcp"
        and (
            lower_bp in {"gaming-station", "steam-headless", "gaming_station"}
            or "steam-headless" in lower_image
            or "sunshine" in lower_image
        )
    ):
        if port_num == 8083:
            return {
                "access_label": "Open Desktop GUI",
                "access_scheme": "http",
                "access_path": "/web/",
                "access_kind": "desktop_gui",
            }
        if port_num == 47990:
            return {
                "access_label": "Open Sunshine",
                "access_scheme": "https",
                "access_path": "/welcome",
                "access_kind": "web_ui",
            }
        if port_num == 47989:
            return {
                "access_label": "Open Sunshine HTTP",
                "access_scheme": "http",
                "access_path": "/",
                "access_kind": "web_ui",
            }
    return {}


def extract_port_details(attrs: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Parse Docker inspect NetworkSettings.Ports into a stable list.
    """
    result: List[Dict[str, str]] = []
    ports_obj = (((attrs or {}).get("NetworkSettings") or {}).get("Ports") or {})
    config = (attrs or {}).get("Config") or {}
    labels = config.get("Labels") or {}
    blueprint_id = str(labels.get("trion.blueprint") or "").strip().lower()
    image_ref = str(config.get("Image") or "").strip().lower()
    for container_port, bindings in dict(ports_obj).items():
        if not bindings:
            continue
        for binding in bindings:
            result.append(
                {
                    "container_port": str(container_port or ""),
                    "host_ip": str((binding or {}).get("HostIp") or "0.0.0.0"),
                    "host_port": str((binding or {}).get("HostPort") or ""),
                    "service_name": infer_service_name(
                        str(container_port or ""),
                        blueprint_id=blueprint_id,
                        image_ref=image_ref,
                    ),
                    **infer_access_link_meta(
                        str(container_port or ""),
                        blueprint_id=blueprint_id,
                        image_ref=image_ref,
                    ),
                }
            )
    return sorted(result, key=lambda p: (p.get("host_port", ""), p.get("container_port", "")))


def build_connection_info(ip_address: Optional[str], ports: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Build user-facing connection hints for WebUI/MCP responses.
    """
    configured_public_host = str(os.environ.get("TRION_PUBLIC_HOST", "")).strip()
    public_host = configured_public_host
    endpoints: List[str] = []
    access_links: List[Dict[str, str]] = []
    seen_links: set[tuple[str, str, str, str]] = set()
    for port in list(ports or []):
        host_port = str(port.get("host_port") or "").strip()
        container_port = str(port.get("container_port") or "").strip()
        if not host_port:
            continue
        proto = "tcp"
        if "/" in container_port:
            _, proto = container_port.rsplit("/", 1)
        endpoint_host = resolve_public_endpoint_host(
            configured_public_host=configured_public_host,
            host_ip=str(port.get("host_ip") or "").strip(),
        )
        if endpoint_host:
            endpoints.append(f"{endpoint_host}:{host_port}/{proto}")
        access_scheme = str(port.get("access_scheme") or "").strip()
        if access_scheme:
            access_path = str(port.get("access_path") or "/").strip() or "/"
            link_key = (host_port, access_scheme, access_path, str(port.get("access_label") or "").strip())
            if link_key not in seen_links:
                seen_links.add(link_key)
                link_url = ""
                if endpoint_host:
                    link_url = f"{access_scheme}://{endpoint_host}:{host_port}{access_path}"
                access_links.append(
                    {
                        "host_ip": str(port.get("host_ip") or "0.0.0.0"),
                        "host_port": host_port,
                        "container_port": container_port,
                        "service_name": str(port.get("service_name") or "").strip(),
                        "label": str(port.get("access_label") or "Open").strip(),
                        "scheme": access_scheme,
                        "path": access_path,
                        "kind": str(port.get("access_kind") or "").strip(),
                        "url": link_url,
                    }
                )
    return {
        "container_ip": str(ip_address or ""),
        "public_host": public_host,
        "endpoints": endpoints,
        "access_links": access_links,
    }


def merge_host_companion_access_info(
    blueprint_id: str,
    ip_address: Optional[str],
    ports: List[Dict[str, str]],
) -> tuple[List[Dict[str, str]], Dict[str, Any]]:
    merged_ports = list(ports or [])
    connection = build_connection_info(ip_address, merged_ports)
    try:
        from .host_companions import get_host_companion_access_links

        access_links = get_host_companion_access_links(blueprint_id)
    except Exception:
        access_links = []
    if not access_links:
        return merged_ports, connection

    seen_ports = {
        (str(item.get("host_port", "")).strip(), str(item.get("container_port", "")).strip())
        for item in merged_ports
    }
    for link in access_links:
        host_port = str(link.get("host_port", "")).strip()
        container_port = str(link.get("container_port", "")).strip()
        key = (host_port, container_port)
        if not host_port or not container_port or key in seen_ports:
            continue
        seen_ports.add(key)
        merged_ports.append(
            {
                "container_port": container_port,
                "host_ip": str(link.get("host_ip", "0.0.0.0")).strip() or "0.0.0.0",
                "host_port": host_port,
                "service_name": str(link.get("service_name", "")).strip(),
                "access_label": str(link.get("access_label", "Open")).strip() or "Open",
                "access_scheme": str(link.get("access_scheme", "")).strip(),
                "access_path": str(link.get("access_path", "/")).strip() or "/",
                "access_kind": str(link.get("access_kind", "")).strip(),
            }
        )
    return merged_ports, build_connection_info(ip_address, merged_ports)
