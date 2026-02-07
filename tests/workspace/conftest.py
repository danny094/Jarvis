# tests/workspace/conftest.py
"""
Shared fixtures for Agent Workspace test suite.
"""

import pytest
import sys
import os
import sqlite3
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime

# ═══════════════════════════════════════════════════════════
# PATH SETUP
# ═══════════════════════════════════════════════════════════

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
SQL_MEMORY_ROOT = os.path.join(PROJECT_ROOT, "sql-memory")
MEMORY_MCP_PATH = os.path.join(SQL_MEMORY_ROOT, "memory_mcp")

for p in [PROJECT_ROOT, SQL_MEMORY_ROOT, MEMORY_MCP_PATH]:
    if p not in sys.path:
        sys.path.insert(0, p)

# Mock modules that may not be available in test environment
for mod in ["openai", "tiktoken"]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()


# ═══════════════════════════════════════════════════════════
# DATABASE FIXTURES
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def db_path(tmp_path):
    """Create a temporary SQLite database file path."""
    return str(tmp_path / "test_workspace.db")


@pytest.fixture
def initialized_db(db_path):
    """
    Create and initialize a temporary database with all required tables.
    Returns the db_path for use in tests.
    """
    with patch("memory_mcp.config.DB_PATH", db_path), \
         patch("memory_mcp.database.DB_PATH", db_path):
        from memory_mcp.database import init_db, migrate_db
        init_db()
        migrate_db()
    return db_path


@pytest.fixture
def db_conn(initialized_db):
    """
    Returns a live SQLite connection to the test database.
    Auto-closes after test.
    """
    conn = sqlite3.connect(initialized_db)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def patch_db_path(initialized_db):
    """Automatically patch DB_PATH for all tests in this module."""
    with patch("memory_mcp.config.DB_PATH", initialized_db), \
         patch("memory_mcp.database.DB_PATH", initialized_db):
        yield initialized_db


# ═══════════════════════════════════════════════════════════
# SAMPLE DATA FIXTURES
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def sample_conversation_id():
    return "test-conv-001"


@pytest.fixture
def sample_workspace_entry():
    """A single sample workspace entry dict."""
    return {
        "conversation_id": "test-conv-001",
        "content": "User prefers dark mode and concise answers.",
        "entry_type": "observation",
        "source_layer": "thinking",
    }


@pytest.fixture
def sample_workspace_entries():
    """Multiple sample workspace entries for batch testing."""
    return [
        {
            "conversation_id": "test-conv-001",
            "content": "User mentioned they work with Python and Docker.",
            "entry_type": "observation",
            "source_layer": "thinking",
        },
        {
            "conversation_id": "test-conv-001",
            "content": "Ran memory_graph_search for 'Docker setup'.",
            "entry_type": "note",
            "source_layer": "control",
        },
        {
            "conversation_id": "test-conv-001",
            "content": "Follow up: check if Docker Compose config is saved.",
            "entry_type": "task",
            "source_layer": "control",
        },
        {
            "conversation_id": "test-conv-002",
            "content": "Different conversation - user asked about weather.",
            "entry_type": "observation",
            "source_layer": "thinking",
        },
    ]


@pytest.fixture
def populated_workspace(initialized_db, sample_workspace_entries):
    """
    Database pre-populated with sample workspace entries.
    Returns list of (entry_dict, entry_id) tuples.
    """
    with patch("memory_mcp.config.DB_PATH", initialized_db), \
         patch("memory_mcp.database.DB_PATH", initialized_db):
        from memory_mcp.database import save_workspace_entry
        results = []
        for entry in sample_workspace_entries:
            entry_id = save_workspace_entry(**entry)
            results.append((entry, entry_id))
        return results


# ═══════════════════════════════════════════════════════════
# GRAPH FIXTURES
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def graph_store(initialized_db):
    """Create a fresh GraphStore pointing to the test DB."""
    # Reset singleton
    import graph.graph_store as gs_module
    gs_module._graph_store = None

    with patch("memory_mcp.config.DB_PATH", initialized_db):
        from graph.graph_store import GraphStore
        store = GraphStore(initialized_db)
        yield store
        gs_module._graph_store = None


@pytest.fixture
def graph_with_nodes(graph_store):
    """Graph pre-populated with sample nodes at different confidence levels."""
    node_ids = []
    # Auto-extracted nodes (confidence=0.5)
    n1 = graph_store.add_node("fact", "Danny likes pizza", confidence=0.5)
    n2 = graph_store.add_node("fact", "Server runs on Proxmox", confidence=0.5)
    # Workspace-promoted nodes (confidence=0.9)
    n3 = graph_store.add_node("workspace", "User prefers dark mode", confidence=0.9)
    n4 = graph_store.add_node("workspace", "Docker setup uses 11 containers", confidence=0.9)

    # Add edges
    graph_store.add_edge(n1, n2, "temporal", weight=1.0)
    graph_store.add_edge(n2, n3, "temporal", weight=1.0)
    graph_store.add_edge(n3, n4, "temporal", weight=1.0)

    return {
        "store": graph_store,
        "node_ids": [n1, n2, n3, n4],
        "auto_ids": [n1, n2],
        "workspace_ids": [n3, n4],
    }


# ═══════════════════════════════════════════════════════════
# MOCK MCP HUB
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def mock_mcp_hub():
    """Mock MCP Hub that records tool calls."""
    hub = MagicMock()
    hub.initialize = MagicMock()
    hub.call_tool = MagicMock(return_value={
        "structuredContent": {"id": 1, "conversation_id": "test-conv-001"}
    })
    return hub


# ═══════════════════════════════════════════════════════════
# ORCHESTRATOR FIXTURES
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def mock_thinking_plan():
    """Sample thinking plan with observable intent."""
    return {
        "intent": "User asks about Docker configuration",
        "needs_memory": True,
        "memory_keys": ["docker", "compose"],
        "hallucination_risk": "medium",
        "needs_sequential_thinking": False,
        "is_fact_query": True,
    }


@pytest.fixture
def mock_thinking_plan_high_risk():
    """Thinking plan with high hallucination risk."""
    return {
        "intent": "User asks about personal information",
        "needs_memory": True,
        "memory_keys": ["age", "birthday"],
        "hallucination_risk": "high",
        "needs_sequential_thinking": True,
    }


@pytest.fixture
def mock_thinking_plan_trivial():
    """Trivial thinking plan (no observations worth saving)."""
    return {
        "intent": "unknown",
        "needs_memory": False,
        "memory_keys": [],
        "hallucination_risk": "low",
    }


@pytest.fixture
def mock_verification_with_corrections():
    """Control layer verification result with corrections and warnings."""
    return {
        "approved": True,
        "corrections": {"memory_keys": ["docker_setup"]},
        "warnings": ["Memory key 'compose' not found"],
    }


@pytest.fixture
def mock_verification_clean():
    """Control layer verification with no corrections."""
    return {
        "approved": True,
        "corrections": {},
        "warnings": [],
    }
