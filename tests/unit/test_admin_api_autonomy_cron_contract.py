from pathlib import Path


def _read_main() -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / "adapters" / "admin-api" / "main.py").read_text(encoding="utf-8")


def _read_config() -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / "config.py").read_text(encoding="utf-8")


def test_autonomy_cron_endpoints_exist():
    src = _read_main()
    assert '@app.get("/api/autonomy/cron/status")' in src
    assert '@app.get("/api/autonomy/cron/jobs")' in src
    assert '@app.post("/api/autonomy/cron/jobs")' in src
    assert '@app.get("/api/autonomy/cron/jobs/{cron_job_id}")' in src
    assert '@app.put("/api/autonomy/cron/jobs/{cron_job_id}")' in src
    assert '@app.delete("/api/autonomy/cron/jobs/{cron_job_id}")' in src
    assert '@app.post("/api/autonomy/cron/jobs/{cron_job_id}/pause")' in src
    assert '@app.post("/api/autonomy/cron/jobs/{cron_job_id}/resume")' in src
    assert '@app.post("/api/autonomy/cron/jobs/{cron_job_id}/run-now")' in src
    assert '@app.get("/api/autonomy/cron/queue")' in src


def test_autonomy_cron_scheduler_wired_on_startup_and_shutdown():
    src = _read_main()
    assert "AutonomyCronScheduler(" in src
    assert "submit_cb=_submit_autonomy_job_from_cron" in src
    assert "await _autonomy_cron_scheduler.start()" in src
    assert "await _autonomy_cron_scheduler.stop()" in src


def test_config_exposes_autonomy_cron_knobs():
    src = _read_config()
    assert "def get_autonomy_cron_state_path()" in src
    assert "AUTONOMY_CRON_STATE_PATH" in src
    assert "def get_autonomy_cron_tick_s()" in src
    assert "AUTONOMY_CRON_TICK_S" in src
    assert "def get_autonomy_cron_max_concurrency()" in src
    assert "AUTONOMY_CRON_MAX_CONCURRENCY" in src
    assert "def get_autonomy_cron_max_jobs()" in src
    assert "AUTONOMY_CRON_MAX_JOBS" in src
    assert "def get_autonomy_cron_max_jobs_per_conversation()" in src
    assert "AUTONOMY_CRON_MAX_JOBS_PER_CONVERSATION" in src
    assert "def get_autonomy_cron_min_interval_s()" in src
    assert "AUTONOMY_CRON_MIN_INTERVAL_S" in src
    assert "def get_autonomy_cron_max_pending_runs()" in src
    assert "AUTONOMY_CRON_MAX_PENDING_RUNS" in src
    assert "def get_autonomy_cron_max_pending_runs_per_job()" in src
    assert "AUTONOMY_CRON_MAX_PENDING_RUNS_PER_JOB" in src
    assert "def get_autonomy_cron_manual_run_cooldown_s()" in src
    assert "AUTONOMY_CRON_MANUAL_RUN_COOLDOWN_S" in src
    assert "def get_autonomy_cron_trion_safe_mode()" in src
    assert "AUTONOMY_CRON_TRION_SAFE_MODE" in src
    assert "def get_autonomy_cron_trion_min_interval_s()" in src
    assert "AUTONOMY_CRON_TRION_MIN_INTERVAL_S" in src
    assert "def get_autonomy_cron_trion_max_loops()" in src
    assert "AUTONOMY_CRON_TRION_MAX_LOOPS" in src
    assert "def get_autonomy_cron_trion_require_approval_for_risky()" in src
    assert "AUTONOMY_CRON_TRION_REQUIRE_APPROVAL_FOR_RISKY" in src
    assert "def get_autonomy_cron_hardware_guard_enabled()" in src
    assert "AUTONOMY_CRON_HARDWARE_GUARD_ENABLED" in src
    assert "def get_autonomy_cron_hardware_cpu_max_percent()" in src
    assert "AUTONOMY_CRON_HARDWARE_CPU_MAX_PERCENT" in src
    assert "def get_autonomy_cron_hardware_mem_max_percent()" in src
    assert "AUTONOMY_CRON_HARDWARE_MEM_MAX_PERCENT" in src
