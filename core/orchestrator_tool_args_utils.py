import re
import time
from typing import Any, Callable, Dict, Optional

from core.host_runtime_policy import build_host_runtime_exec_args


def build_tool_args(
    tool_name: str,
    user_text: str,
    verified_plan: Optional[Dict[str, Any]] = None,
    *,
    extract_requested_skill_name_fn: Callable[[str], str],
    looks_like_host_runtime_lookup_fn: Callable[[str], bool],
    extract_cron_schedule_from_text_fn: Callable[[str, Optional[Dict[str, Any]]], Dict[str, str]],
    build_cron_objective_fn: Callable[[str], str],
    build_cron_name_fn: Callable[[str], str],
    extract_cron_job_id_from_text_fn: Callable[[str, Optional[Dict[str, Any]]], str],
    extract_cron_expression_from_text_fn: Callable[[str, Optional[Dict[str, Any]]], str],
    now_ts_fn: Callable[[], float] = time.time,
    strftime_fn: Callable[[str], str] = time.strftime,
) -> dict:
    # Skill Tools
    if tool_name == "run_skill":
        skill_name = extract_requested_skill_name_fn(user_text)
        args = {"action": "run", "args": {}}
        if skill_name:
            args["name"] = skill_name
        return args
    elif tool_name == "get_skill_info":
        return {"skill_name": user_text.strip()}
    elif tool_name == "create_skill":
        raw = (user_text or "").strip().lower()
        name = "".join(ch if (ord(ch) < 128 and ch.isalnum()) else "_" for ch in raw).strip("_")
        if not name:
            name = f"auto_skill_{int(now_ts_fn())}"
        if len(name) > 48:
            name = name[:48].rstrip("_")
        desc = f"Auto-generated skill scaffold from request: {(user_text or '').strip()[:240]}"
        code = (
            "def main(args=None):\n"
            "    \"\"\"Auto-generated fallback scaffold.\"\"\"\n"
            "    args = args or {}\n"
            "    return {\n"
            f"        \"skill\": \"{name}\",\n"
            "        \"status\": \"todo\",\n"
            "        \"message\": \"Scaffold created via fallback. Implement logic.\",\n"
            "        \"args\": args,\n"
            "    }\n"
        )
        return {
            "name": name,
            "description": desc,
            "code": code,
        }
    elif tool_name == "autonomous_skill_task":
        return {
            "user_text": user_text.strip(),
            "intent": user_text.strip(),
            "allow_auto_create": True,
            "execute_after_create": True,
        }
    # Memory Tools
    elif tool_name == "think":
        return {"message": user_text.strip(), "steps": 4}
    elif tool_name in ("memory_search", "memory_graph_search"):
        return {"query": user_text.strip()}
    elif tool_name == "analyze":
        return {"query": user_text.strip()}
    elif tool_name in ("memory_save", "memory_fact_save"):
        vp = verified_plan or {}
        fact_key = str(vp.get("new_fact_key") or "").strip()
        if fact_key and vp.get("is_new_fact"):
            content = f"[{fact_key}]: {user_text.strip()}"
        else:
            content = user_text.strip()
        return {"conversation_id": "auto", "role": "user", "content": content}
    # Container Tools
    elif tool_name == "request_container":
        lower = str(user_text or "").lower()
        if any(tok in lower for tok in ("steam-headless", "sunshine", "gaming station", "gaming-station", "zocken", "moonlight")):
            return {"blueprint_id": "gaming-station"}
        return {"blueprint_id": "python-sandbox"}
    elif tool_name == "exec_in_container":
        if looks_like_host_runtime_lookup_fn(user_text):
            return build_host_runtime_exec_args(container_id="PENDING")
        return {"container_id": "PENDING", "command": "echo 'Container ready'"}
    elif tool_name in ("stop_container", "container_stats"):
        return {"container_id": "PENDING"}
    elif tool_name == "container_logs":
        return {"container_id": "PENDING", "tail": 50}
    elif tool_name == "container_list":
        return {}
    elif tool_name == "container_inspect":
        return {"container_id": "PENDING"}
    elif tool_name == "blueprint_list":
        return {}
    elif tool_name == "blueprint_create":
        lower = str(user_text or "").lower()
        if any(tok in lower for tok in ("steam-headless", "sunshine", "gaming station", "gaming-station", "moonlight")):
            return {
                "id": "gaming-station",
                "name": "Gaming Station (Steam Headless + Sunshine)",
                "image": "josh5/steam-headless:latest",
                "description": "GPU gaming container with Sunshine streaming and Steam support.",
                "network": "full",
                "runtime": "nvidia",
                "ports": [
                    "47984:47984/tcp",
                    "47989:47989/tcp",
                    "48010:48010/tcp",
                    "48100-48110:48100-48110/udp",
                ],
                "environment": {
                    "TZ": "UTC",
                    "PUID": "1000",
                    "PGID": "1000",
                    "STEAM_USER": "vault://STEAM_USERNAME",
                    "STEAM_PASS": "vault://STEAM_PASSWORD",
                },
                "memory_limit": "8g",
                "cpu_limit": "4.0",
                "tags": ["gaming", "steam", "sunshine", "gpu", "nvidia"],
            }
        return {
            "id": f"user-blueprint-{int(now_ts_fn())}",
            "name": "User Blueprint",
            "image": "python:3.12-slim",
            "description": user_text.strip()[:240],
        }
    # Storage Broker Tools
    elif tool_name in {"storage_list_disks", "storage_list_mounts", "storage_get_summary", "storage_get_policy", "storage_list_blocked_paths", "storage_list_managed_paths"}:
        return {}
    elif tool_name == "storage_get_disk":
        text = str(user_text or "")
        m = re.search(r"\b((?:sd[a-z]|vd[a-z]|xvd[a-z])(?:\d+)?|nvme\d+n\d+(?:p\d+)?|mmcblk\d+(?:p\d+)?)\b", text.lower())
        disk_id = m.group(1) if m else ""
        return {"disk_id": disk_id} if disk_id else {}
    elif tool_name in {"storage_set_disk_zone", "storage_set_disk_policy"}:
        text = str(user_text or "").lower()
        m = re.search(r"\b((?:sd[a-z]|vd[a-z]|xvd[a-z])(?:\d+)?|nvme\d+n\d+(?:p\d+)?|mmcblk\d+(?:p\d+)?)\b", text)
        disk_id = m.group(1) if m else ""
        if tool_name == "storage_set_disk_zone":
            zone = ""
            for candidate in ("managed_services", "backup", "external", "docker_runtime", "system", "unzoned"):
                if candidate in text:
                    zone = candidate
                    break
            return {"disk_id": disk_id, "zone": zone} if (disk_id and zone) else {}
        policy_state = ""
        for candidate in ("managed_rw", "read_only", "blocked"):
            if candidate in text:
                policy_state = candidate
                break
        return {"disk_id": disk_id, "policy_state": policy_state} if (disk_id and policy_state) else {}
    elif tool_name == "storage_validate_path":
        m = re.search(r"(/[A-Za-z0-9._\\-/]+)", str(user_text or ""))
        return {"path": m.group(1)} if m else {}
    elif tool_name == "storage_create_service_dir":
        text = str(user_text or "")
        raw_name = re.sub(r"[^a-zA-Z0-9_-]+", "-", text.strip().lower()).strip("-")
        service_name = (raw_name or f"service-{int(now_ts_fn())}")[:64]
        zone = "managed_services"
        lower = text.lower()
        if "backup" in lower:
            zone = "backup"
        elif "external" in lower:
            zone = "external"
        return {"service_name": service_name, "zone": zone, "dry_run": True}
    elif tool_name == "storage_audit_log":
        return {"limit": 50}
    # Cron Tools
    elif tool_name == "autonomy_cron_create_job":
        schedule = extract_cron_schedule_from_text_fn(user_text, verified_plan)
        schedule_mode = str(schedule.get("schedule_mode", "recurring")).strip().lower() or "recurring"
        objective = build_cron_objective_fn(user_text)
        direct_one_shot_objective = str(objective).startswith(("user_reminder::", "self_state_report::"))
        return {
            "name": build_cron_name_fn(user_text),
            "objective": objective,
            "conversation_id": "",
            "cron": schedule.get("cron", "*/15 * * * *"),
            "schedule_mode": schedule_mode,
            "run_at": schedule.get("run_at", ""),
            "timezone": "UTC",
            "max_loops": 1 if (schedule_mode == "one_shot" and direct_one_shot_objective) else (4 if schedule_mode == "one_shot" else 6),
            "created_by": "user",
            "enabled": True,
            "user_approved": False,
        }
    elif tool_name == "autonomy_cron_update_job":
        cron_job_id = extract_cron_job_id_from_text_fn(user_text, verified_plan)
        if not cron_job_id:
            return {}
        schedule = extract_cron_schedule_from_text_fn(user_text, verified_plan)
        return {
            "cron_job_id": cron_job_id,
            "cron": schedule.get("cron", "*/15 * * * *"),
            "schedule_mode": schedule.get("schedule_mode", "recurring"),
            "run_at": schedule.get("run_at", ""),
        }
    elif tool_name in {"autonomy_cron_run_now", "autonomy_cron_delete_job", "autonomy_cron_pause_job", "autonomy_cron_resume_job"}:
        cron_job_id = extract_cron_job_id_from_text_fn(user_text, verified_plan)
        return {"cron_job_id": cron_job_id} if cron_job_id else {}
    elif tool_name == "autonomy_cron_validate":
        return {"cron": extract_cron_expression_from_text_fn(user_text, verified_plan)}
    elif tool_name in {"autonomy_cron_status", "autonomy_cron_list_jobs", "autonomy_cron_queue", "cron_reference_links_list"}:
        return {}
    # SysInfo Tools
    elif tool_name == "get_system_info":
        return {"type": "gpu"}
    elif tool_name == "get_system_overview":
        return {}
    # Home Tools
    elif tool_name == "home_read":
        return {"path": "."}
    elif tool_name == "home_list":
        return {"path": "."}
    elif tool_name == "home_write":
        return {"path": f"notes/note_{strftime_fn('%Y-%m-%d_%H-%M-%S')}.md", "content": user_text.strip()}
    return {}
