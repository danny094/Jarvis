import pytest

from core.master.orchestrator import MasterContext, MasterOrchestrator, OrchestrationState


class _DummyPipeline:
    pass


@pytest.mark.asyncio
async def test_execute_objective_emits_planning_start_and_done(monkeypatch):
    events = []

    def _sink(conversation_id, event_type, payload):
        events.append((conversation_id, event_type, payload))

    master = MasterOrchestrator(_DummyPipeline(), event_sink=_sink)
    monkeypatch.setattr(
        master,
        "_load_settings",
        lambda: {
            "enabled": True,
            "use_thinking_layer": False,
            "max_loops": 3,
            "completion_threshold": 2,
        },
    )

    async def _fake_loop(context):
        context.state = OrchestrationState.COMPLETED
        return {"loops_executed": 0, "final_state": "completed", "steps": []}

    monkeypatch.setattr(master, "_autonomous_loop", _fake_loop)

    out = await master.execute_objective("Summarize incidents", "conv-master-1")

    assert out["success"] is True
    event_types = [e[1] for e in events]
    assert event_types[0] == "planning_start"
    assert "planning_done" in event_types


@pytest.mark.asyncio
async def test_execute_objective_returns_error_when_master_disabled(monkeypatch):
    events = []

    def _sink(conversation_id, event_type, payload):
        events.append((conversation_id, event_type, payload))

    master = MasterOrchestrator(_DummyPipeline(), event_sink=_sink)
    monkeypatch.setattr(
        master,
        "_load_settings",
        lambda: {
            "enabled": False,
            "use_thinking_layer": False,
            "max_loops": 10,
            "completion_threshold": 2,
        },
    )

    out = await master.execute_objective("Do task", "conv-master-2")

    assert out["success"] is False
    assert out["final_state"] == "failed"
    assert events
    assert events[-1][1] == "planning_error"


@pytest.mark.asyncio
async def test_reflect_uses_completion_threshold_setting():
    master = MasterOrchestrator(_DummyPipeline())
    context = MasterContext(
        objective="obj",
        state=OrchestrationState.REFLECTING,
        conversation_id="conv-master-3",
        max_loops=3,
    )
    context.steps_completed = [
        {"success": True},
        {"success": True},
    ]

    master.settings = {"completion_threshold": 3}
    should_continue = await master._reflect(context)
    assert should_continue is True

    master.settings = {"completion_threshold": 2}
    should_continue = await master._reflect(context)
    assert should_continue is False


@pytest.mark.asyncio
async def test_execute_objective_marks_loop_guard_as_failure(monkeypatch):
    master = MasterOrchestrator(_DummyPipeline())
    monkeypatch.setattr(
        master,
        "_load_settings",
        lambda: {
            "enabled": True,
            "use_thinking_layer": False,
            "max_loops": 1,
            "completion_threshold": 2,
        },
    )

    out = await master.execute_objective("Quick check", "conv-master-loopguard", max_loops=1)

    assert out["success"] is False
    assert out["final_state"] == "failed"
    assert out["error_code"] == "max_loops_reached"
    assert out["stop_reason"] == "max_loops_reached"


@pytest.mark.asyncio
async def test_plan_loop_detected_sets_terminal_error():
    master = MasterOrchestrator(_DummyPipeline())
    context = MasterContext(
        objective="obj",
        state=OrchestrationState.PLANNING,
        conversation_id="conv-master-plan",
    )
    context.steps_completed = [
        {"action": "repeat"},
        {"action": "repeat"},
        {"action": "repeat"},
    ]

    created = await master._plan(context)
    assert created is False
    assert context.terminal_error_code == "loop_detected"
    assert context.stop_reason == "loop_detected"


@pytest.mark.asyncio
async def test_reflect_too_many_failures_sets_terminal_error():
    master = MasterOrchestrator(_DummyPipeline())
    context = MasterContext(
        objective="obj",
        state=OrchestrationState.REFLECTING,
        conversation_id="conv-master-reflect",
    )
    context.steps_completed = [
        {"success": False},
        {"success": False},
        {"success": False},
    ]
    master.settings = {"completion_threshold": 5}

    should_continue = await master._reflect(context)
    assert should_continue is False
    assert context.terminal_error_code == "too_many_failures"
    assert context.stop_reason == "too_many_failures"
