"""
tests/e2e/test_ai_pipeline_perf.py
==================================
Live performance probe for TRION's chat pipeline with token/speed metrics.

Runs both sync and stream calls against /api/chat and writes a JSON report.

Opt-in:
  AI_TEST_LIVE=1  (or AI_PERF_ENABLE=1)

Config (env):
  AI_PERF_BASE_URL                 default: AI_TEST_TRION_URL or AI_TEST_BASE_URL or http://127.0.0.1:8200
  AI_PERF_MODEL                    default: AI_TEST_MODEL or ministral-3:8b
  AI_PERF_RUNS                     default: 6
  AI_PERF_WARMUP                   default: 2
  AI_PERF_TIMEOUT_S                default: 120
  AI_PERF_PROMPTS_JSON             optional JSON list[str]
  AI_PERF_REPORT                   optional output file path
  AI_PERF_EMBED_CPU_ONLY           true|false, force embedding_runtime_policy=cpu_only during run
  AI_PERF_FORCE_ROUTING_EMBEDDING_AUTO
                                   true|false, set compute layer_routing.embedding=auto during run

Optional gate thresholds:
  AI_PERF_MAX_P95_E2E_MS           0 disables check
  AI_PERF_MAX_P95_TTFT_MS          0 disables check
  AI_PERF_MIN_P50_TPS              0 disables check
  AI_PERF_MAX_P95_TOTAL_TOKENS     0 disables check
  AI_PERF_REQUIRE_CONTEXT_MARKERS  true|false

Optional baseline regression check:
  AI_PERF_BASELINE                 path to baseline report json
  AI_PERF_MAX_REGRESSION_PCT       default: 15
"""

from __future__ import annotations

import json
import math
import os
import statistics
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import pytest

from utils.chunker import count_tokens


def _bool_env(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    if len(xs) == 1:
        return float(xs[0])
    rank = (len(xs) - 1) * p
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return float(xs[lo])
    w = rank - lo
    return float(xs[lo] * (1.0 - w) + xs[hi] * w)


def _base_url() -> str:
    raw = (
        os.getenv("AI_PERF_BASE_URL")
        or os.getenv("AI_TEST_TRION_URL")
        or os.getenv("AI_TEST_BASE_URL")
        or "http://127.0.0.1:8200"
    ).rstrip("/")
    # Prefer explicit IPv4 loopback here to avoid localhost/IPv6 edge cases in CI/dev hosts.
    if raw.startswith("http://localhost:"):
        return raw.replace("http://localhost:", "http://127.0.0.1:", 1)
    if raw == "http://localhost":
        return "http://127.0.0.1"
    return raw


def _prompts() -> List[str]:
    raw = os.getenv("AI_PERF_PROMPTS_JSON")
    if raw:
        try:
            arr = json.loads(raw)
            if isinstance(arr, list) and all(isinstance(x, str) and x.strip() for x in arr):
                return [x.strip() for x in arr]
        except Exception:
            pass
    return [
        "Nenne kurz die wichtigsten Schritte für ein sicheres TRION Update.",
        "Welche Skills würdest du für Docker Diagnose verwenden und warum?",
        "Erkläre in drei Sätzen den Unterschied zwischen active und draft Skills.",
    ]


def _report_path() -> Path:
    configured = os.getenv("AI_PERF_REPORT", "").strip()
    if configured:
        return Path(configured)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return Path("logs/perf") / f"ai_pipeline_perf_{ts}.json"


def _api_get_json(client: httpx.Client, url: str, timeout_s: int = 10) -> Optional[Dict[str, Any]]:
    try:
        resp = client.get(url, timeout=timeout_s)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _api_post_json(
    client: httpx.Client,
    url: str,
    payload: Dict[str, Any],
    timeout_s: int = 10,
) -> Optional[Dict[str, Any]]:
    try:
        resp = client.post(url, json=payload, timeout=timeout_s)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _prepare_embedding_cpu_mode(client: httpx.Client, base_url: str) -> Dict[str, Any]:
    """
    Force CPU-only embedding for the duration of this perf run and return restore state.
    Uses:
      - typed runtime endpoint for set/verify
      - generic settings endpoint for cleanup/reset
    """
    state: Dict[str, Any] = {
        "enabled": True,
        "prepare_ok": False,
        "restore_ok": False,
        "before_policy": None,
        "after_policy": None,
        "before_overrides": {},
        "before_layer_routing": None,
    }

    before_runtime = _api_get_json(client, f"{base_url}/api/settings/embeddings/runtime", timeout_s=10) or {}
    before_policy = (
        ((before_runtime.get("runtime") or {}).get("active_policy"))
        or (((before_runtime.get("effective") or {}).get("embedding_runtime_policy") or {}).get("value"))
    )
    state["before_policy"] = before_policy

    before_overrides = _api_get_json(client, f"{base_url}/api/settings", timeout_s=10) or {}
    state["before_overrides"] = before_overrides

    routing_before = _api_get_json(client, f"{base_url}/api/runtime/compute/routing", timeout_s=10) or {}
    if isinstance(routing_before.get("layer_routing"), dict):
        state["before_layer_routing"] = dict(routing_before["layer_routing"])

    # Optional safety: avoid explicit embedding pin to unavailable compute target.
    if _bool_env("AI_PERF_FORCE_ROUTING_EMBEDDING_AUTO", True):
        _api_post_json(
            client,
            f"{base_url}/api/runtime/compute/routing",
            {"layer_routing": {"embedding": "auto"}},
            timeout_s=10,
        )

    set_res = _api_post_json(
        client,
        f"{base_url}/api/settings/embeddings/runtime",
        {"embedding_runtime_policy": "cpu_only"},
        timeout_s=10,
    )
    assert set_res is not None, "Failed to set embedding_runtime_policy=cpu_only"

    after_runtime = _api_get_json(client, f"{base_url}/api/settings/embeddings/runtime", timeout_s=10) or {}
    after_policy = (
        ((after_runtime.get("runtime") or {}).get("active_policy"))
        or (((after_runtime.get("effective") or {}).get("embedding_runtime_policy") or {}).get("value"))
    )
    state["after_policy"] = after_policy
    assert after_policy == "cpu_only", (
        f"CPU embedding policy not active: expected 'cpu_only', got '{after_policy}'"
    )

    state["prepare_ok"] = True
    return state


def _restore_embedding_cpu_mode(client: httpx.Client, base_url: str, state: Dict[str, Any]) -> bool:
    """
    Best-effort restoration of settings changed by _prepare_embedding_cpu_mode().
    """
    ok = True
    before_overrides = state.get("before_overrides") or {}
    valid_policies = {"auto", "prefer_gpu", "cpu_only"}
    before_policy = str(state.get("before_policy") or "").strip().lower()
    desired_policy = before_policy if before_policy in valid_policies else "auto"

    # Restore via typed runtime endpoint (stable contract for Scope 3.1).
    res_runtime = _api_post_json(
        client,
        f"{base_url}/api/settings/embeddings/runtime",
        {"embedding_runtime_policy": desired_policy},
        timeout_s=10,
    )
    if res_runtime is None:
        ok = False
    else:
        check_runtime = _api_get_json(client, f"{base_url}/api/settings/embeddings/runtime", timeout_s=10) or {}
        active_policy = (
            ((check_runtime.get("runtime") or {}).get("active_policy"))
            or (((check_runtime.get("effective") or {}).get("embedding_runtime_policy") or {}).get("value"))
        )
        if active_policy != desired_policy:
            ok = False

    # Legacy key restore is best-effort and only applied if it existed before.
    if "EMBEDDING_EXECUTION_MODE" in before_overrides:
        res_legacy = _api_post_json(
            client,
            f"{base_url}/api/settings",
            {"EMBEDDING_EXECUTION_MODE": before_overrides["EMBEDDING_EXECUTION_MODE"]},
            timeout_s=10,
        )
        if res_legacy is None:
            ok = False

    layer_routing = state.get("before_layer_routing")
    if isinstance(layer_routing, dict):
        res_route = _api_post_json(
            client,
            f"{base_url}/api/runtime/compute/routing",
            {"layer_routing": layer_routing},
            timeout_s=10,
        )
        if res_route is None:
            ok = False

    state["restore_ok"] = ok
    return ok


def _extract_tokens_prompt(messages: List[Dict[str, Any]]) -> int:
    text = "\n".join(str(m.get("content", "")) for m in messages)
    return count_tokens(text)


def _parse_ndjson_line(line: str) -> Optional[Dict[str, Any]]:
    line = line.strip()
    if not line:
        return None
    try:
        data = json.loads(line)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _run_sync_once(
    client: httpx.Client,
    base_url: str,
    model: str,
    prompt: str,
    timeout_s: int,
    run_index: int,
    max_retries: int,
) -> Dict[str, Any]:
    conv_id = f"perf-sync-{run_index}-{uuid.uuid4().hex[:8]}"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "conversation_id": conv_id,
    }
    prompt_tokens_est = _extract_tokens_prompt(payload["messages"])

    last_error = ""
    resp: Optional[httpx.Response] = None
    e2e_ms = 0.0
    for attempt in range(max_retries + 1):
        t0 = time.monotonic()
        try:
            resp = client.post(f"{base_url}/api/chat", json=payload, timeout=timeout_s)
            e2e_ms = (time.monotonic() - t0) * 1000.0
            resp.raise_for_status()
            break
        except Exception as exc:
            e2e_ms = (time.monotonic() - t0) * 1000.0
            last_error = str(exc)
            resp = None
            if attempt < max_retries:
                time.sleep(1.0)

    if resp is None:
        return {
            "mode": "sync",
            "ok": False,
            "error": last_error or "request_failed",
            "prompt": prompt,
            "run_index": run_index,
            "conversation_id": conv_id,
            "status_code": 0,
            "e2e_ms": round(e2e_ms, 3),
            "ttft_ms": round(e2e_ms, 3),
            "tokens_per_sec": 0.0,
            "prompt_tokens_est": prompt_tokens_est,
            "completion_tokens_est": 0,
            "total_tokens_est": prompt_tokens_est,
            "response_chars": 0,
            "done_reason": "error",
            "chunk_count": 0,
            "event_types": [],
            "context_chars": None,
            "retrieval_count": None,
            "context_sources": None,
        }

    response_text = ""
    done_reason = ""
    event_types: List[str] = []
    context_chars: Optional[int] = None
    retrieval_count: Optional[int] = None
    context_sources: Optional[List[str]] = None

    for line in resp.text.splitlines():
        data = _parse_ndjson_line(line)
        if not data:
            continue
        if isinstance(data.get("type"), str):
            event_types.append(data["type"])
        msg = data.get("message", {})
        chunk = msg.get("content", "") if isinstance(msg, dict) else ""
        if chunk:
            response_text += chunk
        if data.get("done"):
            done_reason = str(data.get("done_reason", ""))
        if isinstance(data.get("context_chars"), int):
            context_chars = data["context_chars"]
        if isinstance(data.get("retrieval_count"), int):
            retrieval_count = data["retrieval_count"]
        if isinstance(data.get("context_sources"), list):
            context_sources = [str(x) for x in data["context_sources"]]

    completion_tokens_est = count_tokens(response_text)
    total_tokens_est = prompt_tokens_est + completion_tokens_est
    # For sync, TTFT is unavailable from server events; use full latency as upper bound.
    ttft_ms = e2e_ms
    tokens_per_sec = (
        completion_tokens_est / max(e2e_ms / 1000.0, 0.001)
        if completion_tokens_est > 0
        else 0.0
    )

    return {
        "mode": "sync",
        "ok": True,
        "error": None,
        "prompt": prompt,
        "run_index": run_index,
        "conversation_id": conv_id,
        "status_code": resp.status_code,
        "e2e_ms": round(e2e_ms, 3),
        "ttft_ms": round(ttft_ms, 3),
        "tokens_per_sec": round(tokens_per_sec, 3),
        "prompt_tokens_est": prompt_tokens_est,
        "completion_tokens_est": completion_tokens_est,
        "total_tokens_est": total_tokens_est,
        "response_chars": len(response_text),
        "done_reason": done_reason,
        "chunk_count": 1 if response_text else 0,
        "event_types": sorted(set(event_types)),
        "context_chars": context_chars,
        "retrieval_count": retrieval_count,
        "context_sources": context_sources,
    }


def _run_stream_once(
    client: httpx.Client,
    base_url: str,
    model: str,
    prompt: str,
    timeout_s: int,
    run_index: int,
    max_retries: int,
) -> Dict[str, Any]:
    conv_id = f"perf-stream-{run_index}-{uuid.uuid4().hex[:8]}"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "conversation_id": conv_id,
    }
    prompt_tokens_est = _extract_tokens_prompt(payload["messages"])

    response_text = ""
    done_reason = ""
    event_types: List[str] = []
    context_chars: Optional[int] = None
    retrieval_count: Optional[int] = None
    context_sources: Optional[List[str]] = None
    chunk_count = 0

    e2e_ms = 0.0
    ttft_ms = 0.0
    last_error = ""
    ok = False

    for attempt in range(max_retries + 1):
        response_text = ""
        done_reason = ""
        event_types = []
        context_chars = None
        retrieval_count = None
        context_sources = None
        chunk_count = 0

        t0 = time.monotonic()
        first_token_ts: Optional[float] = None

        try:
            with client.stream("POST", f"{base_url}/api/chat", json=payload, timeout=timeout_s) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    data = _parse_ndjson_line(line)
                    if not data:
                        continue
                    if isinstance(data.get("type"), str):
                        event_types.append(data["type"])

                    msg = data.get("message", {})
                    chunk = msg.get("content", "") if isinstance(msg, dict) else ""
                    if chunk:
                        if first_token_ts is None:
                            first_token_ts = time.monotonic()
                        response_text += chunk
                        chunk_count += 1

                    if isinstance(data.get("context_chars"), int):
                        context_chars = data["context_chars"]
                    if isinstance(data.get("retrieval_count"), int):
                        retrieval_count = data["retrieval_count"]
                    if isinstance(data.get("context_sources"), list):
                        context_sources = [str(x) for x in data["context_sources"]]

                    if data.get("done"):
                        done_reason = str(data.get("done_reason", ""))
                        break

            t_end = time.monotonic()
            e2e_ms = (t_end - t0) * 1000.0
            ttft_ms = ((first_token_ts - t0) * 1000.0) if first_token_ts is not None else e2e_ms
            ok = True
            break
        except Exception as exc:
            last_error = str(exc)
            e2e_ms = (time.monotonic() - t0) * 1000.0
            ttft_ms = e2e_ms
            if attempt < max_retries:
                time.sleep(1.0)

    if not ok:
        return {
            "mode": "stream",
            "ok": False,
            "error": last_error or "request_failed",
            "prompt": prompt,
            "run_index": run_index,
            "conversation_id": conv_id,
            "status_code": 0,
            "e2e_ms": round(e2e_ms, 3),
            "ttft_ms": round(ttft_ms, 3),
            "tokens_per_sec": 0.0,
            "prompt_tokens_est": prompt_tokens_est,
            "completion_tokens_est": 0,
            "total_tokens_est": prompt_tokens_est,
            "response_chars": 0,
            "done_reason": "error",
            "chunk_count": 0,
            "event_types": [],
            "context_chars": None,
            "retrieval_count": None,
            "context_sources": None,
        }

    gen_ms = max(e2e_ms - ttft_ms, 1.0)

    completion_tokens_est = count_tokens(response_text)
    total_tokens_est = prompt_tokens_est + completion_tokens_est
    tokens_per_sec = (completion_tokens_est * 1000.0 / gen_ms) if completion_tokens_est > 0 else 0.0

    return {
        "mode": "stream",
        "ok": True,
        "error": None,
        "prompt": prompt,
        "run_index": run_index,
        "conversation_id": conv_id,
        "status_code": 200,
        "e2e_ms": round(e2e_ms, 3),
        "ttft_ms": round(ttft_ms, 3),
        "tokens_per_sec": round(tokens_per_sec, 3),
        "prompt_tokens_est": prompt_tokens_est,
        "completion_tokens_est": completion_tokens_est,
        "total_tokens_est": total_tokens_est,
        "response_chars": len(response_text),
        "done_reason": done_reason,
        "chunk_count": chunk_count,
        "event_types": sorted(set(event_types)),
        "context_chars": context_chars,
        "retrieval_count": retrieval_count,
        "context_sources": context_sources,
    }


def _summarize(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    def _bucket(mode: str) -> List[Dict[str, Any]]:
        return [r for r in records if r["mode"] == mode]

    def _stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not rows:
            return {}
        e2e = [float(r["e2e_ms"]) for r in rows]
        ttft = [float(r["ttft_ms"]) for r in rows]
        tps = [float(r["tokens_per_sec"]) for r in rows]
        total_tokens = [float(r["total_tokens_est"]) for r in rows]
        prompt_tokens = [float(r["prompt_tokens_est"]) for r in rows]
        completion_tokens = [float(r["completion_tokens_est"]) for r in rows]
        return {
            "runs": len(rows),
            "p50_e2e_ms": round(_percentile(e2e, 0.50), 3),
            "p95_e2e_ms": round(_percentile(e2e, 0.95), 3),
            "p50_ttft_ms": round(_percentile(ttft, 0.50), 3),
            "p95_ttft_ms": round(_percentile(ttft, 0.95), 3),
            "p50_tokens_per_sec": round(_percentile(tps, 0.50), 3),
            "p95_tokens_per_sec": round(_percentile(tps, 0.95), 3),
            "avg_prompt_tokens_est": round(statistics.mean(prompt_tokens), 3),
            "avg_completion_tokens_est": round(statistics.mean(completion_tokens), 3),
            "p95_total_tokens_est": round(_percentile(total_tokens, 0.95), 3),
        }

    sync_rows = _bucket("sync")
    stream_rows = _bucket("stream")
    both = records[:]

    return {
        "sync": _stats(sync_rows),
        "stream": _stats(stream_rows),
        "overall": _stats(both),
    }


def _assert_thresholds(summary: Dict[str, Any]) -> None:
    max_p95_e2e = _float_env("AI_PERF_MAX_P95_E2E_MS", 0.0)
    max_p95_ttft = _float_env("AI_PERF_MAX_P95_TTFT_MS", 0.0)
    min_p50_tps = _float_env("AI_PERF_MIN_P50_TPS", 0.0)
    max_p95_total_tokens = _float_env("AI_PERF_MAX_P95_TOTAL_TOKENS", 0.0)

    overall = summary.get("overall", {})
    stream = summary.get("stream", {})

    if max_p95_e2e > 0:
        assert overall.get("p95_e2e_ms", 0.0) <= max_p95_e2e, (
            f"p95_e2e_ms too high: {overall.get('p95_e2e_ms')} > {max_p95_e2e}"
        )
    if max_p95_ttft > 0:
        assert stream.get("p95_ttft_ms", 0.0) <= max_p95_ttft, (
            f"p95_ttft_ms too high: {stream.get('p95_ttft_ms')} > {max_p95_ttft}"
        )
    if min_p50_tps > 0:
        assert stream.get("p50_tokens_per_sec", 0.0) >= min_p50_tps, (
            f"p50_tokens_per_sec too low: {stream.get('p50_tokens_per_sec')} < {min_p50_tps}"
        )
    if max_p95_total_tokens > 0:
        assert overall.get("p95_total_tokens_est", 0.0) <= max_p95_total_tokens, (
            f"p95_total_tokens_est too high: {overall.get('p95_total_tokens_est')} > {max_p95_total_tokens}"
        )


def _assert_baseline_regression(summary: Dict[str, Any]) -> None:
    baseline_path = os.getenv("AI_PERF_BASELINE", "").strip()
    if not baseline_path:
        return

    p = Path(baseline_path)
    assert p.exists(), f"AI_PERF_BASELINE not found: {p}"
    with p.open("r", encoding="utf-8") as f:
        baseline = json.load(f)
    bsum = baseline.get("summary", {})
    max_reg_pct = _float_env("AI_PERF_MAX_REGRESSION_PCT", 15.0)

    checks_lower = [
        ("overall", "p95_e2e_ms"),
        ("stream", "p95_ttft_ms"),
        ("overall", "p95_total_tokens_est"),
    ]
    checks_higher = [
        ("stream", "p50_tokens_per_sec"),
    ]

    for sec, key in checks_lower:
        cur = float(summary.get(sec, {}).get(key, 0.0) or 0.0)
        base = float(bsum.get(sec, {}).get(key, 0.0) or 0.0)
        if base <= 0:
            continue
        allowed = base * (1.0 + max_reg_pct / 100.0)
        assert cur <= allowed, (
            f"Regression {sec}.{key}: current={cur} baseline={base} "
            f"allowed_max={allowed} ({max_reg_pct:.1f}%)"
        )

    for sec, key in checks_higher:
        cur = float(summary.get(sec, {}).get(key, 0.0) or 0.0)
        base = float(bsum.get(sec, {}).get(key, 0.0) or 0.0)
        if base <= 0:
            continue
        allowed_min = base * (1.0 - max_reg_pct / 100.0)
        assert cur >= allowed_min, (
            f"Regression {sec}.{key}: current={cur} baseline={base} "
            f"allowed_min={allowed_min} ({max_reg_pct:.1f}%)"
        )


@pytest.mark.e2e
def test_ai_pipeline_perf_live():
    if not (_bool_env("AI_TEST_LIVE", False) or _bool_env("AI_PERF_ENABLE", False)):
        pytest.skip("Set AI_TEST_LIVE=1 or AI_PERF_ENABLE=1 for live perf test")

    base_url = _base_url()
    model = os.getenv("AI_PERF_MODEL") or os.getenv("AI_TEST_MODEL") or "ministral-3:8b"
    runs = max(1, _int_env("AI_PERF_RUNS", 6))
    warmup = max(0, _int_env("AI_PERF_WARMUP", 2))
    timeout_s = max(10, _int_env("AI_PERF_TIMEOUT_S", 120))
    health_timeout_s = max(3, _int_env("AI_PERF_HEALTH_TIMEOUT_S", 10))
    health_retries = max(0, _int_env("AI_PERF_HEALTH_RETRIES", 2))
    max_retries = max(0, _int_env("AI_PERF_MAX_RETRIES", 1))
    max_error_rate = min(1.0, max(0.0, _float_env("AI_PERF_MAX_ERROR_RATE", 0.30)))
    prompts = _prompts()
    report_path = _report_path()

    cpu_embed_mode_enabled = _bool_env("AI_PERF_EMBED_CPU_ONLY", False)
    cpu_embed_state: Dict[str, Any] = {"enabled": cpu_embed_mode_enabled}

    records: List[Dict[str, Any]] = []
    with httpx.Client() as client:
        if cpu_embed_mode_enabled:
            cpu_embed_state = _prepare_embedding_cpu_mode(client, base_url)
            print(
                "[perf] embedding_cpu_mode enabled "
                f"(before={cpu_embed_state.get('before_policy')} after={cpu_embed_state.get('after_policy')})"
            )

        try:
            health_ok = False
            health_err = ""
            for attempt in range(health_retries + 1):
                try:
                    health = client.get(f"{base_url}/health", timeout=health_timeout_s)
                    health.raise_for_status()
                    health_ok = True
                    break
                except Exception as exc:
                    health_err = str(exc)
                    if attempt < health_retries:
                        time.sleep(1.0)
            if not health_ok:
                print(f"[perf] warning: health check failed after retries: {health_err}")

            total_per_mode = len(prompts) * (warmup + runs)
            print(
                f"[perf] base_url={base_url} model={model} prompts={len(prompts)} "
                f"warmup={warmup} runs={runs} total_calls={total_per_mode * 2}"
            )

            for prompt_idx, prompt in enumerate(prompts, start=1):
                for i in range(warmup + runs):
                    rec = _run_sync_once(
                        client=client,
                        base_url=base_url,
                        model=model,
                        prompt=prompt,
                        timeout_s=timeout_s,
                        run_index=prompt_idx * 10_000 + i,
                        max_retries=max_retries,
                    )
                    if i >= warmup:
                        records.append(rec)

                for i in range(warmup + runs):
                    rec = _run_stream_once(
                        client=client,
                        base_url=base_url,
                        model=model,
                        prompt=prompt,
                        timeout_s=timeout_s,
                        run_index=prompt_idx * 20_000 + i,
                        max_retries=max_retries,
                    )
                    if i >= warmup:
                        records.append(rec)
        finally:
            if cpu_embed_mode_enabled:
                restore_ok = _restore_embedding_cpu_mode(client, base_url, cpu_embed_state)
                print(f"[perf] embedding_cpu_mode restore_ok={restore_ok}")

    assert records, "No perf records collected"
    failed = [r for r in records if not r.get("ok", True)]
    success = [r for r in records if r.get("ok", True)]
    assert success, "No successful perf records collected"
    err_rate = len(failed) / len(records)
    assert err_rate <= max_error_rate, (
        f"Error rate too high: {err_rate:.3f} > {max_error_rate:.3f} "
        f"(failed={len(failed)} total={len(records)})"
    )

    assert any(r["mode"] == "stream" and r["chunk_count"] > 0 for r in success), (
        "Expected at least one stream run with content chunks"
    )
    assert all(float(r["e2e_ms"]) > 0 for r in success), "All successful runs must have positive latency"

    summary = _summarize(success)
    require_ctx_markers = _bool_env("AI_PERF_REQUIRE_CONTEXT_MARKERS", False)
    if require_ctx_markers:
        has_ctx = any(
            (r.get("context_chars") is not None)
            or (r.get("retrieval_count") is not None)
            or (r.get("context_sources") is not None)
            for r in success
        )
        assert has_ctx, "Context markers required but not present in perf stream"

    _assert_thresholds(summary)
    _assert_baseline_regression(summary)

    report = {
        "meta": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "base_url": base_url,
            "model": model,
            "prompts": prompts,
            "runs": runs,
            "warmup": warmup,
            "timeout_s": timeout_s,
            "health_timeout_s": health_timeout_s,
            "health_retries": health_retries,
            "max_retries": max_retries,
            "max_error_rate": max_error_rate,
            "env": {
                "AI_TEST_LIVE": os.getenv("AI_TEST_LIVE", ""),
                "AI_PERF_ENABLE": os.getenv("AI_PERF_ENABLE", ""),
                "AI_PERF_BASELINE": os.getenv("AI_PERF_BASELINE", ""),
                "AI_PERF_MAX_REGRESSION_PCT": os.getenv("AI_PERF_MAX_REGRESSION_PCT", ""),
                "AI_PERF_EMBED_CPU_ONLY": os.getenv("AI_PERF_EMBED_CPU_ONLY", ""),
                "AI_PERF_FORCE_ROUTING_EMBEDDING_AUTO": os.getenv("AI_PERF_FORCE_ROUTING_EMBEDDING_AUTO", ""),
            },
            "embedding_cpu_mode": cpu_embed_state,
        },
        "summary": summary,
        "failed_runs": failed,
        "records": records,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(
        "[perf] "
        f"overall_p95_e2e_ms={summary.get('overall', {}).get('p95_e2e_ms', 0)} "
        f"stream_p95_ttft_ms={summary.get('stream', {}).get('p95_ttft_ms', 0)} "
        f"stream_p50_tps={summary.get('stream', {}).get('p50_tokens_per_sec', 0)} "
        f"overall_p95_total_tokens={summary.get('overall', {}).get('p95_total_tokens_est', 0)}"
    )
    print(f"[perf] report={report_path}")
