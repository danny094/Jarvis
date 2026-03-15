from core.orchestrator_prompt_utils import (
    is_rollout_enabled,
    looks_like_short_confirmation_followup,
    looks_like_short_confirmation_followup_state_only,
    looks_like_short_fact_followup,
    normalize_trace_id,
    recent_user_messages,
    safe_str,
    sanitize_tool_args_for_state,
)


def test_normalize_trace_id_sanitizes_chars_and_limits_length():
    value = normalize_trace_id("abc###:::@@@xyz" + "a" * 200)
    assert len(value) <= 64
    assert "#" not in value
    assert ":" in value


def test_is_rollout_enabled_respects_hard_bounds():
    assert is_rollout_enabled(100, "seed")
    assert not is_rollout_enabled(0, "seed")


def test_recent_user_messages_picks_latest_users_only():
    history = [
        {"role": "assistant", "content": "old"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u2"},
    ]
    assert recent_user_messages(history, limit=2) == ["u2", "u1"]


def test_looks_like_short_fact_followup_requires_marker_or_prefix():
    chat = [{"role": "assistant", "content": "Verifizierte Fakten: ..."}]
    assert looks_like_short_fact_followup(
        "und heute?",
        chat,
        prefixes=("und ",),
        markers=("und", "was ist mit"),
    )
    assert not looks_like_short_fact_followup(
        "komplett neues thema",
        chat,
        prefixes=("und ",),
        markers=("und", "was ist mit"),
    )


def test_looks_like_short_confirmation_followup_detects_yes_after_action_prompt():
    chat = [{"role": "assistant", "content": "Soll ich eine dieser Methoden direkt im laufenden Container testen?"}]
    assert looks_like_short_confirmation_followup(
        "ja bitte testen",
        chat,
        prefixes=("ja", "ja bitte", "bitte"),
        markers=("ja", "bitte testen"),
        assistant_action_markers=("testen", "container", "tool"),
    )


def test_looks_like_short_confirmation_followup_detects_okey_mach_das_bitte_variant():
    chat = [{"role": "assistant", "content": "Soll ich die Netzwerkmethode jetzt direkt im Container testen?"}]
    assert looks_like_short_confirmation_followup(
        "okey mach das bitte",
        chat,
        prefixes=("ja", "ja bitte", "bitte", "ok", "okay", "mach"),
        markers=("ja", "bitte testen", "mach weiter", "weiter"),
        assistant_action_markers=("testen", "container", "tool", "methode"),
    )


def test_looks_like_short_confirmation_followup_state_only_detects_confirmation_action():
    assert looks_like_short_confirmation_followup_state_only(
        "okey mach das bitte",
        action_markers=("mach das", "testen", "weiter", "go"),
    )


def test_looks_like_short_confirmation_followup_state_only_rejects_question():
    assert not looks_like_short_confirmation_followup_state_only(
        "kannst du das bitte testen?",
        action_markers=("mach das", "testen", "weiter", "go"),
    )


def test_safe_str_and_sanitize_tool_args_for_state():
    assert safe_str("x" * 10, max_len=4) == "xxxx"
    out = sanitize_tool_args_for_state({"a": 1, "b": object()})
    assert out["a"] == 1
    assert "b" in out
