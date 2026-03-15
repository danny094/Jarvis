"""
Runtime-safe MCP Hub access helpers.

Purpose:
- avoid hard stream crashes when MCP hub import/init is temporarily unavailable
- keep failure mode explicit and observable
"""

from __future__ import annotations

from typing import Any, Callable, Optional


def get_initialized_hub_safe(
    *,
    log_warn_fn: Optional[Callable[[str], None]] = None,
) -> Any | None:
    """
    Return initialized MCP hub or None on failure.

    This helper intentionally imports get_hub at runtime so partially-loaded
    modules / hot-reload transients do not hard-crash callers.
    """
    try:
        from mcp.hub import get_hub as _get_hub
    except Exception as exc:
        if callable(log_warn_fn):
            log_warn_fn(f"[ToolHubRuntime] import failed: {type(exc).__name__}: {exc}")
        return None

    try:
        hub = _get_hub()
    except Exception as exc:
        if callable(log_warn_fn):
            log_warn_fn(f"[ToolHubRuntime] get_hub failed: {type(exc).__name__}: {exc}")
        return None

    try:
        hub.initialize()
    except Exception as exc:
        if callable(log_warn_fn):
            log_warn_fn(f"[ToolHubRuntime] initialize failed: {type(exc).__name__}: {exc}")
        return None

    return hub

