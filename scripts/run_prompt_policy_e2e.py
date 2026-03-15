#!/usr/bin/env python3
"""
Run prompt/policy E2E batches against TRION admin-api /api/chat.

Features:
- stream-mode event parsing (thinking/control/workspace_update/message/done)
- optional expectation checks per case (domain/approved/needs_memory)
- latency tracking and summary stats
- JSON + Markdown report output
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


SMOKE_CASE_IDS = {
    "T001",
    "T002",
    "T003",
    "T005",
    "T009",
    "T013",
    "T015",
    "T017",
    "T021",
    "T022",
    "T029",
    "T030",
    "T031",
    "T035",
    "T039",
    "T042",
    "T048",
    "T050",
    "T053",
    "T057",
    "T058",
    "T074",
    "T075",
    "T083",
    "T085",
    "T091",
    "T092",
}


@dataclass
class CaseEval:
    domain_match: Optional[bool]
    approval_match: Optional[bool]
    needs_memory_match: Optional[bool]
    score_0_10: Optional[int]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TRION prompt policy E2E suite runner")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("AI_TEST_BASE_URL", "http://127.0.0.1:8200"),
        help="Base URL for admin-api",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("AI_TEST_MODEL", "ministral-3:8b"),
        help="Model name sent to /api/chat",
    )
    parser.add_argument(
        "--cases-file",
        default="tests/e2e/prompt_suite_cases.json",
        help="Path to JSON case file",
    )
    parser.add_argument(
        "--real-cases-file",
        default="tests/e2e/autonomy_real_prompts.json",
        help="Path to JSON file with real autonomy prompts",
    )
    parser.add_argument(
        "--profile",
        choices=("smoke", "full", "real20"),
        default="smoke",
        help="Run subset (smoke), all suite cases (full), or only real autonomy prompts (real20)",
    )
    parser.add_argument(
        "--include-real-autonomy",
        action="store_true",
        help="Append real autonomy prompts to smoke/full profile runs",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=0,
        help="Optional hard cap after profile/filters (0 = no cap)",
    )
    parser.add_argument(
        "--id-prefix",
        default="",
        help="Optional case id prefix filter (e.g. T00)",
    )
    parser.add_argument(
        "--timeout-s",
        type=int,
        default=120,
        help="Read timeout per request in seconds",
    )
    parser.add_argument(
        "--max-case-seconds",
        type=int,
        default=90,
        help="Hard wall-clock cap per case to prevent hangs (0 disables cap)",
    )
    parser.add_argument(
        "--output-dir",
        default="logs/perf",
        help="Directory for report outputs",
    )
    parser.add_argument(
        "--baseline-json",
        default="",
        help="Optional prior report JSON path for KPI deltas",
    )
    parser.add_argument(
        "--target-approved-rate-min",
        type=float,
        default=None,
        help="Fail if approved_rate drops below this threshold (0..1)",
    )
    parser.add_argument(
        "--target-blocked-rate-max",
        type=float,
        default=None,
        help="Fail if blocked_rate exceeds this threshold (0..1)",
    )
    parser.add_argument(
        "--target-tool-exec-rate-min",
        type=float,
        default=None,
        help="Fail if tool_exec_rate drops below this threshold (0..1)",
    )
    parser.add_argument(
        "--target-auto-answer-without-retry-min",
        type=float,
        default=None,
        help="Fail if auto_answer_without_retry_rate drops below this threshold (0..1)",
    )
    parser.add_argument(
        "--require-blocked-rate-improvement-pct",
        type=float,
        default=0.0,
        help="Required blocked_rate reduction vs baseline in percent (e.g. 50 for half)",
    )
    parser.add_argument(
        "--require-tool-exec-rate-improvement-pct",
        type=float,
        default=0.0,
        help="Required tool_exec_rate increase vs baseline in percent (e.g. 20 for +20%)",
    )
    return parser.parse_args()


def _load_cases(path: str, *, source: str = "suite") -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    cases = payload.get("cases", [])
    if not isinstance(cases, list):
        raise ValueError("cases file invalid: 'cases' must be a list")
    out: List[Dict[str, Any]] = []
    for row in cases:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("id") or "").strip()
        prompt = str(row.get("prompt") or "")
        if not cid:
            continue
        out.append(
            {
                "id": cid,
                "prompt": prompt,
                "category": str(row.get("category") or "").strip(),
                "tags": row.get("tags") if isinstance(row.get("tags"), list) else [],
                "expected": row.get("expected") if isinstance(row.get("expected"), dict) else {},
                "source": source,
            }
        )
    return out


def _dedupe_cases(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for row in cases:
        cid = str(row.get("id") or "").strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        out.append(row)
    return out


def _select_cases(cases: List[Dict[str, Any]], profile: str, id_prefix: str, max_cases: int) -> List[Dict[str, Any]]:
    selected = cases
    if profile == "smoke":
        selected = [c for c in selected if c["id"] in SMOKE_CASE_IDS]
    if id_prefix:
        selected = [c for c in selected if str(c.get("id", "")).startswith(id_prefix)]
    selected = sorted(selected, key=lambda c: c.get("id", ""))
    if max_cases and max_cases > 0:
        selected = selected[:max_cases]
    return selected


def _parse_tools_from_workspace_content(text: str) -> List[str]:
    content = str(text or "")
    if not content:
        return []
    m = re.search(r"\*\*Tools executed:\*\*\s*([^\n]+)", content)
    if not m:
        return []
    raw = str(m.group(1) or "").strip()
    if not raw:
        return []
    parts = re.split(r"[,\s]+", raw)
    out: List[str] = []
    for p in parts:
        tool = str(p or "").strip()
        if not tool:
            continue
        if tool.startswith("#"):
            continue
        out.append(tool)
    return out


def _infer_domain(intent: str, tools: List[str], prompt: str) -> str:
    low_intent = str(intent or "").lower()
    low_prompt = str(prompt or "").lower()
    tool_set = {str(t or "").strip().lower() for t in tools}

    if any(t.startswith("autonomy_cron_") or t == "cron_reference_links_list" for t in tool_set):
        return "CRONJOB"
    if any(
        t in {"run_skill", "create_skill", "autonomous_skill_task", "list_skills", "skill_info"}
        or "skill" in t
        for t in tool_set
    ):
        return "SKILL"
    if any(
        t in {
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
            "list_used_ports",
            "find_free_port",
            "check_port",
        }
        for t in tool_set
    ):
        return "CONTAINER"

    if any(tok in low_intent for tok in ("cron", "zeitplan", "schedule")):
        return "CRONJOB"
    if "skill" in low_intent:
        return "SKILL"
    if any(tok in low_intent for tok in ("container", "blueprint", "docker")):
        return "CONTAINER"

    if any(tok in low_prompt for tok in ("cronjob", " cron ", "zeitplan", "schedule")):
        return "CRONJOB"
    if "skill" in low_prompt:
        return "SKILL"
    if any(tok in low_prompt for tok in ("container", "blueprint", "docker")):
        return "CONTAINER"
    return "GENERIC"


def _derive_approved(control_approved: Optional[bool], response_text: str, done_reason: str) -> bool:
    if control_approved is not None:
        return bool(control_approved)
    low = str(response_text or "").lower()
    if "safety policy violation" in low:
        return False
    if "tool-ausführung fehlgeschlagen" in low or "tool-ausf" in low:
        return False
    if str(done_reason or "").lower() == "error":
        return False
    return True


def _evaluate_case(expected: Dict[str, Any], actual: Dict[str, Any]) -> CaseEval:
    checks: List[bool] = []
    domain_match: Optional[bool] = None
    approval_match: Optional[bool] = None
    needs_memory_match: Optional[bool] = None

    if "domain" in expected and expected.get("domain") is not None:
        domain_match = str(actual.get("domain") or "") == str(expected.get("domain") or "")
        checks.append(domain_match)
    if "approved" in expected and expected.get("approved") is not None:
        approval_match = bool(actual.get("approved")) is bool(expected.get("approved"))
        checks.append(approval_match)
    if "needs_memory" in expected and expected.get("needs_memory") is not None:
        needs_memory_match = actual.get("needs_memory") is bool(expected.get("needs_memory"))
        checks.append(needs_memory_match)

    score = int(round((sum(1 for c in checks if c) / len(checks)) * 10.0)) if checks else None
    return CaseEval(
        domain_match=domain_match,
        approval_match=approval_match,
        needs_memory_match=needs_memory_match,
        score_0_10=score,
    )


def _run_case(
    *,
    base_url: str,
    model: str,
    case: Dict[str, Any],
    timeout_s: int,
    max_case_seconds: int,
    run_prefix: str,
    idx: int,
) -> Dict[str, Any]:
    case_id = str(case.get("id") or f"CASE-{idx:03d}")
    prompt = str(case.get("prompt") or "")
    conversation_id = f"{run_prefix}-{case_id.lower()}"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "conversation_id": conversation_id,
    }
    started_at = time.time()

    response_text = ""
    done_reason = ""
    err = ""
    control_approved: Optional[bool] = None
    thinking: Dict[str, Any] = {}
    tools_executed: List[str] = []
    event_type_counts: Dict[str, int] = {}

    try:
        with requests.post(
            f"{base_url.rstrip('/')}/api/chat",
            json=payload,
            timeout=(10, timeout_s),
            stream=True,
        ) as resp:
            resp.raise_for_status()
            for raw in resp.iter_lines():
                if max_case_seconds and (time.time() - started_at) > max_case_seconds:
                    err = f"case_timeout_exceeded:{max_case_seconds}s"
                    done_reason = "timeout"
                    break
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except Exception:
                    continue

                evt = str(row.get("type") or "").strip()
                if evt:
                    event_type_counts[evt] = event_type_counts.get(evt, 0) + 1

                if "thinking" in row and isinstance(row["thinking"], dict):
                    thinking = row["thinking"]

                if evt == "control":
                    if isinstance(row.get("approved"), bool):
                        control_approved = bool(row["approved"])

                if evt == "workspace_update":
                    tools = _parse_tools_from_workspace_content(row.get("content", ""))
                    if tools:
                        tools_executed.extend(tools)

                msg = row.get("message")
                if isinstance(msg, dict):
                    chunk = str(msg.get("content") or "")
                    if chunk:
                        response_text += chunk

                if row.get("done"):
                    done_reason = str(row.get("done_reason") or "")
                    break
    except Exception as exc:
        err = str(exc)
        done_reason = "error"

    elapsed_ms = (time.time() - started_at) * 1000.0
    tools_executed = list(dict.fromkeys(tools_executed))
    intent = str(thinking.get("intent") or "")
    response_non_empty = bool(str(response_text or "").strip())
    retry_detected = any("retry" in str(evt or "").lower() for evt in event_type_counts.keys())
    if not retry_detected and "retry" in str(response_text or "").lower():
        retry_detected = True
    approved = _derive_approved(
        control_approved=control_approved,
        response_text=response_text,
        done_reason=done_reason,
    )
    actual = {
        "domain": _infer_domain(intent=intent, tools=tools_executed, prompt=prompt),
        "needs_memory": thinking.get("needs_memory") if isinstance(thinking.get("needs_memory"), bool) else None,
        "approved": approved,
        "tools_executed": tools_executed,
        "tool_executed": bool(tools_executed),
        "response_non_empty": response_non_empty,
        "retry_detected": retry_detected,
        "auto_answer_without_retry": bool(approved and response_non_empty and not retry_detected),
        "done_reason": done_reason or ("error" if err else "stop"),
        "latency_ms": round(elapsed_ms, 2),
        "conversation_id": conversation_id,
        "error": err or None,
    }
    eval_result = _evaluate_case(case.get("expected", {}), actual)

    return {
        "id": case_id,
        "prompt": prompt,
        "category": case.get("category", ""),
        "tags": case.get("tags", []),
        "expected": case.get("expected", {}),
        "actual": actual,
        "observed": {
            "control_approved": control_approved,
            "thinking": thinking,
            "event_type_counts": event_type_counts,
            "response_preview": response_text[:280],
        },
        "quality": {
            "domain_match": eval_result.domain_match,
            "approval_match": eval_result.approval_match,
            "needs_memory_match": eval_result.needs_memory_match,
            "score": eval_result.score_0_10,
        },
    }


def _summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(results)
    if total == 0:
        return {"total": 0}

    latencies = [float(r["actual"]["latency_ms"]) for r in results if isinstance(r.get("actual", {}).get("latency_ms"), (int, float))]
    blocked = [r for r in results if not bool(r.get("actual", {}).get("approved", True))]
    errors = [r for r in results if r.get("actual", {}).get("error")]

    domains: Dict[str, int] = {}
    for r in results:
        d = str(r.get("actual", {}).get("domain") or "UNKNOWN")
        domains[d] = domains.get(d, 0) + 1

    def _match_rate(key: str) -> Optional[float]:
        vals = [r.get("quality", {}).get(key) for r in results if r.get("quality", {}).get(key) is not None]
        if not vals:
            return None
        ok = sum(1 for v in vals if v is True)
        return round(ok / len(vals), 4)

    scores = [r.get("quality", {}).get("score") for r in results if isinstance(r.get("quality", {}).get("score"), int)]

    approved_count = sum(1 for r in results if bool(r.get("actual", {}).get("approved", False)))
    tool_exec_count = sum(1 for r in results if bool(r.get("actual", {}).get("tool_executed", False)))
    auto_answer_without_retry_count = sum(
        1 for r in results if bool(r.get("actual", {}).get("auto_answer_without_retry", False))
    )

    def _rate(n: int) -> float:
        return round((n / total), 4) if total else 0.0

    cohort_rows = {
        "prompt_suite": [r for r in results if "real_autonomy" not in (r.get("tags") or [])],
        "real_autonomy": [r for r in results if "real_autonomy" in (r.get("tags") or [])],
    }

    def _cohort_kpis(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        n = len(rows)
        if n == 0:
            return None
        blocked_n = sum(1 for r in rows if not bool(r.get("actual", {}).get("approved", True)))
        approved_n = n - blocked_n
        tool_n = sum(1 for r in rows if bool(r.get("actual", {}).get("tool_executed", False)))
        auto_n = sum(1 for r in rows if bool(r.get("actual", {}).get("auto_answer_without_retry", False)))
        return {
            "total": n,
            "approved_rate": round(approved_n / n, 4),
            "blocked_rate": round(blocked_n / n, 4),
            "tool_exec_rate": round(tool_n / n, 4),
            "auto_answer_without_retry_rate": round(auto_n / n, 4),
        }

    return {
        "total": total,
        "approved_count": approved_count,
        "blocked_count": len(blocked),
        "error_count": len(errors),
        "tool_exec_count": tool_exec_count,
        "auto_answer_without_retry_count": auto_answer_without_retry_count,
        "kpis": {
            "approved_rate": _rate(approved_count),
            "blocked_rate": _rate(len(blocked)),
            "tool_exec_rate": _rate(tool_exec_count),
            "auto_answer_without_retry_rate": _rate(auto_answer_without_retry_count),
        },
        "domain_counts": domains,
        "latency_ms": {
            "p50": round(statistics.median(latencies), 2) if latencies else None,
            "mean": round(statistics.fmean(latencies), 2) if latencies else None,
            "max": round(max(latencies), 2) if latencies else None,
        },
        "match_rates": {
            "domain": _match_rate("domain_match"),
            "approval": _match_rate("approval_match"),
            "needs_memory": _match_rate("needs_memory_match"),
        },
        "score_mean_0_10": round(statistics.fmean(scores), 2) if scores else None,
        "cohorts": {
            name: _cohort_kpis(rows)
            for name, rows in cohort_rows.items()
        },
    }


def _load_baseline_summary(path: str) -> Dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if isinstance(payload, dict) and isinstance(payload.get("summary"), dict):
        return payload["summary"]
    return payload if isinstance(payload, dict) else {}


def _kpi_deltas(summary: Dict[str, Any], baseline: Dict[str, Any]) -> Dict[str, Any]:
    current = (summary or {}).get("kpis", {}) if isinstance(summary, dict) else {}
    base = (baseline or {}).get("kpis", {}) if isinstance(baseline, dict) else {}
    keys = (
        "approved_rate",
        "blocked_rate",
        "tool_exec_rate",
        "auto_answer_without_retry_rate",
    )
    out: Dict[str, Any] = {}
    for key in keys:
        cur = current.get(key)
        old = base.get(key)
        if not isinstance(cur, (int, float)) or not isinstance(old, (int, float)):
            out[key] = {"current": cur, "baseline": old, "delta": None, "delta_pct": None}
            continue
        delta = float(cur) - float(old)
        if float(old) == 0.0:
            delta_pct = None
        else:
            delta_pct = (delta / float(old)) * 100.0
        out[key] = {
            "current": round(float(cur), 4),
            "baseline": round(float(old), 4),
            "delta": round(delta, 4),
            "delta_pct": round(delta_pct, 2) if delta_pct is not None else None,
        }
    return out


def _evaluate_kpi_targets(
    *,
    summary: Dict[str, Any],
    baseline: Dict[str, Any],
    args: argparse.Namespace,
) -> List[str]:
    failures: List[str] = []
    kpis = (summary or {}).get("kpis", {}) if isinstance(summary, dict) else {}
    approved_rate = kpis.get("approved_rate")
    blocked_rate = kpis.get("blocked_rate")
    tool_exec_rate = kpis.get("tool_exec_rate")
    auto_answer_rate = kpis.get("auto_answer_without_retry_rate")

    if args.target_approved_rate_min is not None and isinstance(approved_rate, (int, float)):
        if approved_rate < float(args.target_approved_rate_min):
            failures.append(
                f"approved_rate {approved_rate:.4f} < target {float(args.target_approved_rate_min):.4f}"
            )
    if args.target_blocked_rate_max is not None and isinstance(blocked_rate, (int, float)):
        if blocked_rate > float(args.target_blocked_rate_max):
            failures.append(
                f"blocked_rate {blocked_rate:.4f} > target {float(args.target_blocked_rate_max):.4f}"
            )
    if args.target_tool_exec_rate_min is not None and isinstance(tool_exec_rate, (int, float)):
        if tool_exec_rate < float(args.target_tool_exec_rate_min):
            failures.append(
                f"tool_exec_rate {tool_exec_rate:.4f} < target {float(args.target_tool_exec_rate_min):.4f}"
            )
    if args.target_auto_answer_without_retry_min is not None and isinstance(auto_answer_rate, (int, float)):
        if auto_answer_rate < float(args.target_auto_answer_without_retry_min):
            failures.append(
                "auto_answer_without_retry_rate "
                f"{auto_answer_rate:.4f} < target {float(args.target_auto_answer_without_retry_min):.4f}"
            )

    base_kpis = (baseline or {}).get("kpis", {}) if isinstance(baseline, dict) else {}
    base_blocked = base_kpis.get("blocked_rate")
    if (
        isinstance(base_blocked, (int, float))
        and isinstance(blocked_rate, (int, float))
        and float(args.require_blocked_rate_improvement_pct or 0.0) > 0.0
        and base_blocked > 0.0
    ):
        reduction_pct = ((base_blocked - blocked_rate) / base_blocked) * 100.0
        required = float(args.require_blocked_rate_improvement_pct)
        if reduction_pct < required:
            failures.append(
                f"blocked_rate improvement {reduction_pct:.2f}% < required {required:.2f}% "
                f"(baseline={base_blocked:.4f}, current={blocked_rate:.4f})"
            )

    base_tool_exec = base_kpis.get("tool_exec_rate")
    if (
        isinstance(base_tool_exec, (int, float))
        and isinstance(tool_exec_rate, (int, float))
        and float(args.require_tool_exec_rate_improvement_pct or 0.0) > 0.0
        and base_tool_exec > 0.0
    ):
        improve_pct = ((tool_exec_rate - base_tool_exec) / base_tool_exec) * 100.0
        required = float(args.require_tool_exec_rate_improvement_pct)
        if improve_pct < required:
            failures.append(
                f"tool_exec_rate improvement {improve_pct:.2f}% < required {required:.2f}% "
                f"(baseline={base_tool_exec:.4f}, current={tool_exec_rate:.4f})"
            )

    return failures


def _write_reports(
    output_dir: str,
    run_meta: Dict[str, Any],
    results: List[Dict[str, Any]],
    summary: Dict[str, Any],
    *,
    baseline_summary: Optional[Dict[str, Any]] = None,
    kpi_deltas: Optional[Dict[str, Any]] = None,
    gate_failures: Optional[List[str]] = None,
) -> Tuple[str, str]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = f"prompt_policy_e2e_{ts}"
    json_path = out_dir / f"{base}.json"
    md_path = out_dir / f"{base}.md"

    payload = {
        "meta": run_meta,
        "summary": summary,
        "baseline_summary": baseline_summary or {},
        "kpi_deltas": kpi_deltas or {},
        "gate_failures": gate_failures or [],
        "results": results,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines: List[str] = []
    lines.append(f"# Prompt Policy E2E Report ({ts} UTC)")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- total: {summary.get('total')}")
    lines.append(f"- blocked_count: {summary.get('blocked_count')}")
    lines.append(f"- error_count: {summary.get('error_count')}")
    lines.append(f"- kpis: {summary.get('kpis')}")
    lines.append(f"- domain_counts: {summary.get('domain_counts')}")
    lines.append(f"- latency_ms: {summary.get('latency_ms')}")
    lines.append(f"- match_rates: {summary.get('match_rates')}")
    lines.append(f"- score_mean_0_10: {summary.get('score_mean_0_10')}")
    lines.append(f"- cohorts: {summary.get('cohorts')}")
    if baseline_summary:
        lines.append("")
        lines.append("## Baseline Delta")
        lines.append(f"- baseline_kpis: {(baseline_summary or {}).get('kpis')}")
        lines.append(f"- delta: {kpi_deltas or {}}")
    if gate_failures:
        lines.append("")
        lines.append("## Gate Failures")
        for failure in gate_failures:
            lines.append(f"- {failure}")
    lines.append("")
    lines.append("## Failing Expectations")
    for row in results:
        q = row.get("quality", {})
        if any(v is False for v in (q.get("domain_match"), q.get("approval_match"), q.get("needs_memory_match"))):
            lines.append(
                f"- {row.get('id')}: domain_match={q.get('domain_match')} "
                f"approval_match={q.get('approval_match')} needs_memory_match={q.get('needs_memory_match')} "
                f"| actual={row.get('actual')}"
            )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(json_path), str(md_path)


def main() -> int:
    args = _parse_args()
    suite_cases = _load_cases(args.cases_file, source="prompt_suite")
    real_cases = _load_cases(args.real_cases_file, source="real_autonomy")

    if args.profile == "real20":
        cases = _select_cases(real_cases, profile="full", id_prefix=args.id_prefix, max_cases=args.max_cases)
    else:
        cases = _select_cases(suite_cases, profile=args.profile, id_prefix=args.id_prefix, max_cases=args.max_cases)
        if args.include_real_autonomy:
            cases = _dedupe_cases(cases + real_cases)
            if args.max_cases and args.max_cases > 0:
                cases = cases[: args.max_cases]
    if not cases:
        print("No cases selected.")
        return 1

    run_prefix = f"webui-prompt-e2e-{int(time.time())}"
    run_meta = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "model": args.model,
        "cases_file": args.cases_file,
        "real_cases_file": args.real_cases_file,
        "profile": args.profile,
        "include_real_autonomy": bool(args.include_real_autonomy),
        "selected_case_count": len(cases),
    }

    print(f"[prompt-e2e] base_url={args.base_url}")
    print(f"[prompt-e2e] model={args.model}")
    print(f"[prompt-e2e] profile={args.profile} cases={len(cases)}")

    results: List[Dict[str, Any]] = []
    for idx, case in enumerate(cases, start=1):
        cid = case.get("id", f"CASE-{idx:03d}")
        prompt = str(case.get("prompt") or "")
        print(f"[prompt-e2e] ({idx}/{len(cases)}) {cid} :: {prompt[:72]}")
        row = _run_case(
            base_url=args.base_url,
            model=args.model,
            case=case,
            timeout_s=args.timeout_s,
            max_case_seconds=args.max_case_seconds,
            run_prefix=run_prefix,
            idx=idx,
        )
        results.append(row)
        actual = row.get("actual", {})
        print(
            f"[prompt-e2e] -> domain={actual.get('domain')} approved={actual.get('approved')} "
            f"done={actual.get('done_reason')} latency_ms={actual.get('latency_ms')}"
        )

    summary = _summarize(results)
    baseline_summary = _load_baseline_summary(args.baseline_json)
    deltas = _kpi_deltas(summary, baseline_summary) if baseline_summary else {}
    gate_failures = _evaluate_kpi_targets(
        summary=summary,
        baseline=baseline_summary,
        args=args,
    )
    run_meta["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    run_meta["gate_passed"] = len(gate_failures) == 0
    json_path, md_path = _write_reports(
        args.output_dir,
        run_meta,
        results,
        summary,
        baseline_summary=baseline_summary,
        kpi_deltas=deltas,
        gate_failures=gate_failures,
    )

    print("[prompt-e2e] SUMMARY")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if baseline_summary:
        print("[prompt-e2e] KPI_DELTA")
        print(json.dumps(deltas, ensure_ascii=False, indent=2))
    if gate_failures:
        print("[prompt-e2e] GATE FAILURES")
        for failure in gate_failures:
            print(f" - {failure}")
    print(f"[prompt-e2e] report_json={json_path}")
    print(f"[prompt-e2e] report_md={md_path}")
    return 2 if gate_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
