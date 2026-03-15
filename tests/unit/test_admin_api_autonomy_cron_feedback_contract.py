from pathlib import Path


def _read_main() -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / "adapters" / "admin-api" / "main.py").read_text(encoding="utf-8")


def test_admin_api_emits_cron_chat_feedback_workspace_event():
    src = _read_main()
    assert "event_type\": \"cron_chat_feedback\"" in src
    assert "workspace_event_save" in src
    assert "_emit_cron_chat_feedback_event" in src


def test_admin_api_supports_direct_cron_reminder_objective():
    src = _read_main()
    assert "_is_direct_cron_reminder_objective" in src
    assert "user_reminder::" in src
    assert "_extract_direct_cron_reminder_text" in src


def test_admin_api_supports_direct_cron_self_state_objective():
    src = _read_main()
    assert "_is_direct_cron_self_state_objective" in src
    assert "self_state_report::" in src
    assert "_looks_like_self_state_request" in src
    assert "user_request::" in src
    assert "_build_direct_cron_self_state_message" in src


def test_admin_api_cron_feedback_formats_max_loops_reached():
    src = _read_main()
    assert "max_loops_reached" in src
    assert "Lauflimit erreicht" in src
