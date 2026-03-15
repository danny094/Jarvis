"""
Deterministic host-runtime execution helpers.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, List, Sequence


HOST_RUNTIME_PROBE_COMMAND = (
    "sh -lc 'ip=\"\"; ip=$(getent hosts host.docker.internal 2>/dev/null | awk "
    "\"NR==1{print \\$1}\"); [ -z \"$ip\" ] && ip=$(ip route 2>/dev/null | awk "
    "\"/default/ {print \\$3; exit}\"); [ -z \"$ip\" ] && ip=$(hostname -I 2>/dev/null "
    "| awk \"{print \\$1}\"); if [ -n \"$ip\" ]; then echo \"$ip\"; else echo \"IP_NOT_FOUND\"; exit 2; fi'"
)


def build_host_runtime_exec_args(*, container_id: str = "PENDING") -> Dict[str, str]:
    return {
        "container_id": str(container_id or "PENDING"),
        "command": HOST_RUNTIME_PROBE_COMMAND,
    }


def is_host_runtime_probe_command(command: str) -> bool:
    text = str(command or "")
    return ("host.docker.internal" in text) or ("IP_NOT_FOUND" in text)


def coerce_exec_payload(result: Any) -> Dict[str, Any]:
    raw = result.content if hasattr(result, "content") else result
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        if text.startswith("{") and text.endswith("}"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        return {"stdout": text}
    return {}


def build_direct_host_runtime_response(tool_name: str, tool_args: Dict[str, Any], result: Any) -> str:
    if str(tool_name).strip().lower() != "exec_in_container":
        return ""
    command = str((tool_args or {}).get("command") or "")
    if not is_host_runtime_probe_command(command):
        return ""

    payload = coerce_exec_payload(result)
    stdout = str(payload.get("stdout") or "").strip()
    if not stdout or stdout == "IP_NOT_FOUND":
        return ""

    ip = stdout.split()[0]
    return (
        f"Ich habe die aus dem laufenden Container erreichbare Host-Runtime-IP ermittelt: **{ip}**.\n\n"
        "Hinweis: Das ist die Host-/Gateway-Adresse aus Container-Sicht und nicht automatisch eine öffentliche WAN-IP."
    )


def extract_blueprint_id_from_create_result(result: Any) -> str:
    raw = result.content if hasattr(result, "content") else result
    parsed: Any = raw
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = raw

    if not isinstance(parsed, dict):
        return ""

    direct = str(parsed.get("blueprint_id") or parsed.get("id") or "").strip()
    if direct:
        return direct

    nested = parsed.get("blueprint")
    if isinstance(nested, dict):
        nested_id = str(nested.get("id") or nested.get("blueprint_id") or "").strip()
        if nested_id:
            return nested_id

    data = parsed.get("data")
    if isinstance(data, dict):
        data_id = str(data.get("blueprint_id") or data.get("id") or "").strip()
        if data_id:
            return data_id
        nested2 = data.get("blueprint")
        if isinstance(nested2, dict):
            nested2_id = str(nested2.get("id") or nested2.get("blueprint_id") or "").strip()
            if nested2_id:
                return nested2_id

    return ""


def build_host_runtime_blueprint_create_args(
    *,
    user_text: str,
    now_ts: float | None = None,
) -> Dict[str, str]:
    ts = int(now_ts if now_ts is not None else time.time())
    safe_id = f"host-runtime-auto-{ts}"
    return {
        "id": safe_id,
        "name": "Host Runtime Auto Blueprint",
        "image": "python:3.12-slim",
        "description": f"Auto-generated for host runtime lookup: {str(user_text or '').strip()[:180]}",
    }


def build_host_runtime_failure_response(
    *,
    reason: str,
    attempted_blueprint_create: bool,
) -> str:
    detail = str(reason or "").strip() or "unknown"
    attempted = "ja" if attempted_blueprint_create else "nein"
    return (
        "Host-Runtime-IP konnte nicht ermittelt werden.\n"
        f"- Fehlergrund: {detail}\n"
        f"- Fallback blueprint_create versucht: {attempted}\n"
        "Lösungsansatz:\n"
        "1. Prüfe, ob `container_list` mindestens einen laufenden Container liefert.\n"
        "2. Falls nein: bestätige Blueprint-Parameter (Image/Runtime/Netzwerk), damit Start sicher durchläuft.\n"
        "3. Danach erneut Host-Runtime-Query ausführen."
    )


def enforce_host_runtime_exec_first(
    *,
    user_text: str,
    suggested_tools: Sequence[Any],
    looks_like_host_runtime_lookup_fn: Callable[[str], bool],
    extract_tool_name_fn: Callable[[Any], str],
) -> List[Any]:
    if not looks_like_host_runtime_lookup_fn(user_text):
        return list(suggested_tools or [])

    original = list(suggested_tools or [])
    exec_specs: List[Any] = []
    for spec in original:
        if extract_tool_name_fn(spec).strip().lower() == "exec_in_container":
            exec_specs.append(spec)

    if exec_specs:
        return exec_specs
    return ["exec_in_container"]
