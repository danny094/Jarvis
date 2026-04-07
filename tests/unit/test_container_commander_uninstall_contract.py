from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_engine_exposes_remove_stopped_container_helper():
    src = _read("container_commander/engine.py")
    assert "def remove_stopped_container(container_id: str) -> Dict:" in src
    assert 'return {"removed": False, "container_id": container_id, "reason": "running"}' in src
    assert 'return {"removed": True, "container_id": container_id, "blueprint_id": blueprint_id}' in src
    assert 'log_action(container_id, blueprint_id, "remove")' in src
