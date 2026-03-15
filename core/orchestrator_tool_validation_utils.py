from typing import Any, Callable, Dict, Tuple


def validate_tool_args(
    tool_hub: Any,
    tool_name: str,
    tool_args: Dict[str, Any],
    user_text: str,
    *,
    extract_requested_skill_name_fn: Callable[[str], str],
    sanitize_skill_name_candidate_fn: Callable[[Any], str],
    extract_cron_schedule_from_text_fn: Callable[[str, Dict[str, Any] | None], Dict[str, str]],
    prevalidate_cron_policy_args_fn: Callable[[str, Dict[str, Any]], Tuple[bool, str]],
) -> Tuple[bool, Dict[str, Any], str]:
    args = dict(tool_args or {})
    if tool_name == "analyze" and not str(args.get("query", "")).strip():
        args["query"] = (user_text or "").strip()

    required = []
    try:
        schema = (tool_hub._tool_definitions.get(tool_name, {}) or {}).get("inputSchema", {}) or {}
        required = list(schema.get("required", []) or [])
    except Exception:
        required = []

    def _missing(k: str) -> bool:
        v = args.get(k, None)
        if v is None:
            return True
        if isinstance(v, str):
            return not v.strip()
        if isinstance(v, (list, dict)):
            return len(v) == 0
        return False

    missing = [k for k in required if _missing(k)]
    if "query" in missing and (user_text or "").strip():
        args["query"] = user_text.strip()
        missing = [k for k in required if _missing(k)]
    if "message" in missing and (user_text or "").strip():
        args["message"] = user_text.strip()
        missing = [k for k in required if _missing(k)]

    if tool_name == "run_skill":
        extracted_name = extract_requested_skill_name_fn(user_text)
        current_name = str(args.get("name", "") or "").strip()
        sanitized_name = sanitize_skill_name_candidate_fn(current_name)
        if not sanitized_name and extracted_name:
            sanitized_name = extracted_name
        if sanitized_name:
            args["name"] = sanitized_name
        elif "name" not in missing:
            missing = ["name"] + [k for k in missing if k != "name"]

    if tool_name in {"autonomy_cron_create_job", "autonomy_cron_update_job"}:
        if not str(args.get("schedule_mode", "")).strip():
            schedule = extract_cron_schedule_from_text_fn(user_text, verified_plan=None)
            args["schedule_mode"] = schedule.get("schedule_mode", "recurring")
            if not str(args.get("run_at", "")).strip() and schedule.get("run_at"):
                args["run_at"] = schedule.get("run_at")
            if not str(args.get("cron", "")).strip() and schedule.get("cron"):
                args["cron"] = schedule.get("cron")

    cron_ok, cron_reason = prevalidate_cron_policy_args_fn(tool_name, args)
    if not cron_ok:
        return False, args, cron_reason

    if missing:
        return False, args, f"missing_required={missing}"
    return True, args, ""
