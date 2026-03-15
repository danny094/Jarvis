from pathlib import Path


def _read_settings_routes() -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / "adapters" / "admin-api" / "settings_routes.py").read_text(encoding="utf-8")


def test_autonomy_cron_policy_settings_routes_exist():
    src = _read_settings_routes()
    assert '@router.get("/autonomy/cron-policy")' in src
    assert '@router.post("/autonomy/cron-policy")' in src
    assert "class AutonomyCronPolicyUpdate" in src


def test_autonomy_cron_policy_fields_wired():
    src = _read_settings_routes()
    expected = [
        "AUTONOMY_CRON_MAX_JOBS",
        "AUTONOMY_CRON_MAX_JOBS_PER_CONVERSATION",
        "AUTONOMY_CRON_MIN_INTERVAL_S",
        "AUTONOMY_CRON_MAX_PENDING_RUNS",
        "AUTONOMY_CRON_MAX_PENDING_RUNS_PER_JOB",
        "AUTONOMY_CRON_MANUAL_RUN_COOLDOWN_S",
        "AUTONOMY_CRON_TRION_SAFE_MODE",
        "AUTONOMY_CRON_TRION_MIN_INTERVAL_S",
        "AUTONOMY_CRON_TRION_MAX_LOOPS",
        "AUTONOMY_CRON_TRION_REQUIRE_APPROVAL_FOR_RISKY",
        "AUTONOMY_CRON_HARDWARE_GUARD_ENABLED",
        "AUTONOMY_CRON_HARDWARE_CPU_MAX_PERCENT",
        "AUTONOMY_CRON_HARDWARE_MEM_MAX_PERCENT",
    ]
    for key in expected:
        assert key in src
