"""
utils/embedding_metrics.py — Embedding Routing Metrics

Simple in-process counters for embedding routing decisions.
Thread-safe for CPython (GIL-protected dict/list operations).
Reset via reset_metrics() in tests.
"""
from __future__ import annotations

from typing import Dict, List

_METRICS: Dict[str, int] = {
    "routing_fallback_total": 0,
    "routing_target_errors_total": 0,
}

# target → list of latency samples in milliseconds
_LATENCY: Dict[str, List[float]] = {}


def increment_fallback() -> None:
    """Increment routing_fallback_total (effective_target != requested_target)."""
    _METRICS["routing_fallback_total"] += 1


def increment_error() -> None:
    """Increment routing_target_errors_total (hard_error or all-down)."""
    _METRICS["routing_target_errors_total"] += 1


def record_latency(target: str, ms: float) -> None:
    """Record a latency sample for a given target (gpu/cpu)."""
    _LATENCY.setdefault(target, []).append(ms)


def get_metrics() -> dict:
    """Return a snapshot of all metrics including per-target average latency."""
    avg_latency: Dict[str, float] = {}
    for tgt, samples in _LATENCY.items():
        if samples:
            avg_latency[tgt] = round(sum(samples) / len(samples), 1)
    return {
        **_METRICS,
        "embedding_latency_by_target": avg_latency,
    }


def reset_metrics() -> None:
    """Reset all metrics to zero (primarily for tests)."""
    _METRICS["routing_fallback_total"] = 0
    _METRICS["routing_target_errors_total"] = 0
    _LATENCY.clear()
