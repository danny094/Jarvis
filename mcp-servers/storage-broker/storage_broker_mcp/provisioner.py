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
from .models import ProvisionResult, ZONE_CAPABILITIES
from .policy import validate_path, _safe_realpath, get_policy

log = logging.getLogger(__name__)

# Standard directory profiles
PROFILES: dict = {
    "standard": ["config", "data", "logs"],
    "full":     ["config", "data", "logs", "workspace", "backups", "tmp"],
    "minimal":  ["data"],
    "backup":   ["backups"],
}

# Managed base paths per zone (populated from env)
def _managed_bases() -> List[str]:
    raw = os.environ.get("STORAGE_MANAGED_BASES", "")
    return [_safe_realpath(p) for p in raw.split(":") if p.strip()]


def _zone_base(zone: str) -> Optional[str]:
    """Return the configured base path for a zone (or None)."""
    env_key = f"STORAGE_ZONE_{zone.upper()}_BASE"
    raw = os.environ.get(env_key, "")
    if raw:
        return _safe_realpath(raw.strip())
    # Fallback: first managed base
    bases = _managed_bases()
    return bases[0] if bases else None


def create_service_storage(
    service_name: str,
    zone: str,
    profile: str = "standard",
    dry_run: bool = True,
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
    )

    # Check zone capability
    if "create_service_storage" not in ZONE_CAPABILITIES.get(zone, []):
        result.errors.append(
            f"Zone '{zone}' does not support create_service_storage. "
            f"Allowed zones: managed_services, backup"
        )
        result.ok = False
        return result

    # Resolve base
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

    if dry_run:
        result.ok = True
        return result

    # Actual creation
    for p in paths_to_create:
        try:
            os.makedirs(p, mode=0o750, exist_ok=True)
            result.created.append(p)
            log.info(f"[Provisioner] Created: {p}")
        except Exception as e:
            err = f"mkdir failed for '{p}': {e}"
            result.errors.append(err)
            log.error(f"[Provisioner] {err}")

    result.ok = len(result.errors) == 0
    return result


def list_managed_paths() -> List[str]:
    """Return all existing service directories under managed zones."""
    found: List[str] = []
    for base in _managed_bases():
        services_dir = os.path.join(base, "services")
        if not os.path.isdir(services_dir):
            continue
        try:
            for entry in os.scandir(services_dir):
                if entry.is_dir():
                    found.append(entry.path)
        except Exception as e:
            log.warning(f"[Provisioner] scan failed for {services_dir}: {e}")
    return sorted(found)
