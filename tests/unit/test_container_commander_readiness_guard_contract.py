from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_engine_has_readiness_waiter_and_cleanup_contract():
    src = _read("container_commander/engine.py")
    assert "def _derive_readiness_timeout_seconds(config: Dict) -> int:" in src
    assert "def _wait_for_container_health(" in src
    assert "def _cleanup_failed_container_start(" in src
    assert "ready_timeout = _derive_readiness_timeout_seconds(bp.healthcheck)" in src
    assert "healthcheck_timeout_auto_stopped" in src
    assert "healthcheck_unhealthy_auto_stopped" in src
    assert "container_exited_before_ready_auto_stopped" in src


def test_deploy_route_maps_readiness_failures_to_specific_error_codes():
    src = _read("adapters/admin-api/commander_routes.py")
    assert "def _runtime_deploy_error_meta(message: str) -> tuple[str, int]:" in src
    assert "healthcheck_timeout_auto_stopped" in src
    assert "healthcheck_unhealthy_auto_stopped" in src
    assert "container_exited_before_ready_auto_stopped" in src
    assert "\"healthcheck_timeout\", 504" in src
    assert "\"healthcheck_unhealthy\", 409" in src
    assert "\"container_not_ready\", 409" in src


def test_approval_route_maps_readiness_failures_to_specific_error_codes():
    src = _read("adapters/admin-api/commander_api/operations.py")
    assert "def _approval_error_meta(message: str) -> tuple[str, int]:" in src
    assert "healthcheck_timeout_auto_stopped" in src
    assert "healthcheck_unhealthy_auto_stopped" in src
    assert "container_exited_before_ready_auto_stopped" in src
    assert "\"healthcheck_timeout\", 504" in src
    assert "\"healthcheck_unhealthy\", 409" in src
    assert "\"container_not_ready\", 409" in src


def test_terminal_surface_has_readiness_error_hints():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    assert "healthcheck_timeout" in src
    assert "healthcheck_unhealthy" in src
    assert "container_not_ready" in src
    assert "healthcheck_timeout_auto_stopped" in src
    assert "event === 'deploy_failed'" in src
