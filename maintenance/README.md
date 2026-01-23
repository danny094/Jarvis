# Maintenance Module

Handles background tasks for maintaining the health and organization of the assistant's memory system.

## Purpose

As the assistant interacts with users, its memory (long-term facts, short-term logs) can grow and become disorganized. This module provides tools to:
- Consolidate short-term memories into long-term facts
- Clean up duplicate or irrelevant entries
- Summarize conversations
- Optimize the knowledge graph

## Components

### worker.py
Contains the core logic for maintenance jobs.
- **Deduplication**: Identifies and merges similar facts
- **Layer Migration**: Moves relevant items from STM to LTM
- **Graph Optimization**: Prunes weak connections and identifies clusters

### routes.py
Exposes REST endpoints to trigger maintenance tasks manually or via cron jobs.
- /maintenance/run: Triggers a full maintenance cycle

---

## Dependencies

### Required MCP Tools (sql-memory)
- memory_list_conversations
- memory_all_recent
- memory_delete_bulk
- memory_graph_stats
- graph_find_duplicate_nodes
- graph_merge_nodes
- graph_delete_orphan_nodes
- graph_prune_weak_edges

If any missing → empty results or silent failure.

---

## Known Issues

### Duplicate Detection Returns Empty (🔴 Not Fixed)
**Symptom**: Reports "Keine Einträge gefunden" despite data existing  
**Cause**: Response unwrapping issue  
**Status**: Under investigation

### Graph Merging Finds But Doesn't Execute (🔴 Not Fixed)
**Symptom**: "Fand X Duplikat-Gruppen" but "0 merged"  
**Cause**: Tool execution or logic issue  
**Status**: Under investigation

---

## Troubleshooting

### Maintenance Reports "0 Conversations, 0 Entries"

**Check MCP server running:**
```bash
sudo docker ps | grep mcp-sql-memory
```

**Check tool exists:**
```bash
sudo docker exec mcp-sql-memory grep -n 'def memory_list_conversations' /app/memory_mcp/tools.py
```

**Check adapter logs:**
```bash
sudo docker logs lobechat-adapter --tail 50 | grep -i tool not found
```

**Fix**: Restart containers
```bash
sudo docker compose stop mcp-sql-memory
sudo docker compose up -d mcp-sql-memory
sudo docker compose restart lobechat-adapter
```

---

## Recent Fixes

### 2025-12-31: Missing MCP Tool
**Problem**: Maintenance reported 0 conversations/entries  
**Solution**: Implemented memory_list_conversations tool  
**Result**: Now finds 5 conversations, 48 entries, 40 nodes

See: [DEBUGGING_LOG.md](/assistant-proxy/DEBUGGING_LOG.md)

---

## References
- [Core Architecture](/documentation/01_CORE.md)
- [MCP Documentation](/documentation/03_MCP.md)  
- [Debugging Log](/assistant-proxy/DEBUGGING_LOG.md)
