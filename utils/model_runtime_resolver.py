"""
utils/model_runtime_resolver.py

Runtime resolver for chat models on a concrete Ollama endpoint.
Goal: avoid forwarding invalid request model identifiers into /api/chat.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Tuple

import requests


_CACHE_LOCK = threading.Lock()
_TAGS_CACHE: Dict[str, Dict[str, Any]] = {}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _is_truthy(value: str) -> bool:
    return _normalize_text(value).lower() in {"1", "true", "yes", "on"}


def _cache_ttl_seconds() -> float:
    raw = _normalize_text(os.getenv("TRION_MODEL_TAGS_CACHE_TTL", "8"))
    try:
        val = float(raw)
    except Exception:
        val = 8.0
    return max(0.0, min(120.0, val))


def _tags_timeout_seconds() -> float:
    raw = _normalize_text(os.getenv("TRION_MODEL_TAGS_TIMEOUT_S", "1.2"))
    try:
        val = float(raw)
    except Exception:
        val = 1.2
    return max(0.1, min(10.0, val))


def _normalize_endpoint(endpoint: str) -> str:
    return _normalize_text(endpoint).rstrip("/")


def _read_cached_tags(endpoint: str) -> Tuple[bool, List[str]]:
    ttl = _cache_ttl_seconds()
    if ttl <= 0:
        return False, []
    now = time.monotonic()
    with _CACHE_LOCK:
        item = _TAGS_CACHE.get(endpoint)
        if not item:
            return False, []
        ts = float(item.get("ts", 0.0))
        if now - ts > ttl:
            return False, []
        names = item.get("names", [])
        if not isinstance(names, list):
            return False, []
        out = [str(n).strip() for n in names if str(n).strip()]
        return True, out


def _write_cached_tags(endpoint: str, names: List[str]) -> None:
    with _CACHE_LOCK:
        _TAGS_CACHE[endpoint] = {
            "ts": time.monotonic(),
            "names": [str(n).strip() for n in names if str(n).strip()],
        }


def _fetch_tags(endpoint: str) -> Tuple[bool, List[str]]:
    if not endpoint:
        return False, []
    cached_ok, cached_names = _read_cached_tags(endpoint)
    if cached_ok:
        return True, cached_names

    timeout_s = _tags_timeout_seconds()
    try:
        resp = requests.get(f"{endpoint}/api/tags", timeout=timeout_s)
        if int(resp.status_code) >= 400:
            return False, []
        payload = resp.json() if resp.content else {}
    except Exception:
        return False, []

    raw_models = payload.get("models", []) if isinstance(payload, dict) else []
    names: List[str] = []
    seen = set()
    for item in raw_models:
        if isinstance(item, dict):
            name = _normalize_text(item.get("name"))
        else:
            name = _normalize_text(item)
        if not name or name in seen:
            continue
        names.append(name)
        seen.add(name)

    _write_cached_tags(endpoint, names)
    return True, names


def _match_case_insensitive(model: str, available: List[str]) -> str:
    want = _normalize_text(model).lower()
    if not want:
        return ""
    hits = [m for m in available if m.lower() == want]
    if len(hits) == 1:
        return hits[0]
    return ""


def resolve_runtime_chat_model(
    requested_model: str,
    *,
    endpoint: str,
    fallback_model: str,
) -> Dict[str, Any]:
    """
    Resolve a runtime-safe model for /api/chat.

    Returns:
      {
        "requested_model": str,
        "resolved_model": str,
        "fallback_model": str,
        "endpoint": str,
        "tags_ok": bool,
        "available_count": int,
        "used_fallback": bool,
        "reason": str,
      }
    """
    requested = _normalize_text(requested_model)
    fallback = _normalize_text(fallback_model)
    endpoint_norm = _normalize_endpoint(endpoint)

    result: Dict[str, Any] = {
        "requested_model": requested,
        "resolved_model": "",
        "fallback_model": fallback,
        "endpoint": endpoint_norm,
        "tags_ok": False,
        "available_count": 0,
        "used_fallback": False,
        "reason": "unresolved",
    }

    if not _is_truthy(os.getenv("TRION_RUNTIME_MODEL_RESOLVE", "true")):
        chosen = requested or fallback
        result["resolved_model"] = chosen
        result["used_fallback"] = bool(chosen and chosen != requested)
        result["reason"] = "runtime_resolution_disabled"
        return result

    if not requested:
        result["resolved_model"] = fallback
        result["used_fallback"] = bool(fallback)
        result["reason"] = "empty_requested_model"
        return result

    tags_ok, available = _fetch_tags(endpoint_norm)
    result["tags_ok"] = bool(tags_ok)
    result["available_count"] = len(available)

    if tags_ok and available:
        available_set = set(available)
        if requested in available_set:
            result["resolved_model"] = requested
            result["reason"] = "requested_available_exact"
            return result

        ci_match = _match_case_insensitive(requested, available)
        if ci_match:
            result["resolved_model"] = ci_match
            result["used_fallback"] = bool(ci_match != requested)
            result["reason"] = "requested_available_case_insensitive"
            return result

        if fallback:
            if fallback in available_set:
                result["resolved_model"] = fallback
                result["used_fallback"] = bool(fallback != requested)
                result["reason"] = "requested_unavailable_fallback_available"
                return result
            fallback_ci = _match_case_insensitive(fallback, available)
            if fallback_ci:
                result["resolved_model"] = fallback_ci
                result["used_fallback"] = bool(fallback_ci != requested)
                result["reason"] = "requested_unavailable_fallback_case_insensitive"
                return result

        result["resolved_model"] = available[0]
        result["used_fallback"] = bool(available[0] != requested)
        result["reason"] = "requested_unavailable_first_available"
        return result

    # Fail-open with deterministic fallback if model inventory is unavailable.
    if fallback:
        result["resolved_model"] = fallback
        result["used_fallback"] = bool(fallback != requested)
        result["reason"] = "tags_unavailable_fallback_model"
        return result

    result["resolved_model"] = requested
    result["used_fallback"] = False
    result["reason"] = "tags_unavailable_keep_requested"
    return result

