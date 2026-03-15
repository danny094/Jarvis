"""
Runtime state for secret resolve throttling in cloud API key lookup.
"""

from __future__ import annotations

import threading
from typing import Dict, Iterable, List, Tuple


_LOCK = threading.Lock()
_PROVIDER_MISS_TS: Dict[str, float] = {}
_SECRET_NOT_FOUND_TS: Dict[Tuple[str, str], float] = {}
_PREFERRED_SECRET: Dict[str, str] = {}


def _norm_provider(provider: str) -> str:
    return str(provider or "").strip().lower()


def _norm_secret(name: str) -> str:
    return str(name or "").strip().upper()


def clear_provider_miss(provider: str) -> None:
    key = _norm_provider(provider)
    with _LOCK:
        _PROVIDER_MISS_TS.pop(key, None)


def mark_provider_miss(provider: str, now: float) -> None:
    key = _norm_provider(provider)
    if not key:
        return
    with _LOCK:
        _PROVIDER_MISS_TS[key] = float(now)


def provider_miss_active(provider: str, now: float, ttl_s: float) -> bool:
    key = _norm_provider(provider)
    if not key:
        return False
    try:
        ttl = max(0.0, float(ttl_s))
    except Exception:
        ttl = 0.0
    if ttl <= 0.0:
        return False
    with _LOCK:
        ts = _PROVIDER_MISS_TS.get(key)
    return ts is not None and (float(now) - float(ts)) < ttl


def mark_secret_not_found(provider: str, name: str, now: float) -> None:
    p = _norm_provider(provider)
    n = _norm_secret(name)
    if not p or not n:
        return
    with _LOCK:
        _SECRET_NOT_FOUND_TS[(p, n)] = float(now)


def secret_not_found_active(provider: str, name: str, now: float, ttl_s: float) -> bool:
    p = _norm_provider(provider)
    n = _norm_secret(name)
    if not p or not n:
        return False
    try:
        ttl = max(0.0, float(ttl_s))
    except Exception:
        ttl = 0.0
    if ttl <= 0.0:
        return False
    with _LOCK:
        ts = _SECRET_NOT_FOUND_TS.get((p, n))
    return ts is not None and (float(now) - float(ts)) < ttl


def mark_secret_success(provider: str, name: str) -> None:
    p = _norm_provider(provider)
    n = _norm_secret(name)
    if not p or not n:
        return
    with _LOCK:
        _PREFERRED_SECRET[p] = n
        _SECRET_NOT_FOUND_TS.pop((p, n), None)
        _PROVIDER_MISS_TS.pop(p, None)


def order_candidates(provider: str, names: Iterable[str]) -> List[str]:
    p = _norm_provider(provider)
    ordered: List[str] = []
    seen = set()
    for raw in names or []:
        n = _norm_secret(raw)
        if not n or n in seen:
            continue
        seen.add(n)
        ordered.append(n)

    if not ordered:
        return ordered

    with _LOCK:
        preferred = _PREFERRED_SECRET.get(p)
    if preferred and preferred in seen and ordered[0] != preferred:
        ordered.remove(preferred)
        ordered.insert(0, preferred)
    return ordered


def reset_secret_resolve_runtime_state() -> None:
    with _LOCK:
        _PROVIDER_MISS_TS.clear()
        _SECRET_NOT_FOUND_TS.clear()
        _PREFERRED_SECRET.clear()
