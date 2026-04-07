"""
Storage Broker — Provisioner
══════════════════════════════
Creates managed service directory structures on approved zones.

Rules:
- ALWAYS uses os.path.realpath() before any write — prevents path traversal.
- Idempotent: calling multiple times has no side effects.
- dry_run=True (default): returns what WOULD be created, touches nothing.
- Only writes inside zones confirmed as managed_rw.
"""

import os
import logging
from typing import List, Optional
import requests
from .models import ProvisionResult, ZONE_CAPABILITIES
from .policy import validate_path, _safe_realpath, get_policy

log = logging.getLogger(__name__)
HOST_HELPER_URL = str(os.environ.get("STORAGE_HOST_HELPER_URL", "http://storage-host-helper:8090") or "").strip().rstrip("/")

# Standard directory profiles
PROFILES: dict = {
    "standard": ["config", "data", "logs"],
    "full":     ["config", "data", "logs", "workspace", "backups", "tmp"],
    "minimal":  ["data"],
    "backup":   ["backups"],
}

# Managed base paths per zone (populated from env)
def _managed_bases() -> List[str]:
    policy = get_policy()
    config_bases = [_safe_realpath(p) for p in getattr(policy, "managed_bases", []) if p]
    env_raw = os.environ.get("STORAGE_MANAGED_BASES", "")
    env_bases = [_safe_realpath(p) for p in env_raw.split(":") if p.strip()]
    return list(dict.fromkeys(config_bases + env_bases))


def _zone_base(zone: str) -> Optional[str]:
    """Return the configured base path for a zone (or None)."""
    env_key = f"STORAGE_ZONE_{zone.upper()}_BASE"
    raw = os.environ.get(env_key, "")
    if raw:
        return _safe_realpath(raw.strip())
    # Fallback: first managed base
    bases = _managed_bases()
    return bases[0] if bases else None


def _host_helper_post(path: str, payload: dict, timeout: int = 30) -> dict:
    base = str(HOST_HELPER_URL or "").strip().rstrip("/")
    if not base:
        return {"ok": False, "error": "storage-host-helper not configured"}
    try:
        response = requests.post(f"{base}{path}", json=payload, timeout=timeout)
    except Exception as exc:
        return {"ok": False, "error": f"storage-host-helper unreachable: {exc}"}
    try:
        data = response.json()
    except Exception:
        data = {}
    if not response.ok:
        detail = ""
        if isinstance(data, dict):
            detail = str(data.get("detail") or data.get("error") or "").strip()
        if not detail:
            detail = (response.text or "").strip() or f"HTTP {response.status_code}"
        return {"ok": False, "error": detail}
    return data if isinstance(data, dict) else {"ok": False, "error": "invalid host-helper response"}


def _host_path_exists(path: str) -> bool:
    helper_result = _host_helper_post("/v1/path-exists", {"path": path}, timeout=10)
    if helper_result.get("ok") is True:
        return bool(helper_result.get("exists"))
    try:
        return os.path.exists(path)
    except Exception:
        return False


def _casaos_alias_base() -> Optional[str]:
    raw = str(os.environ.get("STORAGE_CASAOS_ALIAS_BASE", "") or "").strip()
    if raw:
        return _safe_realpath(raw)
    if _host_path_exists("/DATA/AppData"):
        return "/DATA/AppData/TRION"
    return None


def _service_alias_path(service_name: str) -> Optional[str]:
    base = _casaos_alias_base()
    if not base:
        return None
    return _safe_realpath(os.path.join(base, service_name))


def create_service_storage(
    service_name: str,
    zone: str,
    profile: str = "standard",
    dry_run: bool = True,
    base_path: str = "",
    owner: str = "",
    group: str = "",
) -> ProvisionResult:
    """
    Create a managed directory structure for a service inside a zone.

    Guarantees:
    - zone must be managed_rw-capable (managed_services or backup)
    - All paths validated via realpath before any mkdir
    - Idempotent (exist_ok=True)
    - dry_run=True → no filesystem changes, returns preview only
    """
    result = ProvisionResult(
        service_name=service_name,
        zone=zone,
        profile=profile,
        dry_run=dry_run,
        base_path=str(base_path or "").strip(),
        owner=str(owner or "").strip(),
        group=str(group or "").strip(),
    )

    # Check zone capability
    if "create_service_storage" not in ZONE_CAPABILITIES.get(zone, []):
        result.errors.append(
            f"Zone '{zone}' does not support create_service_storage. "
            f"Allowed zones: managed_services, backup"
        )
        result.ok = False
        return result

    requested_base = _safe_realpath(str(base_path or "").strip()) if str(base_path or "").strip() else ""
    if requested_base:
        vr = validate_path(requested_base)
        if not vr.valid:
            result.errors.append(f"Requested base '{requested_base}' is not in a managed_rw zone: {vr.reason}")
            result.ok = False
            return result
        base = requested_base
    else:
        base = _zone_base(zone)
    if not base:
        result.errors.append(
            f"No base path configured for zone '{zone}'. "
            "Set STORAGE_ZONE_MANAGED_SERVICES_BASE or STORAGE_MANAGED_BASES env var."
        )
        result.ok = False
        return result

    # Validate base is reachable and accessible
    vr = validate_path(base)
    if not vr.valid:
        result.errors.append(f"Zone base '{base}' is not in a managed_rw zone: {vr.reason}")
        result.ok = False
        return result

    # Build service dir path
    service_root = _safe_realpath(os.path.join(base, "services", service_name))
    result.target_base = service_root

    # Path escape check (service_name could contain ../)
    expected_prefix = _safe_realpath(os.path.join(base, "services")) + "/"
    if not service_root.startswith(expected_prefix):
        result.errors.append(
            f"Path escape detected: service_name '{service_name}' resolves outside zone base."
        )
        result.ok = False
        return result

    subdirs = PROFILES.get(profile, PROFILES["standard"])
    paths_to_create = [service_root] + [
        os.path.join(service_root, d) for d in subdirs
    ]
    result.paths_to_create = paths_to_create
    alias_path = _service_alias_path(service_name)
    if alias_path:
        result.aliases_to_create = [alias_path]

    if dry_run:
        result.ok = True
        return result

    helper_result = _host_helper_post(
        "/v1/mkdirs",
        {
            "paths": paths_to_create,
            "mode": "0750",
            "owner": str(owner or "").strip(),
            "group": str(group or "").strip(),
        },
        timeout=60,
    )
    if helper_result.get("ok") is True:
        result.created = [str(path) for path in helper_result.get("paths", []) if str(path).strip()]
        if alias_path:
            parent = _safe_realpath(os.path.dirname(alias_path.rstrip("/")) or "/")
            parent_result = _host_helper_post("/v1/mkdirs", {"paths": [parent], "mode": "0755"}, timeout=30)
            if parent_result.get("ok") is True:
                alias_result = _host_helper_post(
                    "/v1/ensure-symlink",
                    {"target": service_root, "link_path": alias_path, "replace": True},
                    timeout=30,
                )
                if alias_result.get("ok") is True:
                    result.aliases_created = [alias_path]
                else:
                    result.warnings.append(
                        f"CasaOS alias not created for '{alias_path}': {alias_result.get('error') or 'unknown error'}"
                    )
            else:
                result.warnings.append(
                    f"CasaOS alias parent not created for '{alias_path}': {parent_result.get('error') or 'unknown error'}"
                )
        result.ok = True
        return result

    helper_error = str(helper_result.get("error") or "").strip()
    if helper_error:
        log.warning("[Provisioner] host-helper mkdirs failed, falling back to local fs: %s", helper_error)

    # Fallback for local/dev environments where service paths are container-local.
    for p in paths_to_create:
        try:
            os.makedirs(p, mode=0o750, exist_ok=True)
            result.created.append(p)
            log.info(f"[Provisioner] Created: {p}")
        except Exception as e:
            err = f"mkdir failed for '{p}': {e}"
            result.errors.append(err)
            log.error(f"[Provisioner] {err}")

    if alias_path and not result.errors:
        try:
            os.makedirs(os.path.dirname(alias_path.rstrip("/")) or "/", mode=0o755, exist_ok=True)
            if os.path.islink(alias_path):
                if os.path.realpath(alias_path) != service_root:
                    os.unlink(alias_path)
            elif os.path.exists(alias_path):
                result.warnings.append(f"CasaOS alias path already exists and is not a symlink: {alias_path}")
            if not os.path.exists(alias_path):
                os.symlink(service_root, alias_path)
            if os.path.islink(alias_path):
                result.aliases_created.append(alias_path)
        except Exception as exc:
            result.warnings.append(f"CasaOS alias not created for '{alias_path}': {exc}")

    result.ok = len(result.errors) == 0
    return result


def list_managed_paths() -> List[str]:
    """Return all existing service directories under managed zones."""
    found: List[str] = []
    for base in _managed_bases():
        services_dir = os.path.join(base, "services")
        helper_result = _host_helper_post("/v1/listdir", {"path": services_dir}, timeout=30)
        if helper_result.get("ok") is True:
            entries = [str(path) for path in helper_result.get("entries", []) if str(path).strip()]
            found.extend(entries)
            continue
        if helper_result.get("error"):
            log.warning("[Provisioner] host-helper listdir failed for %s: %s", services_dir, helper_result.get("error"))
        if not os.path.isdir(services_dir):
            continue
        try:
            for entry in os.scandir(services_dir):
                if entry.is_dir():
                    found.append(entry.path)
        except Exception as e:
            log.warning(f"[Provisioner] scan failed for {services_dir}: {e}")
    return sorted(found)
