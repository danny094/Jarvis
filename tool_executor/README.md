# Tool Executor (Layer 4 Execution Runtime)

The **Tool Executor** is the dedicated execution environment for the TRION system. It allows for sidebar-free execution of code, file system modifications, and skill management. It is designed to be the *only* component with write access to the skills directory.

## Architecture

```mermaid
graph TD
    SkillServer[Skill Server] -->|HTTP Request| API[API (api.py)]
    API -->|Validation| Contracts[Contract Validators]
    API -->|Instruction| MiniControl[Mini Control (Validation)]
    
    subgraph "Tool Executor"
        API
        Contracts
        MiniControl
        
        subgraph "Engine"
            Installer[Skill Installer]
            Runner[Skill Runner]
        end
        
        API --> Installer
        API --> Runner
    end
    
    Installer -->|Write| FileSystem[Skills Directory]
    Runner -->|Execute| Sandbox[Python Sandbox]
```

## Modules

### 1. `api.py`

The REST API interface for the execution layer.

- **Endpoints**:
  - `POST /v1/skills/create`: Validates and writes new skill files.
  - `POST /v1/skills/run`: Executes a skill's code in a sandbox.
  - `POST /v1/skills/install`: Downloads and installs skills from a registry.
  - `POST /v1/validation/code`: checks code against safety priors.

### 2. `engine/skill_installer.py`

Handles physical file operations for skills.

- **Responsibilities**:
  - Writing skill files (`.py`) and manifests.
  - Managing draft vs. promoted status.
  - uninstalling skills.

### 3. `engine/skill_runner.py`

Isolated execution environment for running skill code.

- **Responsibilities**:
  - Executing Python code dynamically.
  - Capturing stdout/stderr.
  - Enforcing timeouts and safety limits.

### 4. `contracts/`

Contains JSON schemas (e.g., `create_skill.json`) to enforce strict input validation before any action is taken.

## Usage

This service runs as a standalone FastAPI app.

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```
