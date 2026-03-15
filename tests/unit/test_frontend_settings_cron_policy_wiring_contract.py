from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_advanced_page_contains_cron_guardrail_controls():
    src = _read("adapters/Jarvis/index.html")
    assert "Autonomy Cron Guardrails" in src
    assert 'id="cron-policy-max-jobs"' in src
    assert 'id="cron-policy-min-interval-s"' in src
    assert 'id="cron-policy-trion-min-interval-s"' in src
    assert 'id="cron-policy-trion-safe-mode"' in src
    assert 'id="save-cron-policy-settings"' in src


def test_settings_app_wires_cron_policy_load_and_save():
    src = _read("adapters/Jarvis/js/apps/settings.js")
    assert "loadAutonomyCronPolicy" in src
    assert "saveAutonomyCronPolicy" in src
    assert "setupAutonomyCronPolicyHandlers" in src
    assert "/api/settings/autonomy/cron-policy" in src
