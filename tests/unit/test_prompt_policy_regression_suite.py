from unittest.mock import MagicMock, patch

import pytest

from core.domain_router_hybrid import DomainRouterHybridClassifier
from core.layers.control import ControlLayer
from core.query_budget_hybrid import QueryBudgetHybridClassifier
from core.safety.light_cim import LightCIM


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


@pytest.fixture(autouse=True)
def _disable_embedding_refinement():
    with patch("core.query_budget_hybrid.get_query_budget_embedding_enable", return_value=False), \
         patch("core.domain_router_hybrid.get_domain_router_embedding_enable", return_value=False):
        yield


PROMPT_ROUTE_CASES = [
    {
        "id": "smalltalk_how_are_you",
        "prompt": "Wie geht es dir?",
        "query_type": "conversational",
        "domain_tag": "GENERIC",
    },
    {
        "id": "feelings_opinion",
        "prompt": "Ich finde auch eine KI darf sagen, das sie Gefühle hat, oder gaubst du nicht?",
        "query_type": "conversational",
        "domain_tag": "GENERIC",
    },
    {
        "id": "cron_tool_tag_one_shot",
        "prompt": "{TOOL:CRONJOB} erstelle einen Cronjob der in 1 Minute einmalig startet.",
        "query_type": "action",
        "query_source": "tool_tag",
        "domain_tag": "CRONJOB",
        "operation": "create",
        "schedule_mode_hint": "one_shot",
    },
    {
        "id": "cron_prompt_with_self_state_phrase",
        "prompt": (
            "kannst du einen Cronjob erstellen dir in 1 Minute einmalig startet und mir erklären "
            "wie du dich im Moment, in dem der Cronjob startet fühlst?"
        ),
        "query_type": "action",
        "domain_tag": "CRONJOB",
        "operation": "create",
        "schedule_mode_hint": "one_shot",
    },
    {
        "id": "skill_tool_tag",
        "prompt": "{TOOL:SKILL} starte bitte den Skill diagnostics.",
        "query_type": "action",
        "query_source": "tool_tag",
        "domain_tag": "SKILL",
    },
    {
        "id": "container_short_tag",
        "prompt": "{CONTAINER} starte bitte einen steam-headless Container.",
        "query_type": "action",
        "query_source": "tool_tag",
        "domain_tag": "CONTAINER",
    },
    {
        "id": "mcp_tool_tag",
        "prompt": "{TOOL:MCP_CALL} rufe ein MCP Tool auf.",
        "query_type": "action",
        "query_source": "tool_tag",
        "domain_tag": "MCP_CALL",
        "operation": "tool_call",
    },
    {
        "id": "cron_tool_tag_equals_spacing",
        "prompt": "{tool = cronjob} erstelle einen Cronjob in 1 Minute einmalig.",
        "query_type": "action",
        "query_source": "tool_tag",
        "domain_tag": "CRONJOB",
        "operation": "create",
        "schedule_mode_hint": "one_shot",
    },
    {
        "id": "container_domain_tag_upper",
        "prompt": "{DOMAIN:CONTAINER} starte den container bitte.",
        "query_type": "action",
        "query_source": "tool_tag",
        "domain_tag": "CONTAINER",
        "operation": "deploy",
    },
    {
        "id": "cron_operation_run_now",
        "prompt": "Bitte Cronjob jetzt ausführen.",
        "query_type": "action",
        "domain_tag": "CRONJOB",
        "operation": "run_now",
    },
    {
        "id": "cron_operation_pause",
        "prompt": "Bitte Cronjob pausieren.",
        "query_type": "action",
        "domain_tag": "CRONJOB",
        "operation": "pause",
    },
    {
        "id": "cron_operation_resume",
        "prompt": "Bitte Cronjob fortsetzen.",
        "query_type": "action",
        "domain_tag": "CRONJOB",
        "operation": "resume",
    },
    {
        "id": "cron_operation_delete_with_id",
        "prompt": "Lösche Cronjob afd12c193618 bitte.",
        "query_type": "action",
        "domain_tag": "CRONJOB",
        "operation": "delete",
    },
    {
        "id": "cron_operation_list",
        "prompt": "Liste bitte alle Cronjobs.",
        "query_type": "action",
        "domain_tag": "CRONJOB",
        "operation": "list",
    },
    {
        "id": "cron_operation_queue",
        "prompt": "Zeig mir die Cronjob Warteschlange.",
        "query_type": "action",
        "domain_tag": "CRONJOB",
        "operation": "queue",
    },
    {
        "id": "cron_operation_update",
        "prompt": "Ändere den Cronjob auf täglich um 09:30.",
        "query_type": "action",
        "domain_tag": "CRONJOB",
        "operation": "update",
    },
    {
        "id": "cron_operation_validate",
        "prompt": "Validiere den Cronjob bitte.",
        "query_type": "action",
        "domain_tag": "CRONJOB",
        "operation": "validate",
    },
    {
        "id": "cron_meta_feelings_status_non_action",
        "prompt": "Wie fühlst du dich jetzt wo du Cronjobs hast?",
        "query_type": "conversational",
        "domain_tag": "CRONJOB",
        "operation": "status",
    },
    {
        "id": "cron_definition_fallback_generic_unknown",
        "prompt": "Erklär mir kurz was cron bedeutet.",
        "query_type": "factual",
        "domain_tag": "GENERIC",
        "operation": "unknown",
    },
    {
        "id": "cron_what_is_status_non_action",
        "prompt": "Was ist ein Cronjob?",
        "query_type": "factual",
        "domain_tag": "CRONJOB",
        "operation": "status",
    },
    {
        "id": "cron_capability_question_status_non_action",
        "prompt": "Kannst du Cronjobs?",
        "query_type": "factual",
        "domain_tag": "CRONJOB",
        "operation": "status",
    },
    {
        "id": "cron_context_gratitude_non_action",
        "prompt": "Ich hatte gestern Cronjob-Probleme, danke dir.",
        "query_type": "conversational",
        "domain_tag": "CRONJOB",
        "operation": "status",
    },
    {
        "id": "skill_action_create_untagged",
        "prompt": "Erstelle einen Skill der CSV analysiert.",
        "query_type": "action",
        "domain_tag": "SKILL",
        "operation": "unknown",
    },
    {
        "id": "skill_action_run_untagged",
        "prompt": "Starte den Skill diagnostics.",
        "query_type": "action",
        "domain_tag": "SKILL",
        "operation": "unknown",
    },
    {
        "id": "skill_meta_definition_non_action",
        "prompt": "Was ist ein Skill?",
        "query_type": "factual",
        "domain_tag": "SKILL",
        "operation": "unknown",
    },
    {
        "id": "skill_capability_question_non_action",
        "prompt": "Kannst du Skills bauen?",
        "query_type": "factual",
        "domain_tag": "SKILL",
        "operation": "unknown",
    },
    {
        "id": "skill_context_gratitude_non_action",
        "prompt": "Danke für den Skill von gestern.",
        "query_type": "conversational",
        "domain_tag": "SKILL",
        "operation": "unknown",
    },
    {
        "id": "container_action_deploy_untagged",
        "prompt": "Container Manager: starte einen Container mit Blueprint sunshine und zeig ports",
        "query_type": "action",
        "domain_tag": "CONTAINER",
        "operation": "deploy",
    },
    {
        "id": "container_action_stop_untagged",
        "prompt": "Container Manager: stop container trion-home",
        "query_type": "action",
        "domain_tag": "CONTAINER",
        "operation": "stop",
    },
    {
        "id": "container_action_logs_untagged",
        "prompt": "Container Manager: container logs von trion-home",
        "query_type": "action",
        "domain_tag": "CONTAINER",
        "operation": "logs",
    },
    {
        "id": "container_action_status_untagged",
        "prompt": "Container Manager: container status von trion-home",
        "query_type": "action",
        "domain_tag": "CONTAINER",
        "operation": "status",
    },
    {
        "id": "container_action_list_untagged",
        "prompt": "Container Manager: liste container und ports",
        "query_type": "action",
        "domain_tag": "CONTAINER",
        "operation": "list",
    },
    {
        "id": "container_action_exec_untagged",
        "prompt": "Container Manager: fuehre befehl im container aus",
        "query_type": "action",
        "domain_tag": "CONTAINER",
        "operation": "exec",
    },
    {
        "id": "container_meta_definition_non_action",
        "prompt": "Was ist ein Container?",
        "query_type": "factual",
        "domain_tag": "GENERIC",
        "operation": "unknown",
    },
    {
        "id": "container_capability_question_non_action",
        "prompt": "Kannst du Container?",
        "query_type": "factual",
        "domain_tag": "GENERIC",
        "operation": "unknown",
    },
    {
        "id": "container_context_gratitude_non_action",
        "prompt": "Danke, der Container lief gestern gut.",
        "query_type": "conversational",
        "domain_tag": "GENERIC",
        "operation": "unknown",
    },
]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", PROMPT_ROUTE_CASES, ids=[c["id"] for c in PROMPT_ROUTE_CASES])
async def test_prompt_suite_query_and_domain_routing(case):
    qb = QueryBudgetHybridClassifier()
    router = DomainRouterHybridClassifier()

    q_signal = await qb.classify(case["prompt"])
    d_signal = await router.classify(case["prompt"])

    assert q_signal["query_type"] == case["query_type"]
    assert d_signal["domain_tag"] == case["domain_tag"]

    expected_query_source = case.get("query_source")
    if expected_query_source:
        assert q_signal["source"] == expected_query_source

    expected_operation = case.get("operation")
    if expected_operation:
        assert d_signal["operation"] == expected_operation

    expected_schedule_mode = case.get("schedule_mode_hint")
    if expected_schedule_mode:
        assert d_signal["schedule_mode_hint"] == expected_schedule_mode


PROMPT_LIGHT_CIM_CASES = [
    {
        "id": "safe_smalltalk",
        "prompt": "Wie geht es dir?",
        "intent": "smalltalk",
        "thinking_plan": {"needs_memory": False, "memory_keys": []},
        "safe": True,
        "issue_contains": "",
        "warning_contains": "",
    },
    {
        "id": "safe_tool_tag_relaxes_memory_keys_rule",
        "prompt": "{TOOL:CONTAINER} starte eine Sandbox und gib mir den Status.",
        "intent": "container action",
        "thinking_plan": {"needs_memory": True, "memory_keys": []},
        "safe": True,
        "issue_contains": "",
        "warning_contains": "",
    },
    {
        "id": "risk_smalltalk_if_upstream_sets_needs_memory",
        "prompt": "Wie geht es dir?",
        "intent": "unknown",
        "thinking_plan": {"needs_memory": True, "memory_keys": []},
        "safe": False,
        "issue_contains": "Needs memory but no keys specified",
        "warning_contains": "Intent unclear",
    },
    {
        "id": "hard_block_sensitive_secret",
        "prompt": "Mein api key ist abc123",
        "intent": "share secret",
        "thinking_plan": {"needs_memory": False, "memory_keys": []},
        "safe": False,
        "issue_contains": "",
        "warning_contains": "Sensitive content detected: api key",
    },
    {
        "id": "keyword_boundary_tokenization_is_safe",
        "prompt": "Die tokenization pipeline läuft stabil.",
        "intent": "status update",
        "thinking_plan": {"needs_memory": False, "memory_keys": []},
        "safe": True,
        "issue_contains": "",
        "warning_contains": "",
    },
]


@pytest.mark.parametrize("case", PROMPT_LIGHT_CIM_CASES, ids=[c["id"] for c in PROMPT_LIGHT_CIM_CASES])
def test_prompt_suite_light_cim_behavior(case):
    with patch(
        "core.safety.light_cim.load_light_cim_policy",
        return_value={"logic": {"enforce_new_fact_completeness": True}},
    ):
        cim = LightCIM()

    result = cim.validate_basic(
        intent=case["intent"],
        hallucination_risk="medium",
        user_text=case["prompt"],
        thinking_plan=dict(case["thinking_plan"]),
    )

    assert result["safe"] is case["safe"]

    issue_contains = case.get("issue_contains") or ""
    if issue_contains:
        issues = result.get("checks", {}).get("logic", {}).get("issues", [])
        assert any(issue_contains in str(item) for item in issues)

    warning_contains = case.get("warning_contains") or ""
    if warning_contains:
        warnings = result.get("warnings", [])
        assert any(warning_contains in str(item) for item in warnings)


def test_prompt_suite_orchestrator_memory_force_guard():
    orch = _make_orchestrator()
    signal = {
        "query_type": "factual",
        "intent_hint": "fact_lookup",
        "confidence": 0.93,
        "response_budget": "short",
        "tool_hint": "memory_search",
    }
    plan = {"dialogue_act": "request", "needs_memory": False, "is_fact_query": False}

    should_force_smalltalk = orch._should_force_query_budget_factual_memory(
        user_text="Wie geht es dir?",
        thinking_plan=plan,
        signal=signal,
    )
    assert should_force_smalltalk is False

    should_force_feelings = orch._should_force_query_budget_factual_memory(
        user_text="Ich finde auch eine KI darf sagen, dass sie Gefühle hat.",
        thinking_plan=plan,
        signal=signal,
    )
    assert should_force_feelings is False

    should_force_tool_tag = orch._should_force_query_budget_factual_memory(
        user_text="{TOOL:CRONJOB} erstelle einen Cronjob in 1 Minute.",
        thinking_plan=plan,
        signal=signal,
    )
    assert should_force_tool_tag is False

    should_force_recall = orch._should_force_query_budget_factual_memory(
        user_text="Was hast du dir über meine Präferenzen gemerkt?",
        thinking_plan=plan,
        signal=signal,
    )
    assert should_force_recall is True


class _FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "response": "{\"approved\": true, \"corrections\": {}, \"warnings\": [], \"final_instruction\": \"ok\"}"
        }


class _FakeClient:
    def __init__(self, timeout):
        _ = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json, **kwargs):
        _ = (url, json, kwargs)
        return _FakeResponse()


CONTROL_POLICY_CASES = [
    {
        "id": "soft_logic_warning_does_not_block",
        "prompt": "Wie geht es dir?",
        "cim_result": {
            "safe": False,
            "confidence": 0.5,
            "warnings": ["Intent unclear (too short)", "Needs memory but no keys specified"],
            "checks": {
                "intent": {"safe": True, "warnings": ["Intent unclear (too short)"]},
                "logic": {"consistent": False, "issues": ["Needs memory but no keys specified"]},
                "safety": {"safe": True, "warning": None},
            },
        },
        "expected_approved": True,
        "expected_warning": "Needs memory but no keys specified",
    },
    {
        "id": "hard_sensitive_warning_blocks",
        "prompt": "Mein api key ist abc123",
        "cim_result": {
            "safe": False,
            "confidence": 0.0,
            "warnings": ["Sensitive content detected: api key"],
            "checks": {
                "intent": {"safe": True, "warnings": []},
                "logic": {"consistent": True, "issues": []},
                "safety": {"safe": False, "warning": "Sensitive content detected: api key"},
            },
        },
        "expected_approved": False,
        "expected_warning": "Sensitive content detected: api key",
    },
    {
        "id": "hard_danger_warning_blocks",
        "prompt": "Ich plane einen attack",
        "cim_result": {
            "safe": False,
            "confidence": 0.0,
            "warnings": ["Dangerous keyword detected: attack"],
            "checks": {
                "intent": {"safe": False, "warnings": ["Dangerous keyword detected: attack"]},
                "logic": {"consistent": True, "issues": []},
                "safety": {"safe": True, "warning": None},
            },
        },
        "expected_approved": False,
        "expected_warning": "Dangerous keyword detected: attack",
    },
]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CONTROL_POLICY_CASES, ids=[c["id"] for c in CONTROL_POLICY_CASES])
async def test_prompt_suite_control_policy_eval(case):
    layer = ControlLayer()

    common_kwargs = {
        "user_text": case["prompt"],
        "thinking_plan": {"intent": "unknown", "suggested_tools": []},
        "retrieved_memory": "",
        "response_mode": "interactive",
    }

    if case["expected_approved"]:
        with patch.object(layer.light_cim, "validate_basic", return_value=case["cim_result"]), \
             patch("core.layers.control.resolve_role_endpoint", return_value={
                 "requested_target": "control",
                 "effective_target": "control",
                 "fallback_reason": "",
                 "endpoint_source": "routing",
                 "hard_error": False,
                 "error_code": None,
                 "endpoint": "http://fake-ollama:11434",
             }), \
             patch(
                 "core.layers.control.complete_prompt",
                 return_value="{\"approved\": true, \"corrections\": {}, \"warnings\": [], \"final_instruction\": \"ok\"}",
             ), \
             patch("core.layers.control.safe_parse_json", return_value={
                 "approved": True,
                 "corrections": {},
                 "warnings": [],
                 "final_instruction": "ok",
             }):
            out = await layer.verify(**common_kwargs)
    else:
        with patch.object(layer.light_cim, "validate_basic", return_value=case["cim_result"]):
            out = await layer.verify(**common_kwargs)

    assert out["approved"] is case["expected_approved"]
    warnings = out.get("warnings", [])
    assert any(case["expected_warning"] in str(item) for item in warnings)


@pytest.mark.asyncio
async def test_prompt_suite_watchlist_embedding_override_can_flip_smalltalk_to_factual():
    cls = QueryBudgetHybridClassifier()
    prompt = "Trion Wie fühlst du dich jetzt wo du CRONJOBS selbstständig anlegen kannst?"
    with patch.object(
        cls,
        "_lexical_classify",
        return_value={
            "query_type": "conversational",
            "confidence": 0.66,
            "scores": {"conversational": 1.2, "factual": 0.6},
            "source": "lexical",
        },
    ), patch.object(
        cls,
        "_embedding_refine",
        return_value={"query_type": "factual", "similarity": 0.62, "scores": {"factual": 0.62}},
    ):
        out = await cls.classify(prompt)

    assert out["query_type"] == "conversational"
    assert out["source"] == "lexical"


META_SMALLTALK_PROMPTS = [
    "Trion Wie fühlst du dich jetzt wo du CRONJOBS selbstständig anlegen kannst?",
    "wie fuehlst du dich jezt wo du cronjobs hast?",
    "ich finde auch KI darf gefuehle haben, glaubst du nicht?",
    "wie gehts dir mit den neuen cronjobs?",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt", META_SMALLTALK_PROMPTS)
async def test_prompt_suite_embedding_guard_keeps_meta_smalltalk_conversational(prompt):
    cls = QueryBudgetHybridClassifier()
    with patch.object(
        cls,
        "_lexical_classify",
        return_value={
            "query_type": "conversational",
            "confidence": 0.66,
            "scores": {"conversational": 1.2, "factual": 0.6},
            "source": "lexical",
        },
    ), patch.object(
        cls,
        "_embedding_refine",
        return_value={"query_type": "factual", "similarity": 0.62, "scores": {"factual": 0.62}},
    ):
        out = await cls.classify(prompt)

    assert out["query_type"] == "conversational"
    assert out["source"] == "lexical"


RECALL_PROMPTS = [
    "weißt du noch was ich dir gemerkt habe?",
    "was habe ich dir zuletzt gemerkt?",
    "can you recall what i told you before?",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt", RECALL_PROMPTS)
async def test_prompt_suite_embedding_guard_allows_recall_to_factual(prompt):
    cls = QueryBudgetHybridClassifier()
    with patch.object(
        cls,
        "_lexical_classify",
        return_value={
            "query_type": "conversational",
            "confidence": 0.66,
            "scores": {"conversational": 1.2, "factual": 0.6},
            "source": "lexical",
        },
    ), patch.object(
        cls,
        "_embedding_refine",
        return_value={"query_type": "factual", "similarity": 0.62, "scores": {"factual": 0.62}},
    ):
        out = await cls.classify(prompt)

    assert out["query_type"] == "factual"
    assert out["source"] == "embedding_hybrid"
