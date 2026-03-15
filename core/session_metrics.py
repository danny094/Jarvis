"""
core/session_metrics.py

Runtime session telemetry for WebUI dashboards.
"""
from __future__ import annotations

import math
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict


_LOCK = threading.Lock()
_START_TS = time.time()
_LATENCY_SAMPLES_MS: list[float] = []
_LATENCY_MAX_SAMPLES = 400

_STATE: Dict[str, Any] = {
    "requests_total": 0,
    "requests_stream": 0,
    "requests_non_stream": 0,
    "errors_total": 0,
    "rate_limit_events": 0,
    "chars_in_total": 0,
    "chars_out_total": 0,
    "tokens_in_est_total": 0,
    "tokens_out_est_total": 0,
    "latency_sum_ms": 0.0,
    "latency_count": 0,
    "last_request_at": "",
    "last_error_at": "",
    "status_codes": {},
    "providers": {},
    "models": {},
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def estimate_tokens_from_chars(chars: int) -> int:
    value = max(0, _as_int(chars, 0))
    if value <= 0:
        return 0
    # Fast and stable estimate for dashboard-only telemetry.
    return int(math.ceil(value / 4.0))


def count_input_chars(messages: Any) -> int:
    total = 0
    for item in messages or []:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    total += len(str(part.get("text") or ""))
                elif isinstance(part, str):
                    total += len(part)
        else:
            total += len(str(content or ""))
    return int(total)


def record_chat_turn(
    *,
    model: str,
    provider: str,
    input_chars: int,
    output_chars: int,
    latency_ms: float,
    stream: bool,
    done_reason: str,
    status_code: int,
) -> None:
    now_iso = _iso_now()
    provider_name = str(provider or "unknown").strip().lower() or "unknown"
    model_name = str(model or "unknown").strip() or "unknown"
    done_reason_norm = str(done_reason or "").strip().lower()
    status = _as_int(status_code, 0)
    in_chars = max(0, _as_int(input_chars, 0))
    out_chars = max(0, _as_int(output_chars, 0))
    in_tokens = estimate_tokens_from_chars(in_chars)
    out_tokens = estimate_tokens_from_chars(out_chars)
    latency = max(0.0, _as_float(latency_ms, 0.0))
    has_error = status >= 400 or done_reason_norm == "error"

    with _LOCK:
        _STATE["requests_total"] += 1
        if stream:
            _STATE["requests_stream"] += 1
        else:
            _STATE["requests_non_stream"] += 1
        if has_error:
            _STATE["errors_total"] += 1
            _STATE["last_error_at"] = now_iso
        if status == 429:
            _STATE["rate_limit_events"] += 1

        _STATE["chars_in_total"] += in_chars
        _STATE["chars_out_total"] += out_chars
        _STATE["tokens_in_est_total"] += in_tokens
        _STATE["tokens_out_est_total"] += out_tokens
        _STATE["latency_sum_ms"] += latency
        _STATE["latency_count"] += 1
        _STATE["last_request_at"] = now_iso

        sc_key = str(status if status > 0 else 0)
        status_codes = _STATE["status_codes"]
        status_codes[sc_key] = int(status_codes.get(sc_key, 0)) + 1

        prov = _STATE["providers"].setdefault(
            provider_name,
            {
                "requests": 0,
                "errors": 0,
                "chars_in": 0,
                "chars_out": 0,
                "tokens_in_est": 0,
                "tokens_out_est": 0,
                "last_model": "",
                "last_seen": "",
            },
        )
        prov["requests"] += 1
        prov["chars_in"] += in_chars
        prov["chars_out"] += out_chars
        prov["tokens_in_est"] += in_tokens
        prov["tokens_out_est"] += out_tokens
        prov["last_model"] = model_name
        prov["last_seen"] = now_iso
        if has_error:
            prov["errors"] += 1

        mdl = _STATE["models"].setdefault(
            model_name,
            {
                "provider": provider_name,
                "requests": 0,
                "errors": 0,
                "tokens_in_est": 0,
                "tokens_out_est": 0,
                "last_seen": "",
            },
        )
        mdl["provider"] = provider_name
        mdl["requests"] += 1
        mdl["tokens_in_est"] += in_tokens
        mdl["tokens_out_est"] += out_tokens
        mdl["last_seen"] = now_iso
        if has_error:
            mdl["errors"] += 1

        _LATENCY_SAMPLES_MS.append(latency)
        if len(_LATENCY_SAMPLES_MS) > _LATENCY_MAX_SAMPLES:
            del _LATENCY_SAMPLES_MS[: len(_LATENCY_SAMPLES_MS) - _LATENCY_MAX_SAMPLES]


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    pos = max(0.0, min(1.0, float(p))) * (len(values) - 1)
    lower = int(math.floor(pos))
    upper = int(math.ceil(pos))
    if lower == upper:
        return float(values[lower])
    frac = pos - lower
    return float(values[lower] * (1.0 - frac) + values[upper] * frac)


def get_session_snapshot() -> Dict[str, Any]:
    with _LOCK:
        now_ts = time.time()
        elapsed_s = max(1e-6, now_ts - float(_START_TS))
        total = int(_STATE["requests_total"])
        avg_latency = (
            float(_STATE["latency_sum_ms"]) / float(_STATE["latency_count"])
            if int(_STATE["latency_count"]) > 0
            else 0.0
        )
        total_tokens = int(_STATE["tokens_in_est_total"]) + int(_STATE["tokens_out_est_total"])
        avg_tokens = (float(total_tokens) / float(total)) if total > 0 else 0.0

        lat_samples = sorted(float(v) for v in _LATENCY_SAMPLES_MS)
        p95_latency = _percentile(lat_samples, 0.95)

        providers = [
            {"provider": name, **dict(vals)}
            for name, vals in dict(_STATE["providers"]).items()
        ]
        providers.sort(key=lambda item: int(item.get("requests", 0)), reverse=True)

        models = [
            {"model": name, **dict(vals)}
            for name, vals in dict(_STATE["models"]).items()
        ]
        models.sort(key=lambda item: int(item.get("requests", 0)), reverse=True)

        return {
            "session": {
                "started_at": datetime.fromtimestamp(_START_TS, tz=timezone.utc).isoformat(),
                "uptime_s": round(elapsed_s, 3),
                "requests_total": total,
                "requests_stream": int(_STATE["requests_stream"]),
                "requests_non_stream": int(_STATE["requests_non_stream"]),
                "errors_total": int(_STATE["errors_total"]),
                "rate_limit_events": int(_STATE["rate_limit_events"]),
                "chars_in_total": int(_STATE["chars_in_total"]),
                "chars_out_total": int(_STATE["chars_out_total"]),
                "tokens_in_est_total": int(_STATE["tokens_in_est_total"]),
                "tokens_out_est_total": int(_STATE["tokens_out_est_total"]),
                "tokens_total_est": int(total_tokens),
                "tokens_per_min_est": round(float(total_tokens) / (elapsed_s / 60.0), 3),
                "avg_tokens_per_request_est": round(avg_tokens, 3),
                "avg_latency_ms": round(avg_latency, 3),
                "p95_latency_ms": round(p95_latency, 3),
                "last_request_at": str(_STATE["last_request_at"]),
                "last_error_at": str(_STATE["last_error_at"]),
                "status_codes": dict(_STATE["status_codes"]),
            },
            "providers": providers,
            "models": models,
        }
