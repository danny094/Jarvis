from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_engine_calls_host_companion_setup_for_composite_packages():
    src = _read("container_commander/engine.py")
    assert "ensure_package_storage_scope" in src
    assert 'if isinstance(package_manifest, dict) and package_manifest.get("host_companion")' in src
    assert "ensure_host_companion(blueprint_id, overwrite=False)" in src
    assert 'ensure_package_storage_scope(blueprint_id, blueprint=bp, manifest=package_manifest)' in src
    assert "run_package_postchecks(" in src


def test_commander_routes_expose_host_companion_actions():
    src = _read("adapters/admin-api/commander_api/containers.py")
    assert '@router.get("/containers/{container_id}/host-companion/check")' in src
    assert '@router.post("/containers/{container_id}/host-companion/repair")' in src
    assert '@router.post("/containers/{container_id}/host-companion/uninstall")' in src
    assert "Stop the container before uninstalling its host companion" in src


def test_commander_routes_expose_real_container_uninstall():
    src = _read("adapters/admin-api/commander_api/containers.py")
    assert '@router.post("/containers/{container_id}/uninstall")' in src
    assert "remove_stopped_container" in src
    assert "Stop the container before uninstalling it" in src
