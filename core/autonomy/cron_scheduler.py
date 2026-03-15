"""
Autonomy Cron Scheduler

Simple in-process cron runner that dispatches autonomous objectives into
the existing /api/autonomous/jobs queue.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, FrozenSet, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

from utils.logger import log_info, log_warning, log_error


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    if dt is None:
        dt = _utcnow()
    return dt.astimezone(timezone.utc).isoformat()


class CronParseError(ValueError):
    pass


class CronPolicyError(ValueError):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        status_code: int = 409,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.error_code = str(error_code or "cron_policy_violation")
        self.status_code = int(status_code)
        self.details = details or {}


_TRION_OBJECTIVE_ALLOWED_HINTS = (
    "status",
    "health",
    "summary",
    "digest",
    "report",
    "sync",
    "cleanup",
    "maint",
    "monitor",
    "backup",
    "index",
    "archive",
    "memory",
    "recall",
    "plan",
    "review",
    "check",
)

_TRION_OBJECTIVE_RISKY_HINTS = (
    "delete",
    "drop",
    "truncate",
    "remove",
    "destroy",
    "wipe",
    "shutdown",
    "reboot",
    "restart",
    "kill",
    "secret",
    "password",
    "token",
    "api key",
    "credential",
    "docker",
    "network",
    "firewall",
    "sudo",
    "chmod",
    "chown",
    "rm -rf",
)

# Context whitelist: if the objective contains both a risky keyword AND one of its
# pre-approving context hints, that risky keyword is treated as expected/safe.
# Example: "delete old log files" contains "delete" + "cleanup" → no approval needed.
# Truly dangerous keywords (wipe, truncate, drop, sudo, chmod, chown, secret, password,
# token, credential) are NOT in this map and always require explicit user_approved=true.
_TRION_RISKY_CONTEXT_APPROVED: Dict[str, FrozenSet[str]] = {
    "delete":   frozenset({"cleanup", "maint", "archive", "backup", "index", "digest"}),
    "remove":   frozenset({"cleanup", "maint", "archive", "backup"}),
    "restart":  frozenset({"health", "monitor", "maint", "check", "status"}),
    "kill":     frozenset({"health", "monitor", "maint", "check", "status"}),
    "docker":   frozenset({"status", "health", "monitor", "cleanup", "backup", "maint", "check", "sync"}),
    "network":  frozenset({"status", "health", "monitor", "check", "report"}),
    "shutdown": frozenset({"maint", "backup", "plan"}),
    "reboot":   frozenset({"maint", "health", "check", "plan"}),
    "firewall": frozenset({"status", "health", "monitor", "check", "report"}),
}

_TRION_OBJECTIVE_HARD_BLOCK_HINTS = (
    "rm -rf",
    "mkfs",
    "dd if=",
    "poweroff",
    ":(){:|:&};:",
)


def _collect_keyword_hits(text: str, keywords: Tuple[str, ...]) -> List[str]:
    raw = str(text or "").lower()
    hits: List[str] = []
    for key in keywords:
        token = str(key or "").strip().lower()
        if not token:
            continue
        if " " in token or "-" in token or "/" in token:
            if token in raw:
                hits.append(token)
            continue
        if re.search(rf"\b{re.escape(token)}\b", raw):
            hits.append(token)
    # preserve order, remove duplicates
    return list(dict.fromkeys(hits))


def _normalize_reference_links(raw: Any, *, max_items: int = 12) -> List[Dict[str, Any]]:
    rows = raw if isinstance(raw, list) else []
    out: List[Dict[str, Any]] = []
    seen_urls: Set[str] = set()

    for entry in rows:
        item = entry if isinstance(entry, dict) else {}
        name = str(item.get("name", "")).strip()
        url = str(item.get("url", "")).strip()
        if not name or not url:
            continue
        key = url.lower()
        if key in seen_urls:
            continue
        seen_urls.add(key)
        out.append(
            {
                "name": name[:120],
                "url": url[:500],
                "description": str(item.get("description", "")).strip()[:300],
                "read_only": True,
            }
        )
        if len(out) >= max(1, int(max_items)):
            break
    return out


def _build_default_job_note_md(job: Dict[str, Any]) -> str:
    data = job if isinstance(job, dict) else {}
    name = str(data.get("name", "")).strip() or "cron-job"
    objective = str(data.get("objective", "")).strip() or "No objective provided."
    schedule_mode = str(data.get("schedule_mode", "recurring")).strip().lower() or "recurring"
    timezone_name = str(data.get("timezone", "UTC")).strip() or "UTC"
    created_by = str(data.get("created_by", "user")).strip() or "user"
    conversation_id = str(data.get("conversation_id", "")).strip() or "-"
    try:
        max_loops = int(data.get("max_loops", 1) or 1)
    except Exception:
        max_loops = 1

    lines = [
        f"# Cron Job: {name}",
        "",
        "## Objective",
        objective[:1000],
        "",
        "## Schedule",
        f"- Mode: `{schedule_mode}`",
    ]
    if schedule_mode == "one_shot":
        run_at = str(data.get("run_at", "")).strip() or "-"
        lines.append(f"- Run at (UTC): `{run_at}`")
    else:
        cron_expr = str(data.get("cron", "")).strip() or "-"
        lines.append(f"- Cron: `{cron_expr}`")
    lines.extend(
        [
            f"- Timezone: `{timezone_name}`",
            "",
            "## Runtime",
            f"- Created by: `{created_by}`",
            f"- Conversation: `{conversation_id}`",
            f"- Max loops: `{max_loops}`",
        ]
    )
    return "\n".join(lines).strip()[:6000]


@dataclass
class _CronField:
    values: Set[int]
    any: bool


def _parse_int(token: str, lo: int, hi: int, label: str) -> int:
    try:
        value = int(token)
    except Exception as exc:
        raise CronParseError(f"{label}: invalid int '{token}'") from exc
    if value < lo or value > hi:
        raise CronParseError(f"{label}: {value} out of range [{lo},{hi}]")
    return value


def _expand_segment(segment: str, lo: int, hi: int, label: str) -> Set[int]:
    seg = segment.strip()
    if not seg:
        raise CronParseError(f"{label}: empty segment")

    if "/" in seg:
        base, step_raw = seg.split("/", 1)
        step = _parse_int(step_raw, 1, hi - lo + 1, f"{label} step")
    else:
        base, step = seg, 1

    if base == "*" or not base:
        start, end = lo, hi
    elif "-" in base:
        a, b = base.split("-", 1)
        start = _parse_int(a, lo, hi, f"{label} start")
        end = _parse_int(b, lo, hi, f"{label} end")
        if end < start:
            raise CronParseError(f"{label}: range end < start")
    else:
        value = _parse_int(base, lo, hi, label)
        start, end = value, value

    return set(range(start, end + 1, step))


def _parse_field(raw: str, lo: int, hi: int, label: str, normalize_7_to_0: bool = False) -> _CronField:
    token = str(raw or "").strip()
    if token == "*":
        return _CronField(values=set(range(lo, hi + 1)), any=True)

    values: Set[int] = set()
    for part in token.split(","):
        expanded = _expand_segment(part, lo, hi, label)
        if normalize_7_to_0:
            expanded = {0 if x == 7 else x for x in expanded}
        values.update(expanded)

    if not values:
        raise CronParseError(f"{label}: no values parsed")
    return _CronField(values=values, any=False)


def parse_cron_expression(expr: str) -> Dict[str, Any]:
    parts = str(expr or "").strip().split()
    if len(parts) != 5:
        raise CronParseError("cron expression must have 5 fields: min hour dom month dow")

    minute = _parse_field(parts[0], 0, 59, "minute")
    hour = _parse_field(parts[1], 0, 23, "hour")
    dom = _parse_field(parts[2], 1, 31, "day_of_month")
    month = _parse_field(parts[3], 1, 12, "month")
    dow = _parse_field(parts[4], 0, 7, "day_of_week", normalize_7_to_0=True)

    return {
        "expr": " ".join(parts),
        "minute": minute,
        "hour": hour,
        "day_of_month": dom,
        "month": month,
        "day_of_week": dow,
    }


def cron_matches(parsed: Dict[str, Any], local_dt: datetime) -> bool:
    minute = parsed["minute"]
    hour = parsed["hour"]
    dom = parsed["day_of_month"]
    month = parsed["month"]
    dow = parsed["day_of_week"]

    if local_dt.minute not in minute.values:
        return False
    if local_dt.hour not in hour.values:
        return False
    if local_dt.month not in month.values:
        return False

    dom_match = local_dt.day in dom.values
    cron_dow = (local_dt.weekday() + 1) % 7  # 0=sunday
    dow_match = cron_dow in dow.values

    if dom.any and dow.any:
        return True
    if dom.any:
        return dow_match
    if dow.any:
        return dom_match
    return dom_match or dow_match


def next_matching_utc(
    parsed: Dict[str, Any],
    timezone_name: str,
    from_utc: Optional[datetime] = None,
    max_days: int = 35,
) -> str:
    now_utc = from_utc or _utcnow()
    tz = ZoneInfo(timezone_name)
    local = now_utc.astimezone(tz).replace(second=0, microsecond=0)
    max_minutes = max_days * 24 * 60

    for i in range(1, max_minutes + 1):
        candidate = local + timedelta(minutes=i)
        if cron_matches(parsed, candidate):
            return _iso(candidate.astimezone(timezone.utc))
    return ""


def validate_cron_expression(expr: str) -> Dict[str, Any]:
    parsed = parse_cron_expression(expr)
    return {"valid": True, "normalized": parsed["expr"]}


def estimate_min_interval_seconds(
    parsed: Dict[str, Any],
    *,
    max_days: int = 35,
    max_hits: int = 40,
) -> int:
    """
    Best-effort lower bound of schedule interval by minute-scan.
    Returns a large value when no second hit is found in scan window.
    """
    base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    max_minutes = max_days * 24 * 60
    prev: Optional[datetime] = None
    min_delta: Optional[int] = None
    hits = 0

    for i in range(max_minutes + 1):
        candidate = base + timedelta(minutes=i)
        if not cron_matches(parsed, candidate):
            continue
        hits += 1
        if prev is not None:
            delta = max(60, int((candidate - prev).total_seconds()))
            min_delta = delta if min_delta is None else min(min_delta, delta)
            if min_delta <= 60:
                break
        prev = candidate
        if hits >= max_hits and min_delta is not None:
            break

    return min_delta if min_delta is not None else (366 * 24 * 60 * 60)


def _parse_iso_datetime(raw: str) -> Optional[datetime]:
    txt = str(raw or "").strip()
    if not txt:
        return None
    try:
        dt = datetime.fromisoformat(txt.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _read_host_memory_used_percent() -> Optional[float]:
    """
    Read host memory usage via /proc/meminfo.
    Returns None when unavailable (non-Linux or parse failure).
    """
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            total_kb: Optional[float] = None
            available_kb: Optional[float] = None
            for line in f:
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        total_kb = float(parts[1])
                elif line.startswith("MemAvailable:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        available_kb = float(parts[1])
                if total_kb is not None and available_kb is not None:
                    break
        if total_kb is None or total_kb <= 0 or available_kb is None:
            return None
        used_kb = max(0.0, total_kb - max(0.0, available_kb))
        return max(0.0, min(100.0, (used_kb / total_kb) * 100.0))
    except Exception:
        return None


def _read_host_cpu_load_percent() -> Optional[float]:
    """
    Approximate CPU pressure from 1m load average normalized by CPU count.
    Returns None when load metrics are unavailable.
    """
    try:
        load_1m = float(os.getloadavg()[0])
        cpu_count = max(1, int(os.cpu_count() or 1))
        percent = (load_1m / float(cpu_count)) * 100.0
        return max(0.0, percent)
    except Exception:
        return None


class AutonomyCronScheduler:
    def __init__(
        self,
        state_path: str,
        tick_s: int,
        max_concurrency: int,
        submit_cb: Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[Dict[str, Any]]],
        *,
        max_jobs: int = 200,
        max_jobs_per_conversation: int = 30,
        min_interval_s: int = 300,
        max_pending_runs: int = 500,
        max_pending_runs_per_job: int = 2,
        manual_run_cooldown_s: int = 30,
        trion_safe_mode: bool = True,
        trion_min_interval_s: int = 900,
        trion_max_loops: int = 12,
        trion_require_approval_for_risky: bool = True,
        hardware_guard_enabled: bool = True,
        hardware_cpu_max_percent: int = 90,
        hardware_mem_max_percent: int = 92,
        hardware_probe_cb: Optional[Callable[[], Dict[str, Any]]] = None,
    ):
        self._state_path = str(state_path or "").strip()
        self._tick_s = max(5, int(tick_s))
        self._max_concurrency = max(1, int(max_concurrency))
        self._submit_cb = submit_cb
        self._max_jobs = max(1, int(max_jobs))
        self._max_jobs_per_conversation = max(1, int(max_jobs_per_conversation))
        self._min_interval_s = max(60, int(min_interval_s))
        self._max_pending_runs = max(1, int(max_pending_runs))
        self._max_pending_runs_per_job = max(1, int(max_pending_runs_per_job))
        self._manual_run_cooldown_s = max(0, int(manual_run_cooldown_s))
        self._trion_safe_mode = bool(trion_safe_mode)
        self._trion_min_interval_s = max(60, int(trion_min_interval_s))
        self._trion_max_loops = max(1, int(trion_max_loops))
        self._trion_require_approval_for_risky = bool(trion_require_approval_for_risky)
        self._hardware_guard_enabled = bool(hardware_guard_enabled)
        self._hardware_cpu_max_percent = max(50, min(99, int(hardware_cpu_max_percent)))
        self._hardware_mem_max_percent = max(50, min(99, int(hardware_mem_max_percent)))
        self._hardware_probe_cb = hardware_probe_cb

        self._lock = asyncio.Lock()
        self._queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._pending: List[Dict[str, Any]] = []
        self._running: Dict[str, Dict[str, Any]] = {}
        self._history: List[Dict[str, Any]] = []
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._expr_cache: Dict[str, Dict[str, Any]] = {}

        self._tick_task: Optional[asyncio.Task] = None
        self._workers: List[asyncio.Task] = []
        self._stopping = False

    async def start(self) -> None:
        async with self._lock:
            self._load_state_locked()
            if self._tick_task and not self._tick_task.done():
                return
            self._stopping = False
            self._tick_task = asyncio.create_task(self._tick_loop(), name="autonomy-cron-tick")
            self._workers = [
                asyncio.create_task(self._dispatch_worker(i), name=f"autonomy-cron-worker-{i}")
                for i in range(self._max_concurrency)
            ]
        log_info(
            f"[AutonomyCron] started tick={self._tick_s}s workers={self._max_concurrency} path={self._state_path}"
        )

    async def stop(self) -> None:
        async with self._lock:
            self._stopping = True
            tasks = [t for t in [self._tick_task, *self._workers] if t]
            self._tick_task = None
            self._workers = []
        for task in tasks:
            if task and not task.done():
                task.cancel()
        for task in tasks:
            if not task:
                continue
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        log_info("[AutonomyCron] stopped")

    def _ensure_parent_dir(self) -> None:
        parent = os.path.dirname(self._state_path) or "."
        os.makedirs(parent, exist_ok=True)

    def _save_state_locked(self) -> None:
        if not self._state_path:
            return
        self._ensure_parent_dir()
        data = {
            "version": 1,
            "updated_at": _iso(),
            "jobs": list(self._jobs.values()),
            "history": self._history[-200:],
        }
        tmp = f"{self._state_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self._state_path)

    def _load_state_locked(self) -> None:
        self._jobs = {}
        self._history = []
        self._pending = []
        self._running = {}
        if not self._state_path or not os.path.exists(self._state_path):
            return
        try:
            with open(self._state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for job in (data.get("jobs") or []):
                if not isinstance(job, dict):
                    continue
                job_id = str(job.get("id") or "").strip()
                if not job_id:
                    continue
                self._jobs[job_id] = job
            hist = data.get("history") or []
            if isinstance(hist, list):
                self._history = [x for x in hist if isinstance(x, dict)][-200:]
        except Exception as exc:
            log_warning(f"[AutonomyCron] failed to load state: {exc}")

    def _parsed_expr(self, expr: str) -> Dict[str, Any]:
        key = str(expr or "").strip()
        cached = self._expr_cache.get(key)
        if cached:
            return cached
        parsed = parse_cron_expression(key)
        self._expr_cache[key] = parsed
        return parsed

    @staticmethod
    def _is_one_shot_mode(job: Dict[str, Any]) -> bool:
        return str((job or {}).get("schedule_mode", "recurring")).strip().lower() == "one_shot"

    @staticmethod
    def _is_one_shot_consumed(job: Dict[str, Any]) -> bool:
        marker = str((job or {}).get("last_trigger_key", "") or "")
        return marker.startswith("one_shot:")

    def _next_run_iso(self, job: Dict[str, Any]) -> str:
        try:
            if self._is_one_shot_mode(job):
                run_at = _parse_iso_datetime(str(job.get("run_at", "")))
                if run_at is None:
                    return ""
                if self._is_one_shot_consumed(job):
                    return ""
                return _iso(run_at)
            parsed = self._parsed_expr(str(job.get("cron", "")))
            return next_matching_utc(parsed, str(job.get("timezone", "UTC")))
        except Exception:
            return ""

    async def list_jobs(self) -> List[Dict[str, Any]]:
        async with self._lock:
            out = []
            for job in self._jobs.values():
                entry = dict(job)
                entry["next_run_at"] = self._next_run_iso(job) if bool(job.get("enabled", True)) else ""
                entry["runtime_state"] = self._runtime_state_for_job_locked(str(job.get("id", "")))
                out.append(entry)
            out.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            return out

    async def get_job(self, cron_job_id: str) -> Optional[Dict[str, Any]]:
        job_id = str(cron_job_id or "").strip()
        if not job_id:
            return None
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            out = dict(job)
            out["next_run_at"] = self._next_run_iso(job) if bool(job.get("enabled", True)) else ""
            out["runtime_state"] = self._runtime_state_for_job_locked(job_id)
            return out

    def _runtime_state_for_job_locked(self, cron_job_id: str) -> str:
        if any(x.get("cron_job_id") == cron_job_id for x in self._running.values()):
            return "running"
        if any(x.get("cron_job_id") == cron_job_id for x in self._pending):
            return "queued"
        job = self._jobs.get(cron_job_id) or {}
        if self._is_one_shot_mode(job) and self._is_one_shot_consumed(job):
            return "completed"
        return "active" if bool(job.get("enabled", False)) else "paused"

    def _count_jobs_for_conversation_locked(self, conversation_id: str, exclude_job_id: str = "") -> int:
        conv = str(conversation_id or "").strip()
        exclude = str(exclude_job_id or "").strip()
        return sum(
            1
            for jid, j in self._jobs.items()
            if jid != exclude and str(j.get("conversation_id", "")).strip() == conv
        )

    def _count_runs_for_job_locked(self, cron_job_id: str) -> int:
        job_id = str(cron_job_id or "").strip()
        if not job_id:
            return 0
        pending = sum(1 for x in self._pending if str(x.get("cron_job_id", "")) == job_id)
        running = sum(1 for x in self._running.values() if str(x.get("cron_job_id", "")) == job_id)
        return pending + running

    def _policy_snapshot_locked(self) -> Dict[str, Any]:
        return {
            "max_jobs": self._max_jobs,
            "max_jobs_per_conversation": self._max_jobs_per_conversation,
            "min_interval_s": self._min_interval_s,
            "max_pending_runs": self._max_pending_runs,
            "max_pending_runs_per_job": self._max_pending_runs_per_job,
            "manual_run_cooldown_s": self._manual_run_cooldown_s,
            "trion_safe_mode": self._trion_safe_mode,
            "trion_min_interval_s": self._trion_min_interval_s,
            "trion_max_loops": self._trion_max_loops,
            "trion_require_approval_for_risky": self._trion_require_approval_for_risky,
            "hardware_guard_enabled": self._hardware_guard_enabled,
            "hardware_cpu_max_percent": self._hardware_cpu_max_percent,
            "hardware_mem_max_percent": self._hardware_mem_max_percent,
        }

    def _get_hardware_snapshot(self) -> Dict[str, Any]:
        if callable(self._hardware_probe_cb):
            try:
                snapshot = self._hardware_probe_cb() or {}
            except Exception as exc:
                return {
                    "cpu_percent": None,
                    "memory_percent": None,
                    "probe_error": f"probe_failed:{exc}",
                }
            cpu_raw = snapshot.get("cpu_percent")
            mem_raw = snapshot.get("memory_percent")
            cpu = float(cpu_raw) if isinstance(cpu_raw, (int, float)) else None
            mem = float(mem_raw) if isinstance(mem_raw, (int, float)) else None
            return {
                "cpu_percent": cpu,
                "memory_percent": mem,
                "probe_error": "",
            }
        return {
            "cpu_percent": _read_host_cpu_load_percent(),
            "memory_percent": _read_host_memory_used_percent(),
            "probe_error": "",
        }

    def _evaluate_hardware_guard(self) -> Tuple[bool, str, Dict[str, Any]]:
        snapshot = self._get_hardware_snapshot()
        cpu = snapshot.get("cpu_percent")
        mem = snapshot.get("memory_percent")
        reason = ""

        if not self._hardware_guard_enabled:
            snapshot["guard_enabled"] = False
            return True, "", snapshot

        if isinstance(cpu, (int, float)) and float(cpu) >= float(self._hardware_cpu_max_percent):
            reason = (
                f"cpu_over_limit:{float(cpu):.1f}>={self._hardware_cpu_max_percent}"
            )
        elif isinstance(mem, (int, float)) and float(mem) >= float(self._hardware_mem_max_percent):
            reason = (
                f"mem_over_limit:{float(mem):.1f}>={self._hardware_mem_max_percent}"
            )

        snapshot.update(
            {
                "guard_enabled": True,
                "cpu_limit_percent": self._hardware_cpu_max_percent,
                "mem_limit_percent": self._hardware_mem_max_percent,
            }
        )
        return reason == "", reason, snapshot

    def _enforce_trion_policy_locked(
        self,
        normalized: Dict[str, Any],
        existing_job: Dict[str, Any],
        *,
        creating: bool,
        min_interval_s: Optional[int],
        schedule_mode: str = "recurring",
    ) -> None:
        actor = str(
            normalized.get("created_by")
            if "created_by" in normalized
            else existing_job.get("created_by", "user")
        ).strip().lower()
        if actor != "trion" or not self._trion_safe_mode:
            return

        objective = str(
            normalized.get("objective")
            if "objective" in normalized
            else existing_job.get("objective", "")
        ).strip()
        if not objective:
            raise CronPolicyError(
                "cron_trion_objective_required",
                "trion cron objective is required",
                status_code=400,
            )

        hard_hits = _collect_keyword_hits(objective, _TRION_OBJECTIVE_HARD_BLOCK_HINTS)
        if hard_hits:
            raise CronPolicyError(
                "cron_trion_objective_forbidden",
                "trion objective contains forbidden action pattern",
                status_code=403,
                details={"forbidden_keywords": hard_hits},
            )

        allow_hits = _collect_keyword_hits(objective, _TRION_OBJECTIVE_ALLOWED_HINTS)
        if not allow_hits:
            raise CronPolicyError(
                "cron_trion_objective_not_allowed",
                "trion objective does not match allowed automation categories",
                status_code=409,
                details={"required_any_of": list(_TRION_OBJECTIVE_ALLOWED_HINTS)},
            )

        max_loops = int(
            normalized.get("max_loops")
            if "max_loops" in normalized
            else existing_job.get("max_loops", 10)
        )
        if max_loops > self._trion_max_loops:
            raise CronPolicyError(
                "cron_trion_max_loops_violation",
                f"trion max_loops {max_loops} exceeds policy limit {self._trion_max_loops}",
                status_code=409,
                details={"max_loops": max_loops, "trion_max_loops": self._trion_max_loops},
            )

        if schedule_mode != "one_shot":
            interval_s = min_interval_s
            if interval_s is None:
                cron_expr = str(
                    normalized.get("cron")
                    if "cron" in normalized
                    else existing_job.get("cron", "")
                ).strip()
                if cron_expr:
                    interval_s = estimate_min_interval_seconds(self._parsed_expr(cron_expr))
            if interval_s is not None and interval_s < self._trion_min_interval_s:
                raise CronPolicyError(
                    "cron_trion_min_interval_violation",
                    f"trion cron interval {interval_s}s is below trion minimum {self._trion_min_interval_s}s",
                    status_code=409,
                    details={"interval_s": interval_s, "trion_min_interval_s": self._trion_min_interval_s},
                )

        if not self._trion_require_approval_for_risky:
            return
        risky_hits = _collect_keyword_hits(objective, _TRION_OBJECTIVE_RISKY_HINTS)
        approved = bool(
            normalized.get("user_approved")
            if "user_approved" in normalized
            else existing_job.get("user_approved", False)
        )
        # Context-aware approval: filter out risky keywords that are pre-approved by
        # a semantically compatible allowed hint in the same objective.
        # E.g. "delete" + "cleanup" is expected and doesn't need extra approval.
        # Truly dangerous keywords (wipe, truncate, drop, sudo, chmod, chown,
        # secret, password, token, credential) are never context-approved.
        if risky_hits and not approved:
            allow_hits_set = set(_collect_keyword_hits(objective, _TRION_OBJECTIVE_ALLOWED_HINTS))
            unapproved_risky = [
                kw for kw in risky_hits
                if not (
                    kw in _TRION_RISKY_CONTEXT_APPROVED
                    and _TRION_RISKY_CONTEXT_APPROVED[kw] & allow_hits_set
                )
            ]
            if unapproved_risky:
                raise CronPolicyError(
                    "cron_trion_approval_required",
                    "trion objective requires explicit user approval",
                    status_code=409,
                    details={"risk_keywords": unapproved_risky, "requires": "user_approved=true"},
                )

    def _enforce_job_policy_locked(
        self,
        normalized: Dict[str, Any],
        existing: Optional[Dict[str, Any]],
        *,
        job_id: str = "",
    ) -> None:
        existing_job = existing or {}
        creating = existing is None
        cur_conv = str(existing_job.get("conversation_id", "")).strip()
        new_conv = str(normalized.get("conversation_id", "")).strip()
        conv_changed = creating or (new_conv != cur_conv)
        min_interval_s: Optional[int] = None

        if creating and len(self._jobs) >= self._max_jobs:
            raise CronPolicyError(
                "cron_max_jobs_reached",
                f"max cron jobs reached ({self._max_jobs})",
                status_code=409,
                details={"max_jobs": self._max_jobs},
            )

        if conv_changed:
            used = self._count_jobs_for_conversation_locked(new_conv, exclude_job_id=job_id)
            if used >= self._max_jobs_per_conversation:
                raise CronPolicyError(
                    "cron_conversation_limit_reached",
                    f"conversation '{new_conv}' reached cron limit ({self._max_jobs_per_conversation})",
                    status_code=409,
                    details={
                        "conversation_id": new_conv,
                        "max_jobs_per_conversation": self._max_jobs_per_conversation,
                    },
                )

        cur_cron = str(existing_job.get("cron", "")).strip()
        new_cron = str(normalized.get("cron", "")).strip()
        schedule_mode = str(
            normalized.get("schedule_mode")
            if "schedule_mode" in normalized
            else existing_job.get("schedule_mode", "recurring")
        ).strip().lower() or "recurring"
        if schedule_mode != "one_shot":
            if creating or (new_cron != cur_cron):
                parsed = self._parsed_expr(new_cron)
                min_interval_s = estimate_min_interval_seconds(parsed)
                if min_interval_s < self._min_interval_s:
                    raise CronPolicyError(
                        "cron_min_interval_violation",
                        f"cron interval {min_interval_s}s is below policy minimum {self._min_interval_s}s",
                        status_code=409,
                        details={"interval_s": min_interval_s, "min_interval_s": self._min_interval_s},
                    )
        self._enforce_trion_policy_locked(
            normalized,
            existing_job,
            creating=creating,
            min_interval_s=min_interval_s,
            schedule_mode=schedule_mode,
        )

    def _check_enqueue_policy_locked(
        self,
        *,
        cron_job_id: str,
        reason: str,
        now_utc: datetime,
    ) -> Tuple[bool, Optional[CronPolicyError]]:
        total = len(self._pending) + len(self._running)
        if total >= self._max_pending_runs:
            return (
                False,
                CronPolicyError(
                    "cron_queue_capacity_reached",
                    f"cron queue capacity reached ({self._max_pending_runs})",
                    status_code=429,
                    details={"max_pending_runs": self._max_pending_runs},
                ),
            )

        job_runs = self._count_runs_for_job_locked(cron_job_id)
        if job_runs >= self._max_pending_runs_per_job:
            return (
                False,
                CronPolicyError(
                    "cron_job_backlog_limit_reached",
                    f"cron job backlog reached ({self._max_pending_runs_per_job})",
                    status_code=429,
                    details={"max_pending_runs_per_job": self._max_pending_runs_per_job},
                ),
            )

        if str(reason or "") in {"manual", "tool"} and self._manual_run_cooldown_s > 0:
            job = self._jobs.get(cron_job_id) or {}
            last_manual_at = _parse_iso_datetime(str(job.get("last_manual_trigger_at", "")))
            if last_manual_at is not None:
                elapsed = max(0, int((now_utc - last_manual_at).total_seconds()))
                retry_after = self._manual_run_cooldown_s - elapsed
                if retry_after > 0:
                    return (
                        False,
                        CronPolicyError(
                            "cron_run_now_cooldown",
                            f"run-now cooldown active ({retry_after}s remaining)",
                            status_code=429,
                            details={"retry_after_s": retry_after},
                        ),
                    )

        return (True, None)

    def _normalize_job_payload(
        self,
        payload: Dict[str, Any],
        existing: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        prev = existing or {}
        out: Dict[str, Any] = dict(prev)

        if "schedule_mode" in payload or not existing:
            mode_raw = payload.get("schedule_mode") if "schedule_mode" in payload else prev.get("schedule_mode", "recurring")
            schedule_mode = str(mode_raw or "recurring").strip().lower()
            if schedule_mode not in {"recurring", "one_shot"}:
                raise ValueError("schedule_mode must be one of: recurring, one_shot")
            out["schedule_mode"] = schedule_mode
        else:
            schedule_mode = str(prev.get("schedule_mode", "recurring")).strip().lower() or "recurring"

        if "name" in payload or not existing:
            name = str(payload.get("name") if "name" in payload else prev.get("name", "")).strip()
            if not name:
                raise ValueError("name is required")
            out["name"] = name[:120]

        if "objective" in payload or not existing:
            objective = str(
                payload.get("objective") if "objective" in payload else prev.get("objective", "")
            ).strip()
            if not objective:
                raise ValueError("objective is required")
            out["objective"] = objective[:1000]

        if "conversation_id" in payload or not existing:
            conversation_id = str(
                payload.get("conversation_id")
                if "conversation_id" in payload
                else prev.get("conversation_id", "")
            ).strip()
            if not conversation_id:
                raise ValueError("conversation_id is required")
            out["conversation_id"] = conversation_id[:120]

        if schedule_mode == "recurring":
            if "cron" in payload or not existing:
                cron_expr = str(payload.get("cron") if "cron" in payload else prev.get("cron", "")).strip()
                if not cron_expr:
                    raise ValueError("cron is required for recurring schedule")
                parsed = validate_cron_expression(cron_expr)
                out["cron"] = str(parsed["normalized"])
            out["run_at"] = ""
        else:
            # one_shot: cron is optional (kept for backward-compat metadata)
            if "cron" in payload:
                cron_expr = str(payload.get("cron") or "").strip()
                if cron_expr:
                    parsed = validate_cron_expression(cron_expr)
                    out["cron"] = str(parsed["normalized"])
            elif not existing:
                out["cron"] = "*/15 * * * *"

            run_at_raw = payload.get("run_at") if "run_at" in payload else prev.get("run_at", "")
            run_at_dt = _parse_iso_datetime(str(run_at_raw or ""))
            if run_at_dt is None:
                raise ValueError("run_at is required for one_shot schedule")
            if (existing is None or "run_at" in payload) and run_at_dt <= _utcnow():
                raise ValueError("run_at must be in the future for one_shot schedule")
            out["run_at"] = _iso(run_at_dt)

        if "timezone" in payload or not existing:
            tz_name = str(payload.get("timezone") if "timezone" in payload else prev.get("timezone", "UTC")).strip()
            if not tz_name:
                tz_name = "UTC"
            try:
                ZoneInfo(tz_name)
            except Exception as exc:
                raise ValueError(f"timezone invalid: {tz_name}") from exc
            out["timezone"] = tz_name

        if "max_loops" in payload or not existing:
            raw = payload.get("max_loops") if "max_loops" in payload else prev.get("max_loops", 10)
            try:
                max_loops = int(raw)
            except Exception as exc:
                raise ValueError("max_loops must be an integer") from exc
            if max_loops < 1 or max_loops > 200:
                raise ValueError("max_loops must be between 1 and 200")
            out["max_loops"] = max_loops

        if "created_by" in payload or not existing:
            created_by = str(
                payload.get("created_by") if "created_by" in payload else prev.get("created_by", "user")
            ).strip() or "user"
            created_by = created_by.lower()
            if created_by not in {"user", "trion"}:
                raise ValueError("created_by must be one of: user, trion")
            out["created_by"] = created_by

        if "enabled" in payload:
            out["enabled"] = bool(payload.get("enabled"))
        elif not existing:
            out["enabled"] = True

        if "user_approved" in payload:
            out["user_approved"] = bool(payload.get("user_approved"))
        elif not existing:
            out["user_approved"] = False

        if "reference_links" in payload:
            out["reference_links"] = _normalize_reference_links(payload.get("reference_links"))

        if "reference_source" in payload:
            out["reference_source"] = str(payload.get("reference_source", "")).strip()[:120]

        if "job_note_md" in payload:
            out["job_note_md"] = str(payload.get("job_note_md") or "").strip()[:6000]
        elif not existing:
            out["job_note_md"] = _build_default_job_note_md(out)
        else:
            # Keep manual notes stable; refresh only if the previous note was auto-generated.
            auto_prev = _build_default_job_note_md(prev)
            changed_core = any(
                key in payload
                for key in (
                    "name",
                    "objective",
                    "schedule_mode",
                    "cron",
                    "run_at",
                    "timezone",
                    "conversation_id",
                    "max_loops",
                    "created_by",
                )
            )
            if changed_core and str(prev.get("job_note_md", "")).strip() in {"", auto_prev}:
                out["job_note_md"] = _build_default_job_note_md(out)

        return out

    async def create_job(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        async with self._lock:
            now = _iso()
            normalized = self._normalize_job_payload(payload, existing=None)
            self._enforce_job_policy_locked(normalized, existing=None)
            job_id = uuid.uuid4().hex[:12]
            job = {
                "id": job_id,
                **normalized,
                "created_at": now,
                "updated_at": now,
                "last_triggered_at": "",
                "last_run_at": "",
                "last_status": "never",
                "last_job_id": "",
                "last_error": "",
                "last_trigger_key": "",
                "last_manual_trigger_at": "",
            }
            self._jobs[job_id] = job
            self._save_state_locked()
            out = dict(job)
            out["next_run_at"] = self._next_run_iso(job) if bool(job.get("enabled", True)) else ""
            out["runtime_state"] = self._runtime_state_for_job_locked(job_id)
            return out

    async def update_job(self, cron_job_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        job_id = str(cron_job_id or "").strip()
        if not job_id:
            return None
        async with self._lock:
            current = self._jobs.get(job_id)
            if not current:
                return None
            normalized = self._normalize_job_payload(payload, existing=current)
            self._enforce_job_policy_locked(normalized, existing=current, job_id=job_id)
            normalized["updated_at"] = _iso()
            self._jobs[job_id] = {**current, **normalized}
            self._save_state_locked()
            out = dict(self._jobs[job_id])
            out["next_run_at"] = self._next_run_iso(out) if bool(out.get("enabled", True)) else ""
            out["runtime_state"] = self._runtime_state_for_job_locked(job_id)
            return out

    async def delete_job(self, cron_job_id: str) -> bool:
        job_id = str(cron_job_id or "").strip()
        if not job_id:
            return False
        async with self._lock:
            existed = job_id in self._jobs
            self._jobs.pop(job_id, None)
            self._pending = [x for x in self._pending if x.get("cron_job_id") != job_id]
            if existed:
                self._save_state_locked()
            return existed

    async def pause_job(self, cron_job_id: str) -> Optional[Dict[str, Any]]:
        return await self.update_job(cron_job_id, {"enabled": False})

    async def resume_job(self, cron_job_id: str) -> Optional[Dict[str, Any]]:
        return await self.update_job(cron_job_id, {"enabled": True})

    async def run_now(self, cron_job_id: str, reason: str = "manual") -> Optional[Dict[str, Any]]:
        job_id = str(cron_job_id or "").strip()
        if not job_id:
            return None
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            now_utc = _utcnow()
            allowed, policy_error = self._check_enqueue_policy_locked(
                cron_job_id=job_id,
                reason=str(reason or "manual"),
                now_utc=now_utc,
            )
            if not allowed and policy_error is not None:
                raise policy_error
            run_id = uuid.uuid4().hex[:12]
            item = {
                "run_id": run_id,
                "cron_job_id": job_id,
                "queued_at": _iso(),
                "reason": str(reason or "manual")[:40],
            }
            self._pending.append(item)
            await self._queue.put(item)
            self._jobs[job_id]["last_triggered_at"] = item["queued_at"]
            if self._is_one_shot_mode(job):
                self._jobs[job_id]["last_trigger_key"] = f"one_shot:manual:{item['queued_at']}"
                self._jobs[job_id]["enabled"] = False
            else:
                self._jobs[job_id]["last_trigger_key"] = ""
            if str(item.get("reason", "")) in {"manual", "tool"}:
                self._jobs[job_id]["last_manual_trigger_at"] = item["queued_at"]
            self._save_state_locked()
            out = dict(job)
            out["runtime_state"] = self._runtime_state_for_job_locked(job_id)
            out["next_run_at"] = self._next_run_iso(job) if bool(job.get("enabled", True)) else ""
            return {"scheduled": True, "run_id": run_id, "job": out}

    async def get_status(self) -> Dict[str, Any]:
        async with self._lock:
            total = len(self._jobs)
            enabled = sum(1 for j in self._jobs.values() if bool(j.get("enabled", False)))
            paused = total - enabled
            queued = len(self._pending)
            running = len(self._running)
            return {
                "scheduler": {
                    "running": bool(self._tick_task and not self._tick_task.done()),
                    "tick_s": self._tick_s,
                    "max_concurrency": self._max_concurrency,
                    "state_path": self._state_path,
                },
                "policy": self._policy_snapshot_locked(),
                "counts": {
                    "jobs_total": total,
                    "jobs_active": enabled,
                    "jobs_paused": paused,
                    "queued_runs": queued,
                    "running_runs": running,
                    "history_runs": len(self._history),
                },
            }

    async def get_queue_snapshot(self) -> Dict[str, Any]:
        async with self._lock:
            return {
                "pending": list(self._pending),
                "running": list(self._running.values()),
                "recent": list(self._history[-50:]),
            }

    async def _tick_loop(self) -> None:
        while not self._stopping:
            try:
                await self._tick_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log_warning(f"[AutonomyCron] tick error: {exc}")
            await asyncio.sleep(self._tick_s)

    async def _tick_once(self) -> None:
        now_utc = _utcnow()
        changed = False
        queued = 0
        async with self._lock:
            for job_id, job in self._jobs.items():
                if not bool(job.get("enabled", True)):
                    continue
                if self._is_one_shot_mode(job):
                    if self._is_one_shot_consumed(job):
                        continue
                    run_at = _parse_iso_datetime(str(job.get("run_at", "")))
                    if run_at is None:
                        job["last_status"] = "error"
                        job["last_error"] = "one_shot_run_at_invalid"
                        changed = True
                        continue
                    if now_utc < run_at:
                        continue
                    allowed, policy_error = self._check_enqueue_policy_locked(
                        cron_job_id=job_id,
                        reason="schedule_one_shot",
                        now_utc=now_utc,
                    )
                    if not allowed:
                        if policy_error is not None:
                            job["last_status"] = "throttled"
                            job["last_error"] = policy_error.error_code
                            job["updated_at"] = _iso()
                            changed = True
                        continue

                    run_id = uuid.uuid4().hex[:12]
                    item = {
                        "run_id": run_id,
                        "cron_job_id": job_id,
                        "queued_at": _iso(),
                        "reason": "schedule_one_shot",
                    }
                    self._pending.append(item)
                    await self._queue.put(item)
                    job["last_triggered_at"] = item["queued_at"]
                    job["last_trigger_key"] = f"one_shot:{str(job.get('run_at', ''))}"
                    job["enabled"] = False
                    changed = True
                    queued += 1
                    continue
                cron_expr = str(job.get("cron", ""))
                tz_name = str(job.get("timezone", "UTC"))
                try:
                    parsed = self._parsed_expr(cron_expr)
                    local = now_utc.astimezone(ZoneInfo(tz_name))
                    local = local.replace(second=0, microsecond=0)
                except Exception as exc:
                    job["last_status"] = "error"
                    job["last_error"] = f"cron_parse_error:{exc}"
                    changed = True
                    continue

                minute_key = local.strftime("%Y-%m-%dT%H:%M")
                if not cron_matches(parsed, local):
                    continue
                if str(job.get("last_trigger_key", "")) == minute_key:
                    continue
                allowed, policy_error = self._check_enqueue_policy_locked(
                    cron_job_id=job_id,
                    reason="schedule",
                    now_utc=now_utc,
                )
                if not allowed:
                    if policy_error is not None:
                        job["last_status"] = "throttled"
                        job["last_error"] = policy_error.error_code
                        job["updated_at"] = _iso()
                        changed = True
                    continue

                run_id = uuid.uuid4().hex[:12]
                item = {
                    "run_id": run_id,
                    "cron_job_id": job_id,
                    "queued_at": _iso(),
                    "reason": "schedule",
                }
                self._pending.append(item)
                await self._queue.put(item)
                job["last_triggered_at"] = item["queued_at"]
                job["last_trigger_key"] = minute_key
                changed = True
                queued += 1

            if changed:
                self._save_state_locked()

        if queued:
            log_info(f"[AutonomyCron] queued scheduled runs: {queued}")

    async def _dispatch_worker(self, worker_idx: int) -> None:
        while not self._stopping:
            try:
                item = await self._queue.get()
            except asyncio.CancelledError:
                raise

            run_id = str(item.get("run_id", ""))
            async with self._lock:
                self._pending = [x for x in self._pending if str(x.get("run_id")) != run_id]
                running_entry = {**item, "worker": worker_idx, "started_at": _iso()}
                self._running[run_id] = running_entry
                job = self._jobs.get(str(item.get("cron_job_id", "")))
                if job:
                    job["last_run_at"] = running_entry["started_at"]
                    job["last_status"] = "dispatching"
                self._save_state_locked()

            try:
                job_id = str(item.get("cron_job_id", ""))
                async with self._lock:
                    job = dict(self._jobs.get(job_id) or {})
                if not job:
                    raise RuntimeError("cron_job_not_found")

                allowed, guard_reason, guard_snapshot = self._evaluate_hardware_guard()
                if not allowed:
                    finish = _iso()
                    log_warning(
                        "[AutonomyCron] deferred "
                        f"run_id={run_id} job_id={job_id} reason={guard_reason} "
                        f"cpu={guard_snapshot.get('cpu_percent')} "
                        f"mem={guard_snapshot.get('memory_percent')}"
                    )
                    async with self._lock:
                        self._running.pop(run_id, None)
                        job_ref = self._jobs.get(job_id)
                        if job_ref:
                            job_ref["last_status"] = "deferred_hardware"
                            job_ref["last_error"] = guard_reason[:300]
                            job_ref["updated_at"] = finish
                        self._history.append(
                            {
                                "run_id": run_id,
                                "cron_job_id": job_id,
                                "status": "deferred_hardware",
                                "queued_at": item.get("queued_at"),
                                "started_at": running_entry.get("started_at"),
                                "finished_at": finish,
                                "reason": item.get("reason", "schedule"),
                                "hardware_guard": {
                                    "reason": guard_reason,
                                    "snapshot": guard_snapshot,
                                },
                            }
                        )
                        self._history = self._history[-200:]
                        self._save_state_locked()
                    continue

                conversation_id = str(job.get("conversation_id", "")).strip()
                if not conversation_id:
                    raise RuntimeError("missing_conversation_id")

                payload = {
                    "objective": str(job.get("objective", "")),
                    "conversation_id": conversation_id,
                    "max_loops": int(job.get("max_loops", 10)),
                }
                meta = {
                    "source": "autonomy_cron",
                    "cron_job_id": job_id,
                    "cron_job_name": str(job.get("name", "")),
                    "cron_run_id": run_id,
                    "reason": str(item.get("reason", "schedule")),
                }
                submission = await self._submit_cb(payload, meta)
                submitted_job_id = str(submission.get("job_id", ""))

                finish = _iso()
                hist = {
                    "run_id": run_id,
                    "cron_job_id": job_id,
                    "status": "submitted",
                    "queued_at": item.get("queued_at"),
                    "started_at": running_entry.get("started_at"),
                    "finished_at": finish,
                    "autonomy_job_id": submitted_job_id,
                    "reason": item.get("reason", "schedule"),
                }
                async with self._lock:
                    self._running.pop(run_id, None)
                    job_ref = self._jobs.get(job_id)
                    if job_ref:
                        job_ref["last_status"] = "submitted"
                        job_ref["last_job_id"] = submitted_job_id
                        job_ref["last_error"] = ""
                        job_ref["updated_at"] = finish
                        if self._is_one_shot_mode(job_ref):
                            job_ref["enabled"] = False
                    self._history.append(hist)
                    self._history = self._history[-200:]
                    self._save_state_locked()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                finish = _iso()
                err = str(exc)
                log_error(f"[AutonomyCron] dispatch failed run_id={run_id}: {err}")
                async with self._lock:
                    self._running.pop(run_id, None)
                    job_id = str(item.get("cron_job_id", ""))
                    job_ref = self._jobs.get(job_id)
                    if job_ref:
                        job_ref["last_status"] = "failed"
                        job_ref["last_error"] = err[:300]
                        job_ref["updated_at"] = finish
                        if self._is_one_shot_mode(job_ref):
                            job_ref["enabled"] = False
                    self._history.append(
                        {
                            "run_id": run_id,
                            "cron_job_id": job_id,
                            "status": "failed",
                            "queued_at": item.get("queued_at"),
                            "started_at": item.get("started_at"),
                            "finished_at": finish,
                            "error": err[:500],
                            "reason": item.get("reason", "schedule"),
                        }
                    )
                    self._history = self._history[-200:]
                    self._save_state_locked()
            finally:
                self._queue.task_done()
