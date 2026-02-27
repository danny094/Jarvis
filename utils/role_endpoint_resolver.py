"""
utils/role_endpoint_resolver.py

Runtime endpoint resolution for LLM roles:
  thinking, control, output, tool_selector, embedding

Phase C goals:
- honor persisted layer routing from /api/runtime/compute/routing
- apply deterministic endpoint selection via the compute manager snapshot
- fail closed (hard_error) on explicit pinning without viable fallback
"""
from __future__ import annotations

import os
import time
import threading
from typing import Any, Dict, Optional

import requests

from config import OLLAMA_BASE
from utils import ollama_endpoint_manager as _compute


_CACHE_LOCK = threading.Lock()
_CACHE: Dict[str, Any] = {
    "ts": 0.0,
    "snapshot": None,
}
_CACHE_TTL_SECONDS = float(os.getenv("TRION_ROLE_ROUTING_CACHE_TTL", "3"))

_DISCOVERY_CACHE_LOCK = threading.Lock()
_DISCOVERY_CACHE: Dict[str, Dict[str, Any]] = {}
_DISCOVERY_TTL_SECONDS = float(os.getenv("TRION_OLLAMA_DISCOVERY_TTL", "15"))
_DISCOVERY_TIMEOUT_S = float(os.getenv("TRION_OLLAMA_DISCOVERY_TIMEOUT_S", "0.35"))


def _is_truthy(value: str) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_endpoint(endpoint: str) -> str:
    return (endpoint or "").strip().rstrip("/")


def _candidate_default_endpoints(preferred: str) -> list[str]:
    custom_raw = os.getenv("TRION_OLLAMA_DISCOVERY_CANDIDATES", "").strip()
    custom = [x.strip().rstrip("/") for x in custom_raw.split(",") if x.strip()]
    defaults = [
        preferred,
        "http://host.docker.internal:11434",
        "http://ollama:11434",
        "http://172.17.0.1:11434",
        "http://172.18.0.1:11434",
        "http://127.0.0.1:11434",
        "http://localhost:11434",
    ]
    out: list[str] = []
    seen = set()
    for ep in custom + defaults:
        ep = _normalize_endpoint(ep)
        if not ep or ep in seen:
            continue
        seen.add(ep)
        out.append(ep)
    return out


def _probe_ollama_tags(endpoint: str) -> bool:
    try:
        resp = requests.get(f"{endpoint}/api/tags", timeout=_DISCOVERY_TIMEOUT_S)
        return int(resp.status_code) < 400
    except Exception:
        return False


def clear_ollama_discovery_cache() -> None:
    with _DISCOVERY_CACHE_LOCK:
        _DISCOVERY_CACHE.clear()


def resolve_ollama_base_endpoint(default_endpoint: Optional[str] = None) -> str:
    preferred = _normalize_endpoint((default_endpoint or OLLAMA_BASE).strip())
    if not preferred:
        preferred = _normalize_endpoint(OLLAMA_BASE)

    if not _is_truthy(os.getenv("TRION_OLLAMA_AUTODETECT", "true")):
        return preferred

    now = time.monotonic()
    with _DISCOVERY_CACHE_LOCK:
        cached = _DISCOVERY_CACHE.get(preferred)
        if cached and (now - float(cached.get("ts", 0.0))) < _DISCOVERY_TTL_SECONDS:
            return str(cached.get("endpoint") or preferred)

    chosen = preferred
    for candidate in _candidate_default_endpoints(preferred):
        if _probe_ollama_tags(candidate):
            chosen = candidate
            break

    with _DISCOVERY_CACHE_LOCK:
        _DISCOVERY_CACHE[preferred] = {"ts": now, "endpoint": chosen}
    return chosen


def clear_role_routing_cache() -> None:
    with _CACHE_LOCK:
        _CACHE["ts"] = 0.0
        _CACHE["snapshot"] = None


def _build_snapshot() -> Dict[str, Any]:
    instances = _compute.list_instances()
    layer_routing = _compute.get_layer_routing()
    effective = _compute.resolve_layer_routing(
        layer_routing=layer_routing,
        instances_snapshot=instances,
    )
    return {
        "instances": instances,
        "layer_routing": layer_routing,
        "effective": effective,
    }


def _get_snapshot() -> Optional[Dict[str, Any]]:
    now = time.monotonic()
    stale_cached = None
    with _CACHE_LOCK:
        cached = _CACHE.get("snapshot")
        stale_cached = cached
        if cached is not None and (now - float(_CACHE.get("ts", 0.0))) < _CACHE_TTL_SECONDS:
            return cached
    try:
        snapshot = _build_snapshot()
    except Exception:
        # Prefer stale snapshot over full fallback-to-default to reduce routing flapping
        # during short compute-manager outages.
        if stale_cached is not None:
            return stale_cached
        return None
    with _CACHE_LOCK:
        _CACHE["snapshot"] = snapshot
        _CACHE["ts"] = now
    return snapshot


def _instances_from_snapshot(snapshot: Dict[str, Any]) -> list[Dict[str, Any]]:
    raw = snapshot.get("instances")
    if isinstance(raw, dict):
        items = raw.get("instances")
        if isinstance(items, list):
            return [it for it in items if isinstance(it, dict)]
        return []
    if isinstance(raw, list):
        return [it for it in raw if isinstance(it, dict)]
    return []


def _recover_endpoint_from_instances(
    snapshot: Dict[str, Any],
    requested_target: str,
    effective_target: Optional[str],
) -> Optional[Dict[str, Any]]:
    """
    Recover endpoint from instance inventory when effective routing is incomplete.
    This prevents unnecessary fallback to legacy default endpoint.
    """
    instances = _instances_from_snapshot(snapshot)
    if not instances:
        return None

    by_id: Dict[str, Dict[str, Any]] = {}
    for inst in instances:
        inst_id = str(inst.get("id") or "").strip()
        endpoint = _normalize_endpoint(str(inst.get("endpoint") or ""))
        if not inst_id or not endpoint:
            continue
        by_id[inst_id] = inst

    if not by_id:
        return None

    def _is_recoverable(inst: Dict[str, Any]) -> bool:
        return bool(inst.get("running")) and bool((inst.get("health") or {}).get("ok"))

    def _pick(inst_id: str, reason: str) -> Optional[Dict[str, Any]]:
        inst = by_id.get(inst_id)
        if not inst:
            return None
        if not _is_recoverable(inst):
            return None
        endpoint = _normalize_endpoint(str(inst.get("endpoint") or ""))
        if not endpoint:
            return None
        return {
            "effective_target": inst_id,
            "endpoint": endpoint,
            "fallback_reason": reason,
        }

    # 1) Honor explicit/effective target first if endpoint exists.
    if effective_target:
        picked = _pick(str(effective_target), "missing_effective_endpoint_recovered")
        if picked:
            return picked
    if requested_target and requested_target != "auto":
        picked = _pick(requested_target, "missing_requested_endpoint_recovered")
        if picked:
            return picked

    # 2) Auto recovery by runtime availability/health.
    def _rank(inst: Dict[str, Any]) -> tuple[int, int, str]:
        target = str(inst.get("target") or "")
        running = bool(inst.get("running"))
        healthy = bool((inst.get("health") or {}).get("ok"))
        # Higher is better
        availability = 3 if (running and healthy) else (2 if running else (1 if healthy else 0))
        # Prefer GPU over CPU for auto parity with compute manager.
        target_pref = 1 if target == "gpu" else 0
        inst_id = str(inst.get("id") or "")
        return (availability, target_pref, inst_id)

    candidates = [it for it in by_id.values() if _is_recoverable(it)]
    candidates.sort(key=_rank, reverse=True)
    if not candidates:
        return None

    top = candidates[0]
    top_id = str(top.get("id") or "")
    if not top_id:
        return None
    return _pick(top_id, "no_target_available_recovered")


def resolve_role_endpoint(role: str, default_endpoint: Optional[str] = None) -> Dict[str, Any]:
    """
    Resolve effective endpoint for a role based on compute manager routing.

    Returns:
      {
        "role": str,
        "requested_target": str,
        "effective_target": str|None,
        "endpoint": str|None,
        "endpoint_source": "compute_manager"|"default",
        "fallback_reason": str|None,
        "hard_error": bool,
        "error_code": int|None,
      }
    """
    role_norm = (role or "").strip().lower()
    default_ep = resolve_ollama_base_endpoint(default_endpoint=default_endpoint)

    if role_norm not in _compute.ROLES:
        return {
            "role": role_norm or "unknown",
            "requested_target": "auto",
            "effective_target": None,
            "endpoint": default_ep,
            "endpoint_source": "default",
            "fallback_reason": "unknown_role",
            "hard_error": False,
            "error_code": None,
        }

    snap = _get_snapshot()
    if not snap:
        return {
            "role": role_norm,
            "requested_target": "auto",
            "effective_target": None,
            "endpoint": default_ep,
            "endpoint_source": "default",
            "fallback_reason": "compute_snapshot_unavailable",
            "hard_error": False,
            "error_code": None,
        }

    eff = (snap.get("effective", {}) or {}).get(role_norm, {}) or {}
    requested = str(eff.get("requested_target") or "auto")
    effective_target = eff.get("effective_target")
    endpoint = eff.get("effective_endpoint")
    fallback_reason = eff.get("fallback_reason")

    if endpoint:
        return {
            "role": role_norm,
            "requested_target": requested,
            "effective_target": effective_target,
            "endpoint": endpoint,
            "endpoint_source": "compute_manager",
            "fallback_reason": fallback_reason,
            "hard_error": False,
            "error_code": None,
        }

    recovered = _recover_endpoint_from_instances(
        snapshot=snap,
        requested_target=requested,
        effective_target=effective_target,
    )
    if recovered:
        rec_reason = recovered.get("fallback_reason")
        merged_reason = fallback_reason or rec_reason
        return {
            "role": role_norm,
            "requested_target": requested,
            "effective_target": recovered.get("effective_target") or effective_target,
            "endpoint": recovered.get("endpoint"),
            "endpoint_source": "compute_manager_recovery",
            "fallback_reason": merged_reason,
            "hard_error": False,
            "error_code": None,
        }

    # Fail-closed only for explicit pinning.
    if requested != "auto":
        return {
            "role": role_norm,
            "requested_target": requested,
            "effective_target": effective_target,
            "endpoint": None,
            "endpoint_source": "compute_manager",
            "fallback_reason": fallback_reason or "requested_unavailable",
            "hard_error": True,
            "error_code": 503,
        }

    # Auto mode with no healthy target falls back to legacy endpoint.
    return {
        "role": role_norm,
        "requested_target": requested,
        "effective_target": effective_target,
        "endpoint": default_ep,
        "endpoint_source": "default",
        "fallback_reason": fallback_reason or "no_target_available",
        "hard_error": False,
        "error_code": None,
    }
