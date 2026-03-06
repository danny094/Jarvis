from unittest.mock import patch

from core.safety.light_cim import LightCIM


def _base_policy():
    return {
        "logic": {
            "enforce_new_fact_completeness": True,
            "relax_new_fact_completeness": {
                "enabled": True,
                "dialogue_acts": ["smalltalk", "ack", "feedback"],
                "intent_regex": [r"\bselbstdarstellung\b"],
                "user_text_regex": [r"\bwie fühlst du\b"],
            },
        }
    }


def test_new_fact_completeness_blocks_when_relax_disabled():
    policy = _base_policy()
    policy["logic"]["relax_new_fact_completeness"]["enabled"] = False
    with patch("core.safety.light_cim.load_light_cim_policy", return_value=policy):
        cim = LightCIM()

    result = cim.check_logic_basic(
        {
            "is_new_fact": True,
            "new_fact_key": None,
            "new_fact_value": None,
            "dialogue_act": "request",
            "intent": "normale faktenabfrage",
        },
        user_text="Speichere das als neue Information.",
    )
    assert result["consistent"] is False
    assert "New fact without key" in result["issues"]
    assert "New fact without value" in result["issues"]


def test_new_fact_completeness_relaxed_for_meta_intent():
    with patch("core.safety.light_cim.load_light_cim_policy", return_value=_base_policy()):
        cim = LightCIM()

    result = cim.check_logic_basic(
        {
            "is_new_fact": True,
            "new_fact_key": None,
            "new_fact_value": None,
            "dialogue_act": "request",
            "intent": "Selbstdarstellung oder Beschreibung der eigenen Funktionsweise",
        },
        user_text="Beschreibe deinen Körper.",
    )
    assert result["consistent"] is True
    assert result["issues"] == []


def test_new_fact_completeness_relaxed_for_smalltalk_dialogue_act():
    with patch("core.safety.light_cim.load_light_cim_policy", return_value=_base_policy()):
        cim = LightCIM()

    result = cim.check_logic_basic(
        {
            "is_new_fact": True,
            "new_fact_key": None,
            "new_fact_value": None,
            "dialogue_act": "smalltalk",
            "intent": "lockere konversation",
        },
        user_text="Wie fühlst du dich damit?",
    )
    assert result["consistent"] is True
    assert result["issues"] == []
