"""
tests/harness/runner.py — Commit A
=====================================
HarnessRunner: executes a HarnessInput through a provider,
returning a unified HarnessResult for both sync and stream modes.

Normalizer strips volatile fields (timestamps, UUIDs, epoch ints)
for stable golden comparisons.
"""
from __future__ import annotations

import re
import time
from typing import Dict, List, Optional

from tests.harness.types import HarnessInput, HarnessResult, StreamEvent


# ─────────────────────────────────────────────────────────────────────────────
# Normalizer — strips volatile fields for golden comparison
# ─────────────────────────────────────────────────────────────────────────────

_VOLATILE_PATTERNS: List[tuple] = [
    # ISO 8601 timestamps (with optional fractional seconds and timezone)
    (r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?",
     "<TIMESTAMP>"),
    # UUIDs / request IDs (hex8-hex4-hex4-hex4-hex12)
    (r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
     "<UUID>"),
    # Plain ISO dates YYYY-MM-DD (standalone, not part of a timestamp)
    (r"\b\d{4}-\d{2}-\d{2}\b",
     "<DATE>"),
    # Unix epoch integers (10+ digits = millisecond or second epoch)
    (r"\b\d{10,13}\b",
     "<EPOCH>"),
]


def normalize_response(text: str) -> str:
    """
    Strip volatile fields from a response string for stable golden comparisons.
    Applied in order: timestamps first (greedily), then UUIDs, dates, epoch ints.

    Returns the normalized string stripped of leading/trailing whitespace.
    """
    result = text
    for pattern, replacement in _VOLATILE_PATTERNS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

class HarnessRunner:
    """
    Executes HarnessInput through a provider, returning HarnessResult.

    Provider contract:
        run_sync(prompt, conversation_id, extra) -> dict
            dict keys: text (str), markers (dict), error (str|None)

        run_stream(prompt, conversation_id, extra) -> Iterable[dict]
            dict keys per chunk: text (str), done (bool), markers (dict), error (str|None)

    Both sync and stream test cases run through the same Runner.run() entry point.
    """

    def __init__(self, provider, normalize: bool = True) -> None:
        self.provider = provider
        self.normalize = normalize

    @property
    def provider_name(self) -> str:
        return getattr(self.provider, "name", "unknown")

    def run(self, inp: HarnessInput) -> HarnessResult:
        """Execute a test case. Delegates to sync or stream path based on inp.mode."""
        if inp.mode == "sync":
            return self._run_sync(inp)
        return self._run_stream(inp)

    # ── Sync path ──────────────────────────────────────────────────────────

    def _run_sync(self, inp: HarnessInput) -> HarnessResult:
        t0 = time.monotonic()
        try:
            raw = self.provider.run_sync(
                prompt=inp.prompt,
                conversation_id=inp.conversation_id,
                extra=inp.extra,
            )
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            return HarnessResult(
                mode="sync",
                response_text="",
                markers={},
                elapsed_ms=elapsed,
                provider=self.provider_name,
                ok=False,
                error=str(exc),
            )

        elapsed = (time.monotonic() - t0) * 1000
        text = raw.get("text", "")
        markers: Dict = raw.get("markers", {})
        markers.setdefault("mode", "sync")

        result = HarnessResult(
            mode="sync",
            response_text=text,
            markers=markers,
            elapsed_ms=elapsed,
            provider=self.provider_name,
            ok=raw.get("error") is None,
            error=raw.get("error"),
            raw=raw,
        )
        if self.normalize:
            result.normalized = normalize_response(text)
        return result

    # ── Stream path ────────────────────────────────────────────────────────

    def _run_stream(self, inp: HarnessInput) -> HarnessResult:
        t0 = time.monotonic()
        events: List[StreamEvent] = []
        markers: Dict = {}
        error: Optional[str] = None

        try:
            for i, chunk in enumerate(self.provider.run_stream(
                prompt=inp.prompt,
                conversation_id=inp.conversation_id,
                extra=inp.extra,
            )):
                if chunk.get("error"):
                    error = chunk["error"]
                    events.append(StreamEvent(index=i, text="", event_type="error", raw=chunk))
                    break
                evt_type = "done" if chunk.get("done") else "chunk"
                events.append(StreamEvent(
                    index=i,
                    text=chunk.get("text", ""),
                    event_type=evt_type,
                    raw=chunk,
                ))
                if chunk.get("markers"):
                    markers.update(chunk["markers"])
        except Exception as exc:
            error = str(exc)

        elapsed = (time.monotonic() - t0) * 1000
        markers.setdefault("mode", "stream")

        result = HarnessResult.from_stream(
            events=events,
            markers=markers,
            elapsed_ms=elapsed,
            provider=self.provider_name,
            error=error,
        )
        if self.normalize:
            result.normalized = normalize_response(result.response_text)
        return result
