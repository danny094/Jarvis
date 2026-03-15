#!/usr/bin/env python3
"""
Migrate legacy cron jobs away from a shared fallback conversation id.

Default mode is dry-run. Use --apply to execute updates via Admin API.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Dict, List, Tuple

import requests


@dataclass
class MigrationPlanItem:
    job_id: str
    name: str
    objective: str
    source_conversation: str
    target_conversation: str
    job_type: str


def _job_type(name: str, objective: str) -> str:
    blob = f"{name} {objective}".strip().lower()
    if objective.lower().startswith("user_reminder::") or "reminder" in blob or "erinner" in blob:
        return "reminder"
    if "backup" in blob or "archiv" in blob or "sichern" in blob:
        return "backup"
    if "cleanup" in blob or "bereinig" in blob or "status summary" in blob:
        return "maintenance"
    return "default"


def _target_for(job_type: str, mapping: Dict[str, str]) -> str:
    return mapping.get(job_type, mapping["default"])


def _build_plan(jobs: List[Dict], source_conversation: str, mapping: Dict[str, str]) -> List[MigrationPlanItem]:
    out: List[MigrationPlanItem] = []
    for job in jobs:
        src = str(job.get("conversation_id") or "").strip()
        if src != source_conversation:
            continue
        jid = str(job.get("id") or "").strip()
        if not jid:
            continue
        name = str(job.get("name") or "").strip()
        objective = str(job.get("objective") or "").strip()
        jtype = _job_type(name, objective)
        target = _target_for(jtype, mapping).strip()
        if not target or target == src:
            continue
        out.append(
            MigrationPlanItem(
                job_id=jid,
                name=name,
                objective=objective,
                source_conversation=src,
                target_conversation=target,
                job_type=jtype,
            )
        )
    return out


def _print_plan(plan: List[MigrationPlanItem]) -> None:
    print(f"plan_count={len(plan)}")
    for item in plan:
        print(
            json.dumps(
                {
                    "job_id": item.job_id,
                    "job_type": item.job_type,
                    "source_conversation": item.source_conversation,
                    "target_conversation": item.target_conversation,
                    "name": item.name[:120],
                    "objective": item.objective[:220],
                },
                ensure_ascii=False,
            )
        )


def _migrate(base_url: str, plan: List[MigrationPlanItem]) -> Tuple[int, List[Dict]]:
    ok = 0
    errors: List[Dict] = []
    session = requests.Session()
    for item in plan:
        try:
            resp = session.put(
                f"{base_url}/api/autonomy/cron/jobs/{item.job_id}",
                json={"conversation_id": item.target_conversation},
                timeout=20,
            )
        except Exception as exc:  # pragma: no cover - network exceptions
            errors.append({"job_id": item.job_id, "error": str(exc)})
            continue

        if resp.status_code >= 400:
            payload = {}
            try:
                payload = resp.json()
            except Exception:
                payload = {"error": resp.text[:200]}
            errors.append(
                {
                    "job_id": item.job_id,
                    "status_code": resp.status_code,
                    "error": payload.get("error") or payload.get("error_code") or str(payload)[:300],
                }
            )
            continue
        ok += 1
    return ok, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy cron conversations")
    parser.add_argument("--base-url", default="http://127.0.0.1:8200", help="Admin API base URL")
    parser.add_argument("--source", default="webui-default", help="Source conversation_id to migrate from")
    parser.add_argument("--target-reminder", default="autonomy-reminders", help="Target for reminder-like jobs")
    parser.add_argument("--target-maintenance", default="autonomy-maintenance", help="Target for maintenance jobs")
    parser.add_argument("--target-backup", default="autonomy-backups", help="Target for backup jobs")
    parser.add_argument("--target-default", default="autonomy-legacy", help="Target for uncategorized jobs")
    parser.add_argument("--apply", action="store_true", help="Execute migration (default: dry-run)")
    args = parser.parse_args()

    mapping = {
        "reminder": str(args.target_reminder).strip(),
        "maintenance": str(args.target_maintenance).strip(),
        "backup": str(args.target_backup).strip(),
        "default": str(args.target_default).strip(),
    }
    if not all(mapping.values()):
        print("error=all target conversation ids must be non-empty", file=sys.stderr)
        return 2

    resp = requests.get(f"{args.base_url}/api/autonomy/cron/jobs", timeout=20)
    resp.raise_for_status()
    jobs = (resp.json() or {}).get("jobs") or []
    if not isinstance(jobs, list):
        print("error=invalid jobs payload", file=sys.stderr)
        return 2

    plan = _build_plan(jobs, str(args.source).strip(), mapping)
    _print_plan(plan)
    if not args.apply:
        print("mode=dry_run")
        return 0

    ok, errors = _migrate(args.base_url, plan)
    print(f"applied={ok}")
    if errors:
        print("errors=" + json.dumps(errors, ensure_ascii=False))
        return 1
    print("errors=[]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
