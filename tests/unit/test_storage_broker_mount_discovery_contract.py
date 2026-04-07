from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_storage_broker_compose_uses_host_pid1_mounts_file():
    src = _read("docker-compose.yml")
    assert "/proc/1/mounts:/host/proc_mounts:ro" in src
    assert "storage-host-helper:" in src
    assert "STORAGE_HOST_HELPER_URL=http://storage-host-helper:8090" in src
    assert "privileged: true" in src
    assert "seccomp=unconfined" in src
    assert "user: 1000:1000" in src


def test_storage_broker_discovery_has_proc_self_bind_fallback_detection():
    src = _read("mcp-servers/storage-broker/storage_broker_mcp/discovery.py")
    assert "def _looks_like_proc_self_bind" in src
    assert "STORAGE_MOUNTS_FALLBACKS" in src
    assert "_build_system_disk_set(raw_devs, host_mounts)" in src


def test_storage_broker_policy_blocks_system_override_paths():
    src = _read("mcp-servers/storage-broker/storage_broker_mcp/policy.py")
    assert "System disk" in src
    assert "heuristically detected system disk" in src
    assert "cannot be reassigned to zone" in src
    assert "cannot be changed to policy" in src


def test_storage_broker_tools_use_host_helper_for_mount_ops():
    src = _read("mcp-servers/storage-broker/storage_broker_mcp/tools.py")
    assert 'HOST_HELPER_URL = str(os.environ.get("STORAGE_HOST_HELPER_URL", "http://storage-host-helper:8090") or "").strip().rstrip("/")' in src
    assert 'def _host_helper_post(path: str, payload: dict, timeout: int = 30) -> dict:' in src
    assert '"/v1/mount-targets"' in src
    assert '"/v1/unmount"' in src
    assert '"/v1/format"' in src
