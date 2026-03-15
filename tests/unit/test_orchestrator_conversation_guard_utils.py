from core.orchestrator_conversation_guard_utils import should_suppress_conversational_tools


def test_conversation_guard_respects_followup_reuse_bypass():
    out = should_suppress_conversational_tools(
        "danke",
        {"dialogue_act": "smalltalk", "_followup_tool_reuse_active": True},
        tool_execution_policy={},
        contains_explicit_tool_intent_fn=lambda text: False,
    )
    assert out is False


def test_conversation_guard_suppresses_smalltalk_without_explicit_tool_intent():
    out = should_suppress_conversational_tools(
        "danke",
        {"dialogue_act": "smalltalk"},
        tool_execution_policy={"conversational_guard": {"suppress_dialogue_acts": ["smalltalk"]}},
        contains_explicit_tool_intent_fn=lambda text: False,
    )
    assert out is True


def test_conversation_guard_question_suffix_bypass():
    out = should_suppress_conversational_tools(
        "danke?",
        {"dialogue_act": "smalltalk"},
        tool_execution_policy={
            "conversational_guard": {
                "suppress_dialogue_acts": ["smalltalk"],
                "allow_question_suffix_bypass": True,
            }
        },
        contains_explicit_tool_intent_fn=lambda text: False,
    )
    assert out is False


def test_conversation_guard_explicit_tool_intent_never_suppresses():
    out = should_suppress_conversational_tools(
        "nutze tool",
        {"dialogue_act": "smalltalk"},
        tool_execution_policy={"conversational_guard": {"suppress_dialogue_acts": ["smalltalk"]}},
        contains_explicit_tool_intent_fn=lambda text: True,
    )
    assert out is False
