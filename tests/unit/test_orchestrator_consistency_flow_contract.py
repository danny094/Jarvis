from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_sync_flow_invokes_conversation_consistency_guard():
    src = _read("core/orchestrator_sync_flow_utils.py")
    assert "_apply_conversation_consistency_guard(" in src
    assert "conversation_id=conversation_id" in src
    assert "answer=answer" in src


def test_stream_flow_invokes_guard_and_emits_response_repair_event():
    src = _read("core/orchestrator_stream_flow_utils.py")
    assert "_apply_conversation_consistency_guard(" in src
    assert "\"type\": \"response_repair\"" in src
    assert "\"reason\": \"consistency_guard\"" in src
