"""
tests/e2e/test_golden_regression.py — Commit D
================================================
Golden snapshot regression tests.

Tests that normalized AI responses match stored golden files.
Volatile fields (timestamps, UUIDs, dates, epoch ints) are stripped
before comparison by normalize_response().

Update mode:
    AI_UPDATE_GOLDEN=1 pytest tests/e2e/test_golden_regression.py

All tests run in mock mode by default (no Ollama required).
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tests.harness.ai_client import get_provider
from tests.harness.golden import assert_golden
from tests.harness.runner import HarnessRunner
from tests.harness.types import HarnessInput


# ─────────────────────────────────────────────────────────────────────────────
# Shared fixture
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def runner():
    return HarnessRunner(get_provider("mock"), normalize=True)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 0 golden tests
# ─────────────────────────────────────────────────────────────────────────────

class TestGoldenPhase0:
    """Golden snapshots for Phase 0 basic sanity cases."""

    def test_hello_sync_matches_golden(self, runner):
        """Sync response for 'hello' must match golden snapshot."""
        result = runner.run(HarnessInput(prompt="hello", mode="sync"))
        assert result.ok
        assert_golden(result, key="p0_basic_hello_sync")

    def test_hello_stream_matches_golden(self, runner):
        """Stream response for 'hello' must match golden snapshot."""
        result = runner.run(HarnessInput(prompt="hello", mode="stream"))
        assert result.ok
        assert_golden(result, key="p0_basic_hello_stream")

    def test_ping_sync_matches_golden(self, runner):
        """Sync response for 'ping' must match golden snapshot."""
        result = runner.run(HarnessInput(prompt="ping", mode="sync"))
        assert result.ok
        assert_golden(result, key="p0_basic_ping_sync")

    def test_golden_is_stable_across_runs(self, runner):
        """Same prompt produces identical normalized output on repeated calls."""
        inp = HarnessInput(prompt="hello", mode="sync")
        r1 = runner.run(inp)
        r2 = runner.run(inp)
        assert r1.normalized == r2.normalized, (
            f"Normalization not stable:\n  run1={r1.normalized!r}\n  run2={r2.normalized!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 golden
# ─────────────────────────────────────────────────────────────────────────────

class TestGoldenPhase2:
    """Golden snapshots for Phase 2 dedup/Single Truth Channel cases."""

    def test_single_truth_sync_matches_golden(self, runner):
        result = runner.run(HarnessInput(prompt="single truth", mode="sync"))
        assert result.ok
        assert_golden(result, key="p2_single_truth_sync")

    def test_no_duplication_matches_golden(self, runner):
        result = runner.run(HarnessInput(prompt="no duplication", mode="sync"))
        assert result.ok
        assert_golden(result, key="p2_no_duplication_sync")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 golden
# ─────────────────────────────────────────────────────────────────────────────

class TestGoldenPhase3:
    """Golden snapshots for Phase 3 TypedState / CompactContext cases."""

    def test_compact_context_matches_golden(self, runner):
        result = runner.run(HarnessInput(prompt="compact context", mode="sync"))
        assert result.ok
        assert_golden(result, key="p3_compact_context_sync")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 5 golden
# ─────────────────────────────────────────────────────────────────────────────

class TestGoldenPhase5:
    """Golden snapshots for Phase 5 graph hygiene cases."""

    def test_graph_hygiene_matches_golden(self, runner):
        result = runner.run(HarnessInput(prompt="graph hygiene", mode="sync"))
        assert result.ok
        assert_golden(result, key="p5_graph_hygiene_sync")


# ─────────────────────────────────────────────────────────────────────────────
# Regression: normalizer stability
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalizerStability:
    """Verify the normalizer is deterministic and strips volatile fields."""

    def test_timestamp_is_stripped(self):
        from tests.harness.runner import normalize_response
        text = "Created at 2026-02-19T12:34:56Z by system"
        normalized = normalize_response(text)
        assert "<TIMESTAMP>" in normalized
        assert "2026-02-19T12:34:56Z" not in normalized

    def test_uuid_is_stripped(self):
        from tests.harness.runner import normalize_response
        text = "Request ID: 550e8400-e29b-41d4-a716-446655440000"
        normalized = normalize_response(text)
        assert "<UUID>" in normalized
        assert "550e8400" not in normalized

    def test_plain_date_is_stripped(self):
        from tests.harness.runner import normalize_response
        text = "Report for 2026-02-19."
        normalized = normalize_response(text)
        assert "<DATE>" in normalized

    def test_epoch_is_stripped(self):
        from tests.harness.runner import normalize_response
        text = "Timestamp: 1708339200000"
        normalized = normalize_response(text)
        assert "<EPOCH>" in normalized

    def test_non_volatile_text_preserved(self):
        from tests.harness.runner import normalize_response
        text = "Graph-Index bereinigt. SQLite = Truth."
        normalized = normalize_response(text)
        assert "Graph-Index" in normalized
        assert "SQLite" in normalized

    def test_normalizer_idempotent(self):
        from tests.harness.runner import normalize_response
        text = "Created 2026-02-19T10:00:00Z with ID 550e8400-e29b-41d4-a716-446655440000"
        n1 = normalize_response(text)
        n2 = normalize_response(n1)
        assert n1 == n2, "Normalizer must be idempotent"
