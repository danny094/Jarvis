from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_commander_hardware_router_exposes_blueprint_endpoints():
    src = _read("adapters/admin-api/commander_api/hardware.py")
    assert '@router.get("/blueprints/{blueprint_id}/hardware")' in src
    assert '@router.post("/blueprints/{blueprint_id}/hardware/plan")' in src
    assert '@router.post("/blueprints/{blueprint_id}/hardware/validate")' in src
    assert '@router.post("/blueprints/{blueprint_id}/hardware/resolve")' in src
    assert 'target_type = str(data.get("target_type") or "blueprint").strip() or "blueprint"' in src
    assert 'path="/hardware/plan"' in src
    assert 'path="/hardware/validate"' in src
    assert '"hardware_preview"' in src
    assert '"resolution_preview"' in src


def test_commander_routes_includes_hardware_subrouter():
    src = _read("adapters/admin-api/commander_routes.py")
    assert "from commander_api.hardware import router as hardware_router" in src
    assert "router.include_router(hardware_router)" in src
    assert "hardware_preview: bool = False" in src
    assert '"hardware_preview"' in src


def test_runtime_hardware_container_connector_supports_blueprint_targets():
    planner_src = _read("adapters/runtime-hardware/runtime_hardware/planner.py")
    connector_src = _read("adapters/runtime-hardware/runtime_hardware/connectors/container_connector.py")
    assert 'target_type not in {"container", "blueprint"}' in planner_src
    assert 'if target_type == "blueprint":' in connector_src
    assert 'runtime={"mode": "blueprint_preview"}' in connector_src
    assert 'if target_type != "blueprint":' in connector_src
