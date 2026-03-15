from core.orchestrator_tool_validation_utils import validate_tool_args


class _Hub:
    def __init__(self, defs):
        self._tool_definitions = defs


def _base_kwargs(**overrides):
    kwargs = {
        "extract_requested_skill_name_fn": lambda text: "",
        "sanitize_skill_name_candidate_fn": lambda raw: str(raw or "").strip().lower() or "",
        "extract_cron_schedule_from_text_fn": lambda text, verified_plan=None: {
            "schedule_mode": "recurring",
            "cron": "*/15 * * * *",
            "run_at": "",
        },
        "prevalidate_cron_policy_args_fn": lambda tool_name, args: (True, ""),
    }
    kwargs.update(overrides)
    return kwargs


def test_validate_tool_args_autofills_required_query_for_analyze():
    hub = _Hub({"analyze": {"inputSchema": {"required": ["query"]}}})
    ok, args, reason = validate_tool_args(
        hub,
        "analyze",
        {},
        "prüfe bottleneck",
        **_base_kwargs(),
    )
    assert ok is True
    assert args["query"] == "prüfe bottleneck"
    assert reason == ""


def test_validate_tool_args_run_skill_requires_name_if_not_extractable():
    hub = _Hub({})
    ok, args, reason = validate_tool_args(
        hub,
        "run_skill",
        {"name": ""},
        "run skill",
        **_base_kwargs(
            extract_requested_skill_name_fn=lambda text: "",
            sanitize_skill_name_candidate_fn=lambda raw: "",
        ),
    )
    assert ok is False
    assert reason == "missing_required=['name']"
    assert args.get("name", "") == ""


def test_validate_tool_args_run_skill_autofills_sanitized_extracted_name():
    hub = _Hub({})
    ok, args, reason = validate_tool_args(
        hub,
        "run_skill",
        {"name": ""},
        "bitte run skill system_hardware_info",
        **_base_kwargs(
            extract_requested_skill_name_fn=lambda text: "system_hardware_info",
            sanitize_skill_name_candidate_fn=lambda raw: "",
        ),
    )
    assert ok is True
    assert args["name"] == "system_hardware_info"
    assert reason == ""


def test_validate_tool_args_cron_adds_schedule_defaults_when_missing():
    hub = _Hub({})
    ok, args, reason = validate_tool_args(
        hub,
        "autonomy_cron_create_job",
        {},
        "einmal in 5 minuten",
        **_base_kwargs(
            extract_cron_schedule_from_text_fn=lambda text, verified_plan=None: {
                "schedule_mode": "one_shot",
                "cron": "*/5 * * * *",
                "run_at": "2026-03-13T22:05:00Z",
            }
        ),
    )
    assert ok is True
    assert args["schedule_mode"] == "one_shot"
    assert args["cron"] == "*/5 * * * *"
    assert args["run_at"] == "2026-03-13T22:05:00Z"
    assert reason == ""


def test_validate_tool_args_propagates_cron_policy_rejection():
    hub = _Hub({"autonomy_cron_create_job": {"inputSchema": {"required": []}}})
    ok, args, reason = validate_tool_args(
        hub,
        "autonomy_cron_create_job",
        {"cron": "*/1 * * * *"},
        "jede minute",
        **_base_kwargs(
            prevalidate_cron_policy_args_fn=lambda tool_name, parsed_args: (False, "cron_min_interval_violation"),
        ),
    )
    assert ok is False
    assert args["cron"] == "*/1 * * * *"
    assert reason == "cron_min_interval_violation"
