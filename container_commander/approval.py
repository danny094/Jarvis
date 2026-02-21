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
import logging
import threading
from datetime import datetime
from typing import Optional, List, Dict
from enum import Enum

from .models import NetworkMode, ResourceLimits

logger = logging.getLogger(__name__)

APPROVAL_TTL = int(os.environ.get("APPROVAL_TTL", "300"))  # 5 minutes default


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
                 session_id: str = "",
                 conversation_id: str = ""):
        self.id = str(uuid.uuid4())[:8]
        self.blueprint_id = blueprint_id
        self.reason = reason
        self.network_mode = network_mode
        self.override_resources = override_resources
        self.extra_env = extra_env
        self.resume_volume = resume_volume
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


# ── Approval Store (in-memory) ────────────────────────────


_pending: Dict[str, PendingApproval] = {}
_lock = threading.Lock()
_callbacks: Dict[str, threading.Event] = {}


def request_approval(
    blueprint_id: str,
    reason: str,
    network_mode: NetworkMode,
    override_resources: Optional[ResourceLimits] = None,
    extra_env: Optional[Dict[str, str]] = None,
    resume_volume: Optional[str] = None,
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
            session_id=session_id,
            conversation_id=conversation_id,
        )
        _pending[approval.id] = approval
        _callbacks[approval.id] = threading.Event()

    logger.info(f"[Approval] New request {approval.id}: {blueprint_id} — {reason}")

    from .blueprint_store import log_action
    log_action("", blueprint_id, "approval_requested", reason)

    return approval


def approve(approval_id: str, approved_by: str = "user") -> Optional[Dict]:
    """
    Approve a pending request and start the container.
    Returns the ContainerInstance dict or None.
    """
    with _lock:
        approval = _pending.get(approval_id)
        if not approval:
            return None
        if approval.is_expired():
            approval.status = ApprovalStatus.EXPIRED
            return None
        if approval.status != ApprovalStatus.PENDING:
            return None

        approval.status = ApprovalStatus.APPROVED
        approval.resolved_at = datetime.utcnow().isoformat()
        approval.resolved_by = approved_by

    logger.info(f"[Approval] Approved: {approval_id} by {approved_by}")

    # Now actually start the container
    try:
        from .engine import start_container
        instance = start_container(
            blueprint_id=approval.blueprint_id,
            override_resources=approval.override_resources,
            extra_env=approval.extra_env,
            resume_volume=approval.resume_volume,
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

        return instance.model_dump()

    except Exception as e:
        logger.error(f"[Approval] Start after approve failed: {e}")
        with _lock:
            approval.status = ApprovalStatus.REJECTED
            approval.resolved_at = datetime.utcnow().isoformat()
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
        all_approvals = sorted(_pending.values(),
                               key=lambda a: a.created_at, reverse=True)
        return [a.to_dict() for a in all_approvals[:limit]]


# ── Internal ──────────────────────────────────────────────

def _cleanup_expired():
    """Mark expired approvals (called inside lock)."""
    now = time.time()
    for a in _pending.values():
        if a.status == ApprovalStatus.PENDING and now > a.expires_at:
            a.status = ApprovalStatus.EXPIRED
            logger.info(f"[Approval] Expired: {a.id} ({a.blueprint_id})")


def check_needs_approval(network_mode: NetworkMode) -> Optional[str]:
    """
    Check if a network mode requires approval.
    Returns the reason string or None.
    """
    if network_mode == NetworkMode.FULL:
        return "Container requests internet access (network: full)"
    return None
