from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_engine_exposes_ws_activity_helper():
    src = _read("container_commander/engine.py")
    assert "def _emit_ws_activity(event: str, level: str = \"info\", message: str = \"\", **data):" in src
    assert "from .ws_stream import emit_activity" in src


def test_engine_emits_deploy_and_container_lifecycle_events():
    src = _read("container_commander/engine.py")
    assert '"deploy_start"' in src
    assert '"deploy_failed"' in src
    assert '"container_started"' in src
    assert '"container_stopped"' in src


def test_engine_emits_trust_block_and_ttl_events():
    src = _read("container_commander/engine.py")
    assert '"trust_block"' in src
    assert '"container_ttl_expired"' in src
