from core.layers.thinking import THINKING_PROMPT


def test_thinking_prompt_contains_followup_and_time_reference_rules():
    assert "Folgefragen" in THINKING_PROMPT
    assert '"time_reference"' in THINKING_PROMPT
    assert "heute" in THINKING_PROMPT
    assert "yesterday" in THINKING_PROMPT
