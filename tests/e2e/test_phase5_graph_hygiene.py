"""
tests/e2e/test_phase5_graph_hygiene.py — Commit F
===================================================
Phase 5: Graph Hygiene — dedupe, latest revision, SQLite truth.

Tests:
  1. Dedupe: only one candidate per blueprint_id survives.
  2. Latest revision wins (updated_at + node_id tie-breaker).
  3. Stale/soft-deleted nodes are rejected via SQLite fail-closed check.
  4. Fail-closed: SQLite unavailable → empty results (safe default).
  5. Fail-open override: explicit flag only.
  6. Harness smoke + dataset cases.

Component tests use core.graph_hygiene directly (no Docker needed).
"""
import json
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Pre-mock blueprint_store before importing graph_hygiene
from unittest.mock import MagicMock
if "container_commander.blueprint_store" not in sys.modules:
    _bs_mock = MagicMock()
    _bs_mock.get_active_blueprint_ids = MagicMock(return_value=set())
    sys.modules["container_commander.blueprint_store"] = _bs_mock

from tests.harness.ai_client import get_provider
from tests.harness.assertions import assert_ok, assert_contains, assert_not_contains
from tests.harness.runner import HarnessRunner
from tests.harness.types import HarnessInput

from core.graph_hygiene import (
    GraphCandidate,
    _parse_candidate,
    dedupe_latest_by_blueprint_id,
    filter_against_sqlite_active_set,
    apply_graph_hygiene,
)


@pytest.fixture(scope="module")
def runner():
    return HarnessRunner(get_provider("mock"), normalize=True)


def _make_raw(bp_id: str, score: float, updated_at: str = "", node_id: int = 0) -> dict:
    meta = {"blueprint_id": bp_id, "trust_level": "verified"}
    if updated_at:
        meta["updated_at"] = updated_at
    return {
        "similarity": score,
        "metadata": json.dumps(meta),
        "content": f"{bp_id}: test blueprint",
        "id": node_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# A. Harness smoke
# ─────────────────────────────────────────────────────────────────────────────

class TestGraphHygieneSmoke:
    """Harness-level smoke: mock provider confirms graph hygiene responses."""

    def test_graph_hygiene_response(self, runner):
        result = runner.run(HarnessInput(prompt="graph hygiene", mode="sync"))
        assert_ok(result)
        assert_contains(result, "Graph")

    def test_blueprint_dedup_response(self, runner):
        result = runner.run(HarnessInput(prompt="dedupe blueprint", mode="sync"))
        assert_ok(result)
        assert_contains(result, "blueprint_id")

    def test_sqlite_truth_response(self, runner):
        result = runner.run(HarnessInput(prompt="sqlite", mode="sync"))
        assert_ok(result)
        assert_contains(result, "SQLite")

    def test_stale_node_response(self, runner):
        result = runner.run(HarnessInput(prompt="stale node", mode="sync"))
        assert_ok(result)
        assert_contains(result, "entfernt")

    def test_graph_hygiene_stream_mode(self, runner):
        result = runner.run(HarnessInput(prompt="graph hygiene", mode="stream"))
        assert_ok(result)
        assert_contains(result, "Graph")


# ─────────────────────────────────────────────────────────────────────────────
# B. Dedupe invariants
# ─────────────────────────────────────────────────────────────────────────────

class TestDedupeInvariants:
    """dedupe_latest_by_blueprint_id invariants."""

    def test_single_candidate_survives(self):
        candidates = [GraphCandidate(blueprint_id="bp-1", score=0.9, meta={})]
        result = dedupe_latest_by_blueprint_id(candidates)
        assert len(result) == 1
        assert result[0].blueprint_id == "bp-1"

    def test_duplicate_same_updated_at_keeps_higher_node_id(self):
        candidates = [
            GraphCandidate(blueprint_id="bp-1", score=0.9, meta={}, updated_at="2026-02-19", node_id=5),
            GraphCandidate(blueprint_id="bp-1", score=0.8, meta={}, updated_at="2026-02-19", node_id=10),
        ]
        result = dedupe_latest_by_blueprint_id(candidates)
        assert len(result) == 1
        assert result[0].node_id == 10, "Higher node_id must win on tie"

    def test_newer_updated_at_wins_regardless_of_score(self):
        candidates = [
            GraphCandidate(blueprint_id="bp-2", score=0.99, meta={}, updated_at="2026-02-01", node_id=1),
            GraphCandidate(blueprint_id="bp-2", score=0.50, meta={}, updated_at="2026-02-19", node_id=2),
        ]
        result = dedupe_latest_by_blueprint_id(candidates)
        assert len(result) == 1
        assert result[0].updated_at == "2026-02-19", "Newer updated_at must win"

    def test_different_blueprint_ids_both_survive(self):
        candidates = [
            GraphCandidate(blueprint_id="bp-a", score=0.8, meta={}),
            GraphCandidate(blueprint_id="bp-b", score=0.7, meta={}),
        ]
        result = dedupe_latest_by_blueprint_id(candidates)
        assert len(result) == 2
        ids = {c.blueprint_id for c in result}
        assert ids == {"bp-a", "bp-b"}

    def test_result_sorted_by_score_descending(self):
        candidates = [
            GraphCandidate(blueprint_id="bp-lo", score=0.3, meta={}),
            GraphCandidate(blueprint_id="bp-hi", score=0.9, meta={}),
            GraphCandidate(blueprint_id="bp-mid", score=0.6, meta={}),
        ]
        result = dedupe_latest_by_blueprint_id(candidates)
        scores = [c.score for c in result]
        assert scores == sorted(scores, reverse=True), (
            f"Result must be score-sorted descending, got {scores}"
        )

    def test_empty_list_returns_empty(self):
        assert dedupe_latest_by_blueprint_id([]) == []


# ─────────────────────────────────────────────────────────────────────────────
# C. SQLite fail-closed filter
# ─────────────────────────────────────────────────────────────────────────────

class TestSQLiteFailClosed:
    """filter_against_sqlite_active_set fail-closed semantics."""

    def test_candidate_in_active_set_passes(self):
        candidates = [GraphCandidate(blueprint_id="bp-keep", score=0.9, meta={})]
        result = filter_against_sqlite_active_set(candidates, {"bp-keep"}, fail_closed=True)
        assert len(result) == 1

    def test_candidate_not_in_active_set_rejected(self):
        candidates = [GraphCandidate(blueprint_id="bp-stale", score=0.9, meta={})]
        result = filter_against_sqlite_active_set(candidates, {"bp-keep"}, fail_closed=True)
        assert len(result) == 0, "Stale candidate must be rejected (fail-closed)"

    def test_fail_open_passes_all(self):
        candidates = [
            GraphCandidate(blueprint_id="bp-stale", score=0.9, meta={}),
            GraphCandidate(blueprint_id="bp-keep", score=0.8, meta={}),
        ]
        result = filter_against_sqlite_active_set(candidates, {"bp-keep"}, fail_closed=False)
        assert len(result) == 2, "fail_closed=False must pass all candidates"

    def test_empty_active_set_rejects_all(self):
        candidates = [GraphCandidate(blueprint_id="bp-x", score=0.9, meta={})]
        result = filter_against_sqlite_active_set(candidates, set(), fail_closed=True)
        assert len(result) == 0, "Empty active set → all rejected"

    def test_empty_candidates_returns_empty(self):
        result = filter_against_sqlite_active_set([], {"bp-x"}, fail_closed=True)
        assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# D. Full pipeline: apply_graph_hygiene
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyGraphHygienePipeline:
    """End-to-end pipeline tests for apply_graph_hygiene."""

    def test_pipeline_returns_only_active_ids(self):
        """Only candidates with active SQLite IDs must survive the pipeline."""
        from unittest.mock import patch
        raw = [
            _make_raw("bp-active", 0.9, "2026-02-19", 1),
            _make_raw("bp-stale",  0.8, "2026-02-18", 2),
        ]
        with patch(
            "container_commander.blueprint_store.get_active_blueprint_ids",
            return_value={"bp-active"},
        ):
            candidates, log_meta = apply_graph_hygiene(raw, fail_closed=True)

        assert len(candidates) == 1
        assert candidates[0].blueprint_id == "bp-active"

    def test_pipeline_dedupes_before_sqlite_check(self):
        """Dedup must run before SQLite check (only unique bp_ids cross-checked)."""
        from unittest.mock import patch
        raw = [
            _make_raw("bp-dup", 0.9, "2026-02-19", 10),
            _make_raw("bp-dup", 0.8, "2026-02-19", 5),  # older node_id
        ]
        with patch(
            "container_commander.blueprint_store.get_active_blueprint_ids",
            return_value={"bp-dup"},
        ):
            candidates, log_meta = apply_graph_hygiene(raw, fail_closed=True)

        assert len(candidates) == 1
        assert candidates[0].node_id == 10  # latest wins

    def test_pipeline_sqlite_unavailable_fail_closed_returns_empty(self):
        """SQLite unavailable + fail_closed=True → empty candidates (safe)."""
        from unittest.mock import patch
        raw = [_make_raw("bp-x", 0.9)]
        with patch(
            "container_commander.blueprint_store.get_active_blueprint_ids",
            side_effect=Exception("DB connection refused"),
        ):
            candidates, log_meta = apply_graph_hygiene(raw, fail_closed=True)

        assert len(candidates) == 0
        assert log_meta["graph_crosscheck_mode"] == "fail_closed_no_sqlite"

    def test_pipeline_sqlite_unavailable_fail_open_returns_deduped(self):
        """SQLite unavailable + fail_closed=False → return deduped (explicit override)."""
        from unittest.mock import patch
        raw = [_make_raw("bp-y", 0.9)]
        with patch(
            "container_commander.blueprint_store.get_active_blueprint_ids",
            side_effect=Exception("DB gone"),
        ):
            candidates, log_meta = apply_graph_hygiene(raw, fail_closed=False)

        assert len(candidates) == 1
        assert log_meta["graph_crosscheck_mode"] == "fail_open_no_sqlite"

    def test_log_meta_counts_are_consistent(self):
        """log_meta counts must be monotonically non-increasing through pipeline."""
        from unittest.mock import patch
        raw = [
            _make_raw("bp-a", 0.9),
            _make_raw("bp-b", 0.8),
            _make_raw("bp-a", 0.7),  # duplicate
        ]
        with patch(
            "container_commander.blueprint_store.get_active_blueprint_ids",
            return_value={"bp-a"},
        ):
            candidates, log_meta = apply_graph_hygiene(raw, fail_closed=True)

        r = log_meta["graph_candidates_raw"]
        ae = log_meta["graph_candidates_after_extra"]
        d = log_meta["graph_candidates_deduped"]
        f = log_meta["graph_candidates_after_sqlite_filter"]

        assert r >= ae >= d >= f, (
            f"Log meta counts not monotonically decreasing: raw={r} after_extra={ae} deduped={d} final={f}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# E. Dataset cases
# ─────────────────────────────────────────────────────────────────────────────

class TestPhase5DatasetCases:
    """All dataset cases tagged 'phase5' must pass the harness."""

    def _load_phase5_cases(self):
        try:
            import yaml
            from pathlib import Path
            cases_path = (
                Path(__file__).parent.parent / "datasets" / "cases" / "core_phase0_5.yaml"
            )
            with open(cases_path) as f:
                data = yaml.safe_load(f)
            return [c for c in data.get("cases", []) if "phase5" in c.get("tags", [])]
        except Exception:
            return []

    def test_dataset_phase5_cases_pass(self, runner):
        cases = self._load_phase5_cases()
        if not cases:
            pytest.skip("No phase5 dataset cases found")

        failures = []
        for case in cases:
            if case.get("skip_reason"):
                continue
            modes = ["sync", "stream"] if case["mode"] == "both" else [case["mode"]]
            for mode in modes:
                inp = HarnessInput(
                    prompt=case["input"]["prompt"],
                    mode=mode,
                    conversation_id=case["input"].get("conversation_id", "test-p5"),
                )
                result = runner.run(inp)
                if not result.ok:
                    failures.append(f"{case['id']}[{mode}]: {result.error}")
                    continue
                for text in case.get("expected", {}).get("contains", []):
                    if text not in result.response_text:
                        failures.append(f"{case['id']}[{mode}]: expected {text!r}")
                for text in case.get("expected", {}).get("not_contains", []):
                    if text in result.response_text:
                        failures.append(f"{case['id']}[{mode}]: unexpected {text!r}")

        if failures:
            pytest.fail("Phase5 dataset failures:\n" + "\n".join(failures))
