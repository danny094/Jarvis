"""
tests/harness/assertions.py — Commit A
========================================
Assertion helpers for HarnessResult objects.

Raises HarnessAssertionError with structured output on failure.
All public functions follow the pattern: assert_*(result, ...).
"""
from __future__ import annotations

from typing import Any, Optional

from tests.harness.types import HarnessResult


# ─────────────────────────────────────────────────────────────────────────────
# Error type
# ─────────────────────────────────────────────────────────────────────────────

class HarnessAssertionError(AssertionError):
    """Detailed assertion error with structured context from the run result."""

    def __init__(self, msg: str, result: Optional[HarnessResult] = None) -> None:
        detail = ""
        if result is not None:
            detail = (
                f"\n  provider={result.provider!r}"
                f"  mode={result.mode!r}"
                f"  ok={result.ok}"
                f"  elapsed_ms={result.elapsed_ms:.1f}ms"
                f"\n  response={result.response_text[:240]!r}"
                f"\n  markers={result.markers}"
            )
            if result.error:
                detail += f"\n  error={result.error!r}"
        super().__init__(msg + detail)


# ─────────────────────────────────────────────────────────────────────────────
# Core assertions
# ─────────────────────────────────────────────────────────────────────────────

def assert_ok(result: HarnessResult) -> None:
    """Assert the run completed without errors."""
    if not result.ok:
        raise HarnessAssertionError(
            f"Expected ok=True but run failed with: {result.error}", result
        )


def assert_contains(result: HarnessResult, text: str) -> None:
    """Assert response_text contains the given substring (case-sensitive)."""
    assert_ok(result)
    if text not in result.response_text:
        raise HarnessAssertionError(
            f"Expected response to contain {text!r}",
            result,
        )


def assert_not_contains(result: HarnessResult, text: str) -> None:
    """Assert response_text does NOT contain the given substring."""
    assert_ok(result)
    if text in result.response_text:
        raise HarnessAssertionError(
            f"Expected response NOT to contain {text!r}",
            result,
        )


def assert_event(result: HarnessResult, event_type: str) -> None:
    """
    Assert at least one StreamEvent of the given event_type exists.
    Only meaningful for stream mode; raises HarnessAssertionError in sync mode.
    """
    if result.mode != "stream":
        raise HarnessAssertionError(
            f"assert_event requires stream mode, got {result.mode!r}", result
        )
    found = any(e.event_type == event_type for e in result.events)
    if not found:
        types_seen = list({e.event_type for e in result.events})
        raise HarnessAssertionError(
            f"Expected StreamEvent type={event_type!r}, found types: {types_seen}",
            result,
        )


def assert_context_markers(result: HarnessResult, **expected: Any) -> None:
    """
    Assert specific context markers are present and match expected values.

    Example:
        assert_context_markers(result, mode="sync", retrieval_count=1)
    """
    assert_ok(result)
    mismatches = []
    for key, expected_val in expected.items():
        actual_val = result.markers.get(key)
        if actual_val != expected_val:
            mismatches.append(f"  markers[{key!r}]: expected {expected_val!r}, got {actual_val!r}")
    if mismatches:
        raise HarnessAssertionError(
            "Marker mismatch(es):\n" + "\n".join(mismatches),
            result,
        )


def assert_normalized_stable(result: HarnessResult, snapshot: str) -> None:
    """Assert normalized response matches a known golden snapshot string."""
    assert_ok(result)
    if result.normalized != snapshot:
        raise HarnessAssertionError(
            f"Golden mismatch.\n  Expected: {snapshot[:240]!r}\n  Got:      {result.normalized[:240]!r}",
            result,
        )


def assert_response_nonempty(result: HarnessResult) -> None:
    """Assert response_text is non-empty."""
    assert_ok(result)
    if not result.response_text.strip():
        raise HarnessAssertionError("Expected non-empty response_text", result)


def assert_stream_has_chunks(result: HarnessResult, min_chunks: int = 1) -> None:
    """Assert stream mode produced at least min_chunks chunk events."""
    if result.mode != "stream":
        raise HarnessAssertionError(
            f"assert_stream_has_chunks requires stream mode, got {result.mode!r}", result
        )
    count = result.chunk_count()
    if count < min_chunks:
        raise HarnessAssertionError(
            f"Expected at least {min_chunks} chunk event(s), got {count}",
            result,
        )
