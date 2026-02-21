# TRION

TRION is a local-first autonomous AI system with a real runtime stack.
It combines chat, tools, memory, container execution, and safety controls in one platform.

## What You Get

- Local web UI for chat, tools, settings, and runtime telemetry
- Multi-service backend with memory, control layers, and skill execution
- Managed sandbox containers for safe task execution
- Operational scripts for reset/restore/recovery

## 5-Minute Quick Start

### 1) Prerequisites

- Docker + Docker Compose
- Python 3.12+
- Ollama running locally at `http://localhost:11434`

### 2) Prepare external Docker resources (required by this stack)

```bash
docker network create big-bear-lobe-chat_default || true
docker volume create trion_home_data || true
```

### 3) Start the full stack

```bash
docker compose up -d
```

### 4) Open TRION

- Web UI: `http://localhost:8400`
- Admin API health: `http://localhost:8200/health`

### 5) Verify runtime quickly

```bash
bash scripts/ops/trion_permissions_doctor.sh --check
bash scripts/ops/check_digest_state.sh
```

## Important Services and Ports

- `jarvis-webui` -> `8400`
- `jarvis-admin-api` -> `8200`
- `mcp-sql-memory` -> `8082`
- `trion-runtime` -> `8401`
- `validator-service` -> `8300`
- `tool-executor` -> `8000`

## Common Operations

### Live restore to clean baseline (recommended for test resets)

```bash
bash scripts/ops/trion_live_restore.sh --hard --reseed-skills --pause-admin --smoke-test
```

### Factory-style reset (offline-style)

```bash
bash scripts/ops/trion_reset.sh --hard --reseed-blueprints
```

### Keep TRION home container stopped after restore

```bash
bash scripts/ops/trion_live_restore.sh --hard --reseed-skills --skip-home-start
```

### Preview any destructive operation first

```bash
bash scripts/ops/trion_live_restore.sh --dry-run --hard --reseed-skills --pause-admin --smoke-test
```

## Operations Scripts (New)

See full command reference in [`COMMANDS.md`](COMMANDS.md).

| Script | Purpose |
|---|---|
| `scripts/ops/trion_permissions_doctor.sh` | Checks/fixes common write/lock/script permission issues |
| `scripts/ops/trion_reset.sh` | Factory reset |
| `scripts/ops/trion_live_reset.sh` | Reset while stack stays online |
| `scripts/ops/trion_restore.sh` | Controlled restore / clean-install |
| `scripts/ops/trion_live_restore.sh` | Live restore with readiness + smoke checks |
| `scripts/ops/check_digest_state.sh` | Digest runtime telemetry check |

## Troubleshooting

### "Permission denied" on lock files or write paths

```bash
bash scripts/ops/trion_permissions_doctor.sh --check
bash scripts/ops/trion_permissions_doctor.sh --fix-safe --fix-docker
```

### Web UI says "No containers running"

Run a live restore that ensures `trion-home`:

```bash
bash scripts/ops/trion_live_restore.sh --hard --reseed-skills --pause-admin --smoke-test
```

### Smoke checks fail because services start slowly

```bash
TRION_SMOKE_MAX_WAIT_S=60 TRION_SMOKE_RETRIES=5 TRION_SMOKE_RETRY_DELAY_S=3 \
bash scripts/ops/trion_live_restore.sh --hard --reseed-skills --pause-admin --smoke-test
```

### Digest status check

```bash
bash scripts/ops/check_digest_state.sh
```

## Architecture (Short Version)

TRION uses a layered pipeline:

- Layer 0: tool selection and context narrowing
- Layer 1: reasoning/planning
- Layer 2: control/safety checks
- Layer 3: output orchestration and tool execution routing
- Deterministic executor services for side effects

For deeper docs and internals, see [`docs/digest_rollout_runbook.md`](docs/digest_rollout_runbook.md), [`CLAUDE.md`](CLAUDE.md), and the `Dokumentation/` directory.

## Development Notes

- Use `docker compose ps` to inspect service status
- Use `docker logs -f jarvis-admin-api` for API debugging
- Run gate tests with:

```bash
./scripts/test_gate.sh full
```

## Support

If this project helps you, consider supporting development:

[![Sponsor danny094](https://img.shields.io/badge/Sponsor-danny094-ea4aaa?style=for-the-badge&logo=github-sponsors)](https://github.com/sponsors/danny094)
