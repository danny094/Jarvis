from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_engine_has_runtime_preflight_and_connection_resolver_contract():
    src = _read("container_commander/engine.py")
    assert "def _validate_runtime_preflight" in src
    assert "nvidia_runtime_unavailable" in src
    assert "runtime_ok, runtime_reason = _validate_runtime_preflight(client, bp.runtime)" in src
    assert "def _extract_port_details" in src
    assert "def _build_connection_info" in src
    assert "\"connection\": _build_connection_info(ip_address, ports)" in src


def test_mcp_request_container_returns_connection_and_auto_gaming_blueprint():
    src = _read("container_commander/mcp_tools.py")
    assert "def _ensure_gaming_station_blueprint" in src
    assert "def _compute_gaming_override_resources" in src
    assert "if blueprint_id in {\"gaming-station\", \"steam-headless\", \"gaming_station\"}:" in src
    assert "_ensure_gaming_station_blueprint()" in src
    assert "override_resources=override_resources" in src
    assert "\"connection\": details.get(\"connection\", {})" in src
    assert "image_ref = \"josh5/steam-headless:latest\"" in src
    assert "image=image_ref" in src
    assert "runtime=\"nvidia\"" in src
    assert "\"STEAM_USER\": \"vault://STEAM_USERNAME\"" in src
    assert "\"STEAM_PASS\": \"vault://STEAM_PASSWORD\"" in src


def test_orchestrator_build_tool_args_has_gaming_fallbacks():
    src = _read("core/orchestrator.py")
    assert "if any(tok in lower for tok in (\"steam-headless\", \"sunshine\", \"gaming station\", \"gaming-station\", \"zocken\", \"moonlight\")):" in src
    assert "return {\"blueprint_id\": \"gaming-station\"}" in src
    assert "elif tool_name == \"blueprint_create\":" in src
    assert "\"id\": \"gaming-station\"" in src
    assert "\"image\": \"josh5/steam-headless:latest\"" in src
