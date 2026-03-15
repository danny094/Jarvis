from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_storage_broker_compose_uses_host_pid1_mounts_file():
    src = _read("docker-compose.yml")
    assert "/proc/1/mounts:/host/proc_mounts:ro" in src


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
