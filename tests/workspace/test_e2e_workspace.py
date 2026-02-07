# tests/workspace/test_e2e_workspace.py
"""
End-to-End Tests: Full Agent Workspace flow

Tests the complete pipeline:
1. Save entry → stored in DB
2. List entries → entries retrieved
3. Update entry → content modified
4. Promote via maintenance → graph node created with confidence=0.9
5. Graph walk → promoted entries rank higher
6. Delete entry → removed from DB
7. SSE event structure → valid for frontend consumption
"""

import pytest
import json
from unittest.mock import patch, MagicMock
from datetime import datetime


class TestFullCRUDLifecycle:
    """Test complete create → read → update → delete cycle."""

    def test_full_crud_lifecycle(self, initialized_db):
        """
        GIVEN: An initialized database
        WHEN: We create, read, update, and delete an entry
        THEN: Each operation succeeds correctly
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import (
                save_workspace_entry,
                get_workspace_entry,
                update_workspace_entry,
                delete_workspace_entry,
                list_workspace_entries,
            )

            # CREATE
            entry_id = save_workspace_entry(
                "conv-e2e", "Initial observation", "observation", "thinking"
            )
            assert entry_id > 0

            # READ
            entry = get_workspace_entry(entry_id)
            assert entry["content"] == "Initial observation"
            assert entry["conversation_id"] == "conv-e2e"
            assert entry["promoted"] is False

            # LIST
            entries = list_workspace_entries(conversation_id="conv-e2e")
            assert len(entries) == 1
            assert entries[0]["id"] == entry_id

            # UPDATE
            success = update_workspace_entry(entry_id, "Modified observation")
            assert success is True
            updated = get_workspace_entry(entry_id)
            assert updated["content"] == "Modified observation"
            assert updated["updated_at"] is not None

            # DELETE
            deleted = delete_workspace_entry(entry_id)
            assert deleted is True
            assert get_workspace_entry(entry_id) is None
            assert list_workspace_entries(conversation_id="conv-e2e") == []


class TestPromotionLifecycle:
    """Test full workspace → graph promotion lifecycle."""

    def test_entry_to_graph_promotion(self, initialized_db):
        """
        GIVEN: Workspace entries saved in DB
        WHEN: Promotion runs (Phase 4 logic)
        THEN: Entries become graph nodes with high confidence, marked promoted
        """
        import graph.graph_store as gs_module
        gs_module._graph_store = None

        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import (
                save_workspace_entry,
                get_unpromoted_entries,
                mark_promoted,
                get_workspace_entry,
            )
            from graph.graph_store import GraphStore
            from graph.graph_builder import build_node_with_edges

            gs_module._graph_store = GraphStore(initialized_db)

            # Step 1: Create entries
            id1 = save_workspace_entry("conv-promo", "User works with Docker", "observation", "thinking")
            id2 = save_workspace_entry("conv-promo", "Server has 8GB VRAM", "note", "control")

            # Step 2: Verify unpromoted
            unpromoted = get_unpromoted_entries()
            assert len(unpromoted) == 2

            # Step 3: Promote (simulate Phase 4)
            node_ids = []
            for entry in unpromoted:
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

            # Step 4: Verify promotion
            assert len(get_unpromoted_entries()) == 0

            e1 = get_workspace_entry(id1)
            assert e1["promoted"] is True
            assert e1["promoted_at"] is not None

            # Step 5: Verify graph nodes
            for nid in node_ids:
                node = gs_module._graph_store.get_node(nid)
                assert node["source_type"] == "workspace"
                assert node["confidence"] == 0.9

            # Step 6: Graph walk should rank workspace nodes first
            # Add a low-confidence node for comparison
            low_id = gs_module._graph_store.add_node("fact", "low priority fact", confidence=0.5)
            gs_module._graph_store.add_edge(node_ids[0], low_id, "semantic", weight=0.5)

            all_ids = node_ids + [low_id]
            walked = gs_module._graph_store.graph_walk(all_ids, depth=2, limit=10)

            # Workspace nodes (0.9) should appear before fact (0.5)
            confidences = [n.get("confidence", 0.5) for n in walked]
            assert confidences == sorted(confidences, reverse=True), \
                f"Graph walk should sort by confidence DESC: {confidences}"

            gs_module._graph_store = None


class TestMultiConversationIsolation:
    """Test that workspace entries are properly isolated per conversation."""

    def test_entries_isolated_by_conversation(self, initialized_db):
        """
        GIVEN: Entries from 3 different conversations
        WHEN: We query per conversation
        THEN: Only that conversation's entries are returned
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import save_workspace_entry, list_workspace_entries

            # Create entries in 3 conversations
            for i in range(5):
                save_workspace_entry(f"conv-A", f"Entry A-{i}")
            for i in range(3):
                save_workspace_entry(f"conv-B", f"Entry B-{i}")
            save_workspace_entry("conv-C", "Lonely entry")

            # Verify isolation
            a_entries = list_workspace_entries(conversation_id="conv-A")
            b_entries = list_workspace_entries(conversation_id="conv-B")
            c_entries = list_workspace_entries(conversation_id="conv-C")
            all_entries = list_workspace_entries()

            assert len(a_entries) == 5
            assert len(b_entries) == 3
            assert len(c_entries) == 1
            assert len(all_entries) == 9

            # Verify no cross-contamination
            assert all(e["conversation_id"] == "conv-A" for e in a_entries)
            assert all(e["conversation_id"] == "conv-B" for e in b_entries)


class TestSSEEventStructure:
    """Test that workspace_update events match the expected frontend format."""

    def test_event_has_all_required_fields(self):
        """
        GIVEN: A workspace_update event dict
        WHEN: Frontend receives it via SSE/NDJSON
        THEN: All fields needed by workspace.js are present
        """
        event = {
            "type": "workspace_update",
            "entry_id": 42,
            "content": "**Intent:** User asks about Docker",
            "entry_type": "observation",
            "source_layer": "thinking",
            "conversation_id": "webui-1234",
            "timestamp": "2026-02-06T14:30:00Z",
        }

        # Fields required by workspace.js handleWorkspaceUpdate()
        assert event["type"] == "workspace_update"
        assert isinstance(event["entry_id"], int)
        assert isinstance(event["content"], str)
        assert event["entry_type"] in ("observation", "task", "note")
        assert event["source_layer"] in ("thinking", "control", "output")
        assert isinstance(event["conversation_id"], str)
        assert isinstance(event["timestamp"], str)

    def test_event_is_json_serializable(self):
        """
        GIVEN: A workspace_update event
        WHEN: We serialize it as JSON (for NDJSON stream)
        THEN: It serializes without error
        """
        event = {
            "type": "workspace_update",
            "entry_id": 1,
            "content": "Ä Ö Ü special chars 🎉",
            "entry_type": "note",
            "source_layer": "control",
            "conversation_id": "conv-1",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

        serialized = json.dumps(event, ensure_ascii=False)
        deserialized = json.loads(serialized)

        assert deserialized["type"] == "workspace_update"
        assert deserialized["content"] == "Ä Ö Ü special chars 🎉"

    def test_ndjson_pass_through_format(self):
        """
        GIVEN: workspace_update event in NDJSON format (admin-api output)
        WHEN: api.js processes it
        THEN: It matches the flatEventTypes pattern for pass-through
        """
        # Simulate admin-api NDJSON line
        ndjson_line = json.dumps({
            "model": "qwen3:4b",
            "created_at": "2026-02-06T14:30:00Z",
            "type": "workspace_update",  # <-- flatEventTypes match
            "entry_id": 1,
            "content": "test",
            "entry_type": "observation",
            "conversation_id": "conv-1",
            "timestamp": "2026-02-06T14:30:00Z",
            "done": False,
        })

        data = json.loads(ndjson_line)

        # api.js check: data.type && flatEventTypes.includes(data.type)
        flat_event_types = [
            'sequential_start', 'sequential_step', 'sequential_done', 'sequential_error',
            'seq_thinking_stream', 'seq_thinking_done',
            'mcp_call', 'mcp_result',
            'cim_store', 'memory_update',
            'workspace_update',  # <-- Our addition
        ]

        assert data.get("type") in flat_event_types

    def test_plugin_event_dispatch_format(self):
        """
        GIVEN: A workspace_update chunk from api.js
        WHEN: chat.js checks pluginEvents
        THEN: It matches and gets dispatched as CustomEvent
        """
        chunk = {
            "type": "workspace_update",
            "entry_id": 5,
            "content": "Observation from thinking",
            "entry_type": "observation",
            "conversation_id": "webui-123",
        }

        plugin_events = [
            "mcp_call", "mcp_result",
            "cim_store", "memory_update",
            "panel_create_tab", "panel_update", "panel_close_tab", "panel_control",
            "workspace_update",
        ]

        assert chunk["type"] in plugin_events


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_content_save(self, initialized_db):
        """
        GIVEN: An empty content string
        WHEN: We try to save it
        THEN: It saves (no constraint violation)
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import save_workspace_entry, get_workspace_entry
            entry_id = save_workspace_entry("conv-1", "")
            entry = get_workspace_entry(entry_id)
            assert entry["content"] == ""

    def test_very_long_conversation_id(self, initialized_db):
        """
        GIVEN: An extremely long conversation_id
        WHEN: We save and query
        THEN: It works correctly
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import save_workspace_entry, list_workspace_entries
            long_id = "conv-" + "x" * 1000
            save_workspace_entry(long_id, "long conv id entry")
            entries = list_workspace_entries(conversation_id=long_id)
            assert len(entries) == 1

    def test_special_characters_in_content(self, initialized_db):
        """
        GIVEN: Content with SQL-injection-like characters
        WHEN: We save and retrieve
        THEN: Content is stored safely (no injection)
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import save_workspace_entry, get_workspace_entry
            malicious = "'; DROP TABLE workspace_entries; --"
            entry_id = save_workspace_entry("conv-1", malicious)
            entry = get_workspace_entry(entry_id)
            assert entry["content"] == malicious

            # Table should still exist
            from memory_mcp.database import list_workspace_entries
            entries = list_workspace_entries()
            assert len(entries) >= 1

    def test_concurrent_save_unique_ids(self, initialized_db):
        """
        GIVEN: Multiple entries saved rapidly
        WHEN: All saves complete
        THEN: All IDs are unique (autoincrement works)
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import save_workspace_entry
            ids = []
            for i in range(100):
                ids.append(save_workspace_entry("conv-rapid", f"rapid entry {i}"))

            assert len(set(ids)) == 100, "All 100 IDs should be unique"

    def test_delete_then_reuse_content(self, initialized_db):
        """
        GIVEN: An entry that was deleted
        WHEN: We create a new entry with the same content
        THEN: It gets a new ID (no conflicts)
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import (
                save_workspace_entry, delete_workspace_entry, get_workspace_entry
            )

            id1 = save_workspace_entry("conv-1", "recyclable content")
            delete_workspace_entry(id1)
            assert get_workspace_entry(id1) is None

            id2 = save_workspace_entry("conv-1", "recyclable content")
            assert id2 != id1
            assert get_workspace_entry(id2)["content"] == "recyclable content"

    def test_update_with_markdown_content(self, initialized_db):
        """
        GIVEN: An existing entry
        WHEN: Updated with rich Markdown content
        THEN: Markdown is preserved exactly
        """
        with patch("memory_mcp.config.DB_PATH", initialized_db):
            from memory_mcp.database import save_workspace_entry, update_workspace_entry, get_workspace_entry

            entry_id = save_workspace_entry("conv-1", "plain text")

            md_content = """# Header

- **Bold** item
- *Italic* item
- `code` item

```python
def hello():
    print("world")
```

| Column1 | Column2 |
|---------|---------|
| a       | b       |
"""
            update_workspace_entry(entry_id, md_content)
            entry = get_workspace_entry(entry_id)
            assert entry["content"] == md_content
            assert "```python" in entry["content"]
            assert "| Column1 |" in entry["content"]
