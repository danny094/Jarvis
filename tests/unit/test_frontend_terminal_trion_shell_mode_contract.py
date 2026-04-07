from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_terminal_includes_trion_shell_mode_ui_and_transcript_state():
    template = _read("adapters/Jarvis/js/apps/terminal/template.js")
    terminal = _read("adapters/Jarvis/js/apps/terminal.js")
    assert 'id="term-shell-mode-badge"' in template
    assert 'id="term-shell-addon-strip"' in template
    assert 'id="term-shell-addon-list"' in template
    assert "let trionShellState = {" in terminal
    assert "let trionShellAddonDocs = [];" in terminal
    assert "let shellTranscriptBuffer = [];" in terminal
    assert "function setTrionShellModeState(nextState = {})" in terminal
    assert "function setTrionShellAddonDocsState(docs = [])" in terminal
    assert "function renderTrionShellAddonDocs()" in terminal
    assert "function getShellTranscriptTail(maxChars = 12000)" in terminal
    assert "Describe what TRION should do in the shell" in terminal


def test_xterm_blocks_direct_user_input_while_trion_controls_shell():
    xterm = _read("adapters/Jarvis/js/apps/terminal/xterm.js")
    command_input = _read("adapters/Jarvis/js/apps/terminal/command-input.js")
    websocket = _read("adapters/Jarvis/js/apps/terminal/websocket.js")
    assert "deps.isTrionShellActive?.()" in xterm
    assert "TRION controls the shell. Use the input bar below or /exit." in xterm
    assert "Exit TRION shell mode before switching shell sessions." in xterm
    assert "let pendingMessages = [];" in websocket
    assert "pendingMessages.unshift({ type: 'attach', container_id: attachedContainer });" in websocket
    assert "flushPendingMessages();" in websocket
    assert "loop_guard_repeat" in _read("adapters/admin-api/commander_api/containers.py")
    assert "${isGermanUi() ? 'Zusammenfassung' : 'Summary'}:\\n" in command_input
    assert "deps.setTrionAddonDocs?.(Array.isArray(data?.addon_docs) ? data.addon_docs : []);" in command_input
    assert 'window.dispatchEvent(new CustomEvent("sse-event", {' in websocket
