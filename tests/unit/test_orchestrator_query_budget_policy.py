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


def test_query_budget_factual_low_keeps_control_decisions():
    orch = _make_orchestrator()
    verified_plan = {
        "dialogue_act": "request",
        "_query_budget": {
            "query_type": "factual",
            "complexity_signal": "low",
            "confidence": 0.92,
            "tool_hint": "memory_graph_search",
        },
    }
    control_decisions = {
        "analyze": {"query": "x"},
        "memory_graph_search": {"query": "x"},
        "run_skill": {"name": "x"},
    }
    with patch.object(orch, "_normalize_tools", side_effect=lambda v: v), \
         patch.object(orch, "_prioritize_home_container_tools", side_effect=lambda *a, **k: a[2]), \
         patch("config.get_query_budget_enable", return_value=True), \
         patch("config.get_query_budget_max_tools_factual_low", return_value=1):
        out = orch._resolve_execution_suggested_tools(
            "Was hast du dir gemerkt?",
            verified_plan,
            control_decisions,
            stream=False,
            enable_skill_trigger_router=False,
        )
    assert out == ["analyze", "memory_graph_search", "run_skill"]


def test_query_budget_analytical_interactive_keeps_control_decisions():
    orch = _make_orchestrator()
    verified_plan = {
        "_response_mode": "interactive",
        "_query_budget": {
            "query_type": "analytical",
            "complexity_signal": "high",
            "confidence": 0.93,
            "tool_hint": "analyze",
        },
    }
    control_decisions = {
        "think_simple": {"message": "x"},
        "analyze": {"query": "x"},
        "memory_search": {"query": "x"},
    }
    with patch.object(orch, "_normalize_tools", side_effect=lambda v: v), \
         patch.object(orch, "_prioritize_home_container_tools", side_effect=lambda *a, **k: a[2]), \
         patch("config.get_query_budget_enable", return_value=True):
        out = orch._resolve_execution_suggested_tools(
            "Analysiere meine Pipeline in 5 Punkten.",
            verified_plan,
            control_decisions,
            stream=False,
            enable_skill_trigger_router=False,
        )
    assert out == ["think_simple", "analyze", "memory_search"]


def test_query_budget_conversational_keeps_control_decisions():
    orch = _make_orchestrator()
    verified_plan = {
        "dialogue_act": "smalltalk",
        "_query_budget": {
            "query_type": "conversational",
            "complexity_signal": "low",
            "confidence": 0.95,
            "tool_hint": "",
        },
    }
    control_decisions = {
        "analyze": {"query": "x"},
    }
    with patch.object(orch, "_normalize_tools", side_effect=lambda v: v), \
         patch.object(orch, "_prioritize_home_container_tools", side_effect=lambda *a, **k: a[2]), \
         patch("config.get_query_budget_enable", return_value=True):
        out = orch._resolve_execution_suggested_tools(
            "Hey danke dir!",
            verified_plan,
            control_decisions,
            stream=False,
            enable_skill_trigger_router=False,
        )
    assert out == ["analyze"]


def test_query_budget_keeps_tools_when_user_explicitly_requests_tool_use():
    orch = _make_orchestrator()
    verified_plan = {
        "dialogue_act": "request",
        "_query_budget": {
            "query_type": "factual",
            "complexity_signal": "low",
            "confidence": 0.91,
            "tool_hint": "memory_graph_search",
        },
    }
    control_decisions = {
        "analyze": {"query": "x"},
    }
    with patch.object(orch, "_normalize_tools", side_effect=lambda v: v), \
         patch.object(orch, "_prioritize_home_container_tools", side_effect=lambda *a, **k: a[2]), \
         patch("config.get_query_budget_enable", return_value=True):
        out = orch._resolve_execution_suggested_tools(
            "Bitte nutze ein Tool und analyze das jetzt.",
            verified_plan,
            control_decisions,
            stream=False,
            enable_skill_trigger_router=False,
        )
    assert out == ["analyze"]


def test_skill_trigger_router_skips_without_explicit_skill_intent():
    orch = _make_orchestrator()
    verified_plan = {
        "dialogue_act": "request",
        "is_fact_query": False,
        "_query_budget": {
            "query_type": "analytical",
            "complexity_signal": "medium",
            "confidence": 0.92,
            "tool_hint": "analyze",
        },
    }
    with patch.object(orch, "_normalize_tools", side_effect=lambda v: v), \
         patch.object(orch, "_prioritize_home_container_tools", side_effect=lambda *a, **k: a[2]), \
         patch.object(orch, "_detect_tools_by_keyword", return_value=[]), \
         patch.object(orch, "_detect_skill_by_trigger", return_value=[{"tool": "run_skill", "args": {"name": "test_pipeline_skill"}}]), \
         patch("config.get_query_budget_enable", return_value=True):
        out = orch._resolve_execution_suggested_tools(
            "Nenne drei konkrete Software-Flaschenhälse in orchestrierten LLM-Pipelines.",
            verified_plan,
            {},
            stream=True,
            enable_skill_trigger_router=True,
            conversation_id="conv-x",
            chat_history=[],
        )
    assert out == []


def test_skill_trigger_router_runs_with_explicit_skill_intent():
    orch = _make_orchestrator()
    verified_plan = {
        "dialogue_act": "request",
        "is_fact_query": False,
        "_query_budget": {
            "query_type": "action",
            "complexity_signal": "low",
            "confidence": 0.90,
            "tool_hint": "",
        },
    }
    with patch.object(orch, "_normalize_tools", side_effect=lambda v: v), \
         patch.object(orch, "_prioritize_home_container_tools", side_effect=lambda *a, **k: a[2]), \
         patch.object(orch, "_detect_tools_by_keyword", return_value=[]), \
         patch.object(orch, "_detect_skill_by_trigger", return_value=[{"tool": "run_skill", "args": {"name": "test_pipeline_skill"}}]), \
         patch("config.get_query_budget_enable", return_value=True):
        out = orch._resolve_execution_suggested_tools(
            "Bitte starte den Skill test_pipeline_skill.",
            verified_plan,
            {},
            stream=True,
            enable_skill_trigger_router=True,
            conversation_id="conv-y",
            chat_history=[],
        )
    assert out == [{"tool": "run_skill", "args": {"name": "test_pipeline_skill"}}]


def test_contains_explicit_tool_intent_ignores_tooling_substring():
    orch = _make_orchestrator()
    assert orch._contains_explicit_tool_intent(
        "Analysiere Input-zu-Output Pipeline in 5 Punkten: Thinking, Control, Tooling, Memory, Output."
    ) is False
    assert orch._contains_explicit_tool_intent("Bitte nutze ein Tool dafür.") is True


def test_contains_explicit_skill_intent_uses_word_boundaries():
    orch = _make_orchestrator()
    assert orch._contains_explicit_skill_intent("Unser skillset ist gewachsen.") is False
    assert orch._contains_explicit_skill_intent("Bitte starte den Skill diagnostics.") is True


def test_contains_explicit_tool_intent_detects_tool_domain_tag():
    orch = _make_orchestrator()
    assert orch._contains_explicit_tool_intent("{TOOL:MCP_CALL} führe einen MCP call aus.") is True
    assert orch._contains_explicit_tool_intent("{CRONJOB} erstelle einen one-shot job.") is True


def test_apply_query_budget_to_plan_skips_factual_memory_force_for_feelings_prompt():
    orch = _make_orchestrator()
    plan = {
        "intent": "unknown",
        "needs_memory": False,
        "is_fact_query": False,
        "dialogue_act": "request",
    }
    signal = {
        "query_type": "factual",
        "intent_hint": "fact_lookup",
        "confidence": 0.92,
        "response_budget": "short",
        "tool_hint": "memory_search",
    }
    out = orch._apply_query_budget_to_plan(
        plan,
        signal,
        user_text="Ich finde auch eine KI darf sagen, dass sie Gefühle hat.",
    )
    assert out.get("is_fact_query") is False
    assert out.get("needs_memory") is False
    assert out.get("_query_budget_factual_memory_force_skipped") is True


def test_apply_query_budget_to_plan_skips_memory_force_for_explicit_tool_runtime_prompt():
    orch = _make_orchestrator()
    plan = {
        "intent": "unknown",
        "needs_memory": False,
        "is_fact_query": False,
        "dialogue_act": "request",
    }
    signal = {
        "query_type": "factual",
        "intent_hint": "fact_lookup",
        "confidence": 0.92,
        "response_budget": "medium",
        "tool_hint": "memory_search",
    }
    out = orch._apply_query_budget_to_plan(
        plan,
        signal,
        user_text=(
            "Guten Abend TRION. Kannst du versuchen, due IP addrese vom Host server herraus zu finden? "
            "Nutze gerne alle Tools die du dafür benötigst."
        ),
    )
    assert out.get("is_fact_query") is False
    assert out.get("needs_memory") is False
    assert out.get("_query_budget_factual_memory_force_skipped") is True


def test_resolve_precontrol_policy_conflicts_lifts_query_budget_memory_force_for_locked_container():
    orch = _make_orchestrator()
    plan = {
        "needs_memory": True,
        "is_fact_query": True,
        "memory_keys": [],
        "_query_budget_factual_memory_forced": True,
        "_domain_route": {
            "domain_tag": "CONTAINER",
            "domain_locked": True,
            "operation": "status",
        },
    }
    out = orch._resolve_precontrol_policy_conflicts(
        "Finde die IP Adresse vom Host Server und nutze alle Tools.",
        plan,
    )
    assert out["needs_memory"] is False
    assert out["is_fact_query"] is False
    assert isinstance(out.get("_policy_conflict_resolution"), list)


def test_resolve_precontrol_policy_conflicts_keeps_memory_force_for_recall_prompt():
    orch = _make_orchestrator()
    plan = {
        "needs_memory": True,
        "is_fact_query": True,
        "memory_keys": [],
        "_query_budget_factual_memory_forced": True,
        "_domain_route": {
            "domain_tag": "CONTAINER",
            "domain_locked": True,
            "operation": "status",
        },
    }
    out = orch._resolve_precontrol_policy_conflicts(
        "Was hast du dir über meine Container Präferenz gemerkt?",
        plan,
    )
    assert out["needs_memory"] is True
    assert out["is_fact_query"] is True


def test_resolve_precontrol_policy_conflicts_sets_resolved_marker_and_reason():
    orch = _make_orchestrator()
    plan = {
        "needs_memory": True,
        "is_fact_query": True,
        "memory_keys": [],
        "_query_budget_factual_memory_forced": True,
        "_domain_route": {
            "domain_tag": "CONTAINER",
            "domain_locked": True,
            "operation": "exec",
        },
    }
    out = orch._resolve_precontrol_policy_conflicts(
        "Nutze die Container-Tools und finde die Host-IP.",
        plan,
    )
    assert out["needs_memory"] is False
    assert out["is_fact_query"] is False
    assert out.get("_policy_conflict_resolved") is True
    assert "query_budget_memory_force" in str(out.get("_policy_conflict_reason", ""))


def test_resolve_precontrol_policy_conflicts_disables_sequential_for_container_runtime_fast_path():
    orch = _make_orchestrator()
    plan = {
        "needs_sequential_thinking": True,
        "sequential_thinking_required": True,
        "sequential_complexity": 4,
        "_domain_route": {
            "domain_tag": "CONTAINER",
            "domain_locked": True,
            "operation": "unknown",
        },
        "suggested_tools": ["exec_in_container"],
    }
    out = orch._resolve_precontrol_policy_conflicts(
        "Finde die IP-Adresse vom Host-Server und nutze alle Tools.",
        plan,
    )
    assert out["needs_sequential_thinking"] is False
    assert out["sequential_thinking_required"] is False
    assert out.get("_sequential_deferred") is True
    assert out.get("_sequential_deferred_reason") == "container_runtime_fast_path"
    assert out.get("_policy_conflict_resolved") is True
    assert "container_runtime_fast_path_over_sequential_thinking" in str(out.get("_policy_conflict_reason", ""))


def test_resolve_precontrol_policy_conflicts_drops_request_container_when_exec_present_for_host_lookup():
    orch = _make_orchestrator()
    plan = {
        "_domain_route": {
            "domain_tag": "CONTAINER",
            "domain_locked": True,
            "operation": "unknown",
        },
        "suggested_tools": ["request_container", "exec_in_container"],
    }
    out = orch._resolve_precontrol_policy_conflicts(
        "Kannst du die Host IP herausfinden und alle Tools nutzen?",
        plan,
    )
    assert out.get("suggested_tools") == ["exec_in_container"]
    assert out.get("_policy_conflict_resolved") is True
    assert "existing_container_over_request_container" in str(out.get("_policy_conflict_reason", ""))


def test_resolve_precontrol_policy_conflicts_keeps_sequential_for_recall_signal():
    orch = _make_orchestrator()
    plan = {
        "needs_sequential_thinking": True,
        "sequential_thinking_required": False,
        "_domain_route": {
            "domain_tag": "CONTAINER",
            "domain_locked": True,
            "operation": "status",
        },
    }
    out = orch._resolve_precontrol_policy_conflicts(
        "Was hast du dir über meine Container Präferenz gemerkt?",
        plan,
    )
    assert out["needs_sequential_thinking"] is True
    assert out.get("_sequential_deferred") is not True


def test_coerce_thinking_plan_schema_normalizes_string_bools_and_list_fields():
    orch = _make_orchestrator()
    raw = {
        "needs_memory": "true",
        "is_fact_query": "false",
        "needs_chat_history": "1",
        "memory_keys": "",
        "suggested_tools": "exec_in_container",
        "dialogue_act": "REQUEST",
        "response_tone": "unknown-tone",
        "response_length_hint": "verbose",
    }
    out = orch._coerce_thinking_plan_schema(raw, user_text="Nutze bitte Tools.")
    assert out["needs_memory"] is False
    assert out["is_fact_query"] is False
    assert out["needs_chat_history"] is True
    assert out["memory_keys"] == []
    assert out["suggested_tools"] == ["exec_in_container"]
    assert out["dialogue_act"] == "request"
    assert out["response_tone"] == "neutral"
    assert out["response_length_hint"] == "medium"
    assert isinstance(out.get("_schema_coercion"), list)
