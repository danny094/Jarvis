# Knowledge Graph

The `sql-memory` module includes a graph database implementation built on top of SQLite. This allows the system to model relationships between facts, interactions, and entities.

## Components

### `graph_store.py` (`GraphStore`)
The core database abstraction. It manages two main tables:
- **`graph_nodes`**: Vertices in the graph.
    - `source_type`: e.g., "fact", "message", "file".
    - `content`: Textual content.
    - `embedding`: Vector representation (BLOB).
- **`graph_edges`**: Connections between nodes.
    - `edge_type`: e.g., "semantic", "temporal", "cooccur".
    - `weight`: Strength of the connection (0.0 - 1.0).

**Key Operations**:
- `add_node` / `add_edge`: Basic CRUD.
- `get_neighbors`: Retrieves connected nodes (outgoing/incoming).
- `graph_walk`: Performs a Breadth-First Search (BFS) to find related concepts up to a certain depth.

### `graph_builder.py`
Automates the creation of edges to ensure the graph remains connected and useful.

**Automatic Edge Generation**:
1.  **Temporal Edges**: Connects each new node in a conversation to the previous one, preserving chronology.
2.  **Semantic Edges**: Automatically connects nodes if their vector embeddings have a high cosine similarity (> 0.70).
3.  **Co-occurrence Edges**: Connects nodes that share extracting keywords or topics.

## Usage

The graph is primarily used via the `memory_mcp` tools, specifically `memory_graph_search`, which performs a graph walk starting from semantically relevant nodes to uncover context that keyword search matches might miss.
