import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from core.domain_router_hybrid import DomainRouterHybridClassifier


@pytest.mark.asyncio
async def test_domain_router_rules_classifies_cronjob_create():
    router = DomainRouterHybridClassifier()
    signal = await router.classify("TRION erstelle einen Cronjob der mich jede 1 Minute erinnert")
    assert signal["domain_tag"] == "CRONJOB"
    assert signal["operation"] == "create"
    assert signal["domain_locked"] is True
    assert signal["schedule_mode_hint"] == "recurring"
    assert signal["cron_expression_hint"] in {"*/1 * * * *", "*/1 * * * *".strip()}

    signal2 = await router.classify("Erstelle Cronjob der mich einmal in 1 Minute erinnert")
    assert signal2["schedule_mode_hint"] == "one_shot"
    assert signal2["one_shot_at_hint"]

    signal3 = await router.classify(
        "Bitte erstelle einen Cronjob alle 15 Minuten mit dem Ziel status summary"
    )
    assert signal3["operation"] == "create"


@pytest.mark.asyncio
async def test_domain_router_does_not_treat_meta_cron_smalltalk_as_create():
    router = DomainRouterHybridClassifier()
    signal = await router.classify(
        "TRION wie fühlst du dich jetzt wo du Cronjobs selbstständig anlegen kannst?"
    )
    assert signal["domain_tag"] == "CRONJOB"
    assert signal["operation"] == "status"


@pytest.mark.asyncio
async def test_domain_router_requires_schedule_signal_for_cron_create():
    router = DomainRouterHybridClassifier()
    signal = await router.classify("Erstelle einen Cronjob für mich")
    assert signal["domain_tag"] == "CRONJOB"
    assert signal["operation"] == "status"


@pytest.mark.asyncio
async def test_domain_router_rules_classifies_skill():
    router = DomainRouterHybridClassifier()
    signal = await router.classify("Bitte erstelle einen Skill der CSV-Dateien analysiert")
    assert signal["domain_tag"] == "SKILL"
    assert signal["domain_locked"] is True


@pytest.mark.asyncio
async def test_domain_router_returns_operation_delete_for_cron_id():
    router = DomainRouterHybridClassifier()
    signal = await router.classify("Lösche Cronjob afd12c193618 bitte")
    assert signal["domain_tag"] == "CRONJOB"
    assert signal["operation"] == "delete"
    assert signal["cron_job_id_hint"] == "afd12c193618"


@pytest.mark.asyncio
async def test_domain_router_rules_classifies_container_deploy():
    router = DomainRouterHybridClassifier()
    signal = await router.classify(
        "Bitte starte einen steam-headless Sunshine Container und gib mir Port und IP"
    )
    assert signal["domain_tag"] == "CONTAINER"
    assert signal["domain_locked"] is True
    assert signal["operation"] in {"deploy", "status", "list"}
    assert signal["rule_container_score"] >= 2.0


@pytest.mark.asyncio
async def test_domain_router_one_shot_hint_rounds_up_near_minute_boundary():
    router = DomainRouterHybridClassifier()

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            base = cls(2026, 3, 9, 22, 48, 50)
            if tz is not None:
                return base.replace(tzinfo=tz)
            return base

    with patch("core.domain_router_hybrid.datetime", _FixedDateTime):
        signal = await router.classify("Erstelle Cronjob einmal in 1 Minute")

    assert signal["schedule_mode_hint"] == "one_shot"
    assert signal["one_shot_at_hint"] == "2026-03-09T22:50:00Z"


@pytest.mark.asyncio
async def test_domain_router_respects_explicit_tool_tag_for_container():
    router = DomainRouterHybridClassifier()
    signal = await router.classify("{TOOL:CONTAINER} starte bitte einen Container")
    assert signal["domain_tag"] == "CONTAINER"
    assert signal["domain_locked"] is True
    assert signal["source"] == "tool_tag"
    assert signal["operation"] == "deploy"


@pytest.mark.asyncio
async def test_domain_router_respects_explicit_tool_tag_for_mcp_call():
    router = DomainRouterHybridClassifier()
    signal = await router.classify("{TOOL:MCP_CALL} rufe bitte ein MCP Tool auf")
    assert signal["domain_tag"] == "MCP_CALL"
    assert signal["source"] == "tool_tag"
    assert signal["operation"] == "tool_call"
    assert signal["domain_locked"] is False


@pytest.mark.asyncio
async def test_domain_router_routes_temporal_task_without_explicit_cron_keyword():
    router = DomainRouterHybridClassifier()
    signal = await router.classify("In 5 Minuten soll TRION mir eine Zusammenfassung geben")
    assert signal["domain_tag"] == "CRONJOB"
    assert signal["operation"] == "create"
    assert signal["schedule_mode_hint"] == "one_shot"
    assert bool(signal["one_shot_at_hint"])


def test_domain_router_schedule_hint_ignores_plain_alle_tools_phrase():
    text = (
        "Guten Abend TRION. Kannst du versuchen, die IP addrese vom Host server herraus zu finden? "
        "Nutze gerne alle Tools die du dafür benötigst."
    )
    assert DomainRouterHybridClassifier._has_cron_schedule_signal(text) is False
    mode, one_shot_at = DomainRouterHybridClassifier._infer_schedule_hint(text)
    assert mode == "unknown"
    assert one_shot_at == ""


@pytest.mark.asyncio
async def test_domain_router_host_ip_lookup_routes_to_container_exec():
    router = DomainRouterHybridClassifier()
    signal = await router.classify(
        "Kannst du die IP Adresse vom Host Server herausfinden? Nutze gerne alle Tools."
    )
    assert signal["domain_tag"] == "CONTAINER"
    assert signal["domain_locked"] is True
    assert signal["operation"] == "exec"


@pytest.mark.asyncio
async def test_domain_router_parses_tomorrow_hour_without_minutes():
    router = DomainRouterHybridClassifier()
    signal = await router.classify("Morgen um 14 Uhr: Erstelle einen Report")
    assert signal["domain_tag"] == "CRONJOB"
    assert signal["operation"] == "create"
    assert signal["schedule_mode_hint"] == "one_shot"
    assert bool(signal["one_shot_at_hint"])


@pytest.mark.asyncio
async def test_domain_router_math_query_stays_generic_without_embedding_override():
    router = DomainRouterHybridClassifier()
    with patch("core.domain_router_hybrid.get_domain_router_embedding_enable", return_value=False):
        signal = await router.classify("Rechne mir 2547 * 389 aus")
    assert signal["domain_tag"] == "GENERIC"
    assert signal["domain_locked"] is False


@pytest.mark.asyncio
async def test_domain_router_report_word_does_not_trigger_container_port_marker():
    router = DomainRouterHybridClassifier()
    with patch("core.domain_router_hybrid.get_domain_router_embedding_enable", return_value=False):
        signal = await router.classify("Erstelle einen Report über unsere letzte Diskussion")
    assert signal["domain_tag"] != "CONTAINER"


@pytest.mark.asyncio
async def test_domain_router_definition_guard_stays_generic_even_with_embedding_enabled():
    router = DomainRouterHybridClassifier()
    router._proto_cache = {
        "skill": [1.0, 0.0],
        "cronjob": [0.0, 1.0],
        "container": [0.0, 1.0],
        "generic": [0.0, 1.0],
    }
    with patch("core.domain_router_hybrid.get_domain_router_embedding_enable", return_value=True), \
         patch.object(router, "_ensure_prototypes", AsyncMock(return_value=True)), \
         patch.object(router, "_embed", AsyncMock(return_value=[1.0, 0.0])):
        signal = await router.classify("Erkläre mir was Machine Learning ist")
    assert signal["domain_tag"] == "GENERIC"
    assert signal["source"] == "rules_definition_guard"


@pytest.mark.asyncio
async def test_domain_router_creative_guard_stays_generic_even_with_embedding_enabled():
    router = DomainRouterHybridClassifier()
    router._proto_cache = {
        "skill": [1.0, 0.0],
        "cronjob": [0.0, 1.0],
        "container": [0.0, 1.0],
        "generic": [0.0, 1.0],
    }
    with patch("core.domain_router_hybrid.get_domain_router_embedding_enable", return_value=True), \
         patch.object(router, "_ensure_prototypes", AsyncMock(return_value=True)), \
         patch.object(router, "_embed", AsyncMock(return_value=[1.0, 0.0])):
        signal = await router.classify("Schreibe mir ein Gedicht über AI")
    assert signal["domain_tag"] == "GENERIC"
    assert signal["source"] == "rules_creative_guard"
