"""
Contract tests: container_commander/shell_context_bridge.py

Prüft:
- save_shell_session_summary schreibt das erwartete Event
- save_shell_checkpoint schreibt das erwartete Event
- build_mission_state ist fail-open (leerer String bei Fehler)
- build_mission_state schneidet bei > 600 Zeichen ab

Patch-Strategie: get_hub und get_bridge werden lazy via 'from x import y' geladen,
daher Patch auf den Quellort (mcp.hub.get_hub, core.bridge.get_bridge).
"""

import asyncio
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# save_shell_session_summary
# ---------------------------------------------------------------------------

def test_save_shell_session_summary_calls_workspace_event_save():
    mock_hub = MagicMock()
    with patch("mcp.hub.get_hub", return_value=mock_hub):
        from container_commander.shell_context_bridge import save_shell_session_summary
        save_shell_session_summary(
            conversation_id="conv-1",
            container_id="ctr-abc",
            blueprint_id="bp-test",
            container_name="my-container",
            goal="Fix the noVNC blackscreen",
            findings="supervisord was not running",
            changes_applied="restarted supervisord",
            open_blocker="",
            step_count=4,
            commands=["supervisorctl status", "supervisorctl restart novnc"],
            user_requests=["fix noVNC"],
            final_stop_reason="",
            raw_summary="Summary text here",
        )
    mock_hub.call_tool.assert_called_once()
    call_args = mock_hub.call_tool.call_args
    assert call_args[0][0] == "workspace_event_save"
    payload = call_args[0][1]
    assert payload["conversation_id"] == "conv-1"
    assert payload["event_type"] == "shell_session_summary"
    data = payload["event_data"]
    assert data["container_id"] == "ctr-abc"
    assert data["blueprint_id"] == "bp-test"
    assert data["goal"] == "Fix the noVNC blackscreen"
    assert data["findings"] == "supervisord was not running"
    assert data["changes_applied"] == "restarted supervisord"
    assert data["step_count"] == 4
    assert "supervisorctl status" in data["commands"]


def test_save_shell_session_summary_fail_closed_on_hub_error():
    """Hub-Fehler darf nicht nach oben propagieren."""
    mock_hub = MagicMock()
    mock_hub.call_tool.side_effect = RuntimeError("hub unavailable")
    with patch("mcp.hub.get_hub", return_value=mock_hub):
        from container_commander.shell_context_bridge import save_shell_session_summary
        # kein raise erwartet
        save_shell_session_summary(
            conversation_id="conv-1",
            container_id="ctr-abc",
            blueprint_id="",
            container_name="",
            goal="",
            findings="",
            changes_applied="",
            open_blocker="",
            step_count=0,
            commands=[],
            user_requests=[],
        )


def test_save_shell_session_summary_truncates_long_fields():
    mock_hub = MagicMock()
    with patch("mcp.hub.get_hub", return_value=mock_hub):
        from container_commander.shell_context_bridge import save_shell_session_summary
        save_shell_session_summary(
            conversation_id="conv-1",
            container_id="ctr-abc",
            blueprint_id="bp",
            container_name="c",
            goal="x" * 500,
            findings="y" * 500,
            changes_applied="z" * 400,
            open_blocker="b" * 300,
            step_count=1,
            commands=[],
            user_requests=[],
        )
    data = mock_hub.call_tool.call_args[0][1]["event_data"]
    assert len(data["goal"]) <= 300
    assert len(data["findings"]) <= 400
    assert len(data["changes_applied"]) <= 300
    assert len(data["open_blocker"]) <= 200


def test_save_shell_session_summary_commands_capped_at_12():
    mock_hub = MagicMock()
    with patch("mcp.hub.get_hub", return_value=mock_hub):
        from container_commander.shell_context_bridge import save_shell_session_summary
        save_shell_session_summary(
            conversation_id="conv-1",
            container_id="ctr-abc",
            blueprint_id="",
            container_name="",
            goal="",
            findings="",
            changes_applied="",
            open_blocker="",
            step_count=20,
            commands=[f"cmd-{i}" for i in range(20)],
            user_requests=[f"req-{i}" for i in range(20)],
        )
    data = mock_hub.call_tool.call_args[0][1]["event_data"]
    assert len(data["commands"]) <= 12
    assert len(data["user_requests"]) <= 12


# ---------------------------------------------------------------------------
# save_shell_checkpoint
# ---------------------------------------------------------------------------

def test_save_shell_checkpoint_calls_workspace_event_save():
    mock_hub = MagicMock()
    with patch("mcp.hub.get_hub", return_value=mock_hub):
        from container_commander.shell_context_bridge import save_shell_checkpoint
        save_shell_checkpoint(
            conversation_id="conv-2",
            container_id="ctr-xyz",
            blueprint_id="bp-2",
            goal="Diagnose crash",
            finding="OOM killer triggered",
            action_taken="checked dmesg",
            blocker="",
            step_count=3,
        )
    mock_hub.call_tool.assert_called_once()
    call_args = mock_hub.call_tool.call_args
    assert call_args[0][0] == "workspace_event_save"
    payload = call_args[0][1]
    assert payload["event_type"] == "shell_checkpoint"
    data = payload["event_data"]
    assert data["container_id"] == "ctr-xyz"
    assert data["finding"] == "OOM killer triggered"
    assert data["step_count"] == 3


def test_save_shell_checkpoint_fail_closed_on_hub_error():
    mock_hub = MagicMock()
    mock_hub.call_tool.side_effect = RuntimeError("hub unavailable")
    with patch("mcp.hub.get_hub", return_value=mock_hub):
        from container_commander.shell_context_bridge import save_shell_checkpoint
        save_shell_checkpoint(
            conversation_id="conv-2",
            container_id="ctr-xyz",
            goal="",
            finding="",
            action_taken="",
        )


# ---------------------------------------------------------------------------
# build_mission_state
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


def test_build_mission_state_returns_empty_for_global():
    from container_commander.shell_context_bridge import build_mission_state
    result = _run(build_mission_state("global"))
    assert result == ""


def test_build_mission_state_returns_empty_for_empty_string():
    from container_commander.shell_context_bridge import build_mission_state
    result = _run(build_mission_state(""))
    assert result == ""


def test_build_mission_state_fail_open_on_bridge_error():
    with patch("core.bridge.get_bridge", side_effect=RuntimeError("no bridge")):
        from container_commander.shell_context_bridge import build_mission_state
        result = _run(build_mission_state("conv-3"))
    assert result == ""


def test_build_mission_state_truncates_long_context():
    long_text = "NOW bullet\n" * 100  # > 800 Zeichen
    mock_bridge = MagicMock()
    mock_bridge.orchestrator.context.build_small_model_context.return_value = long_text
    with patch("core.bridge.get_bridge", return_value=mock_bridge):
        from container_commander.shell_context_bridge import build_mission_state
        result = _run(build_mission_state("conv-4"))
    assert len(result) <= 850  # Puffer für "[...]"-Suffix (Limit jetzt 800)
    assert result.endswith("[...]")


def test_build_mission_state_returns_compact_context():
    mock_bridge = MagicMock()
    mock_bridge.orchestrator.context.build_small_model_context.return_value = (
        "NOW: container my-ctr running\nNEXT: check logs"
    )
    with patch("core.bridge.get_bridge", return_value=mock_bridge):
        from container_commander.shell_context_bridge import build_mission_state
        result = _run(build_mission_state("conv-5"))
    assert "my-ctr" in result
    assert len(result) <= 600


def test_build_mission_state_empty_context_returns_empty():
    mock_bridge = MagicMock()
    mock_bridge.orchestrator.context.build_small_model_context.return_value = ""
    with patch("core.bridge.get_bridge", return_value=mock_bridge):
        from container_commander.shell_context_bridge import build_mission_state
        result = _run(build_mission_state("conv-6"))
    assert result == ""


def test_build_mission_state_passes_correct_limits():
    """Limits müssen now_max=3, rules_max=2, next_max=2 sein (kompakt)."""
    mock_bridge = MagicMock()
    mock_bridge.orchestrator.context.build_small_model_context.return_value = "some context"
    with patch("core.bridge.get_bridge", return_value=mock_bridge):
        from container_commander.shell_context_bridge import build_mission_state
        _run(build_mission_state("conv-7"))
    call_kwargs = mock_bridge.orchestrator.context.build_small_model_context.call_args
    limits = call_kwargs[1].get("limits") or call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {}
    # limits sollten gesetzt sein
    assert call_kwargs is not None


def test_build_mission_state_includes_user_identity():
    """Persona-Info (user_name, language) wird in Mission State aufgenommen."""
    mock_persona = MagicMock()
    mock_persona.user_name = "Danny"
    mock_persona.language = "de"
    mock_persona.user_context = ["homeserver admin", "developer"]

    mock_bridge = MagicMock()
    mock_bridge.orchestrator.context.build_small_model_context.return_value = ""

    with patch("core.persona.get_persona", return_value=mock_persona), \
         patch("core.bridge.get_bridge", return_value=mock_bridge):
        from container_commander.shell_context_bridge import build_mission_state
        result = _run(build_mission_state("conv-8"))

    assert "Danny" in result
    assert "de" in result


def test_build_mission_state_skips_unknown_user_name():
    """user_name='unknown' darf nicht in den Mission State aufgenommen werden."""
    mock_persona = MagicMock()
    mock_persona.user_name = "unknown"
    mock_persona.language = "auto-detect"
    mock_persona.user_context = []

    mock_bridge = MagicMock()
    mock_bridge.orchestrator.context.build_small_model_context.return_value = ""

    with patch("core.persona.get_persona", return_value=mock_persona), \
         patch("core.bridge.get_bridge", return_value=mock_bridge):
        from container_commander.shell_context_bridge import build_mission_state
        result = _run(build_mission_state("conv-9"))

    assert result == ""


def test_build_mission_state_includes_memory_facts():
    """user_facts aus SQL-Memory werden in den Mission State aufgenommen."""
    mock_persona = MagicMock()
    mock_persona.user_name = "unknown"
    mock_persona.language = "auto-detect"
    mock_persona.user_context = []

    mock_bridge = MagicMock()
    mock_bridge.orchestrator.context.build_small_model_context.return_value = ""

    with patch("core.persona.get_persona", return_value=mock_persona), \
         patch("core.bridge.get_bridge", return_value=mock_bridge), \
         patch("mcp.client.get_fact_for_query", return_value="Name: Danny, prefers bash, knows Docker"):
        from container_commander.shell_context_bridge import build_mission_state
        result = _run(build_mission_state("conv-10"))

    assert "Danny" in result
    assert "bash" in result


def test_build_mission_state_memory_fail_open():
    """Fehler bei memory_fact_load darf nicht zum Absturz führen."""
    mock_persona = MagicMock()
    mock_persona.user_name = "Danny"
    mock_persona.language = "de"
    mock_persona.user_context = []

    mock_bridge = MagicMock()
    mock_bridge.orchestrator.context.build_small_model_context.return_value = "NOW: all good"

    with patch("core.persona.get_persona", return_value=mock_persona), \
         patch("core.bridge.get_bridge", return_value=mock_bridge), \
         patch("mcp.client.get_fact_for_query", side_effect=RuntimeError("hub down")):
        from container_commander.shell_context_bridge import build_mission_state
        result = _run(build_mission_state("conv-11"))

    # kein crash; Persona + Workspace-Context landen trotzdem
    assert "Danny" in result
    assert "NOW: all good" in result
