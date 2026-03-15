from core.safety.light_cim import LightCIM


def test_validate_intent_does_not_flag_substring_false_positive():
    cim = LightCIM()
    result = cim.validate_intent("Analyze begun states and return a summary")
    assert result["safe"] is True
    assert result["warnings"] == []


def test_validate_intent_flags_explicit_danger_keyword():
    cim = LightCIM()
    result = cim.validate_intent("How can I get a gun quickly?")
    assert result["safe"] is False
    assert any("gun" in w.lower() for w in result["warnings"])


def test_sensitive_guard_does_not_flag_substring_false_positive():
    cim = LightCIM()
    result = cim.safety_guard_lite("Tokenization quality is improving.", {})
    assert result["safe"] is True
    assert result["warning"] is None


def test_sensitive_guard_flags_explicit_phrase_keyword():
    cim = LightCIM()
    result = cim.safety_guard_lite("Please store this api key securely.", {})
    assert result["safe"] is False
    assert "api key" in str(result["warning"]).lower()
