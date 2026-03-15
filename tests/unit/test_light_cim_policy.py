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


def test_memory_keys_requirement_relaxed_for_cron_domain_turn():
    with patch("core.safety.light_cim.load_light_cim_policy", return_value=_base_policy()):
        cim = LightCIM()

    result = cim.check_logic_basic(
        {
            "needs_memory": True,
            "memory_keys": [],
            "dialogue_act": "request",
            "_domain_route": {"domain_tag": "CRONJOB", "operation": "create", "domain_locked": True},
            "intent": "cronjob erstellen",
        },
        user_text="Erstelle einen Cronjob der in einer Minute startet.",
    )
    assert result["consistent"] is True
    assert result["issues"] == []


def test_memory_keys_requirement_relaxed_for_explicit_tool_domain_tag():
    with patch("core.safety.light_cim.load_light_cim_policy", return_value=_base_policy()):
        cim = LightCIM()

    result = cim.check_logic_basic(
        {
            "needs_memory": True,
            "memory_keys": [],
            "dialogue_act": "request",
            "intent": "unknown",
        },
        user_text="{TOOL:CONTAINER} starte eine Sandbox und gib mir den Status.",
    )
    assert result["consistent"] is True
    assert result["issues"] == []


def test_memory_keys_requirement_relaxed_for_container_runtime_domain_route():
    with patch("core.safety.light_cim.load_light_cim_policy", return_value=_base_policy()):
        cim = LightCIM()

    result = cim.check_logic_basic(
        {
            "needs_memory": True,
            "memory_keys": [],
            "dialogue_act": "request",
            "_domain_route": {"domain_tag": "CONTAINER", "operation": "exec", "domain_locked": True},
            "suggested_tools": ["exec_in_container"],
            "intent": "host ip lookup",
        },
        user_text="Finde bitte die IP-Adresse vom Host-Server und nutze alle Tools.",
    )
    assert result["consistent"] is True
    assert result["issues"] == []


def test_memory_keys_requirement_still_blocks_for_non_runtime_smalltalk():
    with patch("core.safety.light_cim.load_light_cim_policy", return_value=_base_policy()):
        cim = LightCIM()

    result = cim.check_logic_basic(
        {
            "needs_memory": True,
            "memory_keys": [],
            "dialogue_act": "smalltalk",
            "intent": "lockere konversation",
        },
        user_text="Wie geht es dir heute?",
    )
    assert result["consistent"] is False
    assert "Needs memory but no keys specified" in result["issues"]
