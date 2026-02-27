"""
tests/unit/test_skill_graph_hygiene.py — C9 Skill Graph Hygiene
===============================================================

Covers:
  1. parse_skill_graph_candidate metadata parsing (including bool coercion)
  2. dedupe_latest_skill_graph_candidates identity dedupe (keeps stale duplicates)
  3. plan_skill_graph_reconcile graph cross-check + tombstone planning
  4. SkillManager.reconcile_skill_graph_index fail-closed + apply behavior
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if not os.path.isdir(os.path.join(_REPO_ROOT, "mcp-servers")):
    _REPO_ROOT = "/DATA/AppData/MCP/Jarvis/Jarvis"
_SKILL_SERVER = os.path.join(_REPO_ROOT, "mcp-servers", "skill-server")

for p in (_REPO_ROOT, _SKILL_SERVER):
    if p not in sys.path:
        sys.path.insert(0, p)


def _load_skill_manager_module():
    spec = importlib.util.spec_from_file_location(
        "skill_manager_c9_test_mod",
        os.path.join(_SKILL_SERVER, "skill_manager.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load_skill_manager_module()
SkillManager = _mod.SkillManager
parse_skill_graph_candidate = _mod.parse_skill_graph_candidate
dedupe_latest_skill_graph_candidates = _mod.dedupe_latest_skill_graph_candidates
plan_skill_graph_reconcile = _mod.plan_skill_graph_reconcile


def _mk_row(
    *,
    node_id: int,
    skill_name: str,
    skill_key: str,
    updated_at: str = "2026-02-22T10:00:00Z",
    is_deleted=False,
) -> dict:
    meta = {
        "skill_name": skill_name,
        "skill_key": skill_key,
        "updated_at": updated_at,
        "is_deleted": is_deleted,
    }
    return {
        "id": node_id,
        "content": f"{skill_name}: test",
        "metadata": json.dumps(meta),
        "similarity": 0.9,
    }


class TestSkillGraphCandidateParsing(unittest.TestCase):
    def test_parse_candidate_coerces_string_false_to_not_deleted(self):
        row = _mk_row(node_id=1, skill_name="alpha", skill_key="alpha", is_deleted="false")
        parsed = parse_skill_graph_candidate(row)
        self.assertIsNotNone(parsed)
        self.assertFalse(parsed["is_deleted"])

    def test_parse_candidate_coerces_string_true_to_deleted(self):
        row = _mk_row(node_id=2, skill_name="alpha", skill_key="alpha", is_deleted="true")
        parsed = parse_skill_graph_candidate(row)
        self.assertIsNotNone(parsed)
        self.assertTrue(parsed["is_deleted"])


class TestSkillGraphCandidateDedupe(unittest.TestCase):
    def test_dedupe_keeps_distinct_live_nodes_same_skill_key(self):
        rows = [
            parse_skill_graph_candidate(_mk_row(node_id=10, skill_name="alpha", skill_key="alpha")),
            parse_skill_graph_candidate(_mk_row(node_id=11, skill_name="alpha", skill_key="alpha")),
            parse_skill_graph_candidate(_mk_row(node_id=11, skill_name="alpha", skill_key="alpha")),
        ]
        deduped = dedupe_latest_skill_graph_candidates([r for r in rows if r is not None])
        self.assertEqual(len(deduped), 2, "stale duplicate cleanup needs multiple live rows preserved")


class TestSkillGraphReconcilePlanning(unittest.TestCase):
    def test_plan_marks_ghost_for_tombstone(self):
        truth = {}
        graph = [parse_skill_graph_candidate(_mk_row(node_id=1, skill_name="ghost", skill_key="ghost"))]
        plan = plan_skill_graph_reconcile(truth, [g for g in graph if g is not None])
        self.assertEqual(len(plan["tombstones"]), 1)
        self.assertEqual(plan["tombstones"][0]["reason"], "ghost_skill")

    def test_plan_is_idempotent_when_tombstone_exists(self):
        truth = {}
        graph = [
            parse_skill_graph_candidate(_mk_row(node_id=1, skill_name="ghost", skill_key="ghost", is_deleted=False)),
            parse_skill_graph_candidate(_mk_row(node_id=2, skill_name="ghost", skill_key="ghost", is_deleted=True)),
        ]
        plan = plan_skill_graph_reconcile(truth, [g for g in graph if g is not None])
        self.assertEqual(plan["tombstones"], [])

    def test_plan_tombstones_each_stale_duplicate(self):
        truth = {"alpha": {"skill_key": "alpha", "name": "alpha", "description": "", "triggers": []}}
        graph = [
            parse_skill_graph_candidate(_mk_row(node_id=30, skill_name="alpha", skill_key="alpha", updated_at="2026-02-22T10:03:00Z")),
            parse_skill_graph_candidate(_mk_row(node_id=20, skill_name="alpha", skill_key="alpha", updated_at="2026-02-22T10:02:00Z")),
            parse_skill_graph_candidate(_mk_row(node_id=10, skill_name="alpha", skill_key="alpha", updated_at="2026-02-22T10:01:00Z")),
        ]
        plan = plan_skill_graph_reconcile(truth, [g for g in graph if g is not None])
        self.assertEqual(len(plan["tombstones"]), 2)
        self.assertEqual({t["reason"] for t in plan["tombstones"]}, {"stale_duplicate"})

    def test_plan_upserts_truth_skill_missing_in_graph(self):
        truth = {"alpha": {"skill_key": "alpha", "name": "alpha", "description": "A", "triggers": ["a"]}}
        plan = plan_skill_graph_reconcile(truth, [])
        self.assertEqual(len(plan["upserts"]), 1)
        self.assertEqual(plan["upserts"][0]["name"], "alpha")


class TestSkillManagerGraphReconcile(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.skills_dir = Path(self._tmp.name)
        (self.skills_dir / "_registry").mkdir(parents=True, exist_ok=True)
        self.registry_path = self.skills_dir / "_registry" / "installed.json"
        self._write_installed({
            "alpha": {
                "skill_key": "alpha",
                "description": "Alpha skill",
                "triggers": ["alpha"],
            }
        })
        self.mgr = SkillManager(str(self.skills_dir), "http://registry.local")

    def _write_installed(self, skills_map: dict) -> None:
        payload = {
            "schema_version": 2,
            "skill_registry_hash": "testhash",
            "skills": skills_map,
        }
        with open(self.registry_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

    async def test_reconcile_disabled_returns_rollback_shape(self):
        self.mgr._is_graph_reconcile_enabled = staticmethod(lambda: False)
        result = await self.mgr.reconcile_skill_graph_index()
        self.assertFalse(result["enabled"])
        self.assertEqual(result["reason"], "SKILL_GRAPH_RECONCILE=false")

    async def test_reconcile_fail_closed_when_all_fetch_calls_fail(self):
        self.mgr._is_graph_reconcile_enabled = staticmethod(lambda: True)
        self.mgr._fetch_skill_graph_candidates = AsyncMock(return_value=([], 0, 1))
        self.mgr._write_skill_tombstone = AsyncMock(return_value=True)
        self.mgr._register_skill_in_graph = AsyncMock(return_value=None)

        result = await self.mgr.reconcile_skill_graph_index()
        self.assertEqual(result.get("error"), "graph_fetch_failed:all_terms_failed")
        self.mgr._write_skill_tombstone.assert_not_called()
        self.mgr._register_skill_in_graph.assert_not_called()

    async def test_reconcile_applies_tombstones_and_upserts(self):
        self.mgr._is_graph_reconcile_enabled = staticmethod(lambda: True)
        rows = [
            _mk_row(node_id=1, skill_name="ghost", skill_key="ghost", is_deleted=False),
        ]
        self.mgr._fetch_skill_graph_candidates = AsyncMock(return_value=(rows, 1, 0))
        self.mgr._write_skill_tombstone = AsyncMock(return_value=True)
        self.mgr._register_skill_in_graph = AsyncMock(return_value=None)

        result = await self.mgr.reconcile_skill_graph_index()
        self.assertEqual(result["tombstones_planned"], 1)
        self.assertEqual(result["upserts_planned"], 1)
        self.assertEqual(result["tombstoned"], 1)
        self.assertEqual(result["upserted"], 1)
        self.mgr._write_skill_tombstone.assert_awaited_once()
        self.mgr._register_skill_in_graph.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
