# Changelog

## [2025-11-30] - Performance, Streaming & Knowledge Graph Update

### ✨ New features

**Streaming Support**
- OutputLayer now supports true token streaming
- Text appears word by word instead of all at once
- More natural UX, perceived faster response times

**Konfigurierbare Modelle**
- All models can be changed centrally in `config.py` or `docker-compose.yml`
- No rebuild is necessary when changing environment variables

**Knowledge Graph System**
- New graph-based memory system for intelligent search
- Facts are stored as nodes with embeddings
- Automatic edge creation between related facts:
- **Semantic Edges**: Connects similar concepts (e.g., "age" ↔ "birthday", similarity 0.87)
- **Temporal Edges**: Connects consecutive facts in a conversation
- **Co-Occurrence Edges**: Connects facts that are mentioned together
- Multi-hop retrieval: Finds related facts via graph walk
- Example: A query for "birthday" also finds "age: 31" via semantic connection

**Graph architecture:**
```
              [Danny name: Danny]
                    │
          ┌────────┴────────┐
          │ 0.82            │ 0.83
          ▼                 │
    [Danny age: 31]         │
          │                 │
          │ 0.87            │
          ▼                 │
    [Danny birthday: 19.11]─┘
```

### ⚡ Performance

**ControlLayer Skip at Low-Risk**
- `SKIP_CONTROL_ON_LOW_RISK=true` skips Layer 2 for simple requests
- ~33% faster for greetings, small talk, and general knowledge

**Memory Retrieval Order (optimized):**
```
1. SQL Fact (Exact) →       Fastest when key matches exactly
2. Graph Search →           Finds related facts across edges
3. Semantic Search →        Embedding-based similarity
4. Text Fallback →          LIKE search as a last resort
```

### 🔧 configuration

**Modify models via `docker-compose.yml`:**
```yaml
environment:
  - THINKING_MODEL=deepseek-r1:8b
  - CONTROL_MODEL=qwen3:4b
  - OUTPUT_MODEL=llama3.1:8b
  - EMBEDDING_MODEL=hellord/mxbai-embed-large-v1:f16
  - SKIP_CONTROL_ON_LOW_RISK=true
```

**Oder via `config.py`:**
```python
THINKING_MODEL = os.getenv("THINKING_MODEL", "deepseek-r1:8b")
CONTROL_MODEL = os.getenv("CONTROL_MODEL", "qwen3:4b")
OUTPUT_MODEL = os.getenv("OUTPUT_MODEL", "llama3.1:8b")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "hellord/mxbai-embed-large-v1:f16")
```

### 📝 Logs

**Low-Risk (z.B. "Hallo"):**
```
[CoreBridge] === LAYER 2: CONTROL === SKIPPED (low-risk)
```

**High-Risk (z.B. "How old am I?"):**
```
[CoreBridge] === LAYER 2: CONTROL ===
[CoreBridge-Control] approved=True
```

**Graph Search:**
```
[CoreBridge-Memory] Trying graph search for 'birthday'
[CoreBridge-Memory] Graph match: Danny age: 31
[CoreBridge-Memory] Graph match: Danny birthday: 19.11
```

### 📁 Modified files

**assistant-proxy:**
- `config.py` - Central Model Configuration
- `core/layers/output.py` - Streaming Support
- `core/bridge.py` - process_stream(), ControlLayer Skip, Graph Search Integration
- `core/mcp/client.py` - graph_search() Funktion
- `adapters/lobechat/main.py` - Streaming Response
- `docker-compose.yml` - Environment Variables

**sql-memory:**
- `graph/` - New folder for graph system
- `graph/graph_store.py` - SQLite Graph with Nodes & Edges
- `graph/graph_builder.py` - Automatic edge creation
- `memory_mcp/tools.py` - New tools: memory_graph_search, memory_graph_neighbors, memory_graph_stats
- `embedding.py` - Configurable EMBEDDING_MODEL variable

### 🗄️ new database tables
```sql
-- Graph Nodes
CREATE TABLE graph_nodes (
    id INTEGER PRIMARY KEY,
    source_type TEXT,      -- 'fact', 'memory', 'persona'
    source_id INTEGER,
    content TEXT,
    embedding BLOB,
    conversation_id TEXT,
    created_at TIMESTAMP
);

-- Graph Edges  
CREATE TABLE graph_edges (
    id INTEGER PRIMARY KEY,
    src_node_id INTEGER,
    dst_node_id INTEGER,
    edge_type TEXT,        -- 'semantic', 'temporal', 'cooccur', 'inferred'
    weight REAL,           -- 0.0 - 1.0
    created_at TIMESTAMP
);
```

