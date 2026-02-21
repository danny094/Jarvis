"""
Unit Tests: Container Restart Recovery (Phase 4)
=================================================
Tests:
  1. recover_runtime_state rebuilds _active from running Docker containers
  2. TTL timer rearmed with remaining time (not original TTL)
  3. Expired containers (TTL elapsed) stopped + expiry event emitted at startup
  4. No-TTL containers registered without timer
  5. Quota recalculated correctly after recovery
  6. Recovery is idempotent (no duplicate entries or timers)
  7. trion.ttl_seconds + trion.expires_at labels present via start_container code path
  8. _set_ttl_timer cancels existing timer before arming (idempotent)

Docker + storage dependencies mocked at sys.modules level so tests run outside Docker.
"""

import pytest
import time
import sys
import os
from unittest.mock import MagicMock, patch

# ─── path so container_commander is importable from repo root ─────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ─────────────────────────────────────────────────────────────────────────────
# Pre-import mocks — must be installed BEFORE container_commander.engine loads
# ─────────────────────────────────────────────────────────────────────────────

def _install_docker_mock():
    """Inject a docker SDK stub if not already present."""
    if "docker" in sys.modules:
        return  # real or already-mocked
    m = MagicMock()
    m.errors = MagicMock()
    m.errors.NotFound = type("NotFound", (Exception,), {})
    m.errors.APIError = type("APIError", (Exception,), {})
    m.errors.BuildError = type("BuildError", (Exception,), {})
    m.errors.ImageNotFound = type("ImageNotFound", (Exception,), {})
    m.errors.DockerException = type("DockerException", (Exception,), {})
    sys.modules["docker"] = m
    sys.modules["docker.errors"] = m.errors


def _install_store_mocks():
    """
    Stub out container_commander sub-modules that call init_db() at module
    import time, which tries to create /app/data and fails outside Docker.
    """
    if "container_commander.blueprint_store" not in sys.modules:
        bs = MagicMock()
        bs.resolve_blueprint = MagicMock(return_value=None)
        bs.log_action = MagicMock(return_value=None)
        sys.modules["container_commander.blueprint_store"] = bs

    if "container_commander.secret_store" not in sys.modules:
        ss = MagicMock()
        ss.get_secrets_for_blueprint = MagicMock(return_value={})
        ss.log_secret_access = MagicMock(return_value=None)
        sys.modules["container_commander.secret_store"] = ss

    # Note: mcp.client is NOT mocked at module level to avoid shadowing the real
    # mcp package for other test files in the same pytest session.
    # Tests that call recover_runtime_state with expired containers already use
    # patch("mcp.client.call_tool", ...) context managers for isolation.


# Install mocks immediately at collection time
_install_docker_mock()
_install_store_mocks()


# ─────────────────────────────────────────────────────────────────────────────
# Import the engine ONCE (no reload — reload would re-run blueprint_store mock)
# ─────────────────────────────────────────────────────────────────────────────

try:
    import container_commander.engine as _ENGINE
except Exception as _ENG_ERR:
    _ENGINE = None
    _ENG_IMPORT_ERR = _ENG_ERR
else:
    _ENG_IMPORT_ERR = None


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def engine():
    """
    Yield the engine module with _active and _ttl_timers cleared for test
    isolation.  Restores original state after each test.
    """
    if _ENGINE is None:
        pytest.skip(f"Cannot import container_commander.engine: {_ENG_IMPORT_ERR}")

    orig_active = dict(_ENGINE._active)
    orig_timers = dict(_ENGINE._ttl_timers)
    orig_quota  = (
        _ENGINE._quota.model_copy()
        if hasattr(_ENGINE._quota, "model_copy")
        else None
    )

    _ENGINE._active.clear()
    _ENGINE._ttl_timers.clear()

    yield _ENGINE

    _ENGINE._active.clear()
    _ENGINE._active.update(orig_active)
    _ENGINE._ttl_timers.clear()
    _ENGINE._ttl_timers.update(orig_timers)
    if orig_quota is not None:
        _ENGINE._quota = orig_quota


# ─────────────────────────────────────────────────────────────────────────────
# Helper builders
# ─────────────────────────────────────────────────────────────────────────────

def _make_mock_container(
    container_id: str = "abc123def456",
    bp_id: str = "bp-test",
    name: str = "trion_bp-test_123",
    ttl_seconds: int = 300,
    expires_at: int = 0,   # 0 = auto-compute from remaining
    remaining: int = 200,  # seconds of TTL still left
    mem_bytes: int = 536870912,   # 512 MB
    nano_cpus: int = 1000000000,  # 1.0 CPU
    session_id: str = "sess-001",
    vol_name: str = "trion_ws_bp-test_123",
):
    """Build a mock Docker container matching Engine's expected interface."""
    if expires_at == 0 and ttl_seconds > 0 and remaining > 0:
        expires_at = int(time.time()) + remaining
    elif expires_at == 0:
        expires_at = 0  # no TTL

    c = MagicMock()
    c.id   = container_id
    c.name = name
    c.labels = {
        "trion.managed":         "true",
        "trion.blueprint":       bp_id,
        "trion.started":         "2026-02-19T10:00:00",
        "trion.session_id":      session_id,
        "trion.volume":          vol_name,
        "trion.ttl_seconds":     str(ttl_seconds),
        "trion.expires_at":      str(expires_at),
        "trion.conversation_id": "conv-001",
    }
    c.attrs = {"HostConfig": {"Memory": mem_bytes, "NanoCpus": nano_cpus}}
    c.stop   = MagicMock()
    c.remove = MagicMock()
    return c


def _mock_docker_client(containers: list) -> MagicMock:
    """Return a mock Docker client whose containers.list() returns `containers`."""
    mc = MagicMock()
    mc.containers.list.return_value = containers
    return mc


# ═════════════════════════════════════════════════════════════════════════════
# Test 1: Rebuild _active from running Docker containers
# ═════════════════════════════════════════════════════════════════════════════

class TestRecoverRebuildActive:
    """recover_runtime_state must register running TRION containers in _active."""

    def test_running_container_registered(self, engine):
        """One running container with TTL=0 → registered in _active."""
        c = _make_mock_container("cid-r1", ttl_seconds=0)
        with patch("container_commander.engine.get_client",
                   return_value=_mock_docker_client([c])), \
             patch("container_commander.engine._update_quota_used"):
            result = engine.recover_runtime_state()

        assert "cid-r1" in engine._active, (
            f"Running container must be in _active. Keys: {list(engine._active.keys())}"
        )
        assert result["recovered"] == 1
        assert result["expired_on_startup"] == 0

    def test_no_running_containers_active_empty(self, engine):
        """No running containers → _active stays empty, recovered=0."""
        with patch("container_commander.engine.get_client",
                   return_value=_mock_docker_client([])), \
             patch("container_commander.engine._update_quota_used"):
            result = engine.recover_runtime_state()

        assert len(engine._active) == 0
        assert result["recovered"] == 0

    def test_instance_has_correct_blueprint_id(self, engine):
        """Recovered ContainerInstance reflects blueprint_id from Docker labels."""
        c = _make_mock_container("cid-bp-ok", bp_id="special-blueprint", ttl_seconds=0)
        with patch("container_commander.engine.get_client",
                   return_value=_mock_docker_client([c])), \
             patch("container_commander.engine._update_quota_used"):
            engine.recover_runtime_state()

        inst = engine._active.get("cid-bp-ok")
        assert inst is not None
        assert inst.blueprint_id == "special-blueprint"

    def test_instance_status_is_running(self, engine):
        """Recovered ContainerInstance must have status=RUNNING."""
        from container_commander.models import ContainerStatus
        c = _make_mock_container("cid-st-ok", ttl_seconds=0)
        with patch("container_commander.engine.get_client",
                   return_value=_mock_docker_client([c])), \
             patch("container_commander.engine._update_quota_used"):
            engine.recover_runtime_state()

        inst = engine._active.get("cid-st-ok")
        assert inst is not None
        assert inst.status == ContainerStatus.RUNNING

    def test_multiple_containers_all_registered(self, engine):
        """Multiple running containers are all registered."""
        c1 = _make_mock_container("cid-m1", ttl_seconds=0)
        c2 = _make_mock_container("cid-m2", ttl_seconds=0)
        with patch("container_commander.engine.get_client",
                   return_value=_mock_docker_client([c1, c2])), \
             patch("container_commander.engine._update_quota_used"):
            result = engine.recover_runtime_state()

        assert "cid-m1" in engine._active
        assert "cid-m2" in engine._active
        assert result["recovered"] == 2


# ═════════════════════════════════════════════════════════════════════════════
# Test 2: TTL-Rearm with remaining time
# ═════════════════════════════════════════════════════════════════════════════

class TestRecoverTtlRearm:
    """TTL timer must be rearmed using remaining time, not original TTL."""

    def test_timer_rearmed_when_ttl_remaining(self, engine):
        """Container with TTL > 0 and remaining > 0 must get a new timer."""
        c = _make_mock_container("cid-ttl-1", ttl_seconds=300, remaining=200)
        with patch("container_commander.engine.get_client",
                   return_value=_mock_docker_client([c])), \
             patch("container_commander.engine._update_quota_used"), \
             patch("container_commander.engine._set_ttl_timer") as mock_timer:
            engine.recover_runtime_state()

        mock_timer.assert_called_once()
        cid_arg, secs_arg = mock_timer.call_args[0]
        assert cid_arg == "cid-ttl-1"
        assert 0 < secs_arg <= 300, f"Timer secs out of range: {secs_arg}"

    def test_timer_uses_remaining_not_original(self, engine):
        """Timer delay must approximate remaining time (< original TTL=600)."""
        remaining = 150
        c = _make_mock_container("cid-rem-1", ttl_seconds=600, remaining=remaining)
        timers_set = []

        with patch("container_commander.engine.get_client",
                   return_value=_mock_docker_client([c])), \
             patch("container_commander.engine._update_quota_used"), \
             patch("container_commander.engine._set_ttl_timer",
                   side_effect=lambda cid, secs: timers_set.append((cid, secs))):
            engine.recover_runtime_state()

        assert len(timers_set) == 1
        _, secs = timers_set[0]
        assert secs < 600, f"Timer must use remaining ({remaining}s) not original (600s), got {secs}"
        assert secs >= 140, f"Timer secs suspiciously low ({secs}), expected ~{remaining}"

    def test_no_timer_when_ttl_is_zero(self, engine):
        """Container with ttl_seconds=0 must NOT get a timer."""
        c = _make_mock_container("cid-no-ttl", ttl_seconds=0)
        with patch("container_commander.engine.get_client",
                   return_value=_mock_docker_client([c])), \
             patch("container_commander.engine._update_quota_used"), \
             patch("container_commander.engine._set_ttl_timer") as mock_timer:
            engine.recover_runtime_state()

        mock_timer.assert_not_called()

    def test_instance_ttl_remaining_reflects_remaining_time(self, engine):
        """ContainerInstance.ttl_remaining must be the remaining time, not original TTL."""
        remaining = 180
        c = _make_mock_container("cid-tr-1", ttl_seconds=300, remaining=remaining)
        with patch("container_commander.engine.get_client",
                   return_value=_mock_docker_client([c])), \
             patch("container_commander.engine._update_quota_used"), \
             patch("container_commander.engine._set_ttl_timer"):
            engine.recover_runtime_state()

        inst = engine._active.get("cid-tr-1")
        assert inst is not None
        assert inst.ttl_remaining <= 300, "ttl_remaining must not exceed original TTL"
        assert inst.ttl_remaining > 0, "ttl_remaining must be > 0 for non-expired container"


# ═════════════════════════════════════════════════════════════════════════════
# Test 3: Expired containers stopped at startup
# ═════════════════════════════════════════════════════════════════════════════

class TestRecoverExpiredAtStartup:
    """Containers whose TTL elapsed must be stopped during recovery."""

    def test_expired_container_is_stopped(self, engine):
        """Container with expires_at in the past → stop() called."""
        expired_epoch = int(time.time()) - 60
        c = _make_mock_container("cid-exp-1", ttl_seconds=300,
                                 expires_at=expired_epoch, remaining=0)
        with patch("container_commander.engine.get_client",
                   return_value=_mock_docker_client([c])), \
             patch("container_commander.engine._update_quota_used"), \
             patch("mcp.client.call_tool", return_value=None):
            result = engine.recover_runtime_state()

        c.stop.assert_called_once()
        assert "cid-exp-1" not in engine._active
        assert result["expired_on_startup"] == 1

    def test_expired_not_in_active(self, engine):
        """Expired container must not appear in _active."""
        expired_epoch = int(time.time()) - 1
        c = _make_mock_container("cid-exp-2", ttl_seconds=100,
                                 expires_at=expired_epoch, remaining=0)
        with patch("container_commander.engine.get_client",
                   return_value=_mock_docker_client([c])), \
             patch("container_commander.engine._update_quota_used"), \
             patch("mcp.client.call_tool", return_value=None):
            engine.recover_runtime_state()

        assert "cid-exp-2" not in engine._active

    def test_mixed_expired_and_valid(self, engine):
        """One expired + one valid → expired stopped, valid registered."""
        expired_epoch = int(time.time()) - 10
        c_exp = _make_mock_container("cid-mix-exp", ttl_seconds=100,
                                     expires_at=expired_epoch, remaining=0)
        c_ok  = _make_mock_container("cid-mix-ok", ttl_seconds=300, remaining=200)
        with patch("container_commander.engine.get_client",
                   return_value=_mock_docker_client([c_exp, c_ok])), \
             patch("container_commander.engine._update_quota_used"), \
             patch("container_commander.engine._set_ttl_timer"), \
             patch("mcp.client.call_tool", return_value=None):
            result = engine.recover_runtime_state()

        assert result["recovered"] == 1
        assert result["expired_on_startup"] == 1
        assert "cid-mix-exp" not in engine._active
        assert "cid-mix-ok" in engine._active


# ═════════════════════════════════════════════════════════════════════════════
# Test 4: Quota recalculation after recovery
# ═════════════════════════════════════════════════════════════════════════════

class TestRecoverQuota:
    """_update_quota_used must be called; quota must reflect recovered containers."""

    def test_quota_update_called(self, engine):
        """_update_quota_used must be invoked after recovery."""
        c = _make_mock_container("cid-q-1", ttl_seconds=0)
        with patch("container_commander.engine.get_client",
                   return_value=_mock_docker_client([c])), \
             patch("container_commander.engine._update_quota_used") as mock_q:
            engine.recover_runtime_state()
        mock_q.assert_called()

    def test_quota_containers_used_after_recovery(self, engine):
        """After recovery, _quota.containers_used equals len(_active)."""
        c1 = _make_mock_container("cid-q2a", ttl_seconds=0)
        c2 = _make_mock_container("cid-q2b", ttl_seconds=0)
        with patch("container_commander.engine.get_client",
                   return_value=_mock_docker_client([c1, c2])):
            engine.recover_runtime_state()

        assert engine._quota.containers_used == 2, (
            f"containers_used must be 2, got {engine._quota.containers_used}"
        )


# ═════════════════════════════════════════════════════════════════════════════
# Test 5: Recovery is idempotent
# ═════════════════════════════════════════════════════════════════════════════

class TestRecoverIdempotent:
    """Calling recover_runtime_state twice must be a no-op on the second call."""

    def test_double_recovery_registers_once(self, engine):
        """Second call must skip already-registered containers (recovered=0)."""
        c = _make_mock_container("cid-idem-1", ttl_seconds=0)
        mock_client = _mock_docker_client([c])
        with patch("container_commander.engine.get_client",
                   return_value=mock_client), \
             patch("container_commander.engine._update_quota_used"):
            r1 = engine.recover_runtime_state()
            r2 = engine.recover_runtime_state()

        assert r1["recovered"] == 1
        assert r2["recovered"] == 0, "Second recovery call must skip already-registered container"
        assert len([k for k in engine._active if k == "cid-idem-1"]) == 1, \
            "Container must appear exactly once in _active"


# ═════════════════════════════════════════════════════════════════════════════
# Test 6: _set_ttl_timer idempotency
# ═════════════════════════════════════════════════════════════════════════════

class TestSetTtlTimerIdempotent:
    """_set_ttl_timer must cancel any existing timer before arming the new one."""

    def test_cancels_existing_timer(self, engine):
        """A second call to _set_ttl_timer cancels the first timer."""
        cancelled = []
        t1 = MagicMock()
        t1.cancel = MagicMock(side_effect=lambda: cancelled.append("t1"))
        engine._ttl_timers["cid-idem-t"] = t1

        with patch("threading.Timer") as mock_timer_cls:
            mock_new = MagicMock()
            mock_new.daemon = True
            mock_timer_cls.return_value = mock_new
            engine._set_ttl_timer("cid-idem-t", 99)

        assert "t1" in cancelled, "Existing timer must have been cancelled"
        mock_new.start.assert_called_once()

    def test_no_error_when_no_prior_timer(self, engine):
        """_set_ttl_timer must work cleanly when no prior timer exists."""
        with patch("threading.Timer") as mock_timer_cls:
            mock_t = MagicMock()
            mock_t.daemon = True
            mock_timer_cls.return_value = mock_t
            engine._set_ttl_timer("cid-fresh", 60)

        mock_t.start.assert_called_once()
        assert "cid-fresh" in engine._ttl_timers


# ═════════════════════════════════════════════════════════════════════════════
# Test 7: Durable TTL labels in containers.run() call
# ═════════════════════════════════════════════════════════════════════════════

class TestDurableTtlLabelsInCode:
    """
    Verify that start_container and recover_runtime_state reference
    the durable TTL label keys.  Inspects source rather than running
    the functions end-to-end (which requires live Docker).
    """

    def test_ttl_label_constants_defined_in_engine(self, engine):
        """engine.py source must include both durable TTL label keys."""
        import inspect
        src = inspect.getsource(engine.start_container)
        assert "trion.ttl_seconds" in src, (
            "start_container source must reference 'trion.ttl_seconds' label"
        )
        assert "trion.expires_at" in src, (
            "start_container source must reference 'trion.expires_at' label"
        )

    def test_recover_parses_ttl_seconds_label(self, engine):
        """recover_runtime_state must read trion.ttl_seconds from container labels."""
        import inspect
        src = inspect.getsource(engine.recover_runtime_state)
        assert "trion.ttl_seconds" in src, (
            "recover_runtime_state must read 'trion.ttl_seconds' from Docker labels"
        )
        assert "trion.expires_at" in src, (
            "recover_runtime_state must read 'trion.expires_at' from Docker labels"
        )


# ═════════════════════════════════════════════════════════════════════════════
# Test 8: TTL event guard — session_id + blueprint_id in expiry event
# ═════════════════════════════════════════════════════════════════════════════

class TestTtlEventGuardRegression:
    """Expiry event written at startup must contain session_id and blueprint_id."""

    def test_expiry_event_contains_session_and_blueprint(self, engine):
        """Expired-at-startup container must emit workspace_event_save with required fields."""
        expired_epoch = int(time.time()) - 5
        c = _make_mock_container(
            "cid-guard-1", bp_id="bp-guard", session_id="sess-guard",
            ttl_seconds=60, expires_at=expired_epoch, remaining=0,
        )

        events_written = []

        def _capture(tool_name, args):
            if tool_name == "workspace_event_save":
                events_written.append(args)

        with patch("container_commander.engine.get_client",
                   return_value=_mock_docker_client([c])), \
             patch("container_commander.engine._update_quota_used"), \
             patch("mcp.client.call_tool", side_effect=_capture):
            engine.recover_runtime_state()

        assert len(events_written) >= 1, "At least one workspace event must be written"
        ev = events_written[0]
        ed = ev.get("event_data", {})
        assert ev.get("event_type") == "container_ttl_expired"
        assert ed.get("session_id") == "sess-guard", (
            f"event_data.session_id must be 'sess-guard', got {ed.get('session_id')!r}"
        )
        assert ed.get("blueprint_id") == "bp-guard", (
            f"event_data.blueprint_id must be 'bp-guard', got {ed.get('blueprint_id')!r}"
        )

    def test_expiry_event_reason_is_startup(self, engine):
        """expired_at_startup path must include reason='ttl_expired_at_startup'."""
        expired_epoch = int(time.time()) - 1
        c = _make_mock_container(
            "cid-guard-2", ttl_seconds=30,
            expires_at=expired_epoch, remaining=0,
        )
        events_written = []

        def _capture(tool_name, args):
            if tool_name == "workspace_event_save":
                events_written.append(args)

        with patch("container_commander.engine.get_client",
                   return_value=_mock_docker_client([c])), \
             patch("container_commander.engine._update_quota_used"), \
             patch("mcp.client.call_tool", side_effect=_capture):
            engine.recover_runtime_state()

        assert events_written, "Event must be written"
        reason = events_written[0].get("event_data", {}).get("reason", "")
        assert reason == "ttl_expired_at_startup", (
            f"reason must be 'ttl_expired_at_startup', got {reason!r}"
        )
