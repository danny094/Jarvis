from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_approval_module_persists_resolved_items_in_history():
    src = _read("container_commander/approval.py")
    assert "_history: List[PendingApproval] = []" in src
    assert "_history.append(approval)" in src
    assert "list(_history)" in src


def test_approval_module_emits_live_events_for_request_and_resolution():
    src = _read("container_commander/approval.py")
    assert "_emit_ws_activity(" in src
    assert '"approval_requested"' in src
    assert '"approval_resolved"' in src


def test_approval_expiry_moves_entries_out_of_pending_store():
    src = _read("container_commander/approval.py")
    assert "_pending.pop(a.id, None)" in src
    assert "a.status = ApprovalStatus.EXPIRED" in src
