from typing import Any, Dict, List, Optional, Sequence


def normalize_container_entries(rows: Any, *, limit: int = 64) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    if not isinstance(rows, list):
        return out
    for item in rows:
        if not isinstance(item, dict):
            continue
        container_id = str(item.get("container_id", "")).strip()
        if not container_id:
            continue
        out.append(
            {
                "container_id": container_id,
                "blueprint_id": str(item.get("blueprint_id", "")).strip(),
                "status": str(item.get("status", "")).strip(),
                "name": str(item.get("name", "")).strip(),
            }
        )
        if len(out) >= limit:
            break
    return out


def merge_container_state_from_tool_result(
    state: Optional[Dict[str, Any]],
    *,
    tool_name: str,
    tool_args: Dict[str, Any],
    result: Any,
    expected_home_blueprint_id: str,
) -> Dict[str, Any]:
    current = state or {}
    known = normalize_container_entries(current.get("known_containers") or [])
    known_by_id = {
        str(r.get("container_id", "")).strip(): r
        for r in known
        if str(r.get("container_id", "")).strip()
    }

    last_active = str(current.get("last_active_container_id", "")).strip()
    home_container_id = str(current.get("home_container_id", "")).strip()

    if tool_name == "container_list" and isinstance(result, dict):
        known_rows = normalize_container_entries(result.get("containers"))
        if known_rows:
            known_by_id = {r["container_id"]: r for r in known_rows}
            for row in known_rows:
                if row.get("status") == "running":
                    last_active = row["container_id"]
                if (
                    row.get("blueprint_id") == expected_home_blueprint_id
                    and row.get("status") == "running"
                ):
                    home_container_id = row["container_id"]
    elif tool_name == "container_inspect" and isinstance(result, dict):
        cid = str(result.get("container_id", "")).strip()
        if cid:
            known_by_id[cid] = {
                "container_id": cid,
                "blueprint_id": str(result.get("blueprint_id", "")).strip(),
                "status": str(result.get("status", "")).strip(),
                "name": str(result.get("name", "")).strip(),
            }
            if str(result.get("running", False)).lower() in {"1", "true"}:
                last_active = cid
            if (
                known_by_id[cid].get("blueprint_id") == expected_home_blueprint_id
                and str(result.get("running", False)).lower() in {"1", "true"}
            ):
                home_container_id = cid
    elif tool_name == "request_container" and isinstance(result, dict):
        cid = str(result.get("container_id", "")).strip()
        if not cid and isinstance(result.get("container"), dict):
            cid = str(result["container"].get("container_id", "")).strip()
        if cid:
            last_active = cid
            bp_id = str(result.get("blueprint_id", "")).strip()
            if not bp_id and isinstance(result.get("container"), dict):
                bp_id = str(result["container"].get("blueprint_id", "")).strip()
            known_by_id[cid] = {
                "container_id": cid,
                "blueprint_id": bp_id,
                "status": "running",
                "name": str(result.get("name", "")).strip(),
            }
            if bp_id == expected_home_blueprint_id:
                home_container_id = cid
    elif tool_name in {"exec_in_container", "container_stats", "container_logs"}:
        cid = str((tool_args or {}).get("container_id", "")).strip()
        if cid:
            last_active = cid
            if cid not in known_by_id:
                known_by_id[cid] = {
                    "container_id": cid,
                    "blueprint_id": "",
                    "status": "running",
                    "name": "",
                }
    elif tool_name == "stop_container" and isinstance(result, dict):
        cid = str(result.get("container_id", "")).strip() or str((tool_args or {}).get("container_id", "")).strip()
        if cid:
            row = known_by_id.get(
                cid,
                {
                    "container_id": cid,
                    "blueprint_id": "",
                    "status": "stopped",
                    "name": "",
                },
            )
            row["status"] = "stopped"
            known_by_id[cid] = row
            if last_active == cid:
                last_active = ""

    known_out = list(known_by_id.values())
    if not home_container_id:
        for row in known_out:
            if (
                row.get("blueprint_id") == expected_home_blueprint_id
                and row.get("status") == "running"
            ):
                home_container_id = row.get("container_id", "")
                break

    return {
        "last_active_container_id": last_active,
        "home_container_id": home_container_id,
        "known_containers": known_out,
    }


def tool_requires_container_id(tool_name: str, required_tools: Sequence[str]) -> bool:
    return str(tool_name or "").strip() in set(required_tools)


def select_preferred_container_id(
    rows: Any,
    *,
    expected_home_blueprint_id: str,
    preferred_ids: Optional[List[str]] = None,
) -> str:
    normalized = normalize_container_entries(rows)
    if not normalized:
        return ""

    preferred: List[str] = []
    for raw in preferred_ids or []:
        cid = str(raw or "").strip()
        if cid and cid not in preferred:
            preferred.append(cid)

    for cid in preferred:
        for row in normalized:
            if row.get("container_id") == cid and str(row.get("status", "")).strip().lower() == "running":
                return cid

    for row in normalized:
        if (
            str(row.get("status", "")).strip().lower() == "running"
            and str(row.get("blueprint_id", "")).strip() == expected_home_blueprint_id
        ):
            return str(row.get("container_id", "")).strip()

    for row in normalized:
        name = str(row.get("name", "")).strip().lower().replace("_", "-")
        if str(row.get("status", "")).strip().lower() == "running" and name in {"trion-home", "trion home"}:
            return str(row.get("container_id", "")).strip()

    for row in normalized:
        if str(row.get("status", "")).strip().lower() == "running":
            return str(row.get("container_id", "")).strip()

    for cid in preferred:
        if any(str(row.get("container_id", "")).strip() == cid for row in normalized):
            return cid

    return str(normalized[0].get("container_id", "")).strip()
