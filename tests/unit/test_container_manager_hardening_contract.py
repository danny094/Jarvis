import threading
from pathlib import Path

import container_commander.approval as approval
from container_commander.models import NetworkMode


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_engine_exec_timeout_contract_present():
    src = _read("container_commander/engine.py")
    assert "EXEC_TIMEOUT_EXIT_CODE = 124" in src
    assert "def _build_timed_exec_command" in src
    assert "def _extract_timeout_marker" in src
    assert "timed_command = _build_timed_exec_command(command, timeout)" in src


def test_engine_quota_reservation_contract_present():
    src = _read("container_commander/engine.py")
    assert "_pending_starts" in src
    assert "def _reserve_quota" in src
    assert "def _release_quota_reservation" in src
    assert "def _commit_quota_reservation" in src
    assert "reserved_mem_mb, reserved_cpu = _reserve_quota(resources)" in src


def test_engine_unique_runtime_suffix_contract_present():
    src = _read("container_commander/engine.py")
    assert "def _unique_runtime_suffix" in src
    assert "unique_suffix = _unique_runtime_suffix()" in src
    assert "container_name = f\"{TRION_PREFIX}{blueprint_id}_{unique_suffix}\"" in src
    assert "volume_name = f\"trion_ws_{blueprint_id}_{unique_suffix}\"" in src


def test_approval_store_persistence_roundtrip(tmp_path, monkeypatch):
    store_path = tmp_path / "approval_store.json"
    monkeypatch.setattr(approval, "APPROVAL_STORE_PATH", str(store_path))

    with approval._lock:
        old_pending = dict(approval._pending)
        old_history = list(approval._history)
        old_callbacks = dict(approval._callbacks)

    item = approval.PendingApproval(
        blueprint_id="python-sandbox",
        reason="needs net",
        network_mode=NetworkMode.FULL,
        extra_env={"A": "1"},
        session_id="sess-1",
        conversation_id="conv-1",
    )

    try:
        with approval._lock:
            approval._pending.clear()
            approval._history.clear()
            approval._callbacks.clear()
            approval._pending[item.id] = item
            approval._callbacks[item.id] = threading.Event()
            approval._save_store_unlocked()

            approval._pending.clear()
            approval._history.clear()
            approval._callbacks.clear()

        approval._load_store()

        with approval._lock:
            assert item.id in approval._pending
            restored = approval._pending[item.id]
            assert restored.blueprint_id == "python-sandbox"
            assert restored.session_id == "sess-1"
            assert item.id in approval._callbacks
    finally:
        with approval._lock:
            approval._pending.clear()
            approval._pending.update(old_pending)
            approval._history.clear()
            approval._history.extend(old_history)
            approval._callbacks.clear()
            approval._callbacks.update(old_callbacks)


def test_bridge_approval_policy_consistent_between_modules(monkeypatch):
    monkeypatch.setattr(approval, "APPROVAL_REQUIRE_BRIDGE", True)

    reason = approval.check_needs_approval(NetworkMode.BRIDGE)
    assert reason is not None

    monkeypatch.setattr(approval, "APPROVAL_REQUIRE_BRIDGE", False)

    reason_off = approval.check_needs_approval(NetworkMode.BRIDGE)
    assert reason_off is None

    network_src = _read("container_commander/network.py")
    assert "APPROVAL_REQUIRE_BRIDGE" in network_src
    assert '"requires_approval": APPROVAL_REQUIRE_BRIDGE' in network_src
