from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_migration_script_exists_with_apply_mode_and_type_mapping():
    src = _read("scripts/ops/migrate_legacy_cron_conversations.py")
    assert "Migrate legacy cron jobs" in src
    assert "--apply" in src
    assert "target-reminder" in src
    assert "target-maintenance" in src
    assert "target-backup" in src


def test_cron_e2e_script_covers_create_run_feedback_delete_flow():
    src = _read("scripts/test_cron_e2e_regression.sh")
    assert "/api/autonomy/cron/jobs" in src
    assert "/run-now" in src
    assert "cron_chat_feedback" in src
    assert "DELETE" in src
    assert "PASS" in src
