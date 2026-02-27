"""
utils/embedding_health.py — Embedding Endpoint Health Checker

Checks availability of GPU/CPU embedding endpoints with TTL cache.
Returns {"gpu": bool, "cpu": bool} for use by the embedding router.
"""
from __future__ import annotations

import time
from typing import Dict, Optional

import requests as _requests

_DEFAULT_CACHE_TTL: float = 30.0  # seconds

_health_cache: Dict[str, dict] = {}  # url → {"status": bool, "ts": float}


def _check_endpoint(url: str, timeout: float) -> bool:
    """HEAD /api/version — returns True if reachable (HTTP < 500)."""
    try:
        resp = _requests.get(f"{url}/api/version", timeout=timeout)
        return resp.status_code < 500
    except Exception:
        return False


def check_embedding_availability(
    base_endpoint: str,
    gpu_endpoint: str = "",
    cpu_endpoint: str = "",
    endpoint_mode: str = "single",
    timeout: float = 2.0,
    cache_ttl: float = _DEFAULT_CACHE_TTL,
) -> Dict[str, bool]:
    """
    Return {"gpu": bool, "cpu": bool} indicating which targets are reachable.

    Single mode: both gpu and cpu reflect the same base_endpoint health.
    Dual mode: each endpoint checked independently; falls back to base if
               dedicated endpoint is not configured.

    Results are cached per URL for cache_ttl seconds.
    """

    def _cached_check(url: str) -> bool:
        now = time.monotonic()
        cached = _health_cache.get(url)
        if cached and (now - cached["ts"]) < cache_ttl:
            return cached["status"]
        status = _check_endpoint(url, timeout)
        _health_cache[url] = {"status": status, "ts": now}
        return status

    eff_gpu = (gpu_endpoint or "").strip()
    eff_cpu = (cpu_endpoint or "").strip()

    if endpoint_mode == "dual":
        gpu_url = eff_gpu if eff_gpu else base_endpoint
        cpu_url = eff_cpu if eff_cpu else base_endpoint
        return {"gpu": _cached_check(gpu_url), "cpu": _cached_check(cpu_url)}

    # Single mode — one endpoint serves both
    base_ok = _cached_check(base_endpoint)
    return {"gpu": base_ok, "cpu": base_ok}


def clear_health_cache() -> None:
    """Clear the health cache (for testing / forced re-check)."""
    _health_cache.clear()
