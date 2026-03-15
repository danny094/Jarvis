from pathlib import Path


def _plugin_source() -> str:
    root = Path(__file__).resolve().parents[2]
    path = root / "trion" / "plugins" / "sequential-thinking" / "plugin.ts"
    return path.read_text(encoding="utf-8")


def test_workspace_update_maps_control_and_chat_done_into_build_activity():
    src = _plugin_source()
    assert "if (isPlanningEvent) {" in src
    assert "if (!isPlanningEvent) return;" not in src
    assert "if (entryType === 'control_decision')" in src
    assert "this.handleWorkspaceControlDecision(fields);" in src
    assert "if (entryType === 'chat_done')" in src
    assert "this.handleWorkspaceChatDone(fields);" in src


def test_workspace_update_maps_observation_and_note_into_build_activity():
    src = _plugin_source()
    assert "if (entryType === 'observation')" in src
    assert "this.handleWorkspaceObservation(sourceLayer, content);" in src
    assert "if (entryType === 'note')" in src
    assert "this.handleWorkspaceNote(content);" in src
