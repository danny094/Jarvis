"""
tests/harness/types.py — Commit A
==================================
Unified result types for sync and stream test runs.

All harness runs produce a HarnessResult regardless of mode.
Stream mode assembles chunk events into response_text automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Stream building block
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StreamEvent:
    """Single chunk or control event from a streaming AI response."""
    index: int
    text: str
    event_type: str = "chunk"   # "chunk" | "done" | "error"
    raw: Dict[str, Any] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Input
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class HarnessInput:
    """Input specification for a single harness test run."""
    prompt: str
    mode: str = "sync"                        # "sync" | "stream"
    conversation_id: str = "test-harness"
    tags: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mode not in ("sync", "stream"):
            raise ValueError(f"mode must be 'sync' or 'stream', got {self.mode!r}")


# ─────────────────────────────────────────────────────────────────────────────
# Result
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class HarnessResult:
    """
    Unified result for both sync and stream runs.

    Fields:
        mode            — "sync" | "stream"
        response_text   — full assembled text
        events          — list of StreamEvent (empty for sync)
        markers         — context markers captured during run:
                            mode, context_sources, context_chars_final, retrieval_count
        elapsed_ms      — wall-clock execution time in milliseconds
        provider        — provider name ("mock" | "live")
        ok              — True if run completed without errors
        error           — error message string or None
        normalized      — response_text after volatile-field masking
        raw             — raw provider response dict (for inspection)
    """
    mode: str
    response_text: str
    events: List[StreamEvent] = field(default_factory=list)
    markers: Dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0
    provider: str = "mock"
    ok: bool = True
    error: Optional[str] = None
    normalized: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_stream(
        cls,
        events: List[StreamEvent],
        markers: Dict[str, Any],
        elapsed_ms: float,
        provider: str,
        error: Optional[str] = None,
    ) -> "HarnessResult":
        """Build a HarnessResult by assembling stream chunk events."""
        text = "".join(e.text for e in events if e.event_type == "chunk")
        return cls(
            mode="stream",
            response_text=text,
            events=events,
            markers=markers,
            elapsed_ms=elapsed_ms,
            provider=provider,
            ok=error is None,
            error=error,
        )

    def chunk_count(self) -> int:
        """Number of chunk events (stream mode only)."""
        return sum(1 for e in self.events if e.event_type == "chunk")

    def has_done_event(self) -> bool:
        """True if a 'done' event was delivered (stream mode)."""
        return any(e.event_type == "done" for e in self.events)
