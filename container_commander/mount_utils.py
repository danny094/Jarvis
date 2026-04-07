"""
Container Commander — Mount Utilities
======================================
Helpers for bind-mount host directory management.

Kept in a standalone module (no docker dep) so it can be unit-tested
without the full engine import chain.
"""
import logging
import os
import json
from urllib import request as _urlrequest
from urllib import error as _urlerror

logger = logging.getLogger(__name__)

HOST_HELPER_URL = str(
    os.environ.get("STORAGE_HOST_HELPER_URL", "http://storage-host-helper:8090") or ""
).strip().rstrip("/")


def _host_helper_mkdirs(paths, mode: str = "0750") -> dict:
    base = str(HOST_HELPER_URL or "").strip().rstrip("/")
    if not base:
        return {"ok": False, "error": "storage-host-helper not configured"}
    payload = json.dumps({"paths": list(paths or []), "mode": str(mode or "0750")}).encode("utf-8")
    req = _urlrequest.Request(
        f"{base}/v1/mkdirs",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _urlrequest.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw) if raw else {}
            return data if isinstance(data, dict) else {"ok": False, "error": "invalid host-helper response"}
    except _urlerror.HTTPError as exc:
        detail = ""
        try:
            raw = exc.read().decode("utf-8", errors="replace")
            data = json.loads(raw) if raw else {}
            if isinstance(data, dict):
                detail = str(data.get("detail") or data.get("error") or "").strip()
        except Exception:
            detail = ""
        return {"ok": False, "error": detail or f"HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def ensure_bind_mount_host_dirs(mounts) -> None:
    """Pre-create missing bind-mount host directories with safe permissions.

    Docker daemon auto-creates missing bind-mount source directories as
    root:root (uid=0, gid=0, mode=0o755).  Any container running as a
    non-root user will then get Permission Denied when it tries to write
    into that path.

    This function creates missing directories *before* ``docker run`` is
    called, using the current process's user (the TRION service user) with
    mode 0o750.  Directories that already exist are left completely
    untouched.
    """
    missing_paths = []
    for mount in (mounts or []):
        mount_type = str(getattr(mount, "type", "bind") or "bind").strip().lower()
        if mount_type != "bind":
            continue
        host_raw = str(getattr(mount, "host", "") or "").strip()
        if not host_raw:
            continue
        host_abs = os.path.abspath(host_raw)
        if not os.path.exists(host_abs):
            missing_paths.append(host_abs)

    helper_created = set()
    if missing_paths:
        helper_result = _host_helper_mkdirs(missing_paths, mode="0750")
        if helper_result.get("ok") is True:
            helper_created = {
                os.path.abspath(str(path).strip())
                for path in list(helper_result.get("paths", []) or [])
                if str(path).strip()
            }
            if helper_created:
                logger.info(
                    "[MountUtils] Pre-created bind-mount dirs via storage-host-helper: %s",
                    ", ".join(sorted(helper_created)),
                )
        elif helper_result.get("error"):
            logger.warning(
                "[MountUtils] storage-host-helper mkdirs failed, falling back to local fs: %s",
                helper_result.get("error"),
            )

    for host_abs in missing_paths:
        if host_abs in helper_created:
            continue
        if not os.path.exists(host_abs):
            try:
                os.makedirs(host_abs, mode=0o750, exist_ok=True)
                logger.info(
                    f"[MountUtils] Pre-created bind-mount dir: {host_abs} (mode=0o750) "
                    "to prevent Docker root:root auto-creation"
                )
            except Exception as e:
                logger.warning(
                    f"[MountUtils] Could not pre-create bind-mount dir '{host_abs}': {e}. "
                    "Docker may create it as root:root — container may get Permission Denied."
                )
