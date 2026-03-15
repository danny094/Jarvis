from unittest.mock import MagicMock, patch


def _make_orchestrator():
    from core.orchestrator import PipelineOrchestrator

    with patch("core.orchestrator.ThinkingLayer", return_value=MagicMock()), \
         patch("core.orchestrator.ControlLayer", return_value=MagicMock()), \
         patch("core.orchestrator.OutputLayer", return_value=MagicMock()), \
         patch("core.orchestrator.ToolSelector", return_value=MagicMock()), \
         patch("core.orchestrator.ContextManager", return_value=MagicMock()), \
         patch("core.orchestrator.get_hub", return_value=MagicMock()), \
         patch("core.orchestrator.get_registry", return_value=MagicMock()), \
         patch("core.orchestrator.get_master_orchestrator", return_value=MagicMock()):
        return PipelineOrchestrator()


def test_persist_master_workspace_event_writes_workspace_entry():
    orch = _make_orchestrator()

    with patch.object(orch, "_save_workspace_entry", return_value={"type": "workspace_update"}) as save:
        out = orch._persist_master_workspace_event(
            "conv-evt-1",
            "planning_step",
            {"phase": "planning", "next_action": "Analyze logs"},
        )

    assert out == {"type": "workspace_update"}
    save.assert_called_once()
    kwargs = save.call_args.kwargs
    assert kwargs["conversation_id"] == "conv-evt-1"
    assert kwargs["entry_type"] == "planning_step"
    assert kwargs["source_layer"] == "master"
    assert "phase=planning" in kwargs["content"]


def test_persist_master_workspace_event_ignores_unknown_event_type():
    orch = _make_orchestrator()

    with patch.object(orch, "_save_workspace_entry") as save:
        out = orch._persist_master_workspace_event(
            "conv-evt-2",
            "not_supported",
            {"foo": "bar"},
        )

    assert out is None
    save.assert_not_called()


def test_master_workspace_summary_includes_error_code_and_stop_reason():
    orch = _make_orchestrator()

    with patch.object(orch, "_save_workspace_entry", return_value={"type": "workspace_update"}) as save:
        orch._persist_master_workspace_event(
            "conv-evt-3",
            "planning_error",
            {
                "phase": "terminal",
                "error": "max loops reached",
                "error_code": "max_loops_reached",
                "stop_reason": "max_loops_reached",
            },
        )

    kwargs = save.call_args.kwargs
    assert kwargs["entry_type"] == "planning_error"
    assert "error_code=max_loops_reached" in kwargs["content"]
    assert "stop_reason=max_loops_reached" in kwargs["content"]
