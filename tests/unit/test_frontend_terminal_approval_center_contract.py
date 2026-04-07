from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_terminal_includes_approval_center_markup_and_toggle_hooks():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    assert 'id="approval-center"' in src
    assert 'id="approval-center-btn"' in src
    assert 'data-approval-tab="pending"' in src
    assert 'data-approval-tab="history"' in src
    assert "toggleApprovalCenter();" in src


def test_terminal_approval_center_loads_pending_and_history():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    assert "apiRequest('/approvals', {}, 'Could not load approvals')" in src
    assert "apiRequest('/approvals/history', {}, 'Could not load approval history')" in src
    assert "function renderApprovalCenter()" in src
    assert "function updateApprovalBadge()" in src


def test_terminal_approval_center_can_resolve_requests_from_list():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    assert "async function resolveApprovalRequest(approvalId, action, reason = '')" in src
    assert "window.termApproveRequest = async function(approvalId)" in src
    assert "window.termRejectRequest = async function(approvalId)" in src


def test_terminal_approval_center_uses_structured_runtime_risk_fields():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    assert "function approvalReason(item)" in src
    assert "approval_reason || item?.reason" in src
    assert "requested_cap_add" in src
    assert "requested_security_opt" in src
    assert "requested_cap_drop" in src
    assert "read_only_rootfs" in src
