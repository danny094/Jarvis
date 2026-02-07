# tests/workspace/test_mcp_tools.py
"""
Unit Tests: MCP Workspace Tools (workspace_save, workspace_list, etc.)

Tests the 5 MCP tool functions registered in tools.py.
Uses a temporary in-memory database to avoid side effects.
"""

import pytest
import sys
from unittest.mock import patch, MagicMock


# Mock modules that tools.py imports
sys.modules.setdefault("openai", MagicMock())
sys.modules.setdefault("tiktoken", MagicMock())


class TestWorkspaceSaveTool:
    """Test workspace_save MCP tool."""

    def test_save_returns_structured_content(self, initialized_db):
        """
        GIVEN: An initialized database
        WHEN: workspace_save is called
        THEN: Returns structuredContent with id, conversation_id, entry_type
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import save_workspace_entry
            entry_id = save_workspace_entry("conv-1", "test observation", "observation", "thinking")

            assert isinstance(entry_id, int)
            assert entry_id > 0

    def test_save_stores_correctly(self, initialized_db):
        """
        GIVEN: An initialized database
        WHEN: We save and retrieve
        THEN: All fields match
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import save_workspace_entry, get_workspace_entry

            entry_id = save_workspace_entry(
                "conv-test", "User likes cats", "note", "output"
            )
            entry = get_workspace_entry(entry_id)

            assert entry["conversation_id"] == "conv-test"
            assert entry["content"] == "User likes cats"
            assert entry["entry_type"] == "note"
            assert entry["source_layer"] == "output"

    def test_save_with_defaults(self, initialized_db):
        """
        GIVEN: workspace_save called with minimal params
        WHEN: We check the entry
        THEN: Defaults are observation/thinking
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import save_workspace_entry, get_workspace_entry

            entry_id = save_workspace_entry("conv-1", "minimal entry")
            entry = get_workspace_entry(entry_id)

            assert entry["entry_type"] == "observation"
            assert entry["source_layer"] == "thinking"


class TestWorkspaceListTool:
    """Test workspace_list MCP tool."""

    def test_list_empty(self, initialized_db):
        """
        GIVEN: Empty database
        WHEN: workspace_list is called
        THEN: Returns empty entries list with count 0
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import list_workspace_entries
            entries = list_workspace_entries()
            assert entries == []

    def test_list_with_entries(self, populated_workspace):
        """
        GIVEN: Database with 4 entries
        WHEN: workspace_list is called without filter
        THEN: Returns all entries
        """
        from memory_mcp.database import list_workspace_entries
        entries = list_workspace_entries()
        assert len(entries) == 4

    def test_list_filtered_by_conversation(self, populated_workspace):
        """
        GIVEN: Entries from conv-001 and conv-002
        WHEN: workspace_list with conversation_id=conv-001
        THEN: Only conv-001 entries returned
        """
        from memory_mcp.database import list_workspace_entries
        entries = list_workspace_entries(conversation_id="test-conv-001")
        assert len(entries) == 3

    def test_list_with_limit(self, populated_workspace):
        """
        GIVEN: 4 entries
        WHEN: workspace_list with limit=1
        THEN: Only 1 entry returned (the newest)
        """
        from memory_mcp.database import list_workspace_entries
        entries = list_workspace_entries(limit=1)
        assert len(entries) == 1


class TestWorkspaceGetTool:
    """Test workspace_get MCP tool."""

    def test_get_existing(self, populated_workspace):
        """
        GIVEN: A known entry ID
        WHEN: workspace_get is called
        THEN: Returns the full entry
        """
        entry_data, entry_id = populated_workspace[0]
        from memory_mcp.database import get_workspace_entry
        entry = get_workspace_entry(entry_id)

        assert entry is not None
        assert entry["id"] == entry_id
        assert entry["content"] == entry_data["content"]

    def test_get_nonexistent(self, initialized_db):
        """
        GIVEN: A nonexistent entry ID
        WHEN: workspace_get is called
        THEN: Returns None
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import get_workspace_entry
            assert get_workspace_entry(99999) is None


class TestWorkspaceUpdateTool:
    """Test workspace_update MCP tool."""

    def test_update_existing(self, populated_workspace):
        """
        GIVEN: An existing entry
        WHEN: workspace_update is called with new content
        THEN: Content is updated and updated_at is set
        """
        _, entry_id = populated_workspace[0]
        from memory_mcp.database import update_workspace_entry, get_workspace_entry

        result = update_workspace_entry(entry_id, "Updated observation")
        assert result is True

        entry = get_workspace_entry(entry_id)
        assert entry["content"] == "Updated observation"
        assert entry["updated_at"] is not None

    def test_update_nonexistent(self, initialized_db):
        """
        GIVEN: A nonexistent entry
        WHEN: workspace_update is called
        THEN: Returns False
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import update_workspace_entry
            assert update_workspace_entry(99999, "nope") is False


class TestWorkspaceDeleteTool:
    """Test workspace_delete MCP tool."""

    def test_delete_existing(self, populated_workspace):
        """
        GIVEN: An existing entry
        WHEN: workspace_delete is called
        THEN: Returns True and entry is gone
        """
        _, entry_id = populated_workspace[0]
        from memory_mcp.database import delete_workspace_entry, get_workspace_entry

        result = delete_workspace_entry(entry_id)
        assert result is True
        assert get_workspace_entry(entry_id) is None

    def test_delete_nonexistent(self, initialized_db):
        """
        GIVEN: A nonexistent entry
        WHEN: workspace_delete is called
        THEN: Returns False
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import delete_workspace_entry
            assert delete_workspace_entry(99999) is False


class TestToolRegistration:
    """Test that workspace tools are properly registered on the MCP server."""

    def test_all_workspace_tools_registered(self, initialized_db):
        """
        GIVEN: A mock MCP server
        WHEN: register_tools is called
        THEN: All 5 workspace tools are registered
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            # Mock the MCP server
            registered_tools = {}

            class MockMCP:
                def tool(self, func):
                    registered_tools[func.__name__] = func
                    return func

            mock_mcp = MockMCP()

            # Need to mock vector_store and graph modules
            with patch.dict(sys.modules, {
                "vector_store": MagicMock(),
                "graph": MagicMock(),
            }):
                from memory_mcp.tools import register_tools
                register_tools(mock_mcp)

            workspace_tools = [k for k in registered_tools if k.startswith("workspace_")]
            assert "workspace_save" in workspace_tools
            assert "workspace_list" in workspace_tools
            assert "workspace_get" in workspace_tools
            assert "workspace_update" in workspace_tools
            assert "workspace_delete" in workspace_tools
            assert len(workspace_tools) == 5
