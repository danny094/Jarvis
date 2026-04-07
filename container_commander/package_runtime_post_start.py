"""
Package runtime post-start hooks
================================

Runtime package hooks that need a running container, for example to write
app-specific configuration based on dynamic mounts.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .models import Blueprint
from .package_runtime_views import _filestash_connections_payload, _list_broker_assets


def _exec_shell(container: Any, script: str) -> tuple[int, str]:
    result = container.exec_run(cmd=["/bin/sh", "-lc", str(script or "")], demux=False)
    raw = result.output or b""
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    return int(result.exit_code or 0), text


def _sync_filestash_connections(container: Any, *, connections: List[Dict[str, Any]]) -> None:
    code, output = _exec_shell(
        container,
        "cat /app/data/state/config/config.json 2>/dev/null || printf '{}'",
    )
    if code != 0:
        raise RuntimeError(f"filestash_config_read_failed: {output.strip() or code}")

    try:
        config = json.loads(output or "{}")
    except Exception:
        config = {}
    if not isinstance(config, dict):
        config = {}
    general = dict(config.get("general") or {})
    if not str(general.get("secret_key") or "").strip():
        general["secret_key"] = "trion-filestash"
    config["general"] = general

    existing = list(config.get("connections") or [])
    keep = [item for item in existing if isinstance(item, dict) and not bool(item.get("trion_managed"))]
    config["connections"] = keep + list(connections or [])

    payload = json.dumps(config, ensure_ascii=True, indent=4)
    script = (
        "mkdir -p /app/data/state/config\n"
        "cat > /app/data/state/config/config.json <<'EOF'\n"
        f"{payload}\n"
        "EOF\n"
    )
    code, output = _exec_shell(container, script)
    if code != 0:
        raise RuntimeError(f"filestash_config_write_failed: {output.strip() or code}")


def run_package_runtime_post_start(
    blueprint_id: str,
    bp: Blueprint,
    manifest: Dict[str, Any] | None,
    container: Any,
) -> List[dict]:
    package_manifest = dict(manifest or {})
    runtime_views = package_manifest.get("runtime_storage_views")
    if not isinstance(runtime_views, dict):
        return []

    broker_assets_cfg = runtime_views.get("broker_assets")
    if not isinstance(broker_assets_cfg, dict) or broker_assets_cfg.get("enabled") is False:
        return []

    connection_mode = str(broker_assets_cfg.get("connection_mode") or "").strip().lower()
    if connection_mode != "filestash_local":
        return []

    container_root = str(broker_assets_cfg.get("container_root") or "/srv/storage-broker").strip()
    if not container_root.startswith("/"):
        container_root = "/srv/storage-broker"
    published_only = bool(broker_assets_cfg.get("published_only", True))
    source_kinds = {
        str(item or "").strip().lower()
        for item in list(broker_assets_cfg.get("source_kinds") or [])
        if str(item or "").strip()
    } or {"service_dir", "existing_path", "import"}
    label_prefix = str(broker_assets_cfg.get("label_prefix") or "TRION /").strip()

    assets = _list_broker_assets(published_only=published_only, source_kinds=source_kinds)
    _mounts, connections = _filestash_connections_payload(
        assets=assets,
        container_root=container_root,
        label_prefix=(f"{label_prefix} " if label_prefix and not label_prefix.endswith(" ") else label_prefix),
    )
    _sync_filestash_connections(container, connections=connections)
    return []
