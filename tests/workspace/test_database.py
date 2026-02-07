# tests/workspace/test_database.py
"""
Unit Tests: workspace_entries CRUD operations in database.py

Tests all database-level workspace functions:
- save_workspace_entry
- list_workspace_entries
- get_workspace_entry
- update_workspace_entry
- delete_workspace_entry
- get_unpromoted_entries
- mark_promoted
- Schema creation & migration
"""

import pytest
import sqlite3
from unittest.mock import patch
from datetime import datetime


class TestWorkspaceSchema:
    """Test workspace_entries table creation and migration."""

    def test_workspace_table_exists_after_init(self, db_conn):
        """
        GIVEN: A freshly initialized database
        WHEN: We check for workspace_entries table
        THEN: The table exists with correct columns
        """
        cursor = db_conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='workspace_entries'
        """)
        assert cursor.fetchone() is not None, "workspace_entries table should exist"

    def test_workspace_table_columns(self, db_conn):
        """
        GIVEN: workspace_entries table exists
        WHEN: We inspect its columns
        THEN: All required columns are present
        """
        cursor = db_conn.cursor()
        cursor.execute("PRAGMA table_info(workspace_entries)")
        columns = {row[1] for row in cursor.fetchall()}

        expected = {
            "id", "conversation_id", "content", "entry_type",
            "source_layer", "created_at", "updated_at",
            "promoted", "promoted_at"
        }
        assert expected.issubset(columns), f"Missing columns: {expected - columns}"

    def test_workspace_index_exists(self, db_conn):
        """
        GIVEN: A freshly initialized database
        WHEN: We check for the conversation_id index
        THEN: idx_workspace_conv index exists
        """
        cursor = db_conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND name='idx_workspace_conv'
        """)
        assert cursor.fetchone() is not None, "idx_workspace_conv index should exist"

    def test_graph_nodes_has_confidence_column(self, initialized_db):
        """
        GIVEN: Database with graph_nodes table (created by GraphStore)
        WHEN: We check graph_nodes columns
        THEN: confidence column exists with default 0.5
        """
        # graph_nodes is created by GraphStore._init_tables, not init_db
        from graph.graph_store import GraphStore
        import graph.graph_store as gs_module
        gs_module._graph_store = None
        gs = GraphStore(initialized_db)

        import sqlite3
        conn = sqlite3.connect(initialized_db)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(graph_nodes)")
        columns = {row[1]: row[4] for row in cursor.fetchall()}
        conn.close()
        gs_module._graph_store = None

        assert "confidence" in columns, "graph_nodes should have confidence column"

    def test_migrate_db_is_idempotent(self, initialized_db):
        """
        GIVEN: An already-migrated database
        WHEN: We run migrate_db() again
        THEN: No errors occur (idempotent)
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import migrate_db
            # Should not raise
            migrate_db()
            migrate_db()


class TestSaveWorkspaceEntry:
    """Test save_workspace_entry function."""

    def test_save_returns_positive_id(self, initialized_db):
        """
        GIVEN: An initialized database
        WHEN: We save a workspace entry
        THEN: A positive integer ID is returned
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import save_workspace_entry
            entry_id = save_workspace_entry("conv-1", "test content")
            assert isinstance(entry_id, int)
            assert entry_id > 0

    def test_save_default_values(self, initialized_db):
        """
        GIVEN: An initialized database
        WHEN: We save with only required params
        THEN: Defaults are applied correctly
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import save_workspace_entry, get_workspace_entry
            entry_id = save_workspace_entry("conv-1", "test content")
            entry = get_workspace_entry(entry_id)

            assert entry["entry_type"] == "observation"
            assert entry["source_layer"] == "thinking"
            assert entry["promoted"] is False
            assert entry["promoted_at"] is None
            assert entry["updated_at"] is None

    def test_save_custom_values(self, initialized_db):
        """
        GIVEN: An initialized database
        WHEN: We save with custom entry_type and source_layer
        THEN: Custom values are stored
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import save_workspace_entry, get_workspace_entry
            entry_id = save_workspace_entry(
                "conv-1", "task: deploy container", "task", "control"
            )
            entry = get_workspace_entry(entry_id)

            assert entry["entry_type"] == "task"
            assert entry["source_layer"] == "control"
            assert entry["content"] == "task: deploy container"

    def test_save_timestamps_are_iso(self, initialized_db):
        """
        GIVEN: We save a workspace entry
        WHEN: We inspect its created_at
        THEN: It's a valid ISO timestamp ending in Z
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import save_workspace_entry, get_workspace_entry
            entry_id = save_workspace_entry("conv-1", "test")
            entry = get_workspace_entry(entry_id)

            assert entry["created_at"].endswith("Z")
            # Should parse without error
            datetime.fromisoformat(entry["created_at"].replace("Z", "+00:00"))

    def test_save_multiple_entries_unique_ids(self, initialized_db):
        """
        GIVEN: An initialized database
        WHEN: We save multiple entries
        THEN: Each gets a unique auto-incremented ID
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import save_workspace_entry
            ids = [save_workspace_entry("conv-1", f"entry {i}") for i in range(5)]
            assert len(set(ids)) == 5, "All IDs should be unique"
            assert ids == sorted(ids), "IDs should be auto-incrementing"

    def test_save_unicode_content(self, initialized_db):
        """
        GIVEN: An initialized database
        WHEN: We save content with Unicode characters
        THEN: Content is preserved correctly
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import save_workspace_entry, get_workspace_entry
            content = "Benutzer sagt: Ä Ö Ü ß 🎉 日本語"
            entry_id = save_workspace_entry("conv-1", content)
            entry = get_workspace_entry(entry_id)
            assert entry["content"] == content

    def test_save_large_content(self, initialized_db):
        """
        GIVEN: An initialized database
        WHEN: We save a very large content string
        THEN: It is stored and retrieved correctly
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import save_workspace_entry, get_workspace_entry
            content = "x" * 50000  # 50KB
            entry_id = save_workspace_entry("conv-1", content)
            entry = get_workspace_entry(entry_id)
            assert len(entry["content"]) == 50000


class TestListWorkspaceEntries:
    """Test list_workspace_entries function."""

    def test_list_empty_database(self, initialized_db):
        """
        GIVEN: An empty database
        WHEN: We list workspace entries
        THEN: An empty list is returned
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import list_workspace_entries
            result = list_workspace_entries()
            assert result == []

    def test_list_all_entries(self, populated_workspace):
        """
        GIVEN: A database with 4 entries across 2 conversations
        WHEN: We list all entries (no filter)
        THEN: All 4 entries are returned
        """
        from memory_mcp.database import list_workspace_entries
        result = list_workspace_entries()
        assert len(result) == 4

    def test_list_filter_by_conversation(self, populated_workspace):
        """
        GIVEN: Entries from conv-001 and conv-002
        WHEN: We filter by conv-001
        THEN: Only conv-001 entries are returned
        """
        from memory_mcp.database import list_workspace_entries
        result = list_workspace_entries(conversation_id="test-conv-001")
        assert len(result) == 3
        assert all(e["conversation_id"] == "test-conv-001" for e in result)

    def test_list_filter_returns_empty_for_unknown_conv(self, populated_workspace):
        """
        GIVEN: Populated workspace
        WHEN: We filter by a nonexistent conversation
        THEN: Empty list returned
        """
        from memory_mcp.database import list_workspace_entries
        result = list_workspace_entries(conversation_id="nonexistent-conv")
        assert result == []

    def test_list_respects_limit(self, populated_workspace):
        """
        GIVEN: 4 entries in database
        WHEN: We set limit=2
        THEN: Only 2 entries returned
        """
        from memory_mcp.database import list_workspace_entries
        result = list_workspace_entries(limit=2)
        assert len(result) == 2

    def test_list_order_is_desc_by_id(self, populated_workspace):
        """
        GIVEN: Multiple entries
        WHEN: We list them
        THEN: They are ordered by id DESC (newest first)
        """
        from memory_mcp.database import list_workspace_entries
        result = list_workspace_entries()
        ids = [e["id"] for e in result]
        assert ids == sorted(ids, reverse=True)


class TestGetWorkspaceEntry:
    """Test get_workspace_entry function."""

    def test_get_existing_entry(self, populated_workspace):
        """
        GIVEN: A known entry ID
        WHEN: We get it
        THEN: Full entry dict is returned with all fields
        """
        entry_data, entry_id = populated_workspace[0]
        from memory_mcp.database import get_workspace_entry
        result = get_workspace_entry(entry_id)

        assert result is not None
        assert result["id"] == entry_id
        assert result["content"] == entry_data["content"]
        assert result["conversation_id"] == entry_data["conversation_id"]
        assert result["entry_type"] == entry_data["entry_type"]
        assert result["source_layer"] == entry_data["source_layer"]
        assert "created_at" in result

    def test_get_nonexistent_returns_none(self, initialized_db):
        """
        GIVEN: An initialized database
        WHEN: We get a nonexistent entry ID
        THEN: None is returned
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import get_workspace_entry
            assert get_workspace_entry(99999) is None


class TestUpdateWorkspaceEntry:
    """Test update_workspace_entry function."""

    def test_update_content(self, populated_workspace):
        """
        GIVEN: An existing workspace entry
        WHEN: We update its content
        THEN: The content is changed and updated_at is set
        """
        _, entry_id = populated_workspace[0]
        from memory_mcp.database import update_workspace_entry, get_workspace_entry

        new_content = "Updated: User also likes dark themes."
        result = update_workspace_entry(entry_id, new_content)
        assert result is True

        entry = get_workspace_entry(entry_id)
        assert entry["content"] == new_content
        assert entry["updated_at"] is not None
        assert entry["updated_at"].endswith("Z")

    def test_update_nonexistent_returns_false(self, initialized_db):
        """
        GIVEN: An initialized database
        WHEN: We update a nonexistent entry
        THEN: False is returned
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import update_workspace_entry
            result = update_workspace_entry(99999, "new content")
            assert result is False

    def test_update_preserves_other_fields(self, populated_workspace):
        """
        GIVEN: An existing entry with conversation_id and entry_type
        WHEN: We update only the content
        THEN: conversation_id, entry_type, source_layer, created_at are preserved
        """
        entry_data, entry_id = populated_workspace[0]
        from memory_mcp.database import update_workspace_entry, get_workspace_entry

        update_workspace_entry(entry_id, "MODIFIED CONTENT")
        entry = get_workspace_entry(entry_id)

        assert entry["conversation_id"] == entry_data["conversation_id"]
        assert entry["entry_type"] == entry_data["entry_type"]
        assert entry["source_layer"] == entry_data["source_layer"]
        assert entry["created_at"] is not None  # Still set from creation


class TestDeleteWorkspaceEntry:
    """Test delete_workspace_entry function."""

    def test_delete_existing_entry(self, populated_workspace):
        """
        GIVEN: An existing entry
        WHEN: We delete it
        THEN: True is returned and entry no longer exists
        """
        _, entry_id = populated_workspace[0]
        from memory_mcp.database import delete_workspace_entry, get_workspace_entry

        result = delete_workspace_entry(entry_id)
        assert result is True
        assert get_workspace_entry(entry_id) is None

    def test_delete_nonexistent_returns_false(self, initialized_db):
        """
        GIVEN: An initialized database
        WHEN: We delete a nonexistent entry
        THEN: False is returned
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import delete_workspace_entry
            assert delete_workspace_entry(99999) is False

    def test_delete_does_not_affect_others(self, populated_workspace):
        """
        GIVEN: 4 entries in database
        WHEN: We delete one
        THEN: The other 3 still exist
        """
        _, entry_id = populated_workspace[0]
        from memory_mcp.database import delete_workspace_entry, list_workspace_entries

        delete_workspace_entry(entry_id)
        remaining = list_workspace_entries()
        assert len(remaining) == 3
        assert all(e["id"] != entry_id for e in remaining)


class TestGetUnpromotedEntries:
    """Test get_unpromoted_entries function."""

    def test_all_unpromoted_initially(self, populated_workspace):
        """
        GIVEN: 4 entries, none promoted
        WHEN: We get unpromoted
        THEN: All 4 are returned
        """
        from memory_mcp.database import get_unpromoted_entries
        result = get_unpromoted_entries()
        assert len(result) == 4
        assert all(e["promoted"] is False for e in result)

    def test_unpromoted_ordered_by_id_asc(self, populated_workspace):
        """
        GIVEN: Multiple unpromoted entries
        WHEN: We get them
        THEN: They are ordered by id ASC (oldest first for batch promotion)
        """
        from memory_mcp.database import get_unpromoted_entries
        result = get_unpromoted_entries()
        ids = [e["id"] for e in result]
        assert ids == sorted(ids)

    def test_promoted_entries_excluded(self, populated_workspace):
        """
        GIVEN: 4 entries, 2 promoted
        WHEN: We get unpromoted
        THEN: Only the 2 unpromoted are returned
        """
        from memory_mcp.database import get_unpromoted_entries, mark_promoted

        _, id1 = populated_workspace[0]
        _, id2 = populated_workspace[1]
        mark_promoted(id1)
        mark_promoted(id2)

        result = get_unpromoted_entries()
        assert len(result) == 2
        ids = [e["id"] for e in result]
        assert id1 not in ids
        assert id2 not in ids


class TestMarkPromoted:
    """Test mark_promoted function."""

    def test_mark_promoted_sets_flag(self, populated_workspace):
        """
        GIVEN: An unpromoted entry
        WHEN: We mark it as promoted
        THEN: promoted=True and promoted_at is set
        """
        _, entry_id = populated_workspace[0]
        from memory_mcp.database import mark_promoted, get_workspace_entry

        result = mark_promoted(entry_id)
        assert result is True

        entry = get_workspace_entry(entry_id)
        assert entry["promoted"] is True
        assert entry["promoted_at"] is not None
        assert entry["promoted_at"].endswith("Z")

    def test_mark_promoted_nonexistent(self, initialized_db):
        """
        GIVEN: An initialized database
        WHEN: We mark a nonexistent entry as promoted
        THEN: False is returned
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import mark_promoted
            assert mark_promoted(99999) is False

    def test_mark_promoted_is_idempotent(self, populated_workspace):
        """
        GIVEN: An already-promoted entry
        WHEN: We mark it promoted again
        THEN: No error, still promoted
        """
        _, entry_id = populated_workspace[0]
        from memory_mcp.database import mark_promoted, get_workspace_entry

        mark_promoted(entry_id)
        mark_promoted(entry_id)  # Second time

        entry = get_workspace_entry(entry_id)
        assert entry["promoted"] is True
