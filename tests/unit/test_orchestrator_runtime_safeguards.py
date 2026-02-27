from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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


def test_response_mode_interactive_defers_heavy_sequential():
    orch = _make_orchestrator()
    plan = {"needs_sequential_thinking": True, "sequential_complexity": 8}
    with patch("config.get_default_response_mode", return_value="interactive"), \
         patch("config.get_response_mode_sequential_threshold", return_value=7):
        mode = orch._apply_response_mode_policy("analysiere pipeline", plan)
    assert mode == "interactive"
    assert plan["needs_sequential_thinking"] is False
    assert plan.get("_sequential_deferred") is True


def test_response_mode_deep_keeps_sequential():
    orch = _make_orchestrator()
    plan = {"needs_sequential_thinking": True, "sequential_complexity": 9}
    with patch("config.get_default_response_mode", return_value="interactive"), \
         patch("config.get_response_mode_sequential_threshold", return_value=7):
        mode = orch._apply_response_mode_policy("/deep analysiere pipeline", plan)
    assert mode == "deep"
    assert plan["needs_sequential_thinking"] is True
    assert plan.get("_sequential_deferred") is None


def test_response_mode_forced_deep_overrides_default():
    orch = _make_orchestrator()
    plan = {"needs_sequential_thinking": True, "sequential_complexity": 9}
    with patch("config.get_default_response_mode", return_value="interactive"), \
         patch("config.get_response_mode_sequential_threshold", return_value=7):
        mode = orch._apply_response_mode_policy(
            "analysiere pipeline",
            plan,
            forced_mode="deep",
        )
    assert mode == "deep"
    assert plan["needs_sequential_thinking"] is True
    assert plan.get("_sequential_deferred") is None


def test_response_mode_interactive_filters_think_from_suggested_tools():
    orch = _make_orchestrator()
    plan = {"suggested_tools": ["think", "list_skills"]}
    with patch("config.get_default_response_mode", return_value="interactive"), \
         patch("config.get_response_mode_sequential_threshold", return_value=7):
        mode = orch._apply_response_mode_policy("zeige skills", plan)
    assert mode == "interactive"
    assert plan["suggested_tools"] == ["list_skills"]


def test_response_mode_deep_keeps_think_in_suggested_tools():
    orch = _make_orchestrator()
    plan = {"suggested_tools": ["think", "list_skills"]}
    with patch("config.get_default_response_mode", return_value="interactive"), \
         patch("config.get_response_mode_sequential_threshold", return_value=7):
        mode = orch._apply_response_mode_policy("/deep analysiere", plan)
    assert mode == "deep"
    assert plan["suggested_tools"] == ["think", "list_skills"]


def test_tool_selector_candidates_drop_think_without_explicit_request():
    orch = _make_orchestrator()
    out = orch._filter_tool_selector_candidates(
        ["think", "list_skills"],
        user_text="zeige meine skills",
    )
    assert out == ["list_skills"]


def test_tool_selector_candidates_keep_think_with_explicit_request():
    orch = _make_orchestrator()
    out = orch._filter_tool_selector_candidates(
        ["think", "list_skills"],
        user_text="bitte denke schrittweise und zeig skills",
    )
    assert out == ["think", "list_skills"]


@pytest.mark.asyncio
async def test_collect_control_tool_decisions_uses_gate_override():
    orch = _make_orchestrator()
    orch.control.decide_tools = AsyncMock(side_effect=AssertionError("must not be called"))
    plan = {"_gate_tools_override": ["think"]}
    out = await orch._collect_control_tool_decisions("denke", plan, stream=True)
    assert "think" in out
    orch.control.decide_tools.assert_not_called()


@pytest.mark.asyncio
async def test_collect_control_tool_decisions_uses_control_decider_output():
    orch = _make_orchestrator()
    orch.control.decide_tools = AsyncMock(return_value=[
        {"name": "memory_graph_search", "arguments": {"query": "abc"}},
    ])
    out = await orch._collect_control_tool_decisions(
        "abc",
        {"suggested_tools": ["memory_graph_search"]},
        stream=False,
    )
    assert out == {"memory_graph_search": {"query": "abc"}}


def test_resolve_execution_suggested_tools_sync_keyword_fallback():
    orch = _make_orchestrator()
    verified_plan = {"suggested_tools": []}
    with patch.object(orch, "_normalize_tools", side_effect=lambda v: v), \
         patch.object(orch, "_detect_tools_by_keyword", return_value=["list_skills"]):
        out = orch._resolve_execution_suggested_tools(
            "zeige skills",
            verified_plan,
            control_tool_decisions={},
            stream=False,
            enable_skill_trigger_router=False,
        )
    assert out == ["list_skills"]
    assert verified_plan["_selected_tools_for_prompt"] == ["list_skills"]


def test_resolve_execution_suggested_tools_stream_trigger_router_fallback():
    orch = _make_orchestrator()
    verified_plan = {"suggested_tools": []}
    with patch.object(orch, "_normalize_tools", side_effect=lambda v: v), \
         patch.object(orch, "_detect_tools_by_keyword", return_value=[]), \
         patch.object(orch, "_detect_skill_by_trigger", return_value=["run_skill"]):
        out = orch._resolve_execution_suggested_tools(
            "starte meinen trigger-skill",
            verified_plan,
            control_tool_decisions={},
            stream=True,
            enable_skill_trigger_router=True,
        )
    assert out == ["run_skill"]
    assert verified_plan["_selected_tools_for_prompt"] == ["run_skill"]


def test_validate_tool_args_autofills_required_query():
    orch = _make_orchestrator()
    fake_hub = MagicMock()
    fake_hub._tool_definitions = {"analyze": {"inputSchema": {"required": ["query"]}}}
    ok, args, reason = orch._validate_tool_args(fake_hub, "analyze", {}, "prüfe bottleneck")
    assert ok is True
    assert args["query"] == "prüfe bottleneck"
    assert reason == ""


def test_validate_tool_args_autofills_required_message():
    orch = _make_orchestrator()
    fake_hub = MagicMock()
    fake_hub._tool_definitions = {"think": {"inputSchema": {"required": ["message"]}}}
    ok, args, reason = orch._validate_tool_args(fake_hub, "think", {}, "denke strukturiert")
    assert ok is True
    assert args["message"] == "denke strukturiert"
    assert reason == ""


def test_build_tool_args_create_skill_contains_required_fields():
    orch = _make_orchestrator()
    args = orch._build_tool_args("create_skill", "Erstelle einen CSV Import Skill")
    assert set(["name", "description", "code"]).issubset(set(args.keys()))
    assert isinstance(args["name"], str) and args["name"]
    assert isinstance(args["description"], str) and args["description"]
    assert isinstance(args["code"], str) and "def main" in args["code"]


def test_tool_context_skip_blocks_success_promotion_helpers():
    orch = _make_orchestrator()
    skip_ctx = "\n### TOOL-SKIP (create_skill): missing_required=['code']\n"
    ok_ctx = "\n[TOOL-CARD: run_skill | ✅ ok | ref=abc]\n"
    assert orch._tool_context_has_failures_or_skips(skip_ctx) is True
    assert orch._tool_context_has_success(skip_ctx) is False
    assert orch._tool_context_has_success(ok_ctx) is True


def test_save_memory_skips_autosave_on_pending_intent():
    orch = _make_orchestrator()
    with patch("core.orchestrator.autosave_assistant") as autosave_mock:
        orch._save_memory(
            conversation_id="conv-1",
            verified_plan={"_pending_intent": {"id": "intent-1", "skill_name": "abc"}},
            answer="Antwort",
        )
    autosave_mock.assert_not_called()


def test_save_memory_skips_autosave_on_tool_failure_or_skip():
    orch = _make_orchestrator()
    with patch("core.orchestrator.autosave_assistant") as autosave_mock:
        orch._save_memory(
            conversation_id="conv-1",
            verified_plan={"_tool_results": "### TOOL-SKIP (container_stats): missing_required=['container_id']"},
            answer="Antwort",
        )
    autosave_mock.assert_not_called()


def test_route_skill_request_fail_closed_on_router_exception():
    orch = _make_orchestrator()
    with patch("core.skill_router.get_skill_router", side_effect=RuntimeError("router-down")):
        decision = orch._route_skill_request("Erstelle einen Skill", {"intent": "create skill"})
    assert decision is not None
    assert decision.get("blocked") is True
    assert decision.get("reason") == "skill_router_unavailable"


def test_route_blueprint_request_fail_closed_on_router_exception():
    orch = _make_orchestrator()
    with patch("core.blueprint_router.get_blueprint_router", side_effect=RuntimeError("router-down")):
        decision = orch._route_blueprint_request("Starte Container", {"intent": "container start"})
    assert decision is not None
    assert decision.get("blocked") is True
    assert decision.get("reason") == "blueprint_router_unavailable"


@pytest.mark.asyncio
async def test_sync_short_circuits_on_pending_intent():
    from core.models import CoreChatRequest, Message, MessageRole

    orch = _make_orchestrator()
    orch.tool_selector.select_tools = AsyncMock(return_value=[])
    orch.thinking.analyze = AsyncMock(return_value={
        "intent": "skill creation",
        "needs_memory": False,
        "memory_keys": [],
        "hallucination_risk": "medium",
        "needs_sequential_thinking": False,
        "suggested_tools": ["create_skill"],
    })
    orch.build_effective_context = MagicMock(return_value=("", {
        "memory_used": False,
        "small_model_mode": False,
        "context_chars": 0,
        "retrieval_count": 0,
        "context_sources": [],
        "context_chars_final": 0,
    }))
    orch._execute_control_layer = AsyncMock(return_value=(
        {"approved": True, "corrections": {}},
        {
            "suggested_tools": ["create_skill"],
            "_pending_intent": {"id": "intent-1", "skill_name": "demo-skill"},
        },
    ))
    orch.control.decide_tools = AsyncMock(return_value=[])
    orch._execute_output_layer = AsyncMock(return_value="should-not-run")
    orch._save_memory = MagicMock()

    with patch("core.orchestrator.INTENT_SYSTEM_AVAILABLE", False):
        request = CoreChatRequest(
            model="test-model",
            messages=[Message(role=MessageRole.USER, content="Bitte skill erstellen")],
            conversation_id="conv-sync",
            source_adapter="test",
        )
        response = await orch.process(request)

    assert response.done_reason == "confirmation_pending"
    assert "demo-skill" in response.content
    orch.control.decide_tools.assert_not_called()
    orch._execute_output_layer.assert_not_called()
    orch._save_memory.assert_not_called()


@pytest.mark.asyncio
async def test_sync_fail_closed_blocks_skill_tools_when_router_unavailable():
    from core.models import CoreChatRequest, Message, MessageRole

    orch = _make_orchestrator()
    captured = {}
    orch.tool_selector.select_tools = AsyncMock(return_value=[])
    orch.thinking.analyze = AsyncMock(return_value={
        "intent": "skill creation",
        "needs_memory": False,
        "memory_keys": [],
        "hallucination_risk": "medium",
        "needs_sequential_thinking": False,
        "suggested_tools": ["autonomous_skill_task"],
    })
    orch._route_skill_request = MagicMock(return_value={
        "blocked": True,
        "reason": "skill_router_unavailable",
    })
    orch._route_blueprint_request = MagicMock(return_value=None)
    orch.build_effective_context = MagicMock(return_value=("", {
        "memory_used": False,
        "small_model_mode": False,
        "context_chars": 0,
        "retrieval_count": 0,
        "context_sources": [],
        "context_chars_final": 0,
    }))

    async def _control_side_effect(_user_text, thinking_plan, *_args):
        captured["skill_gate_blocked"] = bool(thinking_plan.get("_skill_gate_blocked"))
        captured["suggested_tools"] = list(thinking_plan.get("suggested_tools", []))
        return {"approved": True, "corrections": {}}, {"suggested_tools": []}

    orch._execute_control_layer = AsyncMock(side_effect=_control_side_effect)
    orch.control.decide_tools = AsyncMock(return_value=[])
    orch._execute_output_layer = AsyncMock(return_value="ok")
    orch._save_memory = MagicMock()

    request = CoreChatRequest(
        model="test-model",
        messages=[Message(role=MessageRole.USER, content="Bitte Skill erstellen")],
        conversation_id="conv-sync-fail-closed-skill",
        source_adapter="test",
    )
    await orch.process(request)

    assert captured.get("skill_gate_blocked") is True
    assert "autonomous_skill_task" not in captured.get("suggested_tools", [])


@pytest.mark.asyncio
async def test_sync_fail_closed_blocks_blueprint_when_router_unavailable():
    from core.models import CoreChatRequest, Message, MessageRole

    orch = _make_orchestrator()
    captured = {}
    orch.tool_selector.select_tools = AsyncMock(return_value=[])
    orch.thinking.analyze = AsyncMock(return_value={
        "intent": "container start",
        "needs_memory": False,
        "memory_keys": [],
        "hallucination_risk": "medium",
        "needs_sequential_thinking": False,
        "suggested_tools": ["request_container"],
    })
    orch._route_skill_request = MagicMock(return_value=None)
    orch._route_blueprint_request = MagicMock(return_value={
        "blocked": True,
        "reason": "blueprint_router_unavailable",
    })
    orch.build_effective_context = MagicMock(return_value=("", {
        "memory_used": False,
        "small_model_mode": False,
        "context_chars": 0,
        "retrieval_count": 0,
        "context_sources": [],
        "context_chars_final": 0,
    }))

    async def _control_side_effect(_user_text, thinking_plan, *_args):
        captured["blueprint_gate_blocked"] = bool(thinking_plan.get("_blueprint_gate_blocked"))
        captured["blueprint_gate_reason"] = thinking_plan.get("_blueprint_gate_reason")
        return {"approved": True, "corrections": {}}, {"suggested_tools": []}

    orch._execute_control_layer = AsyncMock(side_effect=_control_side_effect)
    orch.control.decide_tools = AsyncMock(return_value=[])
    orch._execute_output_layer = AsyncMock(return_value="ok")
    orch._save_memory = MagicMock()

    request = CoreChatRequest(
        model="test-model",
        messages=[Message(role=MessageRole.USER, content="Container starten")],
        conversation_id="conv-sync-fail-closed-blueprint",
        source_adapter="test",
    )
    await orch.process(request)

    assert captured.get("blueprint_gate_blocked") is True
    assert captured.get("blueprint_gate_reason") == "blueprint_router_unavailable"


@pytest.mark.asyncio
async def test_stream_sets_pending_intent_and_emits_confirmation():
    from core.models import CoreChatRequest, Message, MessageRole

    orch = _make_orchestrator()

    async def _analyze_stream(*args, **kwargs):
        yield "", True, {
            "intent": "skill creation",
            "needs_memory": False,
            "memory_keys": [],
            "hallucination_risk": "medium",
            "needs_sequential_thinking": False,
            "suggested_tools": ["create_skill"],
        }

    orch.tool_selector.select_tools = AsyncMock(return_value=[])
    orch.thinking.analyze_stream = _analyze_stream
    orch.control.verify = AsyncMock(return_value={
        "approved": True,
        "corrections": {},
        "warnings": [],
        "_needs_skill_confirmation": True,
        "_skill_name": "demo-skill",
        "_cim_decision": {"pattern_id": "test"},
    })
    orch.control.apply_corrections = MagicMock(side_effect=lambda plan, verification: dict(plan))
    orch.control.decide_tools = AsyncMock(return_value=[])
    orch.build_effective_context = MagicMock(return_value=("", {
        "memory_used": False,
        "small_model_mode": False,
        "context_chars": 0,
        "retrieval_count": 0,
        "context_sources": [],
        "context_chars_final": 0,
    }))
    orch._extract_workspace_observations = MagicMock(return_value=None)
    orch._save_workspace_entry = MagicMock(return_value=None)
    orch._check_hardware_gate_early = MagicMock(return_value=None)

    with patch("core.orchestrator.INTENT_SYSTEM_AVAILABLE", True), \
         patch("core.orchestrator.IntentOrigin", new=type("IntentOrigin", (), {"USER": "user"})), \
         patch("core.orchestrator.get_intent_store") as get_store_mock, \
         patch("core.orchestrator.SkillCreationIntent") as intent_cls_mock:
        store = MagicMock()
        get_store_mock.return_value = store
        intent_obj = MagicMock()
        intent_obj.id = "intent-12345678"
        intent_obj.to_dict.return_value = {"id": "intent-12345678", "skill_name": "demo-skill"}
        intent_cls_mock.return_value = intent_obj

        request = CoreChatRequest(
            model="test-model",
            messages=[Message(role=MessageRole.USER, content="Bitte skill erstellen")],
            conversation_id="conv-stream",
            source_adapter="test",
        )

        events = []
        async for chunk, done, meta in orch.process_stream_with_events(request):
            events.append((chunk, done, meta))
            if done:
                break

    pending = [meta for _, _, meta in events if meta.get("type") == "confirmation_pending"]
    assert pending, "Expected confirmation_pending event in streaming path"
    assert intent_cls_mock.call_args.kwargs.get("user_text") == "Bitte skill erstellen"


@pytest.mark.asyncio
async def test_stream_sensitive_tool_keeps_control_even_without_skill_keyword():
    from core.models import CoreChatRequest, Message, MessageRole

    orch = _make_orchestrator()

    async def _analyze_stream(*args, **kwargs):
        yield "", True, {
            "intent": "feature implementation",
            "needs_memory": False,
            "memory_keys": [],
            "hallucination_risk": "low",
            "needs_sequential_thinking": False,
            "suggested_tools": ["create_skill"],
        }

    orch.tool_selector.select_tools = AsyncMock(return_value=[])
    orch.thinking.analyze_stream = _analyze_stream
    orch.control.verify = AsyncMock(return_value={
        "approved": True,
        "corrections": {},
        "warnings": [],
        "_needs_skill_confirmation": True,
        "_skill_name": "quick_probe_helper",
        "_cim_decision": {"pattern_id": "test"},
    })
    orch.control.apply_corrections = MagicMock(side_effect=lambda plan, verification: dict(plan))
    orch.control.decide_tools = AsyncMock(return_value=[])
    orch.build_effective_context = MagicMock(return_value=("", {
        "memory_used": False,
        "small_model_mode": False,
        "context_chars": 0,
        "retrieval_count": 0,
        "context_sources": [],
        "context_chars_final": 0,
    }))
    orch._extract_workspace_observations = MagicMock(return_value=None)
    orch._save_workspace_entry = MagicMock(return_value=None)
    orch._check_hardware_gate_early = MagicMock(return_value=None)

    with patch("core.orchestrator.INTENT_SYSTEM_AVAILABLE", True), \
         patch("core.orchestrator.IntentOrigin", new=type("IntentOrigin", (), {"USER": "user"})), \
         patch("core.orchestrator.get_intent_store") as get_store_mock, \
         patch("core.orchestrator.SkillCreationIntent") as intent_cls_mock:
        store = MagicMock()
        get_store_mock.return_value = store
        intent_obj = MagicMock()
        intent_obj.id = "intent-87654321"
        intent_obj.to_dict.return_value = {"id": "intent-87654321", "skill_name": "quick_probe_helper"}
        intent_cls_mock.return_value = intent_obj

        request = CoreChatRequest(
            model="test-model",
            messages=[Message(role=MessageRole.USER, content="Baue eine neue Funktion namens quick_probe_helper")],
            conversation_id="conv-stream-sensitive",
            source_adapter="test",
        )

        events = []
        async for chunk, done, meta in orch.process_stream_with_events(request):
            events.append((chunk, done, meta))
            if done:
                break

    control_events = [meta for _, _, meta in events if meta.get("type") == "control"]
    assert control_events
    assert control_events[0].get("skipped") is False
    pending = [meta for _, _, meta in events if meta.get("type") == "confirmation_pending"]
    assert pending, "Expected confirmation_pending event in streaming path"
    assert intent_cls_mock.call_args.kwargs.get("user_text") == "Baue eine neue Funktion namens quick_probe_helper"


@pytest.mark.asyncio
async def test_pending_confirmation_supplies_required_task_args_and_accepts_prefixed_yes():
    from core.intent_models import SkillCreationIntent, IntentState

    orch = _make_orchestrator()
    intent = SkillCreationIntent(
        skill_name="demo-skill",
        reason="control_layer",
        conversation_id="conv-intent-confirm",
        user_text="Erstelle einen Skill zum Addieren",
        thinking_plan={
            "intent": "skill_create",
            "reasoning": "Need tool",
            "sequential_complexity": 7,
            "suggested_tools": [{"name": "autonomous_skill_task"}, "run_skill"],
            "_sequential_result": {"raw": "drop-me"},
        },
    )

    store = MagicMock()
    store.get_pending_for_conversation.return_value = [intent]
    store.update_state = MagicMock()

    hub = MagicMock()
    hub.call_tool.return_value = {
        "success": True,
        "skill_name": "demo-skill",
        "execution_result": {"ok": True},
        "validation_score": 1.0,
    }

    with patch("core.orchestrator.INTENT_SYSTEM_AVAILABLE", True), \
         patch("core.orchestrator.get_intent_store", return_value=store), \
         patch("core.orchestrator.get_hub", return_value=hub):
        response = await orch._check_pending_confirmation(
            "Ja, bestätige bitte.",
            "conv-intent-confirm",
        )

    assert response is not None
    assert "wurde erstellt" in response.content
    assert intent.state == IntentState.EXECUTED

    hub.call_tool.assert_called_once()
    tool_name, task_args = hub.call_tool.call_args[0]
    assert tool_name == "autonomous_skill_task"
    assert isinstance(task_args.get("user_text"), str) and task_args["user_text"].strip()
    assert isinstance(task_args.get("intent"), str) and task_args["intent"].strip()
    assert task_args["user_text"] == task_args["intent"]
    assert isinstance(task_args.get("_trace_id"), str) and task_args["_trace_id"].strip()
    assert task_args.get("prefer_create") is True
    assert isinstance(task_args.get("thinking_plan"), dict)
    assert "_sequential_result" not in task_args["thinking_plan"]
    assert task_args["thinking_plan"].get("suggested_tools") == ["autonomous_skill_task", "run_skill"]


@pytest.mark.asyncio
async def test_pending_confirmation_treats_created_skill_with_run_error_as_partial_success():
    from core.intent_models import SkillCreationIntent, IntentState

    orch = _make_orchestrator()
    intent = SkillCreationIntent(
        skill_name="demo-skill",
        reason="control_layer",
        conversation_id="conv-intent-partial",
        user_text="Erstelle einen Skill demo-skill",
    )

    store = MagicMock()
    store.get_pending_for_conversation.return_value = [intent]
    store.update_state = MagicMock()

    hub = MagicMock()
    hub.call_tool.return_value = {
        "success": False,
        "skill_created": True,
        "skill_name": "demo-skill",
        "error": "TypeError: unhashable type: 'dict'",
    }

    with patch("core.orchestrator.INTENT_SYSTEM_AVAILABLE", True), \
         patch("core.orchestrator.get_intent_store", return_value=store), \
         patch("core.orchestrator.get_hub", return_value=hub):
        response = await orch._check_pending_confirmation(
            "Ja",
            "conv-intent-partial",
        )

    assert response is not None
    assert "wurde erstellt" in response.content
    assert "Testlauf ist fehlgeschlagen" in response.content
    assert intent.state == IntentState.EXECUTED


@pytest.mark.asyncio
async def test_sync_control_not_skipped_for_low_risk_skill_keywords():
    orch = _make_orchestrator()
    orch.control.verify = AsyncMock(return_value={"approved": True, "corrections": {}, "warnings": []})
    orch.control.apply_corrections = MagicMock(side_effect=lambda plan, verification: dict(plan))

    with patch("core.orchestrator.ENABLE_CONTROL_LAYER", True), \
         patch("core.orchestrator.SKIP_CONTROL_ON_LOW_RISK", True):
        verification, verified_plan = await orch._execute_control_layer(
            user_text="erstelle bitte einen skill",
            thinking_plan={"hallucination_risk": "low"},
            memory_data="",
            conversation_id="conv-sync-guard",
        )

    orch.control.verify.assert_awaited_once()
    assert verified_plan.get("_skipped") is not True
    assert verification.get("approved") is True


@pytest.mark.asyncio
async def test_sync_control_creates_intent_with_user_text():
    orch = _make_orchestrator()
    orch.control.verify = AsyncMock(return_value={
        "approved": True,
        "corrections": {},
        "warnings": [],
        "_needs_skill_confirmation": True,
        "_skill_name": "demo-skill",
        "_cim_decision": {"pattern_id": "test"},
    })
    orch.control.apply_corrections = MagicMock(side_effect=lambda plan, verification: dict(plan))

    with patch("core.orchestrator.INTENT_SYSTEM_AVAILABLE", True), \
         patch("core.orchestrator.IntentOrigin", new=type("IntentOrigin", (), {"USER": "user"})), \
         patch("core.orchestrator.get_intent_store") as get_store_mock, \
         patch("core.orchestrator.SkillCreationIntent") as intent_cls_mock:
        store = MagicMock()
        get_store_mock.return_value = store
        intent_obj = MagicMock()
        intent_obj.id = "intent-sync-1234"
        intent_obj.to_dict.return_value = {"id": "intent-sync-1234", "skill_name": "demo-skill"}
        intent_cls_mock.return_value = intent_obj

        _, verified_plan = await orch._execute_control_layer(
            user_text="Bitte erstelle einen Skill demo-skill",
            thinking_plan={"hallucination_risk": "medium"},
            memory_data="",
            conversation_id="conv-sync-intent",
        )

    assert verified_plan.get("_pending_intent", {}).get("id") == "intent-sync-1234"
    assert intent_cls_mock.call_args.kwargs.get("user_text") == "Bitte erstelle einen Skill demo-skill"


@pytest.mark.asyncio
async def test_sync_control_not_skipped_for_low_risk_sensitive_tools_without_keyword():
    orch = _make_orchestrator()
    orch.control.verify = AsyncMock(return_value={"approved": True, "corrections": {}, "warnings": []})
    orch.control.apply_corrections = MagicMock(side_effect=lambda plan, verification: dict(plan))

    with patch("core.orchestrator.ENABLE_CONTROL_LAYER", True), \
         patch("core.orchestrator.SKIP_CONTROL_ON_LOW_RISK", True):
        verification, verified_plan = await orch._execute_control_layer(
            user_text="Baue eine neue Funktion namens quick_probe_helper",
            thinking_plan={"hallucination_risk": "low", "suggested_tools": ["create_skill"]},
            memory_data="",
            conversation_id="conv-sync-sensitive",
        )

    orch.control.verify.assert_awaited_once()
    assert verified_plan.get("_skipped") is not True
    assert verification.get("approved") is True


@pytest.mark.asyncio
async def test_sync_control_still_skips_for_low_risk_non_skill_text():
    orch = _make_orchestrator()
    orch.control.verify = AsyncMock(return_value={"approved": True, "corrections": {}, "warnings": []})

    with patch("core.orchestrator.ENABLE_CONTROL_LAYER", True), \
         patch("core.orchestrator.SKIP_CONTROL_ON_LOW_RISK", True):
        verification, verified_plan = await orch._execute_control_layer(
            user_text="wie ist das wetter morgen",
            thinking_plan={"hallucination_risk": "low"},
            memory_data="",
            conversation_id="conv-sync-skip",
        )

    orch.control.verify.assert_not_awaited()
    assert verified_plan.get("_skipped") is True
    assert verification.get("approved") is True


def test_should_skip_control_layer_blocks_low_risk_skip_for_sensitive_tools():
    orch = _make_orchestrator()
    with patch("core.orchestrator.ENABLE_CONTROL_LAYER", True), \
         patch("core.orchestrator.SKIP_CONTROL_ON_LOW_RISK", True):
        skip, reason = orch._should_skip_control_layer(
            user_text="Baue eine neue Funktion namens quick_probe_helper",
            thinking_plan={
                "hallucination_risk": "low",
                "suggested_tools": ["create_skill"],
            },
        )
    assert skip is False
    assert "sensitive_tools" in reason


def test_should_skip_control_layer_still_skips_harmless_low_risk():
    orch = _make_orchestrator()
    with patch("core.orchestrator.ENABLE_CONTROL_LAYER", True), \
         patch("core.orchestrator.SKIP_CONTROL_ON_LOW_RISK", True):
        skip, reason = orch._should_skip_control_layer(
            user_text="Wie spät ist es in Berlin?",
            thinking_plan={
                "hallucination_risk": "low",
                "suggested_tools": ["get_system_overview"],
            },
        )
    assert skip is True
    assert reason == "low_risk_skip"
