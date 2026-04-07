from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_admin_api_exposes_runtime_hardware_gateway_routes():
    src = _read("adapters/admin-api/runtime_hardware_routes.py")
    assert '@router.get("/health")' in src
    assert '@router.get("/connectors")' in src
    assert '@router.get("/capabilities")' in src
    assert '@router.get("/resources")' in src
    assert '@router.get("/targets/{target_type}/{target_id}/state")' in src
    assert '@router.post("/plan")' in src
    assert '@router.post("/validate")' in src


def test_runtime_hardware_gateway_has_reachable_fallback_urls():
    src = _read("adapters/admin-api/runtime_hardware_routes.py")
    helper_src = _read("utils/service_endpoint_resolver.py")
    assert 'RUNTIME_HARDWARE_URL' in src
    assert 'candidate_service_endpoints(' in src
    assert 'host.docker.internal:{int(port)}' in helper_src
    assert '127.0.0.1:{int(port)}' in helper_src
    assert 'http://172.17.0.1:8420' not in src


def test_admin_api_main_includes_runtime_hardware_gateway():
    src = _read("adapters/admin-api/main.py")
    assert 'from runtime_hardware_routes import router as runtime_hardware_router' in src
    assert 'app.include_router(runtime_hardware_router, prefix="/api/runtime-hardware")' in src
