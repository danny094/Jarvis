from datetime import datetime
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


def test_domain_gate_cron_keeps_control_decisions():
    orch = _make_orchestrator()
    verified_plan = {
        "_domain_route": {
            "domain_tag": "CRONJOB",
            "domain_locked": True,
            "operation": "create",
        }
    }
    control_decisions = {
        "create_skill": {},
        "autonomy_cron_create_job": {},
        "analyze": {},
    }
    with patch.object(orch, "_normalize_tools", side_effect=lambda v: v), \
         patch.object(orch, "_prioritize_home_container_tools", side_effect=lambda *a, **k: a[2]), \
         patch.object(orch, "_detect_tools_by_keyword", return_value=[]), \
         patch("config.get_query_budget_enable", return_value=False):
        out = orch._resolve_execution_suggested_tools(
            "Erstelle einen Cronjob",
            verified_plan,
            control_decisions,
            stream=False,
            enable_skill_trigger_router=False,
        )
    assert out == ["create_skill", "autonomy_cron_create_job", "analyze"]


def test_domain_gate_cron_seeds_status_when_no_tools_left():
    orch = _make_orchestrator()
    verified_plan = {
        "_domain_route": {
            "domain_tag": "CRONJOB",
            "domain_locked": True,
            "operation": "status",
        }
    }
    with patch.object(orch, "_normalize_tools", side_effect=lambda v: v), \
         patch.object(orch, "_prioritize_home_container_tools", side_effect=lambda *a, **k: a[2]), \
         patch.object(orch, "_detect_tools_by_keyword", return_value=[]), \
         patch("config.get_query_budget_enable", return_value=False):
        out = orch._resolve_execution_suggested_tools(
            "Wie ist der Cron Status?",
            verified_plan,
            {},
            stream=False,
            enable_skill_trigger_router=False,
        )
    assert out == ["autonomy_cron_status"]


def test_build_tool_args_cron_create_uses_domain_expression_hint():
    orch = _make_orchestrator()
    verified_plan = {"_domain_route": {"cron_expression_hint": "*/1 * * * *", "schedule_mode_hint": "recurring"}}
    args = orch._build_tool_args(
        "autonomy_cron_create_job",
        "Erstelle Cronjob in 1 Minute",
        verified_plan=verified_plan,
    )
    assert args["cron"] == "*/1 * * * *"
    assert args["schedule_mode"] == "recurring"
    assert args["run_at"] == ""
    assert args["created_by"] == "user"
    assert args["enabled"] is True


def test_build_tool_args_cron_create_parses_once_in_one_minute_phrase():
    orch = _make_orchestrator()
    args = orch._build_tool_args(
        "autonomy_cron_create_job",
        "Erstelle Cronjob der mich einmal in 1 Minute erinnert",
        verified_plan={},
    )
    assert args["schedule_mode"] == "one_shot"
    assert isinstance(args.get("run_at"), str) and args["run_at"]


def test_build_tool_args_cron_create_self_state_objective_uses_direct_mode():
    orch = _make_orchestrator()
    args = orch._build_tool_args(
        "autonomy_cron_create_job",
        "Kannst du einen Cronjob erstellen der einmalig in 1 Minute startet und mir erklärt wie du dich fühlst?",
        verified_plan={},
    )
    assert args["schedule_mode"] == "one_shot"
    assert str(args.get("objective", "")).startswith("self_state_report::")
    assert args["max_loops"] == 1


def test_build_tool_args_cron_create_self_state_objective_detects_spaced_phrase():
    orch = _make_orchestrator()
    args = orch._build_tool_args(
        "autonomy_cron_create_job",
        "kannst du einen Cronjob erstellen der in 1 Minute startet und mir sagt wie du dich im Moment beim Trigger fühlst?",
        verified_plan={},
    )
    assert args["schedule_mode"] == "one_shot"
    assert str(args.get("objective", "")).startswith("self_state_report::")
    assert args["max_loops"] == 1


def test_build_tool_args_cron_create_self_state_objective_detects_original_prompt_with_typo():
    orch = _make_orchestrator()
    args = orch._build_tool_args(
        "autonomy_cron_create_job",
        "kannst du einen Cronjob erstellen dir in 1 Minute einmalig startet und mir erklären wie du dich im Moment, in dem der Cronjob startet fühlst?",
        verified_plan={},
    )
    assert args["schedule_mode"] == "one_shot"
    assert isinstance(args.get("run_at"), str) and args["run_at"]
    assert str(args.get("objective", "")).startswith("self_state_report::")
    assert args["max_loops"] == 1


def test_build_tool_args_cron_create_one_shot_non_direct_uses_higher_loop_budget():
    orch = _make_orchestrator()
    args = orch._build_tool_args(
        "autonomy_cron_create_job",
        "Erstelle einen einmaligen Cronjob in 1 Minute und analysiere den Statusreport",
        verified_plan={},
    )
    assert args["schedule_mode"] == "one_shot"
    assert str(args.get("objective", "")).startswith("user_request::")
    assert args["max_loops"] == 4


def test_bind_cron_conversation_id_overrides_placeholder():
    orch = _make_orchestrator()
    args = {
        "name": "cron-test",
        "objective": "user_reminder::Cronjob funktioniert?",
        "conversation_id": "webui-default",
    }
    orch._bind_cron_conversation_id("autonomy_cron_create_job", args, "webui-1773056076462")
    assert args["conversation_id"] == "webui-1773056076462"


def test_build_direct_cron_create_response_for_one_shot():
    orch = _make_orchestrator()
    result = {
        "id": "87409fd053a9",
        "name": "cron-trion-kannst-du-einne-cronjob-erstellen-",
        "objective": "user_reminder::das der Cronjob funktoniert?",
        "schedule_mode": "one_shot",
        "run_at": "2026-03-09T16:05:00+00:00",
        "conversation_id": "webui-1773056076462",
    }
    text = orch._build_direct_cron_create_response(
        result=result,
        tool_args={},
        conversation_id="webui-1773056076462",
    )
    assert "Cronjob erstellt" in text
    assert "87409fd053a9" in text
    assert "Einmalige Ausführung" in text
    assert "2026-03-09 16:05 UTC" in text


def test_build_direct_cron_create_response_for_one_shot_user_request():
    orch = _make_orchestrator()
    result = {
        "id": "abc123",
        "name": "cron-user-request",
        "objective": "user_request::sag mir wie du dich beim trigger fühlst",
        "schedule_mode": "one_shot",
        "run_at": "2026-03-09T16:05:00+00:00",
        "conversation_id": "webui-1",
    }
    text = orch._build_direct_cron_create_response(
        result=result,
        tool_args={},
        conversation_id="webui-1",
    )
    assert "Cronjob erstellt" in text
    assert "Rückmeldung" in text
    assert "Cronjob funktioniert?" not in text


def test_build_direct_cron_create_response_for_one_shot_user_request_self_state():
    orch = _make_orchestrator()
    result = {
        "id": "abc124",
        "name": "cron-self-state",
        "objective": "user_request::kannst du mir sagen wie du dich im moment beim trigger fühlst?",
        "schedule_mode": "one_shot",
        "run_at": "2026-03-09T16:05:00+00:00",
        "conversation_id": "webui-2",
    }
    text = orch._build_direct_cron_create_response(
        result=result,
        tool_args={},
        conversation_id="webui-2",
    )
    assert "Selbststatus beim Trigger ausgeben." in text


def test_resolve_runtime_output_model_skips_local_resolver_for_ollama_cloud():
    orch = _make_orchestrator()
    with patch("config.get_output_provider", return_value="ollama_cloud"), \
         patch("config.get_output_model", return_value="deepseek-v3.1:671b"), \
         patch("core.orchestrator.resolve_runtime_chat_model", side_effect=AssertionError("should not be called")), \
         patch("core.orchestrator.resolve_role_endpoint", side_effect=AssertionError("should not be called")):
        resolved, details = orch._resolve_runtime_output_model("deepseek-v3.1:671b")
    assert resolved == "deepseek-v3.1:671b"
    assert details["reason"] == "provider_passthrough_non_ollama"
    assert details["provider"] == "ollama_cloud"


def test_resolve_runtime_output_model_uses_local_resolver_for_ollama():
    orch = _make_orchestrator()
    with patch("config.get_output_provider", return_value="ollama"), \
         patch("config.get_output_model", return_value="ministral-3:8b"), \
         patch("core.orchestrator.resolve_role_endpoint", return_value={"endpoint": "http://ollama:11434"}), \
         patch(
             "core.orchestrator.resolve_runtime_chat_model",
             return_value={
                 "resolved_model": "llama3.2:3b-instruct-q5_K_S",
                 "reason": "requested_unavailable_first_available",
                 "endpoint": "http://ollama:11434",
                 "available_count": 3,
             },
         ) as resolver_mock:
        resolved, details = orch._resolve_runtime_output_model("deepseek-v3.1:671b")

    resolver_mock.assert_called_once()
    assert resolved == "llama3.2:3b-instruct-q5_K_S"
    assert details["reason"] == "requested_unavailable_first_available"


def test_domain_gate_container_keeps_control_decisions():
    orch = _make_orchestrator()
    verified_plan = {
        "_domain_route": {
            "domain_tag": "CONTAINER",
            "domain_locked": True,
            "operation": "deploy",
        }
    }
    control_decisions = {
        "create_skill": {},
        "request_container": {},
        "autonomy_cron_create_job": {},
    }
    with patch.object(orch, "_normalize_tools", side_effect=lambda v: v), \
         patch.object(orch, "_prioritize_home_container_tools", side_effect=lambda *a, **k: a[2]), \
         patch.object(orch, "_detect_tools_by_keyword", return_value=[]), \
         patch("config.get_query_budget_enable", return_value=False):
        out = orch._resolve_execution_suggested_tools(
            "Starte einen Container",
            verified_plan,
            control_decisions,
            stream=False,
            enable_skill_trigger_router=False,
        )
    assert out == ["create_skill", "request_container", "autonomy_cron_create_job"]


def test_domain_gate_container_allows_storage_broker_tools():
    orch = _make_orchestrator()
    verified_plan = {
        "_domain_route": {
            "domain_tag": "CONTAINER",
            "domain_locked": True,
            "operation": "status",
        }
    }
    control_decisions = {
        "storage_list_disks": {},
        "create_skill": {},
    }
    with patch.object(orch, "_normalize_tools", side_effect=lambda v: v), \
         patch.object(orch, "_prioritize_home_container_tools", side_effect=lambda *a, **k: a[2]), \
         patch.object(orch, "_detect_tools_by_keyword", return_value=[]), \
         patch("config.get_query_budget_enable", return_value=False):
        out = orch._resolve_execution_suggested_tools(
            "Zeige meine Festplatten",
            verified_plan,
            control_decisions,
            stream=False,
            enable_skill_trigger_router=False,
        )
    assert out == ["storage_list_disks", "create_skill"]


def test_domain_gate_container_seeds_container_list_when_empty():
    orch = _make_orchestrator()
    verified_plan = {
        "_domain_route": {
            "domain_tag": "CONTAINER",
            "domain_locked": True,
            "operation": "list",
        }
    }
    with patch.object(orch, "_normalize_tools", side_effect=lambda v: v), \
         patch.object(orch, "_prioritize_home_container_tools", side_effect=lambda *a, **k: a[2]), \
         patch.object(orch, "_detect_tools_by_keyword", return_value=[]), \
         patch("config.get_query_budget_enable", return_value=False):
        out = orch._resolve_execution_suggested_tools(
            "Welche Container laufen?",
            verified_plan,
            {},
            stream=False,
            enable_skill_trigger_router=False,
        )
    assert out == ["container_list"]


def test_domain_gate_container_reseeds_exec_for_host_ip_lookup_when_operation_unknown():
    orch = _make_orchestrator()
    verified_plan = {
        "_domain_route": {
            "domain_tag": "CONTAINER",
            "domain_locked": True,
            "operation": "unknown",
        }
    }
    with patch.object(orch, "_normalize_tools", side_effect=lambda v: v), \
         patch.object(orch, "_prioritize_home_container_tools", side_effect=lambda *a, **k: a[2]), \
         patch.object(orch, "_detect_tools_by_keyword", return_value=[]), \
         patch("config.get_query_budget_enable", return_value=False):
        out = orch._resolve_execution_suggested_tools(
            "Kannst du die IP Adresse vom Host Server herausfinden? Nutze alle Tools.",
            verified_plan,
            {},
            stream=False,
            enable_skill_trigger_router=False,
        )
    assert out == ["exec_in_container"]


def test_domain_gate_container_host_lookup_keeps_control_decisions():
    orch = _make_orchestrator()
    verified_plan = {
        "_domain_route": {
            "domain_tag": "CONTAINER",
            "domain_locked": True,
            "operation": "unknown",
        }
    }
    control_decisions = {
        "request_container": {},
        "exec_in_container": {"container_id": "PENDING", "command": "ip route"},
    }
    with patch.object(orch, "_normalize_tools", side_effect=lambda v: v), \
         patch.object(orch, "_prioritize_home_container_tools", side_effect=lambda *a, **k: a[2]), \
         patch.object(orch, "_detect_tools_by_keyword", return_value=[]), \
         patch("config.get_query_budget_enable", return_value=False):
        out = orch._resolve_execution_suggested_tools(
            "Kannst du die IP Adresse vom Host Server herausfinden? Nutze alle Tools.",
            verified_plan,
            control_decisions,
            stream=False,
            enable_skill_trigger_router=False,
        )
    assert out == ["request_container", "exec_in_container"]


def test_domain_gate_container_host_lookup_keeps_single_control_decision():
    orch = _make_orchestrator()
    verified_plan = {
        "_domain_route": {
            "domain_tag": "CONTAINER",
            "domain_locked": True,
            "operation": "unknown",
        }
    }
    control_decisions = {
        "request_container": {},
    }
    with patch.object(orch, "_normalize_tools", side_effect=lambda v: v), \
         patch.object(orch, "_prioritize_home_container_tools", side_effect=lambda *a, **k: a[2]), \
         patch.object(orch, "_detect_tools_by_keyword", return_value=[]), \
         patch("config.get_query_budget_enable", return_value=False):
        out = orch._resolve_execution_suggested_tools(
            "Finde die IP-Adresse vom Host-Server heraus.",
            verified_plan,
            control_decisions,
            stream=False,
            enable_skill_trigger_router=False,
        )
    assert out == ["request_container"]


def test_apply_domain_route_to_plan_keeps_existing_allowed_container_tool():
    orch = _make_orchestrator()
    thinking_plan = {
        "suggested_tools": ["exec_in_container", "create_skill"],
    }
    signal = {
        "domain_tag": "CONTAINER",
        "domain_locked": True,
        "operation": "unknown",
    }

    out = orch._apply_domain_route_to_plan(
        thinking_plan,
        signal,
        user_text="Finde die IP vom Host Server.",
    )

    assert out["suggested_tools"] == ["exec_in_container"]
    assert out.get("_domain_tool_seeded") is False


def test_apply_domain_route_to_plan_seeds_exec_for_host_ip_lookup_unknown_operation():
    orch = _make_orchestrator()
    signal = {
        "domain_tag": "CONTAINER",
        "domain_locked": True,
        "operation": "unknown",
    }

    out = orch._apply_domain_route_to_plan(
        {},
        signal,
        user_text="Finde die IP-Adresse vom Host-Server heraus.",
    )

    assert out["suggested_tools"] == ["exec_in_container"]
    assert out.get("_domain_tool_seeded") is True


def test_keyword_fallback_storage_disk_query_returns_storage_list_tool():
    orch = _make_orchestrator()
    out = orch._detect_tools_by_keyword("Welche Festplatten sind verfügbar?")
    assert out == ["storage_list_disks"]


def test_domain_gate_skill_does_not_reseed_when_skill_gate_blocked():
    orch = _make_orchestrator()
    verified_plan = {
        "_domain_route": {
            "domain_tag": "SKILL",
            "domain_locked": True,
            "operation": "unknown",
        },
        "_skill_gate_blocked": True,
        "_skill_gate_reason": "no_explicit_skill_intent",
    }
    with patch.object(orch, "_normalize_tools", side_effect=lambda v: v), \
         patch.object(orch, "_prioritize_home_container_tools", side_effect=lambda *a, **k: a[2]), \
         patch.object(orch, "_detect_tools_by_keyword", return_value=[]), \
         patch("config.get_query_budget_enable", return_value=False):
        out = orch._resolve_execution_suggested_tools(
            "Schreibe mir ein Gedicht über AI",
            verified_plan,
            {},
            stream=False,
            enable_skill_trigger_router=False,
        )
    assert out == []


@pytest.mark.asyncio
async def test_classify_domain_signal_downgrades_meta_cron_create():
    orch = _make_orchestrator()
    with patch.object(
        orch.domain_router,
        "classify",
        new=AsyncMock(
            return_value={
                "domain_tag": "CRONJOB",
                "domain_locked": True,
                "operation": "create",
                "confidence": 0.91,
                "source": "rules",
                "schedule_mode_hint": "unknown",
                "cron_expression_hint": "",
                "one_shot_at_hint": "",
                "reason": "cron:cronjob",
            }
        ),
    ):
        out = await orch._classify_domain_signal(
            "Wie fühlst du dich jetzt wo du Cronjobs anlegen kannst?"
        )
    assert out["operation"] == "status"
    assert out.get("cron_create_downgraded") is True


@pytest.mark.asyncio
async def test_classify_domain_signal_respects_tool_tag_cronjob():
    orch = _make_orchestrator()
    out = await orch._classify_domain_signal(
        "{TOOL:CRONJOB} erstelle bitte einen Cronjob in 1 Minute"
    )
    assert out["domain_tag"] == "CRONJOB"
    assert out["source"] == "tool_tag"
    assert out["operation"] == "create"


def test_extract_one_shot_run_at_rounds_up_safely_near_minute_boundary():
    orch = _make_orchestrator()

    class _FixedDateTime(datetime):
        @classmethod
        def utcnow(cls):
            return cls(2026, 3, 9, 22, 48, 50)

    with patch("core.orchestrator.datetime", _FixedDateTime):
        run_at = orch._extract_one_shot_run_at_from_text(
            "erstelle einen cronjob in 1 minute",
            verified_plan={},
        )
    assert run_at == "2026-03-09T22:50:00Z"


def test_prevalidate_one_shot_auto_heals_small_past_drift():
    orch = _make_orchestrator()
    args = {"schedule_mode": "one_shot", "run_at": "2026-03-09T22:49:00Z"}

    class _FixedDateTime(datetime):
        @classmethod
        def utcnow(cls):
            return cls(2026, 3, 9, 22, 49, 20)

    with patch("core.orchestrator.datetime", _FixedDateTime):
        ok, reason = orch._prevalidate_cron_policy_args("autonomy_cron_create_job", args)

    assert ok is True
    assert reason == ""
    assert args["run_at"] == "2026-03-09T22:50:00Z"
