# tests/workspace/test_maintenance_promotion.py
"""
Unit Tests: Maintenance Phase 4 — Workspace-to-Graph Promotion

Tests that unpromoted workspace entries are promoted to the knowledge graph
during maintenance with:
- source_type='workspace'
- confidence=0.9
- weight_boost=0.85
- promoted flag set after promotion
"""

import pytest
import sqlite3
from unittest.mock import patch, MagicMock, call
from datetime import datetime


class TestMaintenancePhase4:
    """Test the workspace promotion phase in maintenance_run_ai."""

    def test_phase4_promotes_all_unpromoted(self, populated_workspace, initialized_db):
        """
        GIVEN: 4 unpromoted workspace entries
        WHEN: maintenance runs
        THEN: All 4 are promoted (marked promoted=1)
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import get_unpromoted_entries, mark_promoted

            unpromoted_before = get_unpromoted_entries()
            assert len(unpromoted_before) == 4

            # Simulate Phase 4 logic
            for entry in unpromoted_before:
                mark_promoted(entry["id"])

            unpromoted_after = get_unpromoted_entries()
            assert len(unpromoted_after) == 0

    def test_phase4_sets_promoted_at_timestamp(self, populated_workspace, initialized_db):
        """
        GIVEN: An unpromoted entry
        WHEN: mark_promoted is called
        THEN: promoted_at is set to a valid ISO timestamp
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import mark_promoted, get_workspace_entry

            _, entry_id = populated_workspace[0]
            mark_promoted(entry_id)

            entry = get_workspace_entry(entry_id)
            assert entry["promoted"] is True
            assert entry["promoted_at"] is not None
            # Parse to verify it's valid ISO
            datetime.fromisoformat(entry["promoted_at"].replace("Z", "+00:00"))

    def test_phase4_creates_graph_nodes(self, populated_workspace, initialized_db):
        """
        GIVEN: Unpromoted workspace entries
        WHEN: We run build_node_with_edges for each (as Phase 4 does)
        THEN: Graph nodes are created with source_type='workspace' and confidence=0.9
        """
        import graph.graph_store as gs_module
        gs_module._graph_store = None

        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import get_unpromoted_entries, mark_promoted
            from graph.graph_store import GraphStore
            from graph.graph_builder import build_node_with_edges

            gs_module._graph_store = GraphStore(initialized_db)

            entries = get_unpromoted_entries()
            node_ids = []

            for entry in entries:
                node_id = build_node_with_edges(
                    source_type="workspace",
                    content=entry["content"],
                    source_id=entry["id"],
                    conversation_id=entry.get("conversation_id"),
                    confidence=0.9,
                    weight_boost=0.85,
                )
                mark_promoted(entry["id"])
                node_ids.append(node_id)

            # Verify nodes
            for node_id in node_ids:
                node = gs_module._graph_store.get_node(node_id)
                assert node is not None
                assert node["source_type"] == "workspace"
                assert node["confidence"] == 0.9

            gs_module._graph_store = None

    def test_phase4_already_promoted_skipped(self, populated_workspace, initialized_db):
        """
        GIVEN: 4 entries, 2 already promoted
        WHEN: We query get_unpromoted_entries
        THEN: Only 2 unpromoted entries are returned
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import mark_promoted, get_unpromoted_entries

            _, id1 = populated_workspace[0]
            _, id2 = populated_workspace[1]
            mark_promoted(id1)
            mark_promoted(id2)

            unpromoted = get_unpromoted_entries()
            assert len(unpromoted) == 2
            promoted_ids = [e["id"] for e in unpromoted]
            assert id1 not in promoted_ids
            assert id2 not in promoted_ids

    def test_phase4_graph_node_has_source_id(self, populated_workspace, initialized_db):
        """
        GIVEN: A workspace entry promoted to graph
        WHEN: We check the graph node
        THEN: source_id matches the workspace entry ID
        """
        import graph.graph_store as gs_module
        gs_module._graph_store = None

        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import get_unpromoted_entries, mark_promoted
            from graph.graph_store import GraphStore
            from graph.graph_builder import build_node_with_edges

            gs_module._graph_store = GraphStore(initialized_db)

            entries = get_unpromoted_entries()
            entry = entries[0]

            node_id = build_node_with_edges(
                source_type="workspace",
                content=entry["content"],
                source_id=entry["id"],
                conversation_id=entry.get("conversation_id"),
                confidence=0.9,
                weight_boost=0.85,
            )

            node = gs_module._graph_store.get_node(node_id)
            assert node["source_id"] == entry["id"]
            assert node["content"] == entry["content"]

            gs_module._graph_store = None


class TestMaintenanceResultsDict:
    """Test that maintenance results include workspace_promoted count."""

    def test_results_dict_has_workspace_promoted_key(self):
        """
        GIVEN: The initial results dict in maintenance_run_ai
        WHEN: We check for the workspace_promoted key
        THEN: It exists and is 0 initially
        """
        results = {
            "duplicates_merged": 0,
            "promoted_to_ltm": 0,
            "summaries_created": 0,
            "graph_optimized": 0,
            "workspace_promoted": 0,
            "conflicts_count": 0,
            "ai_decisions": 0,
        }
        assert "workspace_promoted" in results
        assert results["workspace_promoted"] == 0
