from core.orchestrator_tool_args_utils import build_tool_args


def _base_kwargs(**overrides):
    kwargs = {
        "extract_requested_skill_name_fn": lambda text: "",
        "looks_like_host_runtime_lookup_fn": lambda text: False,
        "extract_cron_schedule_from_text_fn": lambda text, vp: {
            "schedule_mode": "recurring",
            "cron": "*/15 * * * *",
            "run_at": "",
        },
        "build_cron_objective_fn": lambda text: f"user_request::{text.strip()}",
        "build_cron_name_fn": lambda text: "cron-default",
        "extract_cron_job_id_from_text_fn": lambda text, vp: "",
        "extract_cron_expression_from_text_fn": lambda text, vp: "*/15 * * * *",
        "now_ts_fn": lambda: 1700000000.0,
        "strftime_fn": lambda fmt: "2026-03-13_22-00-00",
    }
    kwargs.update(overrides)
    return kwargs


def test_build_tool_args_run_skill_uses_extracted_name():
    out = build_tool_args(
        "run_skill",
        "run skill",
        **_base_kwargs(extract_requested_skill_name_fn=lambda text: "system_hardware_info"),
    )
    assert out == {"action": "run", "args": {}, "name": "system_hardware_info"}


def test_build_tool_args_exec_in_container_host_lookup_uses_probe_command():
    out = build_tool_args(
        "exec_in_container",
        "find host ip",
        **_base_kwargs(looks_like_host_runtime_lookup_fn=lambda text: True),
    )
    assert out["container_id"] == "PENDING"
    assert "host.docker.internal" in out["command"]
    assert "IP_NOT_FOUND" in out["command"]
    assert "hostname -I" in out["command"]


def test_build_tool_args_memory_save_prefixes_verified_fact_key():
    out = build_tool_args(
        "memory_save",
        "Jarvis nutzt UTC",
        verified_plan={"is_new_fact": True, "new_fact_key": "timezone"},
        **_base_kwargs(),
    )
    assert out["conversation_id"] == "auto"
    assert out["role"] == "user"
    assert out["content"] == "[timezone]: Jarvis nutzt UTC"


def test_build_tool_args_cron_create_direct_one_shot_uses_one_loop():
    out = build_tool_args(
        "autonomy_cron_create_job",
        "Erinnere mich einmalig",
        **_base_kwargs(
            extract_cron_schedule_from_text_fn=lambda text, vp: {
                "schedule_mode": "one_shot",
                "cron": "*/5 * * * *",
                "run_at": "2026-03-13T22:05:00Z",
            },
            build_cron_objective_fn=lambda text: "user_reminder::test",
            build_cron_name_fn=lambda text: "cron-reminder",
        ),
    )
    assert out["schedule_mode"] == "one_shot"
    assert out["objective"] == "user_reminder::test"
    assert out["max_loops"] == 1


def test_build_tool_args_create_skill_uses_time_based_fallback_name():
    out = build_tool_args(
        "create_skill",
        "!!!",
        **_base_kwargs(now_ts_fn=lambda: 12345.0),
    )
    assert out["name"] == "auto_skill_12345"
    assert "Auto-generated fallback scaffold" in out["code"]
