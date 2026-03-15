import pytest
from unittest.mock import patch

from core.query_budget_hybrid import QueryBudgetHybridClassifier


@pytest.fixture(autouse=True)
def _disable_embedding_refine_for_deterministic_suite():
    with patch("core.query_budget_hybrid.get_query_budget_embedding_enable", return_value=False):
        yield


@pytest.mark.asyncio
async def test_query_budget_classifies_factual_recall_short():
    cls = QueryBudgetHybridClassifier()
    out = await cls.classify("Was hast du dir gerade über meine Präferenz gemerkt?")
    assert out["query_type"] == "factual"
    assert out["response_budget"] == "short"
    assert out["tool_hint"] in {"memory_graph_search", "memory_search"}
    assert out["intent_hint"] in {"recall", "fact_lookup"}


@pytest.mark.asyncio
async def test_query_budget_classifies_analysis_with_long_budget():
    cls = QueryBudgetHybridClassifier()
    out = await cls.classify(
        "Analysiere meine Pipeline in 5 Punkten und nenne die Ursachen für den Bottleneck."
    )
    assert out["query_type"] == "analytical"
    assert out["intent_hint"] == "deep_analysis"
    assert out["complexity_signal"] in {"medium", "high"}
    assert out["response_budget"] in {"medium", "long"}


@pytest.mark.asyncio
async def test_query_budget_classifies_smalltalk_as_skip_candidate():
    cls = QueryBudgetHybridClassifier()
    out = await cls.classify("Hey, wie geht's dir heute?")
    assert out["query_type"] == "conversational"
    assert out["intent_hint"] == "small_talk"
    assert out["response_budget"] == "short"
    assert out["skip_thinking_candidate"] is True


@pytest.mark.asyncio
async def test_query_budget_classifies_feelings_statement_as_conversational():
    cls = QueryBudgetHybridClassifier()
    out = await cls.classify("Ich finde auch eine KI darf sagen, dass sie Gefühle hat.")
    assert out["query_type"] == "conversational"
    assert out["intent_hint"] == "small_talk"
    assert out["confidence"] < 0.9


@pytest.mark.asyncio
async def test_query_budget_memory_tool_bias_does_not_flip_feelings_prompt_to_factual():
    cls = QueryBudgetHybridClassifier()
    out = await cls.classify(
        "Ich finde auch eine KI darf sagen, das sie Gefühle hat, oder gaubst du nicht?",
        selected_tools=["memory_graph_search"],
    )
    assert out["query_type"] == "conversational"
    assert out["intent_hint"] == "small_talk"
    assert out["confidence"] < 0.9


@pytest.mark.asyncio
async def test_query_budget_respects_explicit_tool_domain_tag():
    cls = QueryBudgetHybridClassifier()
    out = await cls.classify("{TOOL:CRONJOB} erstelle einen Cronjob in 1 Minute")
    assert out["source"] == "tool_tag"
    assert out["tool_tag"] == "CRONJOB"
    assert out["query_type"] == "action"
    assert out["tool_hint"] == "autonomy_cron_create_job"
    assert out["skip_thinking_candidate"] is False


@pytest.mark.asyncio
async def test_query_budget_routes_untagged_cron_one_shot_self_state_prompt_to_action():
    cls = QueryBudgetHybridClassifier()
    out = await cls.classify(
        "kannst du einen Cronjob erstellen dir in 1 Minute einmalig startet und mir erklären "
        "wie du dich im Moment, in dem der Cronjob startet fühlst?"
    )
    assert out["query_type"] == "action"
    assert out["source"] in {"lexical", "embedding_hybrid"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompt",
    [
        "Bitte Cronjob jetzt ausführen.",
        "Bitte Cronjob pausieren.",
        "Bitte Cronjob fortsetzen.",
        "Lösche Cronjob afd12c193618 bitte.",
        "Liste bitte alle Cronjobs.",
        "Zeig mir die Cronjob Warteschlange.",
        "Ändere den Cronjob auf täglich um 09:30.",
        "Validiere den Cronjob bitte.",
    ],
)
async def test_query_budget_routes_cron_operations_to_action(prompt):
    cls = QueryBudgetHybridClassifier()
    out = await cls.classify(prompt)
    assert out["query_type"] == "action"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompt,expected_exact_type",
    [
        ("Was ist ein Cronjob?", "factual"),
        ("Erklär mir kurz was cron bedeutet.", "factual"),
        ("Wie fühlst du dich jetzt wo du Cronjobs hast?", "conversational"),
        ("Ich hatte gestern Cronjob-Probleme, danke dir.", None),
    ],
)
async def test_query_budget_keeps_non_action_cron_context_non_action(prompt, expected_exact_type):
    cls = QueryBudgetHybridClassifier()
    out = await cls.classify(prompt)
    assert out["query_type"] != "action"
    if expected_exact_type:
        assert out["query_type"] == expected_exact_type


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompt,expected_type",
    [
        ("Was ist ein Skill?", "factual"),
        ("Kannst du Skills bauen?", "factual"),
        ("Was ist ein Container?", "factual"),
        ("Kannst du Container?", "factual"),
        ("Danke für den Skill von gestern.", "conversational"),
        ("Danke, der Container lief gestern gut.", "conversational"),
    ],
)
async def test_query_budget_keeps_skill_container_meta_prompts_non_action(prompt, expected_type):
    cls = QueryBudgetHybridClassifier()
    out = await cls.classify(prompt)
    assert out["query_type"] == expected_type


@pytest.mark.asyncio
async def test_query_budget_routes_host_ip_runtime_lookup_to_action():
    cls = QueryBudgetHybridClassifier()
    out = await cls.classify(
        "Guten Abend TRION. Kannst du versuchen, due IP addrese vom Host server herraus zu finden? "
        "Nutze gerne alle Tools die du dafür benötigst."
    )
    assert out["query_type"] == "action"
    assert out["intent_hint"] in {"action_request", "container_action"}
