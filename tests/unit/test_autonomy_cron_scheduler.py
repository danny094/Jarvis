from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from core.autonomy.cron_scheduler import (
    AutonomyCronScheduler,
    CronPolicyError,
    _TRION_RISKY_CONTEXT_APPROVED,
    cron_matches,
    next_matching_utc,
    parse_cron_expression,
    validate_cron_expression,
)


async def _wait_until(predicate, *, timeout_s: float = 1.5, step_s: float = 0.02) -> bool:
    import asyncio
    import time

    deadline = time.monotonic() + max(0.1, float(timeout_s))
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(step_s)
    return predicate()


def test_parse_and_validate_cron_expression():
    parsed = parse_cron_expression("*/15 * * * *")
    assert parsed["expr"] == "*/15 * * * *"
    assert 0 in parsed["minute"].values
    assert 15 in parsed["minute"].values
    assert 45 in parsed["minute"].values

    validated = validate_cron_expression("0 4 * * *")
    assert validated["valid"] is True
    assert validated["normalized"] == "0 4 * * *"


def test_cron_matches_and_next_run_utc():
    parsed = parse_cron_expression("30 10 * * *")
    hit = datetime(2026, 3, 9, 10, 30, tzinfo=timezone.utc)
    miss = datetime(2026, 3, 9, 10, 29, tzinfo=timezone.utc)

    assert cron_matches(parsed, hit) is True
    assert cron_matches(parsed, miss) is False

    nxt = next_matching_utc(
        parsed,
        "UTC",
        from_utc=datetime(2026, 3, 9, 10, 29, tzinfo=timezone.utc),
    )
    assert nxt.startswith("2026-03-09T10:30")


@pytest.mark.asyncio
async def test_scheduler_crud_and_manual_queue(tmp_path):
    async def _dummy_submit(payload, meta):
        return {"job_id": "autonomy_dummy_1", "status": "queued"}

    scheduler = AutonomyCronScheduler(
        state_path=str(tmp_path / "autonomy_cron_state.json"),
        tick_s=10,
        max_concurrency=1,
        submit_cb=_dummy_submit,
    )

    created = await scheduler.create_job(
        {
            "name": "nightly-summary",
            "objective": "build nightly summary",
            "conversation_id": "conv-cron",
            "cron": "0 4 * * *",
            "timezone": "UTC",
            "max_loops": 8,
            "created_by": "user",
            "enabled": True,
        }
    )
    cron_id = created["id"]
    assert created["name"] == "nightly-summary"
    assert created["next_run_at"]

    paused = await scheduler.pause_job(cron_id)
    assert paused["enabled"] is False

    resumed = await scheduler.resume_job(cron_id)
    assert resumed["enabled"] is True

    scheduled = await scheduler.run_now(cron_id, reason="manual")
    assert scheduled["scheduled"] is True
    snap = await scheduler.get_queue_snapshot()
    assert len(snap["pending"]) == 1

    deleted = await scheduler.delete_job(cron_id)
    assert deleted is True


@pytest.mark.asyncio
async def test_scheduler_supports_one_shot_job_and_queues_only_once(tmp_path):
    async def _dummy_submit(payload, meta):
        return {"job_id": "autonomy_dummy_one_shot", "status": "queued"}

    scheduler = AutonomyCronScheduler(
        state_path=str(tmp_path / "autonomy_cron_state.json"),
        tick_s=10,
        max_concurrency=1,
        submit_cb=_dummy_submit,
    )

    run_at = datetime(2099, 1, 1, 0, 1, tzinfo=timezone.utc)
    created = await scheduler.create_job(
        {
            "name": "one-shot-reminder",
            "objective": "send one-shot reminder",
            "conversation_id": "conv-one-shot",
            "schedule_mode": "one_shot",
            "run_at": run_at.isoformat().replace("+00:00", "Z"),
            "timezone": "UTC",
            "max_loops": 4,
            "created_by": "user",
            "enabled": True,
        }
    )
    cron_id = created["id"]
    assert created["schedule_mode"] == "one_shot"
    assert created["next_run_at"].startswith("2099-01-01T00:01")

    with patch("core.autonomy.cron_scheduler._utcnow", return_value=run_at + timedelta(minutes=1)):
        await scheduler._tick_once()
        await scheduler._tick_once()

    snap = await scheduler.get_queue_snapshot()
    job = await scheduler.get_job(cron_id)
    assert len(snap["pending"]) == 1
    assert job is not None
    assert job.get("enabled") is False
    assert str(job.get("last_trigger_key", "")).startswith("one_shot:")


@pytest.mark.asyncio
async def test_scheduler_policy_limits_on_create(tmp_path):
    async def _dummy_submit(payload, meta):
        return {"job_id": "autonomy_dummy_1", "status": "queued"}

    scheduler = AutonomyCronScheduler(
        state_path=str(tmp_path / "autonomy_cron_state.json"),
        tick_s=10,
        max_concurrency=1,
        submit_cb=_dummy_submit,
        max_jobs=10,
        max_jobs_per_conversation=1,
        min_interval_s=60,
    )

    await scheduler.create_job(
        {
            "name": "job-a",
            "objective": "first",
            "conversation_id": "conv-shared",
            "cron": "0 4 * * *",
            "timezone": "UTC",
            "max_loops": 5,
            "created_by": "user",
            "enabled": True,
        }
    )

    with pytest.raises(CronPolicyError) as exc:
        await scheduler.create_job(
            {
                "name": "job-b",
                "objective": "second",
                "conversation_id": "conv-shared",
                "cron": "0 5 * * *",
                "timezone": "UTC",
                "max_loops": 5,
                "created_by": "user",
                "enabled": True,
            }
        )
    assert exc.value.error_code == "cron_conversation_limit_reached"


@pytest.mark.asyncio
async def test_scheduler_create_requires_conversation_id(tmp_path):
    async def _dummy_submit(payload, meta):
        return {"job_id": "autonomy_dummy_missing_conv", "status": "queued"}

    scheduler = AutonomyCronScheduler(
        state_path=str(tmp_path / "autonomy_cron_state.json"),
        tick_s=10,
        max_concurrency=1,
        submit_cb=_dummy_submit,
    )

    with pytest.raises(ValueError) as exc:
        await scheduler.create_job(
            {
                "name": "missing-conv",
                "objective": "should fail",
                "cron": "0 4 * * *",
                "timezone": "UTC",
                "max_loops": 4,
                "created_by": "user",
                "enabled": True,
            }
        )
    assert "conversation_id is required" in str(exc.value)


@pytest.mark.asyncio
async def test_scheduler_policy_min_interval_violation(tmp_path):
    async def _dummy_submit(payload, meta):
        return {"job_id": "autonomy_dummy_2", "status": "queued"}

    scheduler = AutonomyCronScheduler(
        state_path=str(tmp_path / "autonomy_cron_state.json"),
        tick_s=10,
        max_concurrency=1,
        submit_cb=_dummy_submit,
        min_interval_s=300,
    )

    with pytest.raises(CronPolicyError) as exc:
        await scheduler.create_job(
            {
                "name": "too-fast",
                "objective": "fast cadence",
                "conversation_id": "conv-fast",
                "cron": "*/1 * * * *",
                "timezone": "UTC",
                "max_loops": 5,
                "created_by": "user",
                "enabled": True,
            }
        )
    assert exc.value.error_code == "cron_min_interval_violation"


@pytest.mark.asyncio
async def test_scheduler_one_shot_ignores_min_interval_policy(tmp_path):
    async def _dummy_submit(payload, meta):
        return {"job_id": "autonomy_dummy_oneshot_min", "status": "queued"}

    scheduler = AutonomyCronScheduler(
        state_path=str(tmp_path / "autonomy_cron_state.json"),
        tick_s=10,
        max_concurrency=1,
        submit_cb=_dummy_submit,
        min_interval_s=900,
    )

    run_at = (datetime.now(timezone.utc) + timedelta(minutes=2)).replace(second=0, microsecond=0)
    created = await scheduler.create_job(
        {
            "name": "oneshot-fast",
            "objective": "one-shot despite recurring min interval",
            "conversation_id": "conv-fast-oneshot",
            "schedule_mode": "one_shot",
            "run_at": run_at.isoformat().replace("+00:00", "Z"),
            "cron": "*/1 * * * *",
            "timezone": "UTC",
            "max_loops": 5,
            "created_by": "user",
            "enabled": True,
        }
    )
    assert created["id"]
    assert created["schedule_mode"] == "one_shot"


@pytest.mark.asyncio
async def test_scheduler_manual_run_cooldown_guardrail(tmp_path):
    async def _dummy_submit(payload, meta):
        return {"job_id": "autonomy_dummy_3", "status": "queued"}

    scheduler = AutonomyCronScheduler(
        state_path=str(tmp_path / "autonomy_cron_state.json"),
        tick_s=10,
        max_concurrency=1,
        submit_cb=_dummy_submit,
        min_interval_s=60,
        max_pending_runs_per_job=3,
        manual_run_cooldown_s=60,
    )
    created = await scheduler.create_job(
        {
            "name": "manual",
            "objective": "manual trigger test",
            "conversation_id": "conv-manual",
            "cron": "0 4 * * *",
            "timezone": "UTC",
            "max_loops": 5,
            "created_by": "user",
            "enabled": True,
        }
    )

    await scheduler.run_now(created["id"], reason="manual")
    with pytest.raises(CronPolicyError) as exc:
        await scheduler.run_now(created["id"], reason="manual")
    assert exc.value.error_code == "cron_run_now_cooldown"


@pytest.mark.asyncio
async def test_trion_cron_min_interval_policy(tmp_path):
    async def _dummy_submit(payload, meta):
        return {"job_id": "autonomy_dummy_4", "status": "queued"}

    scheduler = AutonomyCronScheduler(
        state_path=str(tmp_path / "autonomy_cron_state.json"),
        tick_s=10,
        max_concurrency=1,
        submit_cb=_dummy_submit,
        min_interval_s=300,
        trion_safe_mode=True,
        trion_min_interval_s=900,
    )

    with pytest.raises(CronPolicyError) as exc:
        await scheduler.create_job(
            {
                "name": "trion-fast",
                "objective": "status summary for runtime",
                "conversation_id": "conv-trion",
                "cron": "*/5 * * * *",
                "timezone": "UTC",
                "max_loops": 6,
                "created_by": "trion",
                "enabled": True,
            }
        )
    assert exc.value.error_code == "cron_trion_min_interval_violation"


@pytest.mark.asyncio
async def test_trion_risky_objective_requires_user_approval(tmp_path):
    async def _dummy_submit(payload, meta):
        return {"job_id": "autonomy_dummy_5", "status": "queued"}

    scheduler = AutonomyCronScheduler(
        state_path=str(tmp_path / "autonomy_cron_state.json"),
        tick_s=10,
        max_concurrency=1,
        submit_cb=_dummy_submit,
        trion_safe_mode=True,
        trion_min_interval_s=900,
        trion_require_approval_for_risky=True,
    )

    # "drop user tables" — "drop" is not in context-whitelist, so requires approval
    # regardless of any allowed hint. This tests truly dangerous keywords.
    with pytest.raises(CronPolicyError) as exc:
        await scheduler.create_job(
            {
                "name": "trion-risky",
                "objective": "drop old user tables and create summary report",
                "conversation_id": "conv-trion",
                "cron": "*/15 * * * *",
                "timezone": "UTC",
                "max_loops": 6,
                "created_by": "trion",
                "enabled": True,
            }
        )
    assert exc.value.error_code == "cron_trion_approval_required"

    # Context-aware: "restart" + "status" is now pre-approved — no error expected
    await scheduler.create_job(
        {
            "name": "trion-restart-status",
            "objective": "restart service and create status summary",
            "conversation_id": "conv-trion",
            "cron": "*/15 * * * *",
            "timezone": "UTC",
            "max_loops": 6,
            "created_by": "trion",
            "enabled": True,
        }
    )


@pytest.mark.asyncio
async def test_trion_risky_objective_with_approval_is_allowed(tmp_path):
    async def _dummy_submit(payload, meta):
        return {"job_id": "autonomy_dummy_6", "status": "queued"}

    scheduler = AutonomyCronScheduler(
        state_path=str(tmp_path / "autonomy_cron_state.json"),
        tick_s=10,
        max_concurrency=1,
        submit_cb=_dummy_submit,
        trion_safe_mode=True,
        trion_min_interval_s=900,
        trion_require_approval_for_risky=True,
    )

    created = await scheduler.create_job(
        {
            "name": "trion-risky-approved",
            "objective": "restart service and create status summary",
            "conversation_id": "conv-trion",
            "cron": "*/15 * * * *",
            "timezone": "UTC",
            "max_loops": 6,
            "created_by": "trion",
            "user_approved": True,
            "enabled": True,
        }
    )
    assert created["id"]


@pytest.mark.asyncio
async def test_trion_hard_block_keyword_denied_even_with_approval(tmp_path):
    async def _dummy_submit(payload, meta):
        return {"job_id": "autonomy_dummy_7", "status": "queued"}

    scheduler = AutonomyCronScheduler(
        state_path=str(tmp_path / "autonomy_cron_state.json"),
        tick_s=10,
        max_concurrency=1,
        submit_cb=_dummy_submit,
        trion_safe_mode=True,
    )

    with pytest.raises(CronPolicyError) as exc:
        await scheduler.create_job(
            {
                "name": "trion-forbidden",
                "objective": "rm -rf logs and create status summary",
                "conversation_id": "conv-trion",
                "cron": "*/20 * * * *",
                "timezone": "UTC",
                "max_loops": 4,
                "created_by": "trion",
                "user_approved": True,
                "enabled": True,
            }
        )
    assert exc.value.error_code == "cron_trion_objective_forbidden"


@pytest.mark.asyncio
async def test_scheduler_persists_normalized_reference_links(tmp_path):
    async def _dummy_submit(payload, meta):
        return {"job_id": "autonomy_dummy_8", "status": "queued"}

    scheduler = AutonomyCronScheduler(
        state_path=str(tmp_path / "autonomy_cron_state.json"),
        tick_s=10,
        max_concurrency=1,
        submit_cb=_dummy_submit,
        min_interval_s=60,
    )

    created = await scheduler.create_job(
        {
            "name": "ref-links",
            "objective": "status summary report",
            "conversation_id": "conv-ref",
            "cron": "0 4 * * *",
            "timezone": "UTC",
            "max_loops": 5,
            "created_by": "trion",
            "reference_source": "settings:cronjobs:auto",
            "reference_links": [
                {"name": "A", "url": "https://github.com/org/repo-a", "description": "one"},
                {"name": "A dup", "url": "https://github.com/org/repo-a", "description": "dup"},
                {"name": "B", "url": "https://github.com/org/repo-b", "description": "two"},
                {"name": "", "url": "https://github.com/org/repo-c"},
            ],
            "enabled": True,
        }
    )

    assert created["reference_source"] == "settings:cronjobs:auto"
    refs = created.get("reference_links") or []
    assert len(refs) == 2
    assert refs[0]["url"] == "https://github.com/org/repo-a"
    assert refs[1]["url"] == "https://github.com/org/repo-b"
    assert all(x.get("read_only") is True for x in refs)


@pytest.mark.asyncio
async def test_scheduler_auto_generates_job_note_markdown(tmp_path):
    async def _dummy_submit(payload, meta):
        return {"job_id": "autonomy_dummy_note_auto", "status": "queued"}

    scheduler = AutonomyCronScheduler(
        state_path=str(tmp_path / "autonomy_cron_state.json"),
        tick_s=10,
        max_concurrency=1,
        submit_cb=_dummy_submit,
        min_interval_s=60,
    )

    created = await scheduler.create_job(
        {
            "name": "note-auto",
            "objective": "status summary report",
            "conversation_id": "conv-note",
            "cron": "0 4 * * *",
            "timezone": "UTC",
            "max_loops": 5,
            "created_by": "user",
            "enabled": True,
        }
    )

    note = str(created.get("job_note_md") or "")
    assert note.startswith("# Cron Job: note-auto")
    assert "## Objective" in note
    assert "status summary report" in note
    assert "## Schedule" in note


@pytest.mark.asyncio
async def test_scheduler_keeps_custom_job_note_markdown_on_update(tmp_path):
    async def _dummy_submit(payload, meta):
        return {"job_id": "autonomy_dummy_note_custom", "status": "queued"}

    scheduler = AutonomyCronScheduler(
        state_path=str(tmp_path / "autonomy_cron_state.json"),
        tick_s=10,
        max_concurrency=1,
        submit_cb=_dummy_submit,
        min_interval_s=60,
    )

    custom_note = "# Custom Note\n\nDo not overwrite."
    created = await scheduler.create_job(
        {
            "name": "note-custom",
            "objective": "status summary report",
            "conversation_id": "conv-note-custom",
            "cron": "0 4 * * *",
            "timezone": "UTC",
            "max_loops": 5,
            "created_by": "user",
            "enabled": True,
            "job_note_md": custom_note,
        }
    )

    updated = await scheduler.update_job(
        created["id"],
        {
            "objective": "status summary report updated",
        },
    )
    assert updated is not None
    assert str(updated.get("job_note_md") or "") == custom_note

@pytest.mark.asyncio
async def test_scheduler_defers_dispatch_when_hardware_guard_blocks(tmp_path):
    submissions = []

    async def _dummy_submit(payload, meta):
        submissions.append({"payload": payload, "meta": meta})
        return {"job_id": "autonomy_dummy_hw_block", "status": "queued"}

    scheduler = AutonomyCronScheduler(
        state_path=str(tmp_path / "autonomy_cron_state.json"),
        tick_s=10,
        max_concurrency=1,
        submit_cb=_dummy_submit,
        min_interval_s=60,
        hardware_guard_enabled=True,
        hardware_cpu_max_percent=70,
        hardware_mem_max_percent=90,
        hardware_probe_cb=lambda: {"cpu_percent": 95.0, "memory_percent": 40.0},
    )

    created = await scheduler.create_job(
        {
            "name": "hw-blocked",
            "objective": "status summary",
            "conversation_id": "conv-hw",
            "cron": "0 4 * * *",
            "timezone": "UTC",
            "max_loops": 4,
            "created_by": "user",
            "enabled": True,
        }
    )

    await scheduler.start()
    try:
        await scheduler.run_now(created["id"], reason="manual")
        done = await _wait_until(
            lambda: any(
                h.get("status") == "deferred_hardware"
                for h in (scheduler._history or [])
            ),
            timeout_s=2.0,
        )
        assert done is True
        assert submissions == []

        job = await scheduler.get_job(created["id"])
        assert job is not None
        assert job.get("last_status") == "deferred_hardware"
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_scheduler_dispatches_when_hardware_guard_is_within_limits(tmp_path):
    submissions = []

    async def _dummy_submit(payload, meta):
        submissions.append({"payload": payload, "meta": meta})
        return {"job_id": "autonomy_dummy_hw_ok", "status": "queued"}

    scheduler = AutonomyCronScheduler(
        state_path=str(tmp_path / "autonomy_cron_state.json"),
        tick_s=10,
        max_concurrency=1,
        submit_cb=_dummy_submit,
        min_interval_s=60,
        hardware_guard_enabled=True,
        hardware_cpu_max_percent=80,
        hardware_mem_max_percent=90,
        hardware_probe_cb=lambda: {"cpu_percent": 20.0, "memory_percent": 30.0},
    )

    created = await scheduler.create_job(
        {
            "name": "hw-ok",
            "objective": "status summary",
            "conversation_id": "conv-hw-ok",
            "cron": "0 4 * * *",
            "timezone": "UTC",
            "max_loops": 4,
            "created_by": "user",
            "enabled": True,
        }
    )

    await scheduler.start()
    try:
        await scheduler.run_now(created["id"], reason="manual")
        done = await _wait_until(lambda: len(submissions) >= 1, timeout_s=2.0)
        assert done is True

        job = await scheduler.get_job(created["id"])
        assert job is not None
        assert job.get("last_status") == "submitted"
    finally:
        await scheduler.stop()


# ────────────────────────────────────────────────────────────────────────────
# Context-aware risky keyword whitelist tests
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("objective", [
    "delete old log files from cleanup job",
    "remove stale temp files during maint cycle",
    "restart failed service after health check",
    "kill hung process for health monitoring",
    "docker container cleanup and status report",
    "network status health check monitor",
    "shutdown scheduled for backup maintenance",
])
async def test_context_approved_objectives_dont_require_approval(objective, tmp_path):
    """Risky keywords that are contextually pre-approved by a maintenance hint
    must NOT require user_approved=true."""
    async def _dummy_submit(payload, meta):
        return {"job_id": "dummy_ctx", "status": "queued"}

    scheduler = AutonomyCronScheduler(
        state_path=str(tmp_path / f"state_{hash(objective) & 0xFFFF}.json"),
        tick_s=10,
        max_concurrency=1,
        submit_cb=_dummy_submit,
        trion_safe_mode=True,
        trion_min_interval_s=900,
        trion_require_approval_for_risky=True,
    )
    # Must NOT raise — context whitelist pre-approves these
    created = await scheduler.create_job({
        "name": f"ctx-test-{hash(objective) & 0xFFFF}",
        "objective": objective,
        "conversation_id": "conv-ctx",
        "cron": "0 * * * *",
        "timezone": "UTC",
        "max_loops": 5,
        "created_by": "trion",
        "enabled": True,
    })
    assert created["id"], f"Job creation failed for context-approved objective: '{objective}'"


@pytest.mark.asyncio
@pytest.mark.parametrize("objective", [
    "drop production database tables and archive summary",
    "truncate user records from memory backup",
    "wipe all data including health check logs",
    "sudo chmod 777 all files for status monitor",
    "steal api key credentials for monitoring report",
])
async def test_always_risky_objectives_require_approval(objective, tmp_path):
    """Truly dangerous keywords (drop, truncate, wipe, sudo, credential theft)
    must always require user_approved=true, even with allowed context hints."""
    async def _dummy_submit(payload, meta):
        return {"job_id": "dummy_risky", "status": "queued"}

    scheduler = AutonomyCronScheduler(
        state_path=str(tmp_path / f"state_{hash(objective) & 0xFFFF}.json"),
        tick_s=10,
        max_concurrency=1,
        submit_cb=_dummy_submit,
        trion_safe_mode=True,
        trion_min_interval_s=900,
        trion_require_approval_for_risky=True,
    )
    with pytest.raises(CronPolicyError) as exc:
        await scheduler.create_job({
            "name": f"risky-{hash(objective) & 0xFFFF}",
            "objective": objective,
            "conversation_id": "conv-risky",
            "cron": "0 * * * *",
            "timezone": "UTC",
            "max_loops": 5,
            "created_by": "trion",
            "enabled": True,
        })
    assert exc.value.error_code == "cron_trion_approval_required", (
        f"Expected approval_required for dangerous objective: '{objective}'"
    )


def test_risky_context_approved_map_is_consistent():
    """_TRION_RISKY_CONTEXT_APPROVED must only contain subsets of _TRION_OBJECTIVE_ALLOWED_HINTS."""
    from core.autonomy.cron_scheduler import _TRION_OBJECTIVE_ALLOWED_HINTS
    allowed_set = set(_TRION_OBJECTIVE_ALLOWED_HINTS)
    for risky_kw, ctx_hints in _TRION_RISKY_CONTEXT_APPROVED.items():
        unknown = ctx_hints - allowed_set
        assert not unknown, (
            f"_TRION_RISKY_CONTEXT_APPROVED['{risky_kw}'] contains hints not in "
            f"_TRION_OBJECTIVE_ALLOWED_HINTS: {unknown}"
        )
