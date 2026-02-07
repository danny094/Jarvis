# Skill Server (Semantic Coordination Layer)

The **Skill Server** acts as the central coordination layer in the TRION architecture. It is responsible for semantic routing, skill discovery, and acting as a bridge between the User/Client and the Execution Layer (`tool_executor`).

## Architecture

```mermaid
graph TD
    Client[Client / WebUI] -->|HTTP/MCP| Server[Server (server.py)]
    Server -->|Validation| MiniControl[Mini Control Layer]
    Server -->|Metadata| SkillManager[Skill Manager]
    SkillManager -->|RAG| CIM[CIM (cim_rag.py)]
    SkillManager -->|Execution Requests| ToolExecutor[Tool Executor (Layer 4)]
    
    subgraph "Skill Server"
        Server
        SkillManager
        MiniControl
        CIM
    end
```

## Modules

### 1. `server.py`

The main entry point using FastAPI. It exposes endpoints for tools (`/tools/call`) and manages the MCP connection.

- **Responsibilities**: Request routing, formatting responses, error handling.
- **Key Endpoints**:
  - `POST /tools/call`: Executes a tool (e.g., `list_skills`, `autonomous_skill_task`).
  - `GET /tools`: Lists available tools.

### 2. `skill_manager.py`

Manages the lifecycle and metadata of skills effectively acting as a proxy.

- **Responsibilities**:
  - Listing available and installed skills.
  - Delegating creation and execution requests to `tool_executor`.
  - Handling draft skill promotion.

### 3. `mini_control_layer.py`

Implements the "Mini-Control" logic for autonomous decisions.

- **Responsibilities**:
  - Evaluating task complexity.
  - Deciding whether to create a new skill or use an existing one.
  - Integration with `cim_rag.py` for context.

### 4. `cim_rag.py`

Handles Retrieval-Augmented Generation (RAG) for Contextual Intelligence Memory.

- **Responsibilities**:
  - Loading and querying CIM data (patterns, policies).
  - Providing context for skill generation.

## Usage

This server is typically run as a Docker container or via `uv run server.py`.

```bash
uv run server.py
```
