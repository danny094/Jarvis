# TRION: Consolidated Implementations & Fixes Documentation

Date: February 2026

This document centrally summarizes the distributed architecture analyses, implementation plans, and hotfixes of the TRION project from the `docs` folder. It serves as a "Single Source of Truth" for recent architectural restructurings and resolved critical failures.

---

## 1. System Architecture & Core Refactorings

### 1.1 Context Manager & TypedState Pipeline

The old `ContextManager` was extremely overloaded (over 1,000 lines, cyclic dependencies, "God Object" tendencies). It mixed asynchronous DB calls, API calls, and graph metadata with purely synchronous string rendering.
**Implemented Solution (Stage B - TypedState):**

- **Separation of I/O and Logic:** Introduction of a deterministic, pure-function renderer (`core/typedstate_skills.py`) that translates raw data objects into the LLM context string.
- **Single Truth Channel:** Skill context is now exclusively sourced via the TypedState renderer, eliminating double injections (Skills Echo) in the sync and stream paths (`SKILL_CONTEXT_RENDERER=typedstate`).
- **Budgeted Selection (Top-K & Char-Cap):** Only the most relevant skills are transmitted to prevent context bloat (Mode: `budgeted`).

### 1.2 Skill Server vs. Tool Executor (Architecture)

Responsibilities were strictly separated to enforce security constraints.

- **Skill-Server (Port 8088):** Read-only interface. Executes safety evaluations (CIM Light) and filters requests via the `mini_control_layer`. (Anti-pattern checks like `eval()`, `exec()` are penalized with critical scores).
- **Tool-Executor (Port 8000):** Executes writes (create, install). Encapsulates execution in a *Sandboxed Execution* with 30s timeouts, audit logging, and blocked critical calls.

### 1.3 Browser → Deno Migration (Plugins)

The plugin system was radically "cleaned up", deleting ~2,000 lines of legacy JS code (old plugin system) and rebuilding it onto a secure Deno host system.

- **New Runtime:** `trion/runtime/deno-host.ts` with WebSocket bridge to the browser.
- Strict isolation of plugin data in the `/safespace/` vault.
- Massive reduction of the browser footprint through the new `trion-bridge.js`.

---

## 2. Policy Implementations & Autonomy (Stages A-D)

The rollout stages for the skills and control layers were strictly enforced to prevent drifts between memory and execution.

### Stage A: Single Skill Authority & Keying

- **Truth Store (`installed.json`):** There is now only one absolute truth for installed skills, deterministically secured via atomic writes (`tempfile.mkstemp` -> `os.replace`). The graph acts *only* as a search index.
- **Skill Keying:** A deterministic skill key prevents duplicates. Dedupe strictly keeps only one latest record per key.

### Stage B: (see 1.1 TypedState)

### Stage C: Policy & Security

- **Package Policy:** Introduction of a strict/allowlist logic (`SKILL_PACKAGE_INSTALL_MODE=allowlist_auto`). Installations of non-allowed packages result in `pending_package_approval` and block execution "fail-closed". PEP668 compliance via `pipx`/venv was ensured.
- **Secret Policy (`C8`):** The `SecretScanner` blocks direct OS envs (`os.getenv`) or hardcoded secrets. Skills **must** use `get_secret("NAME")`. The resolver endpoint is hardened via token and rate-limiting. Warn/Strict modes are available.

### Stage D: Graph Hygiene & Autonomous Discovery

- **Graph Hygiene:** Cleanup and reconcile of ghost skills / tombstones. Fetch logics are built to fail-closed.
- **Autonomous Discovery:** Discovery works autonomously and drift-safe as read-only against the graph, reconciled with the truth store. Writes remain policy-gated.

---

## 3. Critical Bugs & Fixes (Hotfixes)

### 3.1 Orchestrator & Tool Intelligence

- **Speculative Intent Disregard:** Synchronous processing previously ignored `_pending_intent` and executed tools speculatively. This was fixed — tools now strictly require confirmation.
- **Incorrect Error Handling as Success:** Many MCP Hub messages only returned `{"error": ...}` but no `success: False`. This was fixed so that tool errors are no longer incorrectly marked as successes with high confidence. Autosave reliably interrupts on errors or pending intents.

### 3.2 Memory MCP Crash Loop

- **Cause:** The FastAPI `FastMCP(..., stateless_http=True)` pattern led to crash loops in the `sql-memory` server, resulting in the loss of skills nodes and autonomy.
- **Fix:** Migration to a stable stateless pattern before server initialization. The system is now fully operational again (`E2E memory_graph_search` and `graph_add_node` run reliably).

### 3.3 Admin API Hard-Hang (terminal.js)

- **Cause:** `terminal.js` started a new polling loop (`pollApprovals`) against the Admin API (`/api/commander/approvals`) unprotected at every `init()`, leading to API floods and `uvicorn` timeouts.
- **Fix:** A polling guard prevents duplicate intervals and protects the backend service from overload.

### 3.4 CPU/RAM Limits through Local Embeddings

- **Problem:** The local embedding models (like `nomic-embed-text`) occupy significant shared memory (up to 75% CPU spikes, 1.2GB RAM Base), degrading R1 performance and Whisper processing.
- **Strategies:** Batching interception, asynchronous queues for vectorization, offloading to dedicated VRAM GPUs (if dual GPU available), or outsourcing to API/lightweight models.

---

## 4. Updates & Operations

### 4.1 The `trion_update.sh` Concept

Since a manual `git pull` can cause risky permission drifts (`root` files) or DB destructions (e.g., accidental `down -v`), a secure pipeline update concept was outlined:

1. **Preflight & Permissions:** Validates lockfiles, Git status (`dirty`), and checks for corrupted file owners using `trion_permissions_doctor.sh`.
2. **Data Protection (Backup):** Snapshot of the DB volumes (`memory-data`, `commander-data`) and skill registry (*before* apply).
3. **Safe Apply:** `git fetch + fast-forward-only` → `docker compose up -d --build --remove-orphans`.
4. **Integration:** Accessible via WebUI under `Settings > Advanced > System Update`, primarily with read-only status display and CLI-execute gating.

### 4.2 Installer & Updater Scripts (`install.sh` / `update.sh`)

Dedicated, robust shell scripts for the installation and maintenance of TRION were introduced.

- **`install.sh`**: Checks system prerequisites (Debian/Ubuntu: git, curl, Docker), reliably clones/updates the repository, generates `.env` (incl. `INTERNAL_SECRET_RESOLVE_TOKEN`), and builds the stack (`docker compose build + up -d`).
- **`update.sh`**: Offers a secured update concept with single-run-lock (`flock`), preflight checks (Git dirty state), automatic backups of databases (`memory-data`, `commander-data`) before apply, and automatic rollback to the previous state in case of an error.

---

## 5. Hardware Integration & Routing UI

### 5.1 AMD GPGPU Support

Hardware support for the compute layer was greatly expanded.

- **Auto-Detect Backend:** Automatic detection of the host backend (`nvidia` | `amd` | `auto`) via `/dev/kfd` and `/dev/dri`.
- **AMD Start Logic:** For AMD systems, the corresponding environment variables are injected (`HSA_VISIBLE_DEVICES`, `ROCR_VISIBLE_DEVICES`, `HIP_VISIBLE_DEVICES`) and necessary groups (`video`, `render`) are assigned to the container.
- **Friendly Names:** Graphics cards are now displayed in the UI with readable names (e.g., "GPU 0 - NVIDIA GeForce RTX 4090 [NVIDIA]" or "AMD Radeon ... [AMD]"), based on host sensors (`/proc/driver/nvidia` or `/sys/class/drm`).

### 5.2 Compute Target Routing UI

A dedicated routing interface enables targeted load distribution per agent role directly in the frontend (`Settings > Models > Compute Target Routing`).

- Administrators can now precisely choose on which hardware instance (auto, CPU, GPU0, GPU1) specific roles (`thinking`, `control`, `output`, `tool_selector`, `embedding`) should run.

---

## 6. Extended Security & Stability Fixes

### 6.1 Secret Key Resolution (`Alias Mapping`)

Secret management was made more tolerant but remains cryptographically deterministic.

- TRION can now map missing exact names during a skill run. If, for example, the secret `TEST_KEY` exists in the database, but the LLM-generated code calls `get_secret("TEST_API_KEY")`, this is securely resolved (`*_API_KEY <-> *_KEY`).

### 6.2 Workspace Event Resilience

- **Problem:** Events from the workspace disappeared after an Admin API refresh or were corrupted by different JSON shapes (list, stringified, dict).
- **Fix:** `workspace.js` and the Admin backend now normalize returns extremely robustly (`tryParseJson`, `pickEventArray`). Deduping logic keeps the state synchronous, and fast-lane tool events now survive hard hub refreshes of the MCP registry.
