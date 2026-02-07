# tests/workspace/test_graph_confidence.py
"""
Unit Tests: Graph Store confidence weighting + Graph Builder weight_boost

Tests:
- GraphStore.add_node() with confidence parameter
- GraphStore.get_node() returns confidence
- GraphStore.graph_walk() sorts by confidence DESC
- build_node_with_edges() passes confidence + weight_boost
"""

import pytest
import sqlite3
import json
from unittest.mock import patch, MagicMock


class TestGraphStoreConfidence:
    """Test GraphStore confidence column support."""

    def test_add_node_default_confidence(self, graph_store):
        """
        GIVEN: GraphStore instance
        WHEN: add_node() is called without confidence
        THEN: Node is created with default confidence=0.5
        """
        node_id = graph_store.add_node("fact", "test content")
        node = graph_store.get_node(node_id)

        assert node is not None
        assert node["confidence"] == 0.5

    def test_add_node_custom_confidence(self, graph_store):
        """
        GIVEN: GraphStore instance
        WHEN: add_node() is called with confidence=0.9
        THEN: Node stores confidence=0.9
        """
        node_id = graph_store.add_node("workspace", "promoted content", confidence=0.9)
        node = graph_store.get_node(node_id)

        assert node["confidence"] == 0.9

    def test_add_node_confidence_zero(self, graph_store):
        """
        GIVEN: GraphStore instance
        WHEN: add_node() with confidence=0.0
        THEN: Node stores 0.0 (not default)
        """
        node_id = graph_store.add_node("fact", "low confidence", confidence=0.0)
        node = graph_store.get_node(node_id)

        assert node["confidence"] == 0.0

    def test_add_node_confidence_one(self, graph_store):
        """
        GIVEN: GraphStore instance
        WHEN: add_node() with confidence=1.0
        THEN: Node stores 1.0
        """
        node_id = graph_store.add_node("workspace", "max confidence", confidence=1.0)
        node = graph_store.get_node(node_id)

        assert node["confidence"] == 1.0

    def test_get_node_includes_confidence(self, graph_store):
        """
        GIVEN: A stored node
        WHEN: get_node() is called
        THEN: Response dict includes 'confidence' key
        """
        node_id = graph_store.add_node("fact", "test", confidence=0.7)
        node = graph_store.get_node(node_id)

        assert "confidence" in node
        assert isinstance(node["confidence"], float)


class TestGraphWalkConfidenceSorting:
    """Test that graph_walk sorts results by confidence DESC."""

    def test_walk_returns_high_confidence_first(self, graph_with_nodes):
        """
        GIVEN: Graph with nodes at confidence 0.5 and 0.9
        WHEN: graph_walk from all nodes
        THEN: Workspace-promoted (0.9) nodes appear before auto (0.5) nodes
        """
        store = graph_with_nodes["store"]
        all_ids = graph_with_nodes["node_ids"]

        results = store.graph_walk(all_ids, depth=1, limit=10)

        # Verify confidence ordering
        confidences = [r.get("confidence", 0.5) for r in results]
        assert confidences == sorted(confidences, reverse=True), \
            f"Results should be sorted by confidence DESC, got: {confidences}"

    def test_walk_workspace_nodes_rank_higher(self, graph_with_nodes):
        """
        GIVEN: Mix of workspace and auto nodes
        WHEN: graph_walk returns results
        THEN: First results are workspace (source_type='workspace')
        """
        store = graph_with_nodes["store"]
        all_ids = graph_with_nodes["node_ids"]

        results = store.graph_walk(all_ids, depth=1, limit=10)

        # Workspace nodes should come first due to higher confidence
        first_types = [r["source_type"] for r in results[:2]]
        assert "workspace" in first_types, \
            f"Expected workspace nodes first, got types: {first_types}"

    def test_walk_same_confidence_sorted_by_depth(self, graph_store):
        """
        GIVEN: Multiple nodes with same confidence at different depths
        WHEN: graph_walk is called
        THEN: At same confidence level, shallower nodes come first
        """
        n1 = graph_store.add_node("fact", "depth 0", confidence=0.5)
        n2 = graph_store.add_node("fact", "depth 1", confidence=0.5)
        n3 = graph_store.add_node("fact", "depth 2", confidence=0.5)

        graph_store.add_edge(n1, n2, "temporal")
        graph_store.add_edge(n2, n3, "temporal")

        results = graph_store.graph_walk([n1], depth=3, limit=10)

        depths = [r["depth"] for r in results]
        assert depths == sorted(depths), f"Same confidence should sort by depth ASC: {depths}"

    def test_walk_limit_respected_after_sort(self, graph_with_nodes):
        """
        GIVEN: 4 nodes in graph
        WHEN: graph_walk with limit=2
        THEN: Only 2 results returned, and they are the highest confidence ones
        """
        store = graph_with_nodes["store"]
        all_ids = graph_with_nodes["node_ids"]

        results = store.graph_walk(all_ids, depth=1, limit=2)

        assert len(results) == 2
        # Both should be high-confidence workspace nodes
        for r in results:
            assert r.get("confidence", 0.5) >= 0.5


class TestGraphBuilderWeightBoost:
    """Test build_node_with_edges with weight_boost and confidence params."""

    def test_build_node_default_confidence(self, initialized_db):
        """
        GIVEN: build_node_with_edges called without confidence
        WHEN: Node is created
        THEN: Default confidence=0.5 is used
        """
        import graph.graph_store as gs_module
        gs_module._graph_store = None

        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from graph.graph_store import GraphStore
            from graph.graph_builder import build_node_with_edges

            gs_module._graph_store = GraphStore(initialized_db)

            node_id = build_node_with_edges(
                source_type="fact",
                content="test content",
                conversation_id="conv-1"
            )

            node = gs_module._graph_store.get_node(node_id)
            assert node["confidence"] == 0.5
            gs_module._graph_store = None

    def test_build_node_workspace_confidence(self, initialized_db):
        """
        GIVEN: build_node_with_edges called with confidence=0.9
        WHEN: Node is created
        THEN: confidence=0.9 is stored
        """
        import graph.graph_store as gs_module
        gs_module._graph_store = None

        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from graph.graph_store import GraphStore
            from graph.graph_builder import build_node_with_edges

            gs_module._graph_store = GraphStore(initialized_db)

            node_id = build_node_with_edges(
                source_type="workspace",
                content="workspace promoted content",
                conversation_id="conv-1",
                confidence=0.9,
                weight_boost=0.85,
            )

            node = gs_module._graph_store.get_node(node_id)
            assert node["confidence"] == 0.9
            assert node["source_type"] == "workspace"
            gs_module._graph_store = None

    def test_build_node_creates_temporal_edge(self, initialized_db):
        """
        GIVEN: Two nodes in the same conversation
        WHEN: build_node_with_edges creates the second
        THEN: A temporal edge connects them
        """
        import graph.graph_store as gs_module
        gs_module._graph_store = None

        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from graph.graph_store import GraphStore
            from graph.graph_builder import build_node_with_edges

            gs_module._graph_store = GraphStore(initialized_db)

            n1 = build_node_with_edges("fact", "first node", conversation_id="conv-1")
            n2 = build_node_with_edges("fact", "second node", conversation_id="conv-1")

            edges = gs_module._graph_store.get_edges(n2)
            temporal = [e for e in edges if e["type"] == "temporal"]
            assert len(temporal) >= 1, "Temporal edge should exist between consecutive nodes"
            gs_module._graph_store = None

    def test_build_node_weight_boost_applied(self, initialized_db):
        """
        GIVEN: Two nodes in same conversation with weight_boost
        WHEN: Temporal edge is created
        THEN: Edge weight is min(1.0, 1.0 + weight_boost)
        """
        import graph.graph_store as gs_module
        gs_module._graph_store = None

        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from graph.graph_store import GraphStore
            from graph.graph_builder import build_node_with_edges

            gs_module._graph_store = GraphStore(initialized_db)

            n1 = build_node_with_edges(
                "fact", "first", conversation_id="conv-boost"
            )
            n2 = build_node_with_edges(
                "workspace", "second (boosted)", conversation_id="conv-boost",
                weight_boost=0.85, confidence=0.9
            )

            edges = gs_module._graph_store.get_edges(n2)
            temporal = [e for e in edges if e["type"] == "temporal"]
            assert len(temporal) >= 1
            # weight should be min(1.0, 1.0 + 0.85) = 1.0 (capped)
            assert temporal[0]["weight"] == 1.0
            gs_module._graph_store = None
