from core.autosave_dedupe import AutosaveDedupeGuard


def test_autosave_dedupe_skips_same_content_within_window():
    guard = AutosaveDedupeGuard(window_s=120, max_entries=256)
    conv = "conv-a"
    text = "Ich habe die Host-Runtime-IP ermittelt: 172.21.0.2"

    assert guard.should_skip(conversation_id=conv, content=text) is False
    assert guard.should_skip(conversation_id=conv, content=text) is True


def test_autosave_dedupe_keeps_conversations_isolated():
    guard = AutosaveDedupeGuard(window_s=120, max_entries=256)
    text = "same payload"

    assert guard.should_skip(conversation_id="conv-a", content=text) is False
    assert guard.should_skip(conversation_id="conv-b", content=text) is False


def test_autosave_dedupe_normalizes_whitespace_case():
    guard = AutosaveDedupeGuard(window_s=120, max_entries=256)
    a = "  Hallo   Welt  "
    b = "hallo welt"

    assert guard.should_skip(conversation_id="conv", content=a) is False
    assert guard.should_skip(conversation_id="conv", content=b) is True

