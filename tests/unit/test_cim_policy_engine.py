from intelligence_modules.cim_policy.cim_policy_engine import CIMPolicyEngine


def test_derive_skill_name_prefers_explicit_name_german():
    engine = CIMPolicyEngine()
    name = engine._derive_skill_name(
        "Erstelle einen Skill namens smoke_sync_live_test, der nur Hallo sagt.",
        {"trigger_category": "meta_creation"},
    )
    assert name == "smoke_sync_live_test"


def test_derive_skill_name_prefers_explicit_name_english():
    engine = CIMPolicyEngine()
    name = engine._derive_skill_name(
        "Create a new function named quick_probe_helper for me.",
        {"trigger_category": "meta_creation"},
    )
    assert name == "quick_probe_helper"


def test_derive_skill_name_falls_back_to_auto_prefix():
    engine = CIMPolicyEngine()
    name = engine._derive_skill_name(
        "Mach bitte etwas Nützliches ohne konkreten Namen.",
        {"trigger_category": "meta_creation"},
    )
    assert name.startswith("auto_meta_creation_")


def test_process_uses_explicit_skill_name_from_input():
    engine = CIMPolicyEngine()
    decision = engine.process(
        "Erstelle einen Skill namens mein_test_skill der hallo sagt",
        available_skills=[],
    )
    assert decision.matched is True
    assert decision.skill_name == "mein_test_skill"
    assert decision.requires_confirmation is True


def test_process_matches_longer_new_function_prompt():
    engine = CIMPolicyEngine()
    decision = engine.process(
        "Baue eine neue Funktion namens quick_probe_helper, die einfach Hallo ausgibt.",
        available_skills=[],
    )
    assert decision.matched is True
    assert decision.skill_name == "quick_probe_helper"
    assert decision.requires_confirmation is True
