from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding='utf-8')


def test_admin_api_dockerfile_copies_commander_api_package():
    src = _read('adapters/admin-api/Dockerfile')
    assert 'COPY adapters/admin-api/commander_api /app/commander_api' in src


def test_admin_api_compose_mounts_commander_api_package_for_runtime():
    src = _read('docker-compose.yml')
    assert './adapters/admin-api/commander_api:/app/commander_api:ro' in src
