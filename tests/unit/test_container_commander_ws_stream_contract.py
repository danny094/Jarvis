from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_ws_stream_separates_log_and_shell_output_channels():
    src = _read("container_commander/ws_stream.py")
    assert '"stream": "logs"' in src
    assert '"stream": "shell"' in src


def test_ws_stream_tracks_exec_sessions_per_ws_and_container():
    src = _read("container_commander/ws_stream.py")
    assert "SessionKey = Tuple[int, str]" in src
    assert "_exec_sessions: Dict[SessionKey, ExecSession] = {}" in src
    assert "_ws_exec_index: Dict[WebSocket, Set[SessionKey]] = {}" in src
    assert "def _session_key(ws: WebSocket, container_id: str) -> SessionKey:" in src


def test_ws_stream_resize_targets_exec_session_not_container_resize():
    src = _read("container_commander/ws_stream.py")
    assert "client.api.exec_resize(session.exec_id, height=rows, width=cols)" in src


def test_ws_stream_exposes_unified_activity_emitter():
    src = _read("container_commander/ws_stream.py")
    assert "def emit_activity(event: str, level: str = \"info\", message: str = \"\", **data):" in src
    assert "broadcast_event_sync(event, payload_without_event)" in src
