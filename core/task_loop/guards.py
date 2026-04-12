from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Dict, Iterable, List, Optional

from core.task_loop.contracts import RiskLevel, StopReason, TaskLoopSnapshot


@dataclass(frozen=True)
class StopDecision:
    should_stop: bool
    reason: Optional[StopReason] = None
    detail: str = ""


def fingerprint_action(value: Any) -> str:
    normalized = json.dumps(value, sort_keys=True, default=str, ensure_ascii=True)
    return sha256(normalized.encode("utf-8")).hexdigest()[:16]


def detect_loop(actions: Iterable[Any], *, repeated_threshold: int = 2) -> bool:
    if repeated_threshold <= 1:
        raise ValueError("repeated_threshold must be > 1")

    fingerprints: List[str] = [fingerprint_action(action) for action in actions]
    if len(fingerprints) < repeated_threshold:
        return False
    tail = fingerprints[-repeated_threshold:]
    return len(set(tail)) == 1


def _coerce_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def evaluate_stop_conditions(
    snapshot: TaskLoopSnapshot,
    *,
    max_steps: int,
    max_runtime_s: int = 0,
    started_at: Any = None,
    now: Any = None,
    progress_made: bool = True,
    repeated_action_threshold: int = 2,
) -> StopDecision:
    if max_steps <= 0:
        return StopDecision(True, StopReason.MAX_STEPS_REACHED, "max_steps must be positive")

    if snapshot.step_index >= max_steps:
        return StopDecision(
            True,
            StopReason.MAX_STEPS_REACHED,
            f"step_index={snapshot.step_index} max_steps={max_steps}",
        )

    if max_runtime_s > 0:
        start_dt = _coerce_datetime(started_at)
        now_dt = _coerce_datetime(now) or datetime.now(timezone.utc)
        if start_dt and (now_dt - start_dt).total_seconds() >= max_runtime_s:
            return StopDecision(
                True,
                StopReason.MAX_RUNTIME_REACHED,
                f"max_runtime_s={max_runtime_s}",
            )

    if snapshot.risk_level in {RiskLevel.NEEDS_CONFIRMATION, RiskLevel.RISKY}:
        return StopDecision(True, StopReason.RISK_GATE_REQUIRED, snapshot.risk_level.value)

    if snapshot.risk_level == RiskLevel.BLOCKED:
        return StopDecision(True, StopReason.NO_CONCRETE_NEXT_STEP, snapshot.risk_level.value)

    if not progress_made:
        return StopDecision(True, StopReason.NO_PROGRESS, "progress_made=false")

    if detect_loop(snapshot.tool_trace, repeated_threshold=repeated_action_threshold):
        return StopDecision(
            True,
            StopReason.LOOP_DETECTED,
            f"repeated_action_threshold={repeated_action_threshold}",
        )

    pending = snapshot.pending_step.strip()
    if not pending and snapshot.state.value in {"planning", "reflecting"}:
        return StopDecision(True, StopReason.NO_CONCRETE_NEXT_STEP, "missing pending_step")

    return StopDecision(False)
