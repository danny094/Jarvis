from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_chat_js_polls_workspace_events_for_cron_feedback():
    src = _read("adapters/Jarvis/static/js/chat.js")
    assert "cron_chat_feedback" in src
    assert "/api/workspace-events" in src
    assert "initCronFeedbackPolling" in src


def test_app_initializes_cron_feedback_polling():
    src = _read("adapters/Jarvis/static/js/app.js")
    assert "initCronFeedbackPolling" in src
    assert "initChatFromStorage();" in src
