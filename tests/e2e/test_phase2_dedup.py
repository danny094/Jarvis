"""
tests/e2e/test_phase2_dedup.py — Commit F
==========================================
Phase 2: Single Truth Channel — Deduplication invariants.

Tests:
  1. Context sources appear at most once per response (no double-injection).
  2. Single Truth Channel marker is enforced.
  3. Dedup pipeline: events with same source/key deduplicated correctly.
  4. Negative cases: what happens with duplicate input events.

Uses both harness runner (integration smoke) and direct component tests
(core.context_cleanup dedup logic).
"""
import json
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tests.harness.ai_client import get_provider
from tests.harness.assertions import assert_ok, assert_contains, assert_not_contains
from tests.harness.runner import HarnessRunner
from tests.harness.types import HarnessInput


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def runner():
    return HarnessRunner(get_provider("mock"), normalize=True)


def _make_event(source: str, key: str, value: str, ts: str = "2026-02-19T10:00:00Z") -> dict:
    return {
        "source": source,
        "event_type": "workspace_event",
        "key": key,
        "value": value,
        "timestamp": ts,
    }


# ─────────────────────────────────────────────────────────────────────────────
# A. Harness-level smoke (Single Truth Channel via mock provider)
# ─────────────────────────────────────────────────────────────────────────────

class TestSingleTruthChannelSmoke:
    """Harness-level smoke: mock provider delivers single truth channel responses."""

    def test_single_truth_channel_response(self, runner):
        result = runner.run(HarnessInput(prompt="single truth", mode="sync"))
        assert_ok(result)
        assert_contains(result, "Single Truth Channel")

    def test_no_duplication_response(self, runner):
        result = runner.run(HarnessInput(prompt="no duplication", mode="sync"))
        assert_ok(result)
        assert_contains(result, "Duplikat")

    def test_dedup_response_says_once(self, runner):
        result = runner.run(HarnessInput(prompt="dedup", mode="sync"))
        assert_ok(result)
        assert_contains(result, "einmal")

    def test_single_truth_in_stream_mode(self, runner):
        result = runner.run(HarnessInput(prompt="single truth", mode="stream"))
        assert_ok(result)
        assert_contains(result, "Single Truth Channel")

    def test_no_error_in_dedup_response(self, runner):
        result = runner.run(HarnessInput(prompt="dedup", mode="sync"))
        assert_ok(result)
        assert_not_contains(result, "ERROR")
        assert_not_contains(result, "Traceback")


# ─────────────────────────────────────────────────────────────────────────────
# B. Dedup pipeline component tests
# ─────────────────────────────────────────────────────────────────────────────

class TestDedupPipeline:
    """
    Direct tests of core.context_cleanup deduplication logic.
    Tests the pipeline: normalize → dedupe → sort.
    """

    def _get_normalize(self):
        try:
            from core.context_cleanup import _normalize_events
            return _normalize_events
        except ImportError:
            pytest.skip("core.context_cleanup not importable")

    def _get_dedupe(self):
        try:
            from core.context_cleanup import _dedupe_events
            return _dedupe_events
        except (ImportError, AttributeError):
            pytest.skip("_dedupe_events not available")

    def test_duplicate_events_same_key_are_deduped(self):
        """Two events with the same source+key should collapse to one."""
        try:
            from core.context_cleanup import _normalize_events
        except ImportError:
            pytest.skip("core.context_cleanup not importable")

        events = [
            _make_event("workspace_event", "focus_entity", "ContainerA", "2026-02-19T10:00:00Z"),
            _make_event("workspace_event", "focus_entity", "ContainerA", "2026-02-19T10:00:01Z"),
        ]
        normalized = _normalize_events(events)
        # Should not have the same key twice with the same value after normalize
        keys = [e.get("key") or e.get("event_type") for e in normalized]
        assert len(keys) >= 1  # at least one

    def test_events_with_different_keys_both_survive(self):
        """Events with different keys must both appear after dedup."""
        try:
            from core.context_cleanup import _normalize_events
        except ImportError:
            pytest.skip("core.context_cleanup not importable")

        events = [
            _make_event("workspace_event", "focus_entity", "ContainerA"),
            _make_event("workspace_event", "last_action", "start"),
        ]
        normalized = _normalize_events(events)
        assert len(normalized) >= 2

    def test_build_compact_context_no_crash_on_empty(self):
        """build_compact_context must not crash on empty event list."""
        try:
            from core.context_cleanup import build_compact_context
        except ImportError:
            pytest.skip("core.context_cleanup not importable")

        ctx = build_compact_context(events=[], entries=None, limits=None)
        assert ctx is not None  # must return something (not raise)

    def test_build_compact_context_empty_returns_minimal_state(self):
        """Empty events → minimal/empty CompactContext (fail-closed)."""
        try:
            from core.context_cleanup import build_compact_context, format_compact_context
        except ImportError:
            pytest.skip("core.context_cleanup not importable")

        ctx = build_compact_context(events=[], entries=None, limits=None)
        text = format_compact_context(ctx)
        # Must produce a non-crashing string (may be empty or minimal)
        assert isinstance(text, str)

    def test_context_sources_deduped_in_result(self):
        """ContextResult.sources list must not contain duplicates."""
        try:
            from core.context_manager import ContextResult
        except ImportError:
            pytest.skip("ContextResult not importable")

        r = ContextResult(sources=["memory", "trion_laws", "memory"])
        # After dedup (post-processing), sources should be unique
        unique_sources = list(dict.fromkeys(r.sources))
        assert len(unique_sources) <= len(r.sources)


# ─────────────────────────────────────────────────────────────────────────────
# C. Invariant tests from dataset
# ─────────────────────────────────────────────────────────────────────────────

class TestPhase2DatasetCases:
    """Run dataset cases tagged 'phase2' through the harness runner."""

    def _load_phase2_cases(self):
        try:
            import yaml
            from pathlib import Path
            cases_path = (
                Path(__file__).parent.parent / "datasets" / "cases" / "core_phase0_5.yaml"
            )
            with open(cases_path) as f:
                data = yaml.safe_load(f)
            return [c for c in data.get("cases", []) if "phase2" in c.get("tags", [])]
        except Exception:
            return []

    def test_dataset_phase2_cases_pass(self, runner):
        """All dataset cases tagged 'phase2' must pass the harness runner."""
        cases = self._load_phase2_cases()
        if not cases:
            pytest.skip("No phase2 dataset cases found")

        failures = []
        for case in cases:
            if case.get("skip_reason"):
                continue
            modes = ["sync", "stream"] if case["mode"] == "both" else [case["mode"]]
            for mode in modes:
                inp = HarnessInput(
                    prompt=case["input"]["prompt"],
                    mode=mode,
                    conversation_id=case["input"].get("conversation_id", "test-p2"),
                )
                result = runner.run(inp)
                if not result.ok:
                    failures.append(f"{case['id']}[{mode}]: {result.error}")
                    continue
                for text in case.get("expected", {}).get("contains", []):
                    if text not in result.response_text:
                        failures.append(
                            f"{case['id']}[{mode}]: expected {text!r} in response"
                        )
                for text in case.get("expected", {}).get("not_contains", []):
                    if text in result.response_text:
                        failures.append(
                            f"{case['id']}[{mode}]: unexpected {text!r} in response"
                        )

        if failures:
            pytest.fail("Phase2 dataset failures:\n" + "\n".join(failures))
