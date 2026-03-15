import re
from typing import Any, Dict, List


def verification_text(verification: Dict[str, Any]) -> str:
    reason = str((verification or {}).get("reason") or "")
    block_reason_code = str((verification or {}).get("block_reason_code") or "")
    final_instruction = str((verification or {}).get("final_instruction") or "")
    warnings = (verification or {}).get("warnings") or []
    warning_text = " ".join(str(w) for w in warnings)
    return f"{reason} {block_reason_code} {final_instruction} {warning_text}".lower()


def looks_like_capability_mismatch(verification: Dict[str, Any]) -> bool:
    text = verification_text(verification)
    markers = (
        "nicht verfügbar",
        "not available",
        "kein tool",
        "no tool",
        "capabilities",
        "zugriffsmöglichkeit",
        "zugriffsmoeglichkeit",
        "keine zugriff",
    )
    return any(marker in text for marker in markers)


def is_cron_tool_name(tool_name: str) -> bool:
    name = str(tool_name or "").strip()
    return bool(name) and (name.startswith("autonomy_cron_") or name == "cron_reference_links_list")


def looks_like_spurious_policy_block(verification: Dict[str, Any]) -> bool:
    text = verification_text(verification)
    markers = (
        "safety policy violation",
        "policy violation",
        "request blocked",
        "needs memory but no keys specified",
        "richtlinie",
        "keine direkte tool-abfrage",
        "kein verifizierten tool-nachweis",
        "keinen verifizierten tool-nachweis",
        "tool-nachweis",
        "belastbare faktenantwort",
        "tool-abfrage erneut",
        "cannot execute tools",
        "can't execute tools",
        "kann keine tools ausführen",
        "kann keine tools ausfuehren",
        "ich kann keine tools ausführen",
        "ich kann keine tools ausfuehren",
        "kein ausführbarer tool-plan",
        "kein ausfuehrbarer tool-plan",
    )
    return any(marker in text for marker in markers)


def has_hard_safety_markers(verification: Dict[str, Any]) -> bool:
    text = verification_text(verification)
    markers = (
        "dangerous keyword detected",
        "sensitive content detected",
        "email address detected",
        "phone number detected",
        "pii",
    )
    return any(marker in text for marker in markers)


def warning_list(raw: Any) -> List[str]:
    if isinstance(raw, list):
        return [str(x) for x in raw if str(x).strip()]
    if raw:
        text = str(raw).strip()
        if text:
            return [text]
    return []


def is_light_cim_hard_denial(cim_result: Dict[str, Any]) -> bool:
    if not isinstance(cim_result, dict):
        return False
    checks = cim_result.get("checks", {}) if isinstance(cim_result.get("checks"), dict) else {}
    safety = checks.get("safety", {}) if isinstance(checks.get("safety"), dict) else {}
    if safety.get("safe") is False:
        return True
    warnings = warning_list(cim_result.get("warnings", []))
    text = " ".join(warnings).lower()
    markers = (
        "dangerous keyword detected",
        "sensitive content detected",
        "email address detected",
        "phone number detected",
        "pii",
    )
    return any(marker in text for marker in markers)


def is_runtime_operation_tool(tool_name: str) -> bool:
    name = str(tool_name or "").strip().lower()
    if not name:
        return False
    runtime_tools = {
        "request_container",
        "stop_container",
        "exec_in_container",
        "container_logs",
        "container_stats",
        "container_list",
        "container_inspect",
        "blueprint_list",
        "blueprint_get",
        "blueprint_create",
        "autonomy_cron_status",
        "autonomy_cron_list_jobs",
        "autonomy_cron_validate",
        "autonomy_cron_create_job",
        "autonomy_cron_update_job",
        "autonomy_cron_pause_job",
        "autonomy_cron_resume_job",
        "autonomy_cron_run_now",
        "autonomy_cron_delete_job",
        "autonomy_cron_queue",
        "run_skill",
        "list_skills",
        "get_skill_info",
        "autonomous_skill_task",
        "create_skill",
        "home_read",
        "home_list",
        "get_system_info",
        "get_system_overview",
    }
    if name in runtime_tools:
        return True
    return name.startswith("autonomy_cron_")


def user_text_has_explicit_skill_intent(user_text: str) -> bool:
    text = str(user_text or "").strip().lower()
    if not text:
        return False
    if re.search(r"\b(skill|skills|run_skill|create_skill|autonomous_skill_task)\b", text):
        return True
    if re.search(r"\b(funktion|funktionen)\b", text) and re.search(
        r"\b(erstell|create|programmier|baue|bau)\b",
        text,
    ):
        return True
    return False


def sanitize_warning_messages(warnings: Any) -> List[str]:
    """
    Drop obvious prompt-template/date-artifact warnings while keeping real runtime signals.
    """
    if not isinstance(warnings, list):
        warnings = [warnings] if warnings else []
    cleaned: List[str] = []
    seen = set()
    for raw in warnings:
        text = str(raw or "").strip()
        if not text:
            continue
        low = text.lower()
        if "{today}" in low:
            continue
        if "2023-10-01" in low:
            continue
        if "wissensstand" in low and "2023" in low:
            continue
        if "zeitliche konsistenz" in low and "2023" in low:
            continue
        if low in seen:
            continue
        seen.add(low)
        cleaned.append(text)
    return cleaned
