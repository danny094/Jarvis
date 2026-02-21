"""
Unit Tests: Graph Hygiene — Phase 5
=====================================

Tests:
  1. _parse_candidate: valid, broken metadata, missing blueprint_id
  2. dedupe_latest_by_blueprint_id: latest revision wins, score-order preserved
  3. filter_against_sqlite_active_set: fail-closed, fail-open, soft-deleted
  4. apply_graph_hygiene: full pipeline (parse→extra_filter→dedupe→sqlite)
  5. fail-closed behavior when SQLite is unavailable
  6. Router/Context consistency: same candidates from both paths
"""

import json
import sys
import os
import pytest
from unittest.mock import patch, MagicMock
from typing import List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# ─── Pre-mock container_commander.blueprint_store ────────────────────────────
# blueprint_store.py calls init_db() at module import time, which creates
# /app/data and fails outside Docker.  We install a stub before any import.
if "container_commander.blueprint_store" not in sys.modules:
    _bs_mock = MagicMock()
    _bs_mock.get_active_blueprint_ids = MagicMock(return_value=set())
    sys.modules["container_commander.blueprint_store"] = _bs_mock

from core.graph_hygiene import (
    GraphCandidate,
    _parse_candidate,
    dedupe_latest_by_blueprint_id,
    filter_against_sqlite_active_set,
    apply_graph_hygiene,
)

# Correct patch target: the function in its source module
_ACTIVE_IDS_PATH = "container_commander.blueprint_store.get_active_blueprint_ids"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _raw(
    blueprint_id: str = "bp-test",
    similarity: float = 0.9,
    updated_at: str = "2026-02-19T10:00:00",
    trust_level: str = "verified",
    node_id: int = 1,
    content: str = "",
    extra_meta: dict = None,
) -> dict:
    """Build a raw graph search result dict."""
    meta = {
        "blueprint_id": blueprint_id,
        "trust_level": trust_level,
        "updated_at": updated_at,
        "capabilities": ["python"],
    }
    if extra_meta:
        meta.update(extra_meta)
    return {
        "similarity": similarity,
        "metadata": json.dumps(meta),
        "content": content or f"{blueprint_id}: A test blueprint",
        "id": node_id,
    }


def _cand(
    blueprint_id: str = "bp-test",
    score: float = 0.9,
    updated_at: str = "2026-02-19T10:00:00",
    node_id: int = 1,
) -> GraphCandidate:
    """Build a GraphCandidate directly."""
    return GraphCandidate(
        blueprint_id=blueprint_id,
        score=score,
        meta={"trust_level": "verified", "updated_at": updated_at},
        content=f"{blueprint_id}: test",
        updated_at=updated_at,
        node_id=node_id,
    )


# ═════════════════════════════════════════════════════════════════════════════
# 1. _parse_candidate
# ═════════════════════════════════════════════════════════════════════════════

class TestParseCandidate:
    """_parse_candidate must handle valid, broken, and partial inputs."""

    def test_valid_result_parsed(self):
        raw = _raw("bp-alpha", similarity=0.85)
        c = _parse_candidate(raw)
        assert c is not None
        assert c.blueprint_id == "bp-alpha"
        assert abs(c.score - 0.85) < 0.001
        assert c.updated_at == "2026-02-19T10:00:00"

    def test_node_id_captured(self):
        raw = _raw("bp-beta", node_id=42)
        c = _parse_candidate(raw)
        assert c is not None
        assert c.node_id == 42

    def test_content_captured(self):
        raw = _raw("bp-gamma", content="bp-gamma: Python sandbox")
        c = _parse_candidate(raw)
        assert c is not None
        assert c.content == "bp-gamma: Python sandbox"

    def test_broken_metadata_json_returns_none(self):
        raw = {"similarity": 0.9, "metadata": "{broken json", "content": "x", "id": 1}
        c = _parse_candidate(raw)
        assert c is None, "Broken JSON metadata must return None"

    def test_missing_blueprint_id_fallback_to_content(self):
        """If metadata has no blueprint_id, parse from content 'id: description'."""
        raw = {
            "similarity": 0.8,
            "metadata": json.dumps({"trust_level": "verified"}),
            "content": "bp-from-content: some description",
            "id": 5,
        }
        c = _parse_candidate(raw)
        assert c is not None
        assert c.blueprint_id == "bp-from-content"

    def test_no_blueprint_id_anywhere_returns_none(self):
        """No blueprint_id in metadata and no ':' in content → None."""
        raw = {
            "similarity": 0.8,
            "metadata": json.dumps({}),
            "content": "no colon here",
            "id": 1,
        }
        c = _parse_candidate(raw)
        assert c is None

    def test_metadata_as_dict_not_string(self):
        """metadata already parsed as dict (some MCP response variants)."""
        raw = {
            "similarity": 0.75,
            "metadata": {"blueprint_id": "bp-dict", "updated_at": "2026-01-01T00:00:00"},
            "content": "bp-dict: dict meta",
            "id": 7,
        }
        c = _parse_candidate(raw)
        assert c is not None
        assert c.blueprint_id == "bp-dict"
        assert c.updated_at == "2026-01-01T00:00:00"

    def test_missing_updated_at_defaults_to_empty(self):
        """Older graph nodes without updated_at should default to ''."""
        raw = _raw("bp-old")
        meta = {"blueprint_id": "bp-old"}  # no updated_at
        raw["metadata"] = json.dumps(meta)
        c = _parse_candidate(raw)
        assert c is not None
        assert c.updated_at == ""

    def test_empty_raw_returns_none(self):
        c = _parse_candidate({})
        assert c is None

    def test_score_from_score_field_fallback(self):
        """If 'similarity' absent, use 'score' field."""
        raw = {
            "score": 0.66,
            "metadata": json.dumps({"blueprint_id": "bp-score"}),
            "content": "bp-score: test",
            "id": 1,
        }
        c = _parse_candidate(raw)
        assert c is not None
        assert abs(c.score - 0.66) < 0.001


# ═════════════════════════════════════════════════════════════════════════════
# 2. dedupe_latest_by_blueprint_id
# ═════════════════════════════════════════════════════════════════════════════

class TestDedupeLatestByBlueprintId:
    """Dedupe must keep exactly one candidate per blueprint_id — the newest."""

    def test_single_candidate_unchanged(self):
        c = _cand("bp-x", score=0.9)
        result = dedupe_latest_by_blueprint_id([c])
        assert len(result) == 1
        assert result[0].blueprint_id == "bp-x"

    def test_two_different_blueprints_both_kept(self):
        c1 = _cand("bp-a", score=0.9)
        c2 = _cand("bp-b", score=0.8)
        result = dedupe_latest_by_blueprint_id([c1, c2])
        ids = {c.blueprint_id for c in result}
        assert ids == {"bp-a", "bp-b"}

    def test_newer_updated_at_wins(self):
        old = _cand("bp-dup", score=0.9, updated_at="2026-01-01T00:00:00", node_id=1)
        new = _cand("bp-dup", score=0.7, updated_at="2026-02-19T12:00:00", node_id=2)
        result = dedupe_latest_by_blueprint_id([old, new])
        assert len(result) == 1
        assert result[0].updated_at == "2026-02-19T12:00:00", (
            "Newer updated_at must win regardless of score order"
        )

    def test_higher_node_id_wins_when_updated_at_equal(self):
        """When updated_at is identical (e.g. both ''), higher node_id = newer."""
        low  = _cand("bp-dup", score=0.9, updated_at="", node_id=10)
        high = _cand("bp-dup", score=0.7, updated_at="", node_id=99)
        result = dedupe_latest_by_blueprint_id([low, high])
        assert len(result) == 1
        assert result[0].node_id == 99, "Higher node_id must win when updated_at is equal"

    def test_score_order_preserved_after_dedupe(self):
        """After dedupe, result must be sorted descending by score."""
        candidates = [
            _cand("bp-low",  score=0.5),
            _cand("bp-high", score=0.95),
            _cand("bp-mid",  score=0.7),
        ]
        result = dedupe_latest_by_blueprint_id(candidates)
        scores = [c.score for c in result]
        assert scores == sorted(scores, reverse=True), (
            f"Result must be score-sorted descending, got {scores}"
        )

    def test_empty_input_returns_empty(self):
        assert dedupe_latest_by_blueprint_id([]) == []

    def test_three_duplicates_one_survives(self):
        c1 = _cand("bp-triple", updated_at="2026-01-01", node_id=1)
        c2 = _cand("bp-triple", updated_at="2026-01-15", node_id=2)
        c3 = _cand("bp-triple", updated_at="2026-02-01", node_id=3)
        result = dedupe_latest_by_blueprint_id([c1, c2, c3])
        assert len(result) == 1
        assert result[0].updated_at == "2026-02-01"

    def test_older_node_presented_first_still_loses(self):
        """Input order must NOT determine which candidate wins — only timestamp/node_id."""
        new_first = _cand("bp-order", updated_at="2025-12-01", node_id=5)
        old_first  = _cand("bp-order", updated_at="2026-02-01", node_id=99)
        # new_first has lower node_id/timestamp — old_first is actually newer
        result = dedupe_latest_by_blueprint_id([new_first, old_first])
        assert len(result) == 1
        assert result[0].node_id == 99


# ═════════════════════════════════════════════════════════════════════════════
# 3. filter_against_sqlite_active_set
# ═════════════════════════════════════════════════════════════════════════════

class TestFilterAgainstSqliteActiveSet:
    """filter_against_sqlite_active_set — fail-closed and fail-open behaviour."""

    def test_active_blueprint_passes(self):
        c = _cand("bp-active")
        result = filter_against_sqlite_active_set([c], {"bp-active"}, fail_closed=True)
        assert len(result) == 1
        assert result[0].blueprint_id == "bp-active"

    def test_soft_deleted_rejected_fail_closed(self):
        c = _cand("bp-deleted")
        result = filter_against_sqlite_active_set([c], {"bp-other"}, fail_closed=True)
        assert result == [], "Soft-deleted blueprint must be rejected when fail_closed=True"

    def test_empty_active_set_rejects_all_fail_closed(self):
        candidates = [_cand("bp-a"), _cand("bp-b")]
        result = filter_against_sqlite_active_set(candidates, set(), fail_closed=True)
        assert result == []

    def test_fail_open_returns_all_regardless(self):
        c = _cand("bp-not-in-sqlite")
        result = filter_against_sqlite_active_set([c], set(), fail_closed=False)
        assert len(result) == 1, "fail_closed=False must pass all candidates through"

    def test_mixed_active_and_deleted(self):
        active  = _cand("bp-keep")
        deleted = _cand("bp-remove")
        result = filter_against_sqlite_active_set(
            [active, deleted], {"bp-keep"}, fail_closed=True
        )
        assert len(result) == 1
        assert result[0].blueprint_id == "bp-keep"

    def test_empty_input_returns_empty(self):
        result = filter_against_sqlite_active_set([], {"bp-x"}, fail_closed=True)
        assert result == []


# ═════════════════════════════════════════════════════════════════════════════
# 4. apply_graph_hygiene — full pipeline
# ═════════════════════════════════════════════════════════════════════════════

class TestApplyGraphHygiene:
    """apply_graph_hygiene: end-to-end pipeline with mocked SQLite."""

    def _active_patch(self, ids):
        return patch(
            "core.graph_hygiene.filter_against_sqlite_active_set",
            side_effect=lambda cands, active, fail_closed=True: (
                [c for c in cands if c.blueprint_id in ids]
            ),
        )

    def test_healthy_candidate_passes_pipeline(self):
        raw = [_raw("bp-healthy", similarity=0.9)]
        with patch(
            _ACTIVE_IDS_PATH,
            return_value={"bp-healthy"},
        ):
            candidates, meta = apply_graph_hygiene(raw)
        assert len(candidates) == 1
        assert candidates[0].blueprint_id == "bp-healthy"
        assert meta["graph_candidates_raw"] == 1
        assert meta["graph_candidates_after_sqlite_filter"] == 1

    def test_soft_deleted_filtered_out(self):
        raw = [_raw("bp-deleted", similarity=0.9)]
        with patch(
            _ACTIVE_IDS_PATH,
            return_value=set(),  # deleted → not in active set
        ):
            candidates, meta = apply_graph_hygiene(raw)
        assert candidates == []
        assert meta["graph_candidates_after_sqlite_filter"] == 0

    def test_dedupe_applied_before_sqlite_check(self):
        """Two nodes for same blueprint_id → only one reaches SQLite check."""
        raw = [
            _raw("bp-dup", similarity=0.9, updated_at="2026-01-01", node_id=1),
            _raw("bp-dup", similarity=0.8, updated_at="2026-02-01", node_id=2),
        ]
        sqlite_calls = []

        def _active():
            # Track how many unique blueprint_ids reach SQLite check
            sqlite_calls.append(1)
            return {"bp-dup"}

        with patch(_ACTIVE_IDS_PATH, side_effect=_active):
            candidates, meta = apply_graph_hygiene(raw)

        assert meta["graph_candidates_raw"] == 2
        assert meta["graph_candidates_deduped"] == 1
        assert len(candidates) == 1
        # The newer node (node_id=2, updated_at="2026-02-01") must survive
        assert candidates[0].updated_at == "2026-02-01"

    def test_extra_filter_applied_before_dedupe(self):
        """extra_filter must run before dedupe so untrusted nodes are excluded early."""
        raw = [
            _raw("bp-trusted",   trust_level="verified",   similarity=0.9),
            _raw("bp-untrusted", trust_level="unverified", similarity=0.95),
        ]
        extra = lambda c: c.meta.get("trust_level") == "verified"

        with patch(
            _ACTIVE_IDS_PATH,
            return_value={"bp-trusted", "bp-untrusted"},
        ):
            candidates, meta = apply_graph_hygiene(raw, extra_filter=extra)

        assert meta["graph_candidates_raw"] == 2
        assert meta["graph_candidates_after_extra"] == 1
        assert len(candidates) == 1
        assert candidates[0].blueprint_id == "bp-trusted"

    def test_log_meta_keys_present(self):
        raw = [_raw("bp-x")]
        with patch(
            _ACTIVE_IDS_PATH,
            return_value={"bp-x"},
        ):
            _, meta = apply_graph_hygiene(raw)
        for key in [
            "graph_candidates_raw",
            "graph_candidates_after_extra",
            "graph_candidates_deduped",
            "graph_candidates_after_sqlite_filter",
            "graph_crosscheck_mode",
        ]:
            assert key in meta, f"log_meta missing key: {key!r}"

    def test_empty_raw_returns_empty_pipeline(self):
        with patch(
            _ACTIVE_IDS_PATH,
            return_value={"bp-x"},
        ):
            candidates, meta = apply_graph_hygiene([])
        assert candidates == []
        assert meta["graph_candidates_raw"] == 0

    def test_multiple_different_blueprints_all_pass(self):
        raw = [
            _raw("bp-a", similarity=0.9),
            _raw("bp-b", similarity=0.8),
            _raw("bp-c", similarity=0.7),
        ]
        with patch(
            _ACTIVE_IDS_PATH,
            return_value={"bp-a", "bp-b", "bp-c"},
        ):
            candidates, meta = apply_graph_hygiene(raw)
        assert len(candidates) == 3
        assert meta["graph_candidates_after_sqlite_filter"] == 3

    def test_crosscheck_mode_in_log_meta(self):
        raw = [_raw("bp-y")]
        with patch(
            _ACTIVE_IDS_PATH,
            return_value={"bp-y"},
        ):
            _, meta = apply_graph_hygiene(raw, crosscheck_mode="strict")
        assert meta["graph_crosscheck_mode"] == "strict"


# ═════════════════════════════════════════════════════════════════════════════
# 5. Fail-closed when SQLite is unavailable
# ═════════════════════════════════════════════════════════════════════════════

class TestFailClosed:
    """apply_graph_hygiene must return [] when SQLite is unavailable (default)."""

    def test_sqlite_error_returns_empty_fail_closed(self):
        raw = [_raw("bp-safe")]
        with patch(
            _ACTIVE_IDS_PATH,
            side_effect=Exception("SQLite connection refused"),
        ):
            candidates, meta = apply_graph_hygiene(raw, fail_closed=True)
        assert candidates == [], (
            "fail_closed=True + SQLite error must return empty list (safe default)"
        )
        assert meta["graph_crosscheck_mode"] == "fail_closed_no_sqlite"

    def test_sqlite_error_fail_open_returns_deduped(self):
        """fail_closed=False explicitly: return deduped candidates even if SQLite fails."""
        raw = [
            _raw("bp-1", similarity=0.9),
            _raw("bp-2", similarity=0.8),
        ]
        with patch(
            _ACTIVE_IDS_PATH,
            side_effect=Exception("SQLite unavailable"),
        ):
            candidates, meta = apply_graph_hygiene(raw, fail_closed=False)
        assert len(candidates) == 2, (
            "fail_closed=False + SQLite error must return deduped candidates"
        )
        assert meta["graph_crosscheck_mode"] == "fail_open_no_sqlite"

    def test_fail_closed_is_default(self):
        """Default call must use fail_closed=True (no explicit argument needed)."""
        raw = [_raw("bp-default")]
        with patch(
            _ACTIVE_IDS_PATH,
            side_effect=RuntimeError("DB gone"),
        ):
            candidates, meta = apply_graph_hygiene(raw)  # no fail_closed arg
        assert candidates == []
        assert "fail_closed" in meta["graph_crosscheck_mode"]

    def test_sqlite_import_error_treated_as_failure(self):
        """ImportError on get_active_blueprint_ids → fail-closed."""
        raw = [_raw("bp-import")]
        with patch(
            _ACTIVE_IDS_PATH,
            side_effect=ImportError("container_commander not found"),
        ):
            candidates, meta = apply_graph_hygiene(raw, fail_closed=True)
        assert candidates == []


# ═════════════════════════════════════════════════════════════════════════════
# 6. DoD verification: final_candidates ⊆ SQLite active set
# ═════════════════════════════════════════════════════════════════════════════

class TestDoDInvariant:
    """DoD item 1: for every query, final_candidates ⊆ SQLite active set."""

    def test_all_candidates_in_active_set(self):
        active_ids = {"bp-a", "bp-b"}
        raw = [
            _raw("bp-a", similarity=0.9),
            _raw("bp-b", similarity=0.8),
            _raw("bp-c", similarity=0.7),  # not active
        ]
        with patch(
            _ACTIVE_IDS_PATH,
            return_value=active_ids,
        ):
            candidates, _ = apply_graph_hygiene(raw)

        returned_ids = {c.blueprint_id for c in candidates}
        assert returned_ids.issubset(active_ids), (
            f"Returned candidates {returned_ids} must be subset of active_ids {active_ids}"
        )

    def test_max_one_candidate_per_blueprint_id(self):
        """DoD item 2: at most one candidate per blueprint_id."""
        raw = [
            _raw("bp-dup", similarity=0.9, node_id=1, updated_at="2026-01-01"),
            _raw("bp-dup", similarity=0.8, node_id=2, updated_at="2026-02-01"),
            _raw("bp-dup", similarity=0.7, node_id=3, updated_at="2025-12-01"),
        ]
        with patch(
            _ACTIVE_IDS_PATH,
            return_value={"bp-dup"},
        ):
            candidates, _ = apply_graph_hygiene(raw)

        bp_ids = [c.blueprint_id for c in candidates]
        assert len(bp_ids) == len(set(bp_ids)), (
            f"Duplicate blueprint_ids in result: {bp_ids}"
        )
        assert len(candidates) == 1

    def test_soft_deleted_never_in_result(self):
        """DoD item 3: soft-deleted blueprints never appear in result."""
        raw = [_raw("bp-soft-del")]
        # Simulate soft-delete: blueprint_id not in active set
        with patch(
            _ACTIVE_IDS_PATH,
            return_value=set(),
        ):
            candidates, _ = apply_graph_hygiene(raw)
        bp_ids = {c.blueprint_id for c in candidates}
        assert "bp-soft-del" not in bp_ids
