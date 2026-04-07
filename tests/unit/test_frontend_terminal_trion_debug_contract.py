from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_terminal_prompt_supports_trion_debug_command_for_attached_container():
    config_src = _read("adapters/Jarvis/js/apps/terminal/config.js")
    cmd_src = _read("adapters/Jarvis/js/apps/terminal/command-input.js")
    assert "{ cmd: 'trion', desc: 'Analyze attached container or enter shell mode: trion <task>|shell' }" in config_src
    assert "{ cmd: '/trion', expand: 'trion ', desc: 'TRION debug attached container' }" in cmd_src
    assert "case 'trion': {" in cmd_src
    assert "/trion-debug" in cmd_src
    assert "Attach a container first, then run: trion <task>" in cmd_src
    assert "/trion-shell/start" in cmd_src
    assert "/trion-shell/step" in cmd_src
    assert "/trion-shell/stop" in cmd_src
    assert "Usage: trion <task> | trion shell" in cmd_src
    assert "if (shellModeActive)" in cmd_src
