"""
Admin API — Storage Broker Settings Routes
══════════════════════════════════════════
Provides the frontend with read/write access to storage broker policy.
Stored in STORAGE_BROKER_SETTINGS_PATH (typically shared with storage-broker policy file).

Endpoints:
  GET  /api/storage-broker/settings      → full policy config
  POST /api/storage-broker/settings      → update policy fields
  GET  /api/storage-broker/disks         → proxy: list_disks from broker
  POST /api/storage-broker/disks/{id}/policy → set zone/policy for one disk/partition
  GET  /api/storage-broker/summary       → proxy: get_summary from broker
  GET  /api/storage-broker/managed-paths → proxy: list_managed_paths from broker
  POST /api/storage-broker/validate-path → proxy: validate_path from broker
  POST /api/storage-broker/provision/service-dir → proxy: create_service_dir from broker
  POST /api/storage-broker/mount         → proxy: mount_device from broker
  POST /api/storage-broker/format        → proxy: format_device from broker
  GET  /api/storage-broker/audit         → proxy: audit_log from broker
"""

import json
import os
import logging
import threading
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from datetime import datetime, timezone

router = APIRouter()
log = logging.getLogger(__name__)

SETTINGS_PATH = os.environ.get("STORAGE_BROKER_SETTINGS_PATH",
                                "/app/data/storage_broker_settings.json")
BROKER_URL    = os.environ.get("STORAGE_BROKER_URL", "http://storage-broker:8089")
_LOCK         = threading.Lock()

# ── Default settings (what the frontend shows) ────────────

_DEFAULT_SETTINGS = {
    "external_default_policy":     "read_only",
    "unknown_mount_default":       "blocked",
    "dry_run_default":             True,
    "requires_approval_for_writes": True,
    "blacklist_extra":             [],
    "managed_bases":               [],
    "zone_overrides":              {},
    "policy_overrides":            {},
    "zone_capability_matrix":      {
        "system":           [],
        "managed_services": ["create_directory", "set_permissions",
                             "assign_to_container", "create_service_storage"],
        "backup":           ["create_directory", "create_service_storage"],
        "external":         ["create_directory"],
        "docker_runtime":   [],
        "unzoned":          [],
    },
}


def _load() -> dict:
    if not os.path.exists(SETTINGS_PATH):
        return dict(_DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_PATH, "r") as f:
            data = json.load(f)
        # Keep unknown keys intact so broker-native fields are not lost on save.
        cfg = dict(data) if isinstance(data, dict) else {}
        for k, v in _DEFAULT_SETTINGS.items():
            cfg.setdefault(k, v)
        return cfg
    except Exception as e:
        log.warning(f"[StorageBroker] Settings load failed: {e}")
        return dict(_DEFAULT_SETTINGS)


def _save(cfg: dict):
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    tmp = SETTINGS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, SETTINGS_PATH)


# ── Proxy helper — MCP JSON-RPC over POST ─────────────────

async def _mcp_call(tool_name: str, args: dict | None = None) -> dict:
    """
    Call a storage-broker MCP tool via JSON-RPC 2.0 POST.
    FastMCP streamable-http returns SSE lines: 'data: {...}'.
    """
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": args or {}},
        "id": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{BROKER_URL}/mcp",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "mcp-session-id": f"admin-api-{tool_name}",
                },
            )
            if r.status_code not in (200, 202):
                log.warning(f"[StorageBroker] {tool_name} → HTTP {r.status_code}")
                return {"error": f"broker returned HTTP {r.status_code}"}

            # FastMCP returns SSE: each response line starts with "data: "
            for line in r.text.splitlines():
                if not line.startswith("data:"):
                    continue
                envelope = json.loads(line[5:].strip())
                result = envelope.get("result", {})
                content = result.get("content", [])
                if content:
                    # Tool result is serialised as text inside content[0]
                    return json.loads(content[0].get("text", "{}"))
                return result  # fallback: return raw result

    except Exception as e:
        log.warning(f"[StorageBroker] MCP call '{tool_name}' failed: {e}")
    return {"error": "storage-broker unreachable"}


# ── Routes ────────────────────────────────────────────────

@router.get("/settings")
async def get_settings():
    """Return current storage broker policy settings."""
    with _LOCK:
        cfg = _load()
    return {"settings": cfg, "updated_at": datetime.now(timezone.utc).isoformat()}


@router.post("/settings")
async def update_settings(request: Request):
    """
    Update storage broker policy settings.
    Allowed keys: external_default_policy, unknown_mount_default,
                  dry_run_default, requires_approval_for_writes,
                  blacklist_extra, managed_bases
    """
    try:
        data = await request.json()
        allowed = {
            "external_default_policy", "unknown_mount_default",
            "dry_run_default", "requires_approval_for_writes",
            "blacklist_extra", "managed_bases",
        }
        valid_policies = {"blocked", "read_only", "managed_rw"}

        with _LOCK:
            cfg = _load()
            for k, v in data.items():
                if k not in allowed:
                    continue
                if k in ("external_default_policy", "unknown_mount_default"):
                    if v not in valid_policies:
                        return JSONResponse(
                            {"error": f"Invalid policy value '{v}' for {k}"},
                            status_code=400,
                        )
                cfg[k] = v
            cfg["updated_at"] = datetime.now(timezone.utc).isoformat()
            _save(cfg)

        return {"ok": True, "settings": cfg}
    except Exception as e:
        log.error(f"[StorageBroker] Settings update failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/disks")
async def get_disks():
    """Proxy: list all disks from storage-broker MCP."""
    return await _mcp_call("storage_list_disks")


@router.post("/disks/{disk_id}/policy")
async def set_disk_policy_route(disk_id: str, request: Request):
    """
    Update zone and/or policy_state for a single disk/partition.
    Body supports:
      - zone: system|managed_services|backup|external|docker_runtime|unzoned
      - policy_state: blocked|read_only|managed_rw
    """
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    zone = str((data or {}).get("zone") or "").strip()
    policy_state = str((data or {}).get("policy_state") or "").strip()
    if not zone and not policy_state:
        return JSONResponse(
            {"error": "Provide at least one of: zone, policy_state"},
            status_code=400,
        )

    allowed_zones = {"system", "managed_services", "backup", "external", "docker_runtime", "unzoned"}
    allowed_policies = {"blocked", "read_only", "managed_rw"}
    if zone and zone not in allowed_zones:
        return JSONResponse({"error": f"Invalid zone '{zone}'"}, status_code=400)
    if policy_state and policy_state not in allowed_policies:
        return JSONResponse({"error": f"Invalid policy_state '{policy_state}'"}, status_code=400)

    results = {}
    errors = []

    if zone:
        zone_result = await _mcp_call("storage_set_disk_zone", {"disk_id": disk_id, "zone": zone})
        results["zone"] = zone_result
        if zone_result.get("error") or zone_result.get("ok") is False:
            errors.append(zone_result.get("error") or "zone update failed")

    if policy_state:
        policy_result = await _mcp_call(
            "storage_set_disk_policy",
            {"disk_id": disk_id, "policy_state": policy_state},
        )
        results["policy_state"] = policy_result
        if policy_result.get("error") or policy_result.get("ok") is False:
            errors.append(policy_result.get("error") or "policy update failed")

    disk_result = await _mcp_call("storage_get_disk", {"disk_id": disk_id})
    if disk_result.get("error"):
        errors.append(disk_result.get("error"))

    return {
        "ok": len(errors) == 0,
        "disk_id": disk_id,
        "results": results,
        "disk": disk_result.get("disk"),
        "errors": errors,
    }


@router.get("/summary")
async def get_summary():
    """Proxy: storage summary from storage-broker MCP."""
    return await _mcp_call("storage_get_summary")


@router.get("/managed-paths")
async def get_managed_paths():
    """Proxy: list managed paths from storage-broker MCP."""
    return await _mcp_call("storage_list_managed_paths")


@router.post("/validate-path")
async def validate_path_route(request: Request):
    """Proxy: validate one path against storage policy."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    path = str((data or {}).get("path") or "").strip()
    if not path:
        return JSONResponse({"error": "path is required"}, status_code=400)

    return await _mcp_call("storage_validate_path", {"path": path})


@router.post("/provision/service-dir")
async def provision_service_dir_route(request: Request):
    """Proxy: preview/apply managed service directory provisioning."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    service_name = str((data or {}).get("service_name") or "").strip()
    zone = str((data or {}).get("zone") or "managed_services").strip() or "managed_services"
    profile = str((data or {}).get("profile") or "standard").strip() or "standard"
    dry_run = bool((data or {}).get("dry_run", True))

    if not service_name:
        return JSONResponse({"error": "service_name is required"}, status_code=400)

    return await _mcp_call(
        "storage_create_service_dir",
        {
            "service_name": service_name,
            "zone": zone,
            "profile": profile,
            "dry_run": dry_run,
        },
    )


@router.post("/mount")
async def mount_device_route(request: Request):
    """Proxy: preview/apply device mount action."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    device = str((data or {}).get("device") or "").strip()
    mountpoint = str((data or {}).get("mountpoint") or "").strip()
    filesystem = str((data or {}).get("filesystem") or "").strip()
    options = str((data or {}).get("options") or "").strip()
    dry_run = bool((data or {}).get("dry_run", True))

    if not device or not mountpoint:
        return JSONResponse(
            {"error": "device and mountpoint are required"},
            status_code=400,
        )

    return await _mcp_call(
        "storage_mount_device",
        {
            "device": device,
            "mountpoint": mountpoint,
            "filesystem": filesystem,
            "options": options,
            "dry_run": dry_run,
        },
    )


@router.post("/format")
async def format_device_route(request: Request):
    """Proxy: preview/apply device format action (destructive)."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    device = str((data or {}).get("device") or "").strip()
    filesystem = str((data or {}).get("filesystem") or "").strip()
    label = str((data or {}).get("label") or "").strip()
    dry_run = bool((data or {}).get("dry_run", True))

    if not device or not filesystem:
        return JSONResponse(
            {"error": "device and filesystem are required"},
            status_code=400,
        )

    return await _mcp_call(
        "storage_format_device",
        {
            "device": device,
            "filesystem": filesystem,
            "label": label,
            "dry_run": dry_run,
        },
    )


@router.get("/audit")
async def get_audit(limit: int = 50):
    """Proxy: storage audit log from storage-broker MCP."""
    return await _mcp_call("storage_audit_log", {"limit": limit})


@router.get("/health")
async def broker_health():
    """Check if storage-broker is reachable via MCP initialize handshake."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.post(
                f"{BROKER_URL}/mcp",
                json={"jsonrpc": "2.0", "method": "initialize",
                      "params": {"protocolVersion": "2024-11-05",
                                 "capabilities": {},
                                 "clientInfo": {"name": "admin-api", "version": "1.0"}},
                      "id": 0},
                headers={"Content-Type": "application/json",
                         "Accept": "application/json, text/event-stream",
                         "mcp-session-id": "admin-api-health"},
            )
            online = r.status_code == 200
    except Exception:
        online = False
    return {"online": online, "url": BROKER_URL}
