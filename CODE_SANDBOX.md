# Code Sandbox Feature

A secure, isolated environment for executing code directly from the AI assistant.

---

## What Can the Sandbox Do?

- **Execute code** in an isolated Docker container
- **Security isolation** - each container runs with restricted permissions
- **Resource limits** - CPU, memory, and network can be controlled per container
- **Auto-cleanup** - containers are automatically removed after execution
- **Auto-detection** - AI automatically detects when code should be executed
- **Live output** - see stdout/stderr in real-time via the Web UI terminal

---

## Architecture Overview

```
User sends code → ThinkingLayer detects execution intent
                         ↓
              Auto-Execute Heuristic (Fallback)
                         ↓
              Container-Manager starts sandbox
                         ↓
              Code runs in isolated Docker container
                         ↓
              Output streamed back to Web UI
                         ↓
              Container automatically cleaned up
```

---

## Auto-Execute Detection

The system automatically detects when you want code executed:

### Will Execute ✅
- Code block + "test this", "run it", "try this"
- Code block + "does it work?", "is it correct?"
- Code block + "what's the output?", "what happens?"
- Code block with minimal surrounding text

### Won't Execute ❌
- "Explain this code" (analysis only)
- "Write me a function that..." (generation only)
- "Improve this code" (refactoring only)
- "Why does this work?" (explanation only)

---

## Add Your Own Containers

### 1. Registry (`containers/registry.yaml`)

This file defines which containers are available and their rules:

```yaml
containers:
  code-sandbox:
    description: "Python code execution environment"
    dockerfile: "./code-sandbox/Dockerfile"
    
    triggers:
      - "execute code"
      - "run python"
      - "test this"
    
    security:
      network_mode: "none"      # No internet access
      read_only: false
      needs_confirm: false
    
    resources:
      memory: "256m"
      cpus: "0.5"
      timeout: 60

settings:
  auto_cleanup: true
  max_concurrent: 3
```

### Configuration Options

| Option | Description |
|--------|-------------|
| `triggers` | Keywords that activate this container |
| `network_mode` | `none` (isolated) or `bridge` (internet access) |
| `read_only` | Mount filesystem as read-only |
| `needs_confirm` | Require user confirmation before execution |
| `memory` | Memory limit (e.g., "256m", "1g") |
| `cpus` | CPU limit (e.g., "0.5" = 50% of one core) |
| `timeout` | Max execution time in seconds |

---

### 2. Container Definition (`containers/code-sandbox/`)

Each container has its own folder containing:

- **`Dockerfile`** - Defines the container image
- **`SYSTEM.md`** - Instructions for the AI on how to use this container

**Example Dockerfile:**
```dockerfile
FROM python:3.11-slim
WORKDIR /workspace
RUN pip install numpy pandas matplotlib
```

---

## Container Manager

Located in `container-manager/main.py`

**Responsibilities:**
- Loads and validates `registry.yaml`
- Starts containers with security settings applied
- Executes code via Docker SDK
- Streams output back to the caller
- Cleans up containers after execution

**API Endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/containers` | GET | List available containers |
| `/containers/start` | POST | Start container and execute code |
| `/containers/exec` | POST | Run command in existing container |
| `/containers/stop` | POST | Stop and remove a container |
| `/containers/status` | GET | Show active containers |
| `/containers/cleanup` | POST | Clean up all containers |

---

## MCP Registry Integration

New MCP tools are automatically registered:

| Tool | Description |
|------|-------------|
| `container_list` | List available sandbox environments |
| `container_start` | Start a container and execute code |
| `container_exec` | Run command in existing container |
| `container_stop` | Stop and remove a container |

---

## Security Considerations

⚠️ **Important:** The Container-Manager has access to the Docker socket. Only allow trusted containers in your registry.

**Default security settings:**
- Network isolated (`network_mode: none`)
- Resource limited (256MB RAM, 0.5 CPU)
- Auto-timeout after 60 seconds
- No persistent storage (container deleted after use)

---

## Web UI Terminal

The Web UI includes a split-screen terminal that shows:
- Container start events
- Live stdout/stderr output
- Exit codes and execution time
- Error messages with full stack traces

Toggle the terminal with the `[🖥️]` button next to the send button.

**Example Output:**
```
🚀 Starting container: code-sandbox
   Task: execute
📤 Output:
Hello from the Sandbox!
4
✅ Completed successfully (exit: 0)
```

---

## Quick Start

1. **Send code in chat:**
```
```python
print("Hello World!")
print(2 + 2)
```
```

2. **AI auto-detects and executes**

3. **See results in terminal panel**

4. **AI explains the output**

That's it! No special commands needed.
