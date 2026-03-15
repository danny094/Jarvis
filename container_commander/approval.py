"""
Container Commander — Human-in-the-Loop Approval System
═══════════════════════════════════════════════════════════
Handles approval workflow for high-risk container operations:

  - Internet access (NetworkMode.FULL)
  - Bridge network access
  - Privileged operations (future)

Flow:
  1. KI or API requests deploy with full/bridge network
  2. Engine detects requires_approval=True from network.resolve_network()
  3. Instead of starting, creates a PendingApproval entry
  4. Frontend shows approval dialog in Terminal app
  5. User approves/rejects via REST API
  6. On approve: Engine starts container normally
  7. On reject: Entry removed, KI gets rejection notice
  8. Auto-expire: Pending requests expire after APPROVAL_TTL seconds

Security:
  - Approvals are stored in-memory only (no persistence needed)
  - Each approval has a unique token
  - Expired approvals auto-reject
"""

import os
import uuid
import time
import json
import logging
import threading
from datetime import datetime
from typing import Optional, List, Dict
from enum import Enum

from .models import NetworkMode, ResourceLimits

logger = logging.getLogger(__name__)

APPROVAL_TTL = int(os.environ.get("APPROVAL_TTL", "300"))  # 5 minutes default
APPROVAL_STORE_PATH = os.environ.get("APPROVAL_STORE_PATH", "/tmp/trion_approvals_store.json")
APPROVAL_REQUIRE_BRIDGE = str(os.environ.get("APPROVAL_REQUIRE_BRIDGE", "1")).strip().lower() in {
    "1", "true", "yes", "on"
}


# ── Types ─────────────────────────────────────────────────

class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class PendingApproval:
    """A container deploy request waiting for user approval."""

    def __init__(self, blueprint_id: str, reason: str,
                 network_mode: NetworkMode,
                 override_resources: Optional[ResourceLimits] = None,
                 extra_env: Optional[Dict[str, str]] = None,
                 resume_volume: Optional[str] = None,
                 mount_overrides: Optional[List[dict]] = None,
                 storage_scope_override: Optional[str] = None,
                 device_overrides: Optional[List[str]] = None,
                 session_id: str = "",
                 conversation_id: str = ""):
        self.id = str(uuid.uuid4())[:8]
        self.blueprint_id = blueprint_id
        self.reason = reason
        self.network_mode = network_mode
        self.override_resources = override_resources
        self.extra_env = extra_env
        self.resume_volume = resume_volume
        self.mount_overrides = list(mount_overrides or [])
        self.storage_scope_override = str(storage_scope_override or "").strip()
        self.device_overrides = list(device_overrides or [])
        self.session_id = session_id
        self.conversation_id = conversation_id
        self.status = ApprovalStatus.PENDING
        self.created_at = datetime.utcnow().isoformat()
        self.expires_at = time.time() + APPROVAL_TTL
        self.resolved_at = None
        self.resolved_by = None

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "blueprint_id": self.blueprint_id,
            "reason": self.reason,
            "network_mode": self.network_mode.value,
            "status": self.status.value,
            "created_at": self.created_at,
            "ttl_remaining": max(0, int(self.expires_at - time.time())),
            "resolved_at": self.resolved_at,
            "resolved_by": self.resolved_by,
        }

    def to_persist_dict(self) -> dict:
        """Serialized representation including execution context for restart recovery."""
        return {
            "id": self.id,
            "blueprint_id": self.blueprint_id,
            "reason": self.reason,
            "network_mode": self.network_mode.value,
            "status": self.status.value,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "resolved_at": self.resolved_at,
            "resolved_by": self.resolved_by,
            "override_resources": self.override_resources.model_dump() if self.override_resources else None,
            "extra_env": dict(self.extra_env or {}),
            "resume_volume": self.resume_volume,
            "mount_overrides": list(self.mount_overrides or []),
            "storage_scope_override": self.storage_scope_override or "",
            "device_overrides": list(self.device_overrides or []),
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
        }

    @classmethod
    def from_persist_dict(cls, payload: dict) -> "PendingApproval":
        """Restore approval object from persisted storage."""
        data = dict(payload or {})
        network_mode = NetworkMode(str(data.get("network_mode", NetworkMode.FULL.value)))
        override_raw = data.get("override_resources")
        override_resources = ResourceLimits(**override_raw) if isinstance(override_raw, dict) else None
        obj = cls(
            blueprint_id=str(data.get("blueprint_id", "")),
            reason=str(data.get("reason", "")),
            network_mode=network_mode,
            override_resources=override_resources,
            extra_env=data.get("extra_env") if isinstance(data.get("extra_env"), dict) else None,
            resume_volume=data.get("resume_volume"),
            mount_overrides=data.get("mount_overrides") if isinstance(data.get("mount_overrides"), list) else None,
            storage_scope_override=str(data.get("storage_scope_override", "") or "").strip(),
            device_overrides=data.get("device_overrides") if isinstance(data.get("device_overrides"), list) else None,
            session_id=str(data.get("session_id", "")),
            conversation_id=str(data.get("conversation_id", "")),
        )
        if data.get("id"):
            obj.id = str(data.get("id"))
        status_raw = str(data.get("status", ApprovalStatus.PENDING.value))
        obj.status = ApprovalStatus(status_raw) if status_raw in ApprovalStatus._value2member_map_ else ApprovalStatus.PENDING
        if data.get("created_at"):
            obj.created_at = str(data.get("created_at"))
        if data.get("expires_at") is not None:
            try:
                obj.expires_at = float(data.get("expires_at"))
            except Exception:
                pass
        obj.resolved_at = data.get("resolved_at")
        obj.resolved_by = data.get("resolved_by")
        return obj


# ── Approval Store (in-memory) ────────────────────────────


_pending: Dict[str, PendingApproval] = {}
_history: List[PendingApproval] = []
_lock = threading.Lock()
_callbacks: Dict[str, threading.Event] = {}


def _emit_ws_activity(event: str, level: str = "info", message: str = "", **data):
    try:
        from .ws_stream import emit_activity

        emit_activity(event, level=level, message=message, **data)
    except Exception as e:
        logger.debug(f"[Approval] WS activity emit failed ({event}): {e}")


def _save_store_unlocked() -> None:
    """Persist pending/history approval state. Must be called while holding _lock."""
    try:
        payload = {
            "pending": [a.to_persist_dict() for a in _pending.values()],
            "history": [a.to_persist_dict() for a in _history],
        }
        os.makedirs(os.path.dirname(APPROVAL_STORE_PATH), exist_ok=True)
        tmp = f"{APPROVAL_STORE_PATH}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=True, indent=2)
        os.replace(tmp, APPROVAL_STORE_PATH)
    except Exception as e:
        logger.warning(f"[Approval] Failed to persist approval store: {e}")


def _load_store() -> None:
    """Restore approval state from disk at module import/startup."""
    if not os.path.exists(APPROVAL_STORE_PATH):
        return
    try:
        with open(APPROVAL_STORE_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        logger.warning(f"[Approval] Failed to load approval store: {e}")
        return

    pending_rows = raw.get("pending", []) if isinstance(raw, dict) else []
    history_rows = raw.get("history", []) if isinstance(raw, dict) else []

    with _lock:
        _pending.clear()
        _history.clear()
        _callbacks.clear()

        for row in pending_rows:
            try:
                item = PendingApproval.from_persist_dict(row)
                if item.status == ApprovalStatus.PENDING:
                    _pending[item.id] = item
                    _callbacks[item.id] = threading.Event()
                else:
                    _history.append(item)
            except Exception:
                continue

        for row in history_rows:
            try:
                item = PendingApproval.from_persist_dict(row)
                _history.append(item)
            except Exception:
                continue

        _cleanup_expired()
        _save_store_unlocked()


def request_approval(
    blueprint_id: str,
    reason: str,
    network_mode: NetworkMode,
    override_resources: Optional[ResourceLimits] = None,
    extra_env: Optional[Dict[str, str]] = None,
    resume_volume: Optional[str] = None,
    mount_overrides: Optional[List[dict]] = None,
    storage_scope_override: Optional[str] = None,
    device_overrides: Optional[List[str]] = None,
    session_id: str = "",
    conversation_id: str = "",
) -> PendingApproval:
    """
    Create a new pending approval request.
    Returns the PendingApproval object (with ID for polling).
    """
    with _lock:
        # Clean expired
        _cleanup_expired()

        approval = PendingApproval(
            blueprint_id=blueprint_id,
            reason=reason,
            network_mode=network_mode,
            override_resources=override_resources,
            extra_env=extra_env,
            resume_volume=resume_volume,
            mount_overrides=mount_overrides,
            storage_scope_override=storage_scope_override,
            device_overrides=device_overrides,
            session_id=session_id,
            conversation_id=conversation_id,
        )
        _pending[approval.id] = approval
        _callbacks[approval.id] = threading.Event()
        _save_store_unlocked()

    logger.info(f"[Approval] New request {approval.id}: {blueprint_id} — {reason}")
    _emit_ws_activity(
        "approval_requested",
        level="warn",
        message=f"Approval requested for {blueprint_id}",
        approval_id=approval.id,
        blueprint_id=blueprint_id,
        reason=reason,
        network_mode=network_mode.value,
        ttl_seconds=APPROVAL_TTL,
    )

    from .blueprint_store import log_action
    log_action("", blueprint_id, "approval_requested", reason)

    return approval


def approve(approval_id: str, approved_by: str = "user") -> Optional[Dict]:
    """
    Approve a pending request and start the container.
    Returns the ContainerInstance dict or None.
    """
    expired_notice = None
    with _lock:
        approval = _pending.get(approval_id)
        if not approval:
            return None
        if approval.is_expired():
            approval.status = ApprovalStatus.EXPIRED
            approval.resolved_at = datetime.utcnow().isoformat()
            approval.resolved_by = "system_ttl"
            _pending.pop(approval_id, None)
            _history.append(approval)
            _callbacks.pop(approval_id, None)
            _save_store_unlocked()
            expired_notice = approval
            approval = None
        if approval is None:
            pass
        elif approval.status != ApprovalStatus.PENDING:
            return None

        if approval is not None:
            approval.status = ApprovalStatus.APPROVED
            approval.resolved_at = datetime.utcnow().isoformat()
            approval.resolved_by = approved_by

    if expired_notice is not None:
        _emit_ws_activity(
            "approval_resolved",
            level="warn",
            message=f"Approval expired for {expired_notice.blueprint_id}",
            approval_id=expired_notice.id,
            blueprint_id=expired_notice.blueprint_id,
            status=expired_notice.status.value,
            resolved_by=expired_notice.resolved_by,
        )
        return None

    logger.info(f"[Approval] Approved: {approval_id} by {approved_by}")

    # Now actually start the container
    try:
        from .engine import start_container
        instance = start_container(
            blueprint_id=approval.blueprint_id,
            override_resources=approval.override_resources,
            extra_env=approval.extra_env,
            resume_volume=approval.resume_volume,
            mount_overrides=approval.mount_overrides,
            storage_scope_override=approval.storage_scope_override,
            device_overrides=approval.device_overrides,
            _skip_approval=True,  # Don't re-trigger approval check
            session_id=approval.session_id,
            conversation_id=approval.conversation_id,
        )

        from .blueprint_store import log_action
        log_action(instance.container_id, approval.blueprint_id,
                    "approval_approved", f"by {approved_by}")

        # Signal any waiting threads
        evt = _callbacks.pop(approval_id, None)
        if evt:
            evt.set()

        # Clean up
        with _lock:
            _pending.pop(approval_id, None)
            _history.append(approval)
            _save_store_unlocked()

        _emit_ws_activity(
            "approval_resolved",
            level="success",
            message=f"Approval approved for {approval.blueprint_id}",
            approval_id=approval_id,
            blueprint_id=approval.blueprint_id,
            status=approval.status.value,
            resolved_by=approved_by,
            container_id=instance.container_id,
        )

        return instance.model_dump()

    except Exception as e:
        logger.error(f"[Approval] Start after approve failed: {e}")
        with _lock:
            approval.status = ApprovalStatus.REJECTED
            approval.resolved_at = datetime.utcnow().isoformat()
            approval.resolved_by = approved_by
            _pending.pop(approval_id, None)
            _history.append(approval)
            _save_store_unlocked()
        _emit_ws_activity(
            "approval_resolved",
            level="error",
            message=f"Approval failed for {approval.blueprint_id}",
            approval_id=approval_id,
            blueprint_id=approval.blueprint_id,
            status=approval.status.value,
            resolved_by=approved_by,
            error=str(e),
        )
        return {"error": str(e)}


def reject(approval_id: str, rejected_by: str = "user", reason: str = "") -> bool:
    """Reject a pending approval."""
    with _lock:
        approval = _pending.get(approval_id)
        if not approval or approval.status != ApprovalStatus.PENDING:
            return False

        approval.status = ApprovalStatus.REJECTED
        approval.resolved_at = datetime.utcnow().isoformat()
        approval.resolved_by = rejected_by

    logger.info(f"[Approval] Rejected: {approval_id} by {rejected_by} — {reason}")

    from .blueprint_store import log_action
    log_action("", approval.blueprint_id, "approval_rejected",
               f"by {rejected_by}: {reason}")

    # Signal waiting threads
    evt = _callbacks.pop(approval_id, None)
    if evt:
        evt.set()

    with _lock:
        _pending.pop(approval_id, None)
        _history.append(approval)
        _save_store_unlocked()

    _emit_ws_activity(
        "approval_resolved",
        level="warn",
        message=f"Approval rejected for {approval.blueprint_id}",
        approval_id=approval_id,
        blueprint_id=approval.blueprint_id,
        status=approval.status.value,
        resolved_by=rejected_by,
        reason=reason or "",
    )

    return True


def get_pending() -> List[Dict]:
    """Get all pending approval requests."""
    with _lock:
        _cleanup_expired()
        return [a.to_dict() for a in _pending.values()
                if a.status == ApprovalStatus.PENDING]


def get_approval(approval_id: str) -> Optional[Dict]:
    """Get a specific approval request."""
    with _lock:
        a = _pending.get(approval_id)
        if a:
            if a.is_expired() and a.status == ApprovalStatus.PENDING:
                a.status = ApprovalStatus.EXPIRED
            return a.to_dict()
    return None


def get_history(limit: int = 20) -> List[Dict]:
    """Get all approval requests including resolved ones."""
    with _lock:
        all_approvals = sorted(
            list(_history) + [a for a in _pending.values() if a.status != ApprovalStatus.PENDING],
            key=lambda a: a.created_at,
            reverse=True,
        )
        return [a.to_dict() for a in all_approvals[:limit]]


# ── Internal ──────────────────────────────────────────────

def _cleanup_expired():
    """Mark expired approvals (called inside lock)."""
    now = time.time()
    to_archive = []
    for a in list(_pending.values()):
        if a.status == ApprovalStatus.PENDING and now > a.expires_at:
            a.status = ApprovalStatus.EXPIRED
            logger.info(f"[Approval] Expired: {a.id} ({a.blueprint_id})")
            a.resolved_at = datetime.utcnow().isoformat()
            a.resolved_by = "system_ttl"
            to_archive.append(a)
    for a in to_archive:
        _pending.pop(a.id, None)
        _history.append(a)
        _emit_ws_activity(
            "approval_resolved",
            level="warn",
            message=f"Approval expired for {a.blueprint_id}",
            approval_id=a.id,
            blueprint_id=a.blueprint_id,
            status=a.status.value,
            resolved_by=a.resolved_by,
        )
    if to_archive:
        _save_store_unlocked()


def check_needs_approval(network_mode: NetworkMode) -> Optional[str]:
    """
    Check if a network mode requires approval.
    Returns the reason string or None.
    """
    if network_mode == NetworkMode.FULL:
        return "Container requests internet access (network: full)"
    if network_mode == NetworkMode.BRIDGE and APPROVAL_REQUIRE_BRIDGE:
        return "Container requests host bridge access (network: bridge)"
    return None


_load_store()
