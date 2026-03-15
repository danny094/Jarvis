"""
Runtime registry for the Autonomy Cron Scheduler singleton.

This decouples scheduler users (API routes, MCP tools, etc.) from app module imports.
"""

from __future__ import annotations

from typing import Any, Optional

_scheduler: Optional[Any] = None


def set_scheduler(scheduler: Any) -> None:
    global _scheduler
    _scheduler = scheduler


def get_scheduler() -> Optional[Any]:
    return _scheduler


def clear_scheduler() -> None:
    global _scheduler
    _scheduler = None

