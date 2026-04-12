from pathlib import Path


def test_lobechat_adapter_service_mounts_adapter_source_tree():
    root = Path(__file__).resolve().parents[2]
    src = (root / "docker-compose.yml").read_text(encoding="utf-8")
    assert "- ./adapters/lobechat:/app/adapters/lobechat:ro" in src
