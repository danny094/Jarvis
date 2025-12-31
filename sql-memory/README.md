# SQL Memory MCP Server

This module implements a Model Context Protocol (MCP) server that provides persistent memory capabilities using SQLite and Vector Search. It allows for storing, retrieving, and searching conversation history and structured facts, leveraging embeddings for semantic understanding.

## Purpose

The `sql-memory` module serves as a long-term memory store for AI assistants. It enables:
- **Persistent Storage**: Saves conversation turns and extracted facts to a SQLite database.
- **Semantic Search**: Uses vector embeddings (via Ollama) to find relevant memories based on meaning rather than just keywords.
- **Graph Connections**: Manages relationships between facts using a graph structure.
- **Maintenance**: Provides tools for cleaning up and optimizing the memory store.

## Dependencies

- **FastMCP**: Framework for building MCP servers.
- **SQLite3**: Local relational database.
- **Ollama**: External service used for generating text embeddings.
- **Requests**: For HTTP communication with Ollama.

## Configuration

The module is configured via environment variables:

- `OLLAMA_URL`: URL of the Ollama instance (default: `http://ollama:11434`)
- `EMBEDDING_MODEL`: The model used for generating embeddings (default: `hellord/mxbai-embed-large-v1:f16`)
- `DB_PATH`: Path to the SQLite database file (defined in internal config).

## Key Components

### `embedding.py`
Handles communication with the Ollama API to generate vector embeddings for text.

### `vector_store.py`
Manages the `embeddings` table in SQLite. It handles:
- Initialization of the database schema.
- Adding new embeddings.
- Performing cosine similarity searches to find relevant content.

### `memory_mcp/server.py`
The entry point for the MCP server. It initializes the database and registers the available tools.

### `memory_mcp/tools.py`
Defines the tools exposed to the MCP client.

## Available Tools

The server exposes a wide range of tools for memory management:

### Basic Memory
- `memory_save`: Saves free-text memory.
- `memory_search`: Performs a keyword-based search (SQL `LIKE`).
- `memory_recent`: Retrieves the most recent memory entries.
- `memory_delete`: Deletes a specific memory entry.

### Semantic Memory
- `memory_semantic_save`: Saves content with its vector embedding.
- `memory_semantic_search`: Finds entries semantically similar to a query.
- `memory_search_layered`: Searches across different memory layers (short-term, mid-term, long-term).

### Structured Facts & Graph
- `memory_fact_save`: Saves a structured fact (subject, key, value) and creates a corresponding graph node.
- `memory_fact_load`: Retrieves a specific fact.
- `memory_graph_search`: Performs a graph walk to find connected information.
- `memory_graph_neighbors`: Gets the neighbors of a specific graph node.
- `memory_graph_stats`: Returns statistics about the knowledge graph.

### Maintenance
- `maintenance_run`: AI-powered maintenance task to organize and clean memory.
- `memory_all_recent`, `memory_delete_bulk`: Helper tools for bulk operations.
- `graph_find_duplicate_nodes`, `graph_merge_nodes`: Tools for deduplicating the graph.

## Usage

This module is designed to be run as a Docker container or a standalone Python process.

### Running with Docker
Ensure the `Dockerfile` is built and the container is connected to the same network as your Ollama instance.

### Running Manually
```bash
python -m memory_mcp.server
```
