"""
Unit Tests: Graph Hygiene — Commit 4 (Delete/Tombstone/Reconcile)
==================================================================

Tests:
  A. _parse_candidate nil-safety (None/invalid score and node_id)
  B. updated_at in BOTH sync paths (single + bulk)
  C. remove_blueprint_from_graph tombstone logic
  D. DELETE route calls tombstone async (commander_routes)
  E. reconcile_graph_index: identifies stale nodes, dry-run/apply modes

All external dependencies (blueprint_store, docker, commander.db, memory.db)
are mocked at sys.modules or via patch().
"""

import json
import sys
import os
import sqlite3
import tempfile
import pytest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# ─── Pre-mock blueprint_store (init_db at module import) ─────────────────────
if "container_commander.blueprint_store" not in sys.modules:
    _bs_mock = MagicMock()
    _bs_mock.get_active_blueprint_ids = MagicMock(return_value=set())
    sys.modules["container_commander.blueprint_store"] = _bs_mock

from core.graph_hygiene import _parse_candidate, GraphCandidate


# ═════════════════════════════════════════════════════════════════════════════
# A. _parse_candidate nil-safety
# ═════════════════════════════════════════════════════════════════════════════

class TestParseCandidateNilSafety:
    """_parse_candidate must not raise on None/invalid score or node_id."""

    def _valid_meta(self, bp_id="bp-nil") -> str:
        return json.dumps({"blueprint_id": bp_id})

    def test_none_similarity_defaults_to_zero(self):
        raw = {"similarity": None, "metadata": self._valid_meta(), "content": "x", "id": 1}
        c = _parse_candidate(raw)
        assert c is not None
        assert c.score == 0.0

    def test_string_similarity_invalid_defaults_to_zero(self):
        raw = {"similarity": "not-a-float", "metadata": self._valid_meta(), "content": "x", "id": 1}
        c = _parse_candidate(raw)
        assert c is not None
        assert c.score == 0.0

    def test_none_id_defaults_to_zero(self):
        raw = {"similarity": 0.9, "metadata": self._valid_meta(), "content": "x", "id": None}
        c = _parse_candidate(raw)
        assert c is not None
        assert c.node_id == 0

    def test_string_id_invalid_defaults_to_zero(self):
        raw = {"similarity": 0.9, "metadata": self._valid_meta(), "content": "x", "id": "bad"}
        c = _parse_candidate(raw)
        assert c is not None
        assert c.node_id == 0

    def test_missing_similarity_and_score_defaults_to_zero(self):
        raw = {"metadata": self._valid_meta(), "content": "x", "id": 1}
        c = _parse_candidate(raw)
        assert c is not None
        assert c.score == 0.0

    def test_missing_id_and_node_id_defaults_to_zero(self):
        raw = {"similarity": 0.8, "metadata": self._valid_meta(), "content": "x"}
        c = _parse_candidate(raw)
        assert c is not None
        assert c.node_id == 0

    def test_none_content_defaults_to_empty_string(self):
        raw = {"similarity": 0.7, "metadata": self._valid_meta(), "content": None, "id": 2}
        c = _parse_candidate(raw)
        assert c is not None
        assert c.content == ""

    def test_none_updated_at_in_meta_defaults_to_empty(self):
        meta = json.dumps({"blueprint_id": "bp-nuat", "updated_at": None})
        raw = {"similarity": 0.7, "metadata": meta, "content": "bp-nuat: x", "id": 1}
        c = _parse_candidate(raw)
        assert c is not None
        assert c.updated_at == ""

    def test_valid_numeric_score_preserved(self):
        raw = {"similarity": 0.87, "metadata": self._valid_meta("bp-score"), "content": "x", "id": 5}
        c = _parse_candidate(raw)
        assert c is not None
        assert abs(c.score - 0.87) < 0.001

    def test_valid_numeric_node_id_preserved(self):
        raw = {"similarity": 0.5, "metadata": self._valid_meta("bp-nid"), "content": "x", "id": 42}
        c = _parse_candidate(raw)
        assert c is not None
        assert c.node_id == 42


# ═════════════════════════════════════════════════════════════════════════════
# B. updated_at present in BOTH sync paths
# ═════════════════════════════════════════════════════════════════════════════

class TestUpdatedAtInSyncPaths:
    """Both _sync_single_blueprint_to_graph and sync_blueprints_to_graph
    must include updated_at in the graph node metadata."""

    def _make_bp(self, bp_id="bp-sync", updated_at="2026-02-19T10:00:00"):
        bp = MagicMock()
        bp.id = bp_id
        bp.name = f"Blueprint {bp_id}"
        bp.description = "Test blueprint"
        bp.updated_at = updated_at
        bp.tags = ["python"]
        bp.network = MagicMock()
        bp.network.value = "internal"
        bp.resources = MagicMock()
        bp.resources.memory_limit = "512m"
        bp.resources.cpu_limit = "1.0"
        return bp

    def test_single_sync_includes_updated_at(self):
        """_sync_single_blueprint_to_graph must write updated_at to metadata."""
        import inspect
        import container_commander.blueprint_store as bs_module

        # Inspect the source of _sync_single_blueprint_to_graph
        try:
            src = inspect.getsource(bs_module._sync_single_blueprint_to_graph)
        except (AttributeError, TypeError):
            pytest.skip("_sync_single_blueprint_to_graph not inspectable (mocked)")

        assert '"updated_at"' in src or "'updated_at'" in src, (
            "_sync_single_blueprint_to_graph must include 'updated_at' in metadata dict"
        )

    def test_bulk_sync_includes_updated_at(self):
        """sync_blueprints_to_graph must write updated_at to metadata."""
        import inspect
        import container_commander.blueprint_store as bs_module

        try:
            src = inspect.getsource(bs_module.sync_blueprints_to_graph)
        except (AttributeError, TypeError):
            pytest.skip("sync_blueprints_to_graph not inspectable (mocked)")

        assert '"updated_at"' in src or "'updated_at'" in src, (
            "sync_blueprints_to_graph must include 'updated_at' in metadata dict"
        )

    def test_both_sync_paths_have_updated_at(self):
        """Consistency check: both paths must reference the same field name."""
        import inspect
        import container_commander.blueprint_store as bs_module

        try:
            src_single = inspect.getsource(bs_module._sync_single_blueprint_to_graph)
            src_bulk   = inspect.getsource(bs_module.sync_blueprints_to_graph)
        except (AttributeError, TypeError):
            pytest.skip("Source not inspectable")

        has_single = '"updated_at"' in src_single or "'updated_at'" in src_single
        has_bulk   = '"updated_at"' in src_bulk   or "'updated_at'" in src_bulk
        assert has_single and has_bulk, (
            f"updated_at missing in: "
            f"{'_sync_single' if not has_single else ''}"
            f"{'sync_bulk' if not has_bulk else ''}"
        )


# ═════════════════════════════════════════════════════════════════════════════
# C. remove_blueprint_from_graph tombstone logic
# ═════════════════════════════════════════════════════════════════════════════

class TestRemoveBlueprintFromGraph:
    """
    remove_blueprint_from_graph tombstone logic.

    blueprint_store.py is un-importable outside Docker (init_db() creates /app/data).
    We use source inspection for structural assertions (consistent with Phase-4 pattern
    for TestDurableTtlLabelsInCode).
    """

    def _get_source(self):
        # Search sys.path for the project root that contains blueprint_store.py.
        # This works both when the file is run from /tmp and from tests/unit/.
        for base in sys.path:
            candidate = os.path.join(base, "container_commander", "blueprint_store.py")
            if os.path.isfile(candidate):
                with open(candidate, "r") as f:
                    return f.read()
        raise FileNotFoundError(
            "container_commander/blueprint_store.py not found in sys.path"
        )

    def test_remove_function_exists_in_source(self):
        """remove_blueprint_from_graph must be defined in blueprint_store.py."""
        src = self._get_source()
        assert "def remove_blueprint_from_graph(" in src, (
            "remove_blueprint_from_graph must be defined in blueprint_store.py"
        )

    def test_tombstone_sets_is_deleted_true(self):
        """Function source must set is_deleted=True in tombstone metadata."""
        src = self._get_source()
        # Find the function body
        start = src.find("def remove_blueprint_from_graph(")
        # Find the next top-level def after this one
        next_def = src.find("\ndef ", start + 1)
        fn_src = src[start:next_def] if next_def != -1 else src[start:]

        assert '"is_deleted"' in fn_src or "'is_deleted'" in fn_src, (
            "Tombstone must set 'is_deleted' key in metadata"
        )
        assert "True" in fn_src, (
            "Tombstone must set is_deleted=True"
        )

    def test_tombstone_includes_deleted_at(self):
        """Function source must set a deleted_at timestamp in tombstone metadata."""
        src = self._get_source()
        start = src.find("def remove_blueprint_from_graph(")
        next_def = src.find("\ndef ", start + 1)
        fn_src = src[start:next_def] if next_def != -1 else src[start:]

        assert '"deleted_at"' in fn_src or "'deleted_at'" in fn_src, (
            "Tombstone must include 'deleted_at' timestamp in metadata"
        )

    def test_tombstone_calls_graph_add_node(self):
        """Function source must call graph_add_node to persist tombstone."""
        src = self._get_source()
        start = src.find("def remove_blueprint_from_graph(")
        next_def = src.find("\ndef ", start + 1)
        fn_src = src[start:next_def] if next_def != -1 else src[start:]

        assert "graph_add_node" in fn_src, (
            "Tombstone must call graph_add_node to write tombstone node to graph"
        )

    def test_tombstone_uses_memory_graph_search_to_find_nodes(self):
        """Function must search for existing nodes before tombstoning."""
        src = self._get_source()
        start = src.find("def remove_blueprint_from_graph(")
        next_def = src.find("\ndef ", start + 1)
        fn_src = src[start:next_def] if next_def != -1 else src[start:]

        assert "memory_graph_search" in fn_src, (
            "Tombstone must use memory_graph_search to find existing graph nodes"
        )

    def test_tombstone_is_fail_safe_wrapped(self):
        """Function must have try/except so tombstone errors don't crash callers."""
        src = self._get_source()
        start = src.find("def remove_blueprint_from_graph(")
        next_def = src.find("\ndef ", start + 1)
        fn_src = src[start:next_def] if next_def != -1 else src[start:]

        assert "except" in fn_src, (
            "remove_blueprint_from_graph must handle exceptions gracefully"
        )

    def test_tombstone_returns_int_count(self):
        """Function source must return an integer (count of tombstoned nodes)."""
        src = self._get_source()
        start = src.find("def remove_blueprint_from_graph(")
        next_def = src.find("\ndef ", start + 1)
        fn_src = src[start:next_def] if next_def != -1 else src[start:]

        assert "return 0" in fn_src or "return marked" in fn_src, (
            "Function must return an integer count (0 on no-op or error, marked on success)"
        )


# ═════════════════════════════════════════════════════════════════════════════
# D. DELETE route calls tombstone async
# ═════════════════════════════════════════════════════════════════════════════

class TestDeleteRouteTombstone:
    """The DELETE /blueprints/{id} route source must reference remove_blueprint_from_graph."""

    def test_delete_route_references_tombstone_function(self):
        """Inspect commander_routes source for tombstone call."""
        import inspect
        try:
            import adapters.admin_api.commander_routes as cr
        except ImportError:
            try:
                sys.path.insert(0, os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                    "adapters", "admin-api"
                ))
                import commander_routes as cr
            except ImportError:
                pytest.skip("commander_routes not importable")

        src = inspect.getsource(cr.api_delete_blueprint)
        assert "remove_blueprint_from_graph" in src, (
            "api_delete_blueprint must reference remove_blueprint_from_graph (tombstone)"
        )

    def test_delete_route_tombstone_is_noncritical(self):
        """Tombstone must be in a try/except so DELETE still succeeds on tombstone failure."""
        import inspect
        try:
            sys.path.insert(0, os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "adapters", "admin-api"
            ))
            import commander_routes as cr
        except ImportError:
            pytest.skip("commander_routes not importable")

        src = inspect.getsource(cr.api_delete_blueprint)
        # Tombstone wrapped in try/except — error must not propagate
        assert "except" in src, (
            "api_delete_blueprint tombstone must be wrapped in try/except (non-critical)"
        )


# ═════════════════════════════════════════════════════════════════════════════
# E. reconcile_graph_index
# ═════════════════════════════════════════════════════════════════════════════

class TestReconcileGraphIndex:
    """reconcile_graph_index.py: identifies stale nodes, dry-run/apply."""

    def _make_dbs(self, active_bp_ids: list, graph_nodes: list):
        """
        Create two in-memory SQLite DBs:
          - commander.db with blueprints table
          - memory.db with graph_nodes table
        Returns (commander_path, memory_path).
        """
        tmpdir = tempfile.mkdtemp()
        cmd_path = os.path.join(tmpdir, "commander.db")
        mem_path = os.path.join(tmpdir, "memory.db")

        # commander.db
        cmd_conn = sqlite3.connect(cmd_path)
        cmd_conn.execute(
            "CREATE TABLE blueprints (id TEXT PRIMARY KEY, is_deleted INTEGER DEFAULT 0)"
        )
        for bp_id in active_bp_ids:
            cmd_conn.execute("INSERT INTO blueprints (id, is_deleted) VALUES (?, 0)", (bp_id,))
        cmd_conn.commit()
        cmd_conn.close()

        # memory.db — graph_nodes
        mem_conn = sqlite3.connect(mem_path)
        mem_conn.execute(
            "CREATE TABLE graph_nodes "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT, "
            " content TEXT, metadata TEXT)"
        )
        for node in graph_nodes:
            mem_conn.execute(
                "INSERT INTO graph_nodes (conversation_id, content, metadata) VALUES (?, ?, ?)",
                ("_blueprints", node["content"], json.dumps(node["meta"])),
            )
        mem_conn.commit()
        mem_conn.close()

        return cmd_path, mem_path

    def test_dry_run_finds_stale_node(self):
        """Dry-run identifies stale node without deleting it."""
        cmd_path, mem_path = self._make_dbs(
            active_bp_ids=["bp-keep"],
            graph_nodes=[
                {"content": "bp-keep: ok", "meta": {"blueprint_id": "bp-keep"}},
                {"content": "bp-stale: old", "meta": {"blueprint_id": "bp-stale"}},
            ],
        )
        from tools.reconcile_graph_index import reconcile
        result = reconcile(commander_db=cmd_path, memory_db=mem_path, apply=False)

        assert result["active_in_sqlite"] == 1
        assert result["graph_nodes_total"] == 2
        assert len(result["stale_nodes"]) == 1
        assert result["stale_nodes"][0]["blueprint_id"] == "bp-stale"
        assert result["removed"] == 0, "Dry-run must NOT delete anything"
        assert result["dry_run"] is True

    def test_apply_removes_stale_node(self):
        """Apply mode actually removes stale node from graph_nodes."""
        cmd_path, mem_path = self._make_dbs(
            active_bp_ids=["bp-keep"],
            graph_nodes=[
                {"content": "bp-keep: ok", "meta": {"blueprint_id": "bp-keep"}},
                {"content": "bp-gone: old", "meta": {"blueprint_id": "bp-gone"}},
            ],
        )
        from tools.reconcile_graph_index import reconcile
        result = reconcile(commander_db=cmd_path, memory_db=mem_path, apply=True)

        assert result["removed"] == 1

        # Verify the node is actually gone from memory.db
        conn = sqlite3.connect(mem_path)
        remaining = conn.execute(
            "SELECT COUNT(*) FROM graph_nodes WHERE conversation_id='_blueprints'"
        ).fetchone()[0]
        conn.close()
        assert remaining == 1, f"Only 1 node should remain, got {remaining}"

    def test_tombstoned_node_identified_as_stale(self):
        """Nodes with is_deleted=true in metadata must be identified as stale."""
        cmd_path, mem_path = self._make_dbs(
            active_bp_ids=["bp-tomb"],
            graph_nodes=[
                {
                    "content": "bp-tomb: tombstoned",
                    "meta": {"blueprint_id": "bp-tomb", "is_deleted": True},
                },
            ],
        )
        from tools.reconcile_graph_index import reconcile
        result = reconcile(commander_db=cmd_path, memory_db=mem_path, apply=False)

        assert len(result["stale_nodes"]) == 1
        assert result["stale_nodes"][0]["blueprint_id"] == "bp-tomb"
        assert "tombstone" in result["stale_nodes"][0]["reason"]

    def test_clean_graph_reports_zero_stale(self):
        """If all graph nodes are active, stale_nodes is empty."""
        cmd_path, mem_path = self._make_dbs(
            active_bp_ids=["bp-a", "bp-b"],
            graph_nodes=[
                {"content": "bp-a: ok", "meta": {"blueprint_id": "bp-a"}},
                {"content": "bp-b: ok", "meta": {"blueprint_id": "bp-b"}},
            ],
        )
        from tools.reconcile_graph_index import reconcile
        result = reconcile(commander_db=cmd_path, memory_db=mem_path, apply=False)

        assert len(result["stale_nodes"]) == 0
        assert result["removed"] == 0

    def test_node_with_unknown_blueprint_id_is_stale(self):
        """Graph node with no parseable blueprint_id is always stale."""
        cmd_path, mem_path = self._make_dbs(
            active_bp_ids=["bp-known"],
            graph_nodes=[
                {"content": "no colon here", "meta": {}},  # unparseable
            ],
        )
        from tools.reconcile_graph_index import reconcile
        result = reconcile(commander_db=cmd_path, memory_db=mem_path, apply=False)

        assert len(result["stale_nodes"]) == 1
        assert "unknown" in result["stale_nodes"][0]["blueprint_id"].lower() or \
               result["stale_nodes"][0]["blueprint_id"] == "(unknown)"

    def test_apply_leaves_active_nodes_intact(self):
        """apply=True must not delete active (non-stale) nodes."""
        cmd_path, mem_path = self._make_dbs(
            active_bp_ids=["bp-keep-1", "bp-keep-2"],
            graph_nodes=[
                {"content": "bp-keep-1: ok", "meta": {"blueprint_id": "bp-keep-1"}},
                {"content": "bp-keep-2: ok", "meta": {"blueprint_id": "bp-keep-2"}},
                {"content": "bp-stale: old", "meta": {"blueprint_id": "bp-stale"}},
            ],
        )
        from tools.reconcile_graph_index import reconcile
        result = reconcile(commander_db=cmd_path, memory_db=mem_path, apply=True)

        assert result["removed"] == 1

        conn = sqlite3.connect(mem_path)
        remaining_ids = {
            json.loads(row[0]).get("blueprint_id")
            for row in conn.execute(
                "SELECT metadata FROM graph_nodes WHERE conversation_id='_blueprints'"
            ).fetchall()
        }
        conn.close()
        assert "bp-keep-1" in remaining_ids
        assert "bp-keep-2" in remaining_ids
        assert "bp-stale" not in remaining_ids
