Join: https://discord.gg/t8jAxMtk
[ARCHITECTURE.md](https://github.com/user-attachments/files/24145427/ARCHITECTURE.md)
# Assistant Proxy - Architecture & Documentation

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Technology Stack](#technology-stack)
4. [Data Flow](#data-flow)
5. [Container Manager](#container-manager)
6. [Code Examples](#code-examples)
7. [Best Practices](#best-practices)
8. [Roadmap](#roadmap)

---

## Project Overview

The **Assistant Proxy** is a Multi-Layer AI System that acts as an intelligent proxy between Chat UIs (LobeChat, OpenWebUI) and various LLM backends. The system implements an innovative 3-Layer architecture to improve response quality and reduce hallucinations.

### Main Components

```
assistant-proxy/
├── assistant-proxy/          # Core Bridge Application
│   ├── adapters/             # Chat-UI Adapters (LobeChat, OpenWebUI)
│   ├── core/                 # 3-Layer Architecture
│   │   ├── bridge.py         # Orchestrator
│   │   ├── layers/
│   │   │   ├── thinking.py   # Layer 1: Intent Analysis
│   │   │   ├── control.py    # Layer 2: Verification
│   │   │   └── output.py     # Layer 3: Response Generation
│   │   ├── models.py         # Data Models
│   │   └── persona.py        # Persona Management
│   ├── mcp/                  # MCP Hub & Clients
│   │   ├── hub.py            # Tool Management
│   │   ├── client.py         # Tool Calls
│   │   └── transports/       # HTTP, SSE, STDIO
│   ├── container-manager/    # Container Sandbox System
│   │   └── main.py           # Container API & Lifecycle
│   ├── containers/           # Sandbox Definitions
│   │   ├── registry.yaml     # Container Configuration
│   │   └── code-sandbox/     # Python Sandbox
│   │       ├── Dockerfile
│   │       └── SYSTEM.md
│   ├── classifier/           # Message Classification
│   └── utils/                # Logging, Streaming, Prompts
├── sql-memory/               # Persistent Memory System
│   ├── memory_mcp/           # Memory Tools
│   ├── vector_store.py       # Embedding-based Search
│   └── graph/                # Knowledge Graph
├── validator-service/        # Quality Assurance
│   └── main.py               # Embedding & LLM Validation
└── Sequential Thinking/      # Reasoning MCP
    └── mcp-sequential/       # Sequential Reasoning Tools
```

### Statistics

- **Codebase**: ~8,500 lines of Python code (Core)
- **Services**: 5 main services (Bridge, Memory, Validator, Sequential Thinking, Container-Manager)
- **Adapters**: 2 Chat-UI adapters (LobeChat, OpenWebUI)
- **MCP Transports**: 3 protocols (HTTP, SSE, STDIO)
- **Containers**: 1 Sandbox environment (code-sandbox), extensible
- **Database**: SQLite with FTS5 (Full-Text Search) and Vector Store

---

## Architecture

### 1. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Chat UI Layer                            │
│              (LobeChat / OpenWebUI / Web Debug UI)              │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Adapter Layer                              │
│  ┌──────────────────┐              ┌──────────────────┐        │
│  │  LobeChat        │              │  OpenWebUI       │        │
│  │  Adapter         │              │  Adapter         │        │
│  └──────────────────┘              └──────────────────┘        │
│         │ Transform Request/Response │                          │
└─────────┴───────────────────────────┴──────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Core Bridge Layer                          │
│                                                                 │
│  ┌───────────────────────────────────────────────────────┐    │
│  │  Layer 1: Thinking (DeepSeek-R1:8b)                   │    │
│  │  • Intent Analysis                                     │    │
│  │  • Hallucination Risk Assessment                       │    │
│  │  • Memory Need Detection                               │    │
│  │  • Container Need Detection (Code Execution)           │    │
│  └────────────────────────┬───────────────────────────────┘    │
│                            ▼                                    │
│  ┌───────────────────────────────────────────────────────┐    │
│  │  Auto-Execute Heuristic (Fallback)                     │    │
│  │  • Detects code blocks + trigger phrases               │    │
│  │  • Overrides ThinkingLayer if needed                   │    │
│  └────────────────────────┬───────────────────────────────┘    │
│                            ▼                                    │
│  ┌───────────────────────────────────────────────────────┐    │
│  │  Memory Retrieval (Optional)                           │    │
│  │  • Facts (SQL)                                         │    │
│  │  • Embeddings (Vector Search)                          │    │
│  │  • Knowledge Graph                                     │    │
│  └────────────────────────┬───────────────────────────────┘    │
│                            ▼                                    │
│  ┌───────────────────────────────────────────────────────┐    │
│  │  Container Execution (Optional)                        │    │
│  │  • Start isolated Docker container                     │    │
│  │  • Execute code & capture output                       │    │
│  │  • Stream results to Web UI terminal                   │    │
│  └────────────────────────┬───────────────────────────────┘    │
│                            ▼                                    │
│  ┌───────────────────────────────────────────────────────┐    │
│  │  Layer 2: Control (Qwen3:4b)                          │    │
│  │  • Fact-Checking                                       │    │
│  │  • Hallucination Detection                             │    │
│  │  • Correction Generation                               │    │
│  └────────────────────────┬───────────────────────────────┘    │
│                            ▼                                    │
│  ┌───────────────────────────────────────────────────────┐    │
│  │  Layer 3: Output (Llama3.1:8b / Qwen-Coder:3b)        │    │
│  │  • Final Response Generation                           │    │
│  │  • Dynamic Model Selection (Code vs Chat)              │    │
│  │  • Persona Application                                 │    │
│  │  • Streaming Support                                   │    │
│  └────────────────────────┬───────────────────────────────┘    │
│                            ▼                                    │
│  ┌───────────────────────────────────────────────────────┐    │
│  │  Memory Save (Optional)                                │    │
│  │  • Extract & Save Facts                                │    │
│  │  • Update Knowledge Graph                              │    │
│  │  • Generate Embeddings                                 │    │
│  └───────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┬─────────────────┐
        ▼                   ▼                   ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ SQL Memory   │  │  Validator   │  │   MCP Hub    │  │  Container   │
│   Service    │  │   Service    │  │   (Tools)    │  │   Manager    │
└──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘
                                                              │
                                                              ▼
                                                     ┌──────────────┐
                                                     │ Docker Engine│
                                                     │  (Sandboxes) │
                                                     └──────────────┘
```

### 2. 3-Layer Architecture in Detail

#### Layer 1: Thinking Layer (Intent & Risk Analysis)

**Purpose**: Analyzes user request and assesses complexity

**Model**: DeepSeek-R1:8b (Reasoning-optimized)

**Output**:
```json
{
  "intent": "code-execution",
  "needs_memory": true,
  "needs_container": true,
  "container_name": "code-sandbox",
  "container_task": "execute",
  "use_code_model": true,
  "hallucination_risk": "low",
  "reasoning": "User wants to test code - needs sandbox execution"
}
```

**Decision Logic**:
- `hallucination_risk == "low"` → Skip Control Layer
- `needs_memory == true` → Activate Memory Retrieval
- `needs_container == true` → Execute code in sandbox
- `use_code_model == true` → Use Qwen-Coder for output

#### Layer 2: Control Layer (Verification & Correction)

**Purpose**: Fact-checking and hallucination prevention

**Model**: Qwen3:4b (Efficient & Precise)

**Skipped when**:
- `hallucination_risk == "low"`
- `ENABLE_CONTROL_LAYER == false`

#### Layer 3: Output Layer (Final Response)

**Purpose**: Generates final, persona-conforming response

**Model**: 
- `Llama3.1:8b` for general chat
- `Qwen2.5-Coder:3b` for code-related tasks (automatic selection)

**Features**:
- Persona application (Tone, Style, Constraints)
- Markdown formatting
- Streaming support
- Container result integration

### 3. MCP Hub Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      MCP Hub                                    │
│                                                                 │
│  ┌───────────────────────────────────────────────────────┐    │
│  │  Auto-Discovery & Registration                        │    │
│  │  • Scan mcp_registry.py                               │    │
│  │  • Detect Transport Type (HTTP/SSE/STDIO)             │    │
│  │  • Register Tools in Knowledge Graph                  │    │
│  └────────────────────────┬──────────────────────────────┘    │
│                           ▼                                     │
│  ┌───────────────────────────────────────────────────────┐    │
│  │  Transport Layer (Pluggable)                          │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐             │    │
│  │  │   HTTP   │ │   SSE    │ │  STDIO   │             │    │
│  │  │ Transport│ │ Transport│ │ Transport│             │    │
│  │  └──────────┘ └──────────┘ └──────────┘             │    │
│  └───────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│              External MCP Servers                               │
│  • sql-memory (STDIO)                                           │
│  • Sequential Thinking (STDIO)                                  │
│  • Container Manager (HTTP)                                     │
│  • Custom Tools (HTTP/SSE)                                      │
└─────────────────────────────────────────────────────────────────┘
```

### 4. Memory System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    SQL Memory Service                           │
│                                                                 │
│  ┌───────────────────────────────────────────────────────┐    │
│  │  Facts Database (SQLite)                              │    │
│  │  • Structured facts (Key-Value)                       │    │
│  │  • Per conversation isolated                          │    │
│  │  • FTS5 Full-text search                              │    │
│  │  • Categorization (person, preference, etc.)          │    │
│  └────────────────────────┬──────────────────────────────┘    │
│                           │                                     │
│  ┌────────────────────────┴──────────────────────────────┐    │
│  │  Vector Store (Embeddings)                            │    │
│  │  • mxbai-embed-large-v1:f16                           │    │
│  │  • Cosine Similarity Search                           │    │
│  │  • Top-K Retrieval                                    │    │
│  └────────────────────────┬──────────────────────────────┘    │
│                           │                                     │
│  ┌────────────────────────┴──────────────────────────────┐    │
│  │  Knowledge Graph                                      │    │
│  │  • Entity-Relationship Mapping                        │    │
│  │  • Tool Descriptions                                  │    │
│  │  • Cross-Reference Search                             │    │
│  └───────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Technology Stack

### Backend

| Component | Technology | Version | Usage |
|-----------|------------|---------|-------|
| **Framework** | FastAPI | Latest | REST API & Async Support |
| **Server** | Uvicorn | Latest | ASGI Server |
| **Database** | SQLite3 | 3.x | Facts, Embeddings, Graph |
| **HTTP Client** | httpx | 0.25+ | Async HTTP |
| **YAML** | PyYAML | 6.0+ | Configs & Personas |
| **MCP** | FastMCP | Latest | MCP Protocol |
| **Docker** | docker-py | 6.x | Container Management |

### AI/ML Models (Ollama)

| Layer | Model | Size | Purpose |
|-------|-------|------|---------|
| Thinking | DeepSeek-R1 | 8B | Reasoning & Planning |
| Control | Qwen3 | 4B | Fact-Checking |
| Output (Chat) | Llama3.1 | 8B | Response Generation |
| Output (Code) | Qwen2.5-Coder | 3B | Code Tasks |
| Embeddings | mxbai-embed-large-v1 | f16 | Semantic Search |

### Container Infrastructure

- **Docker** - Containerization
- **Docker Compose** - Multi-service orchestration
- **Networks**: Isolated bridge networks per service

---

## Data Flow

### Request Flow (Detailed)

```
1. User Input in Chat UI
   └─> POST /api/chat/completions
       {
         "model": "gpt-4",
         "messages": [{"role": "user", "content": "..."}],
         "stream": true
       }

2. Adapter (e.g., LobeChat)
   └─> transform_request()
       • OpenAI format → CoreChatRequest
       • Conversation ID extraction
       • Persona lookup

3. Core Bridge - Layer 1: Thinking
   └─> ThinkingLayer.process()
       • DeepSeek-R1 Reasoning
       • Output: thinking_plan
         {
           "needs_memory": true,
           "hallucination_risk": "low",
           "needs_container": true,
           "container_name": "code-sandbox",
           "use_code_model": true
         }

4. Auto-Execute Heuristic (Fallback)
   └─> _should_auto_execute_code()
       • Check for code blocks
       • Check trigger phrases ("test", "run", "output")
       • Override needs_container if needed

5. Memory Retrieval (if needs_memory=true)
   └─> MCPHub.get_memory_context()
       • Facts: query_facts(search_queries)
       • Embeddings: search_similar(query, top_k=5)
       • Graph: get_related_entities()
       • Combine → memory_context (String)

6. Container Execution (if needs_container=true)
   └─> Container-Manager API
       • Extract code from message
       • POST /containers/start
       • Execute in sandbox
       • Return stdout/stderr
       • Add result to memory context

7. Core Bridge - Layer 2: Control (if risk != "low")
   └─> ControlLayer.process()
       • Input: user_query + memory_context
       • Qwen3 Fact-Checking
       • Output: corrections (if needed)

8. Core Bridge - Layer 3: Output
   └─> OutputLayer.process()
       • Select model (CODE_MODEL if use_code_model)
       • Input: query + memory + corrections + container_result
       • Llama3.1/Qwen-Coder generation (streaming)
       • Output: final_response (Generator)

9. Memory Save (if needs_memory=true)
   └─> MCPHub.save_to_memory()
       • Extract facts (LLM-based)
       • Save to SQL
       • Generate embeddings
       • Update Knowledge Graph

10. Adapter
    └─> transform_response()
        • CoreChatResponse → OpenAI format
        • Stream SSE Events

11. Chat UI
    └─> Display Response (streaming)
```

---

## Container Manager

### Overview

The Container Manager enables secure code execution in isolated Docker containers. The ThinkingLayer automatically detects when code should be executed.

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Container Manager Service                    │
│                         (Port 8300)                             │
│                                                                 │
│  ┌───────────────────────────────────────────────────────┐    │
│  │  Registry Loader                                      │    │
│  │  • Loads containers/registry.yaml                     │    │
│  │  • Validates container definitions                    │    │
│  │  • Registers allowed sandboxes                        │    │
│  └────────────────────────┬──────────────────────────────┘    │
│                           ▼                                     │
│  ┌───────────────────────────────────────────────────────┐    │
│  │  Container Lifecycle Management                       │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ │    │
│  │  │  Start   │ │  Exec    │ │  Stop    │ │ Cleanup │ │    │
│  │  └──────────┘ └──────────┘ └──────────┘ └─────────┘ │    │
│  └────────────────────────┬──────────────────────────────┘    │
│                           ▼                                     │
│  ┌───────────────────────────────────────────────────────┐    │
│  │  Security Enforcement                                 │    │
│  │  • Network Isolation (none/bridge)                    │    │
│  │  • Resource Limits (CPU, Memory)                      │    │
│  │  • Timeout Enforcement                                │    │
│  │  • Read-only Filesystem (optional)                    │    │
│  │  • Thread-safe container tracking                     │    │
│  └───────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Docker Engine                              │
│  ┌───────────────────────────────────────────────────────┐    │
│  │  code-sandbox Container                               │    │
│  │  • Python 3.11 + numpy, pandas, matplotlib            │    │
│  │  • Network: none (isolated)                           │    │
│  │  • Memory: 256MB limit                                │    │
│  │  • CPU: 0.5 cores                                     │    │
│  │  • Timeout: 60 seconds                                │    │
│  └───────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### Auto-Execute Detection

The system automatically detects when code should be executed:

```
┌─────────────────────────────────────────────────────────────────┐
│                   ThinkingLayer Analysis                        │
│                                                                 │
│  User Message: "```python\nprint('hello')\n```\nDoes it work?" │
│                           │                                     │
│                           ▼                                     │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │  1. Code Block Detection: ✅ (```python...```)          │  │
│  │  2. Trigger Analysis:                                    │  │
│  │     • "Does it work?" → Implicit Execute Trigger ✅      │  │
│  │  3. Decision: needs_container = true                     │  │
│  └─────────────────────────────────────────────────────────┘  │
│                           │                                     │
│                           ▼                                     │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │  Fallback Heuristic (if ThinkingLayer unsure):          │  │
│  │                                                          │  │
│  │  POSITIVE TRIGGERS (→ Execute):                         │  │
│  │  • "test", "run", "execute", "try"                      │  │
│  │  • "what output", "what result", "what happens"         │  │
│  │  • "does it work", "is it correct"                      │  │
│  │  • Code block + minimal text (<50 chars)                │  │
│  │                                                          │  │
│  │  NEGATIVE TRIGGERS (→ Don't Execute):                   │  │
│  │  • "explain", "how does it work", "why"                 │  │
│  │  • "improve", "optimize", "refactor"                    │  │
│  │  • "write me", "create", "generate"                     │  │
│  └─────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Container Registry (registry.yaml)

```yaml
containers:
  code-sandbox:
    description: "Secure Python execution environment"
    dockerfile: "./code-sandbox/Dockerfile"
    system_prompt: "./code-sandbox/SYSTEM.md"
    
    triggers:
      - "execute code"
      - "test this code"
      - "run python"
    
    security:
      network_mode: "none"      # No internet access
      read_only: false
      needs_confirm: false      # No user confirmation needed
    
    resources:
      memory: "256m"
      cpus: "0.5"
      timeout: 60

settings:
  auto_cleanup: true
  max_concurrent: 3
  default_timeout: 60
```

### Adding Custom Containers

1. **Create folder**: `containers/my-sandbox/`
2. **Add Dockerfile**:
```dockerfile
FROM python:3.11-slim
WORKDIR /workspace
RUN pip install your-packages-here
```
3. **Add SYSTEM.md** (instructions for AI)
4. **Register in registry.yaml**:
```yaml
containers:
  my-sandbox:
    description: "My custom sandbox"
    dockerfile: "./my-sandbox/Dockerfile"
    security:
      network_mode: "bridge"  # Allow internet
      memory: "512m"
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/containers` | GET | List available containers |
| `/containers/start` | POST | Start container and execute code |
| `/containers/exec` | POST | Run command in running container |
| `/containers/stop` | POST | Stop and remove container |
| `/containers/status` | GET | Show active containers |
| `/containers/cleanup` | POST | Clean up all containers |

### Code Transfer Method

Code is transferred via **tar archive** (Docker `put_archive`) for byte-accurate transfer without shell escaping issues:

```python
import io
import tarfile

# Create tar archive in memory
tar_stream = io.BytesIO()
with tarfile.open(fileobj=tar_stream, mode='w') as tar:
    code_bytes = code.encode('utf-8')
    tarinfo = tarfile.TarInfo(name='code.py')
    tarinfo.size = len(code_bytes)
    tar.addfile(tarinfo, io.BytesIO(code_bytes))

tar_stream.seek(0)
container.put_archive('/workspace', tar_stream)

# Execute
exec_result = container.exec_run(["python", "/workspace/code.py"], demux=True)
```

### Web UI Terminal Integration

The Web UI includes a split-screen terminal that shows container execution in real-time:

```
┌─────────────────────────────────────────────────────────────────┐
│  Web UI (Split View)                                            │
│  ┌────────────────────────────┬────────────────────────────┐   │
│  │                            │  Terminal Panel            │   │
│  │      Chat Panel            │  ┌──────────────────────┐  │   │
│  │                            │  │ 🚀 Starting: sandbox │  │   │
│  │  User: test this           │  │    Task: execute     │  │   │
│  │  ```python                 │  │ 📤 Output:           │  │   │
│  │  print("Hello")            │  │    Hello             │  │   │
│  │  print(2 + 2)              │  │    4                 │  │   │
│  │  ```                       │  │ ✅ Completed (0)     │  │   │
│  │                            │  └──────────────────────┘  │   │
│  │  AI: The code outputs...   │                            │   │
│  └────────────────────────────┴────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### SSE Events

| Event | Payload | Description |
|-------|---------|-------------|
| `container_start` | `{container, task}` | Container is starting |
| `container_done` | `{exit_code, stdout, stderr}` | Execution completed |

```javascript
// Web UI receives events
eventSource.onmessage = (e) => {
    const data = JSON.parse(e.data);
    if (data.type === 'container_start') {
        terminal.log(`🚀 Starting: ${data.container}`);
    }
    if (data.type === 'container_done') {
        terminal.log(`📤 Output: ${data.result.stdout}`);
        terminal.log(`✅ Completed (${data.result.exit_code})`);
    }
};
```

### Security Considerations

⚠️ **Important:** The Container Manager has access to the Docker socket. Only allow trusted containers in your registry.

**Default security settings:**
- Network isolated (`network_mode: none`)
- Resource limited (256MB RAM, 0.5 CPU)
- Auto-timeout after 60 seconds
- No persistent storage (container deleted after use)
- Thread-safe container tracking with locks

---

## Code Examples

### 1. Async HTTP with Connection Pooling

```python
# utils/http_client.py
import httpx
from typing import Optional

class HTTPClientManager:
    """Singleton for shared HTTP client with connection pooling"""

    _instance: Optional[httpx.AsyncClient] = None

    @classmethod
    def get_client(cls) -> httpx.AsyncClient:
        if cls._instance is None:
            cls._instance = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=5.0,
                    read=60.0,
                    write=10.0,
                    pool=5.0
                ),
                limits=httpx.Limits(
                    max_connections=100,
                    max_keepalive_connections=20,
                    keepalive_expiry=30.0
                ),
                http2=True
            )
        return cls._instance

    @classmethod
    async def close(cls):
        if cls._instance:
            await cls._instance.aclose()
            cls._instance = None
```

### 2. Thread-Safe Container Tracking

```python
# container-manager/main.py
import threading
from typing import Dict, Any

active_containers: Dict[str, Dict[str, Any]] = {}
active_containers_lock = threading.Lock()

def track_container(container_id: str, info: Dict[str, Any]) -> None:
    """Thread-safe: Add container to tracking."""
    with active_containers_lock:
        active_containers[container_id] = info

def untrack_container(container_id: str) -> bool:
    """Thread-safe: Remove container from tracking."""
    with active_containers_lock:
        if container_id in active_containers:
            del active_containers[container_id]
            return True
        return False

def is_container_tracked(container_id: str) -> bool:
    """Thread-safe: Check if container is tracked."""
    with active_containers_lock:
        return container_id in active_containers

def get_tracked_containers() -> Dict[str, Dict[str, Any]]:
    """Thread-safe: Get copy of all tracked containers."""
    with active_containers_lock:
        return dict(active_containers)
```

### 3. Auto-Execute Heuristic

```python
# core/bridge.py
def _should_auto_execute_code(self, text: str, thinking_plan: Dict) -> bool:
    """
    Heuristic: Should code be automatically executed?
    
    Used as FALLBACK when ThinkingLayer says needs_container=false,
    but context suggests execution is wanted.
    """
    # If ThinkingLayer already said yes, don't override
    if thinking_plan.get("needs_container"):
        return True
    
    # Check if code block exists
    has_code_block = '```' in text
    if not has_code_block:
        return False
    
    text_lower = text.lower()
    
    # POSITIVE triggers
    execute_triggers = [
        "test", "run", "execute", "try", "start",
        "what output", "what result", "what happens",
        "does it work", "is it correct", "check"
    ]
    
    # NEGATIVE triggers (take precedence)
    no_execute_triggers = [
        "explain", "how does", "why",
        "improve", "optimize", "refactor",
        "write me", "create", "generate"
    ]
    
    # Check negative triggers first
    for trigger in no_execute_triggers:
        if trigger in text_lower:
            return False
    
    # Check positive triggers
    for trigger in execute_triggers:
        if trigger in text_lower:
            return True
    
    # Special case: Code block with minimal text
    text_without_code = re.sub(r'```[\s\S]*?```', '', text).strip()
    if len(text_without_code) < 50 and has_code_block:
        return True
    
    return False
```

### 4. Sync Endpoints for Docker Operations

```python
# container-manager/main.py
# NOTE: Using sync (def) instead of async for Docker operations
# FastAPI automatically runs sync endpoints in threadpool
# This prevents blocking the event loop with Docker SDK calls

@app.post("/containers/start")
def container_start(request: ContainerStartRequest):
    """
    Start container and execute code.
    
    NOTE: Sync endpoint - FastAPI runs this in threadpool,
    so Docker's blocking calls don't block the event loop.
    """
    # Docker SDK calls are blocking but run in threadpool
    container = docker_client.containers.run(**options)
    # ...

@app.post("/containers/stop")
def container_stop(request: ContainerStopRequest):
    """Stop and remove container (sync - threadpool)."""
    container.stop(timeout=5)
    container.remove()
    # ...
```

---

## Best Practices

### Python Best Practices

#### Type Hints Everywhere

```python
from typing import Optional, List, Dict, Any

async def get_memory_context(
    conversation_id: str,
    queries: List[str],
    max_results: int = 5
) -> Dict[str, Any]:
    ...
```

#### Specific Exception Handling

```python
# ❌ Bad
try:
    result = do_something()
except:
    pass

# ✅ Good
try:
    result = do_something()
except TimeoutError as e:
    logger.error(f"Operation timed out: {e}")
    raise
except ValueError as e:
    logger.warning(f"Invalid value: {e}")
    return None
except Exception as e:
    logger.exception(f"Unexpected error: {e}")
    raise
```

#### Context Managers for Resources

```python
# ✅ Good
async with httpx.AsyncClient() as client:
    response = await client.get(url)

# ❌ Bad
client = httpx.AsyncClient()
response = await client.get(url)
# Forgets await client.aclose()
```

### FastAPI Best Practices

#### Sync vs Async Endpoints

```python
# Use ASYNC for I/O-bound operations with async libraries
@app.post("/api/chat")
async def chat(request: ChatRequest):
    result = await async_operation()  # Non-blocking
    return result

# Use SYNC for blocking operations (Docker SDK, etc.)
# FastAPI automatically runs these in threadpool
@app.post("/containers/start")
def container_start(request: ContainerStartRequest):
    container = docker_client.containers.run(...)  # Blocking but in threadpool
    return result
```

### Docker Best Practices

#### Non-Root User

```dockerfile
FROM python:3.11-slim

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app
COPY --chown=appuser:appuser . .

USER appuser
CMD ["python", "main.py"]
```

#### Health Checks

```dockerfile
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8000/health')"
```

---

## Roadmap

### Phase 1: Critical Fixes ✅ (Completed)

- [x] Async/Await migration (httpx instead of requests)
- [x] Connection pooling implementation
- [x] Fix bare except blocks
- [x] Thread-safe container tracking (Lock)
- [x] Docker endpoints sync (FastAPI threadpool)
- [x] CORS configuration for Web UI

### Phase 2: Container System ✅ (Completed)

- [x] Container Manager service
- [x] Registry-based container configuration
- [x] Auto-Execute detection (ThinkingLayer + Heuristic)
- [x] Web UI terminal integration
- [x] SSE events for container status
- [x] Secure code transfer (tar/put_archive)
- [x] Dynamic model selection (Code vs Chat)

### Phase 3: Testing & Quality (In Progress)

- [ ] pytest setup
- [ ] Unit tests for Container Manager
- [ ] Integration tests for Auto-Execute
- [ ] E2E tests for complete pipeline
- [ ] CI/CD pipeline (GitHub Actions)

### Phase 4: Security & Auth

- [ ] API key authentication
- [ ] Rate limiting (60 req/min)
- [ ] Request size limits
- [ ] CORS whitelist (production)
- [ ] Audit logging

### Phase 5: Performance Optimization

- [ ] Memory caching (Redis)
- [ ] Fix N+1 query problems
- [ ] Database index optimization
- [ ] Load testing (Locust)

### Phase 6: Advanced Features

- [ ] Multi-model support (OpenAI, Anthropic)
- [ ] Observability (Prometheus, Grafana)
- [ ] Multi-tenancy support
- [ ] Additional sandbox containers (Node.js, Bash)

---

## Summary

This document provides a comprehensive overview of:

1. **Architecture**: 3-Layer system with MCP Hub, Memory, and Container Manager
2. **Container System**: Secure code execution with auto-detection
3. **Data Flow**: Complete request lifecycle with all components
4. **Code Examples**: Production-ready patterns and best practices
5. **Roadmap**: Structured plan with completed and upcoming phases

### Quick Start

```bash
# 1. Clone repository
git clone 

# 2. Start services
cd assistant-proxy
docker-compose up -d --build

# 3. Access Web UI
open http://localhost:3000

# 4. Test code execution
# Send a message with code block - it will auto-execute!
```

For questions or further details on specific topics, feel free to ask!
