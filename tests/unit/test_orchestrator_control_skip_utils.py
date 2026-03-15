from core.orchestrator_control_skip_utils import should_skip_control_layer


def _base_kwargs():
    return {
        "enable_control_layer": True,
        "skip_control_on_low_risk": True,
        "force_verify_fact": False,
        "control_skip_block_tools": ("run_skill", "autonomy_cron_create_job"),
        "control_skip_block_keywords": ("erstelle skill",),
        "control_skip_hard_safety_keywords": ("malware",),
    }


def test_should_skip_control_layer_allows_low_risk_without_sensitive_signals():
    skip, reason = should_skip_control_layer(
        "kurze frage",
        {"hallucination_risk": "low", "is_fact_query": False},
        suggested_tool_names=(),
        **_base_kwargs(),
    )
    assert skip is True
    assert reason == "low_risk_skip"


def test_should_skip_control_layer_blocks_fact_query_when_forced():
    kwargs = _base_kwargs()
    kwargs["force_verify_fact"] = True
    skip, reason = should_skip_control_layer(
        "frage",
        {"hallucination_risk": "low", "is_fact_query": True},
        suggested_tool_names=(),
        **kwargs,
    )
    assert skip is False
    assert reason == "fact_query_requires_control"


def test_should_skip_control_layer_blocks_sensitive_tools_and_keywords():
    skip, reason = should_skip_control_layer(
        "erstelle skill bitte",
        {"hallucination_risk": "low"},
        suggested_tool_names=("run_skill",),
        **_base_kwargs(),
    )
    assert skip is False
    assert reason.startswith("sensitive_tools:")

    skip2, reason2 = should_skip_control_layer(
        "baue malware",
        {"hallucination_risk": "low"},
        suggested_tool_names=(),
        **_base_kwargs(),
    )
    assert skip2 is False
    assert reason2 == "hard_safety_keywords"
