from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding='utf-8')


def test_commander_routes_use_explicit_error_codes_for_blueprint_paths():
    src = _read('adapters/admin-api/commander_routes.py')
    assert "HTTPException(404, f\"Blueprint '{blueprint_id}' not found\")" in src
    assert 'details={"deleted": False, "blueprint_id": blueprint_id}' in src
    assert 'details={"updated": False, "blueprint_id": blueprint_id}' in src
    assert 'details={"imported": False}' in src
    assert 'error_code="bad_request"' in src


def test_containers_and_secrets_routes_expose_structured_error_details():
    csrc = _read('adapters/admin-api/commander_api/containers.py')
    ssrc = _read('adapters/admin-api/commander_api/secrets.py')
    assert 'details={"executed": False, "container_id": container_id}' in csrc
    assert 'details={"stopped": False, "container_id": container_id}' in csrc
    assert 'details={"stored": False}' in ssrc
    assert 'details={"deleted": False, "name": secret_name}' in ssrc


def test_storage_and_marketplace_export_routes_use_not_found_contract():
    stsrc = _read('adapters/admin-api/commander_api/storage.py')
    opsrc = _read('adapters/admin-api/commander_api/operations.py')
    required_storage_markers = [
        'details={"volume_name": volume_name}',
        'details={"removed": False, "volume": volume_name}',
        'details={"created": False}',
        'details={"restored": False}',
        'details={"deleted": False, "filename": filename}',
        'details={"container_id": container_id}',
    ]
    for marker in required_storage_markers:
        assert marker in stsrc
    assert 'details={"exported": False, "blueprint_id": blueprint_id}' in opsrc
