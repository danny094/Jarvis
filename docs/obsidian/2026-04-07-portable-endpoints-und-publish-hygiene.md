# Portable Endpoints and Publish Hygiene

Created: 2026-04-07
Status: **In Progress**

## Problem

TRION still relied on local network assumptions in several places:

- fixed host fallbacks such as `172.17.0.1`
- duplicated resolver logic for `runtime-hardware`, `admin-api`, and `ollama`
- direct assumptions about host/container topology instead of a clear
  `internal` / `host` split

At the same time, a public Git repository still needed a second hardening pass:

- runtime data, memories, logs, and local diagnostic artifacts must stay
  separate from versioned code
- local secrets and device-specific endpoints must not leak into defaults or
  accidentally committed runtime files

## Decision Direction

For local portability, the new rules are:

1. No fixed bridge IP in product code.
2. Internal service-to-service communication should prefer service names.
3. Host-facing communication should use a strict fallback order:
   - explicit environment configuration
   - known internal service name
   - dynamically detected Docker gateway
   - `host.docker.internal`
   - `127.0.0.1`
   - `localhost`
4. Fixed bridges such as `172.17.0.1` are treated as legacy and should not be
   introduced again.

## Code State 2026-04-07

Newly introduced:

- central resolver:
  - `utils/service_endpoint_resolver.py`
  - encapsulates:
    - container detection
    - default gateway detection
    - canonical candidate lists
    - container-aware default endpoints

Moved to the central resolver:

- `adapters/admin-api/runtime_hardware_routes.py`
- `adapters/runtime-hardware/runtime_hardware/connectors/container_storage_discovery.py`
- `container_commander/hardware_resolution.py`
- `utils/role_endpoint_resolver.py`

Container-aware Ollama defaults:

- `config.py`
- `core/context_compressor.py`
- `core/lifecycle/archive.py`
- `adapters/admin-api/settings_routes.py`

Effect:

- `runtime-hardware`, `admin-api`, and `ollama` reachability is no longer tied
  to a fixed local bridge IP
- known service names are preferred inside containers
- outside containers, defaults fall back to loopback in a controlled way
- visible container access links no longer default blindly to `127.0.0.1`
  when `TRION_PUBLIC_HOST` is unset; they now prefer explicit public hosts or
  concrete bound host IPs
- the Time MCP UI now uses the current browser host instead of a hardcoded
  `localhost`

## Verified

- `python -m py_compile` for all affected modules: ok
- `pytest -q`
  - `tests/unit/test_service_endpoint_resolver.py`
  - `tests/unit/test_runtime_hardware_gateway_contract.py`
  - `tests/unit/test_container_commander_hardware_resolution.py`
  - `tests/unit/test_scope4_compute_routing.py`
  - result: `43 passed`

## Publish Hygiene: Target State

For a Git-safe setup without data leaks, TRION should be split into four
classes:

- versioned:
  - code
  - migrations
  - example configurations
  - synthetic demo or seed data
- local, not versioned:
  - `.env`
  - secrets
  - API keys
  - tokens
- runtime-persistent, not versioned:
  - `/app/data`
  - `/app/memory_data`
  - database files
  - conversation and workspace state
- diagnostics and artifacts, not versioned:
  - `logs/`
  - snapshots
  - export files
  - local performance reports

First implemented protection:

- `scripts/ops/sanitize_for_publish.sh`
  - `--check` reports tracked publish-sensitive files
  - `--export <dir>` builds a sanitized export directory from `git archive`
    without modifying the local worktree
- `.gitignore` was tightened for local env, log, snapshot, and runtime artifacts

## Recommended Follow-Up

1. Tighten `.env.example`, `*.local`, and repo-wide secret boundaries.
2. Continue the `sanitize_for_publish` workflow:
   - clear logs
   - remove DB and snapshot files
   - remove runtime-state files
   - validate local API URLs and secrets against example values
3. Add a secret scanner as a pre-commit or CI gate.
4. Continue moving browser and UI paths to relative paths or `PUBLIC_*`
   configuration so that implicit `localhost` assumptions disappear there too.

## Open Remainder

- several dev and ops scripts still use `localhost` or `127.0.0.1` as
  intentional local defaults; that is often acceptable for host tools, but it
  is not centrally unified yet
- some UI and MCP config defaults still contain local URLs
- Git history may still contain old runtime or log artifacts; if the repo is
  published or mirrored externally, a separate history cleanup should be
  considered

## Repo Cleanup State 2026-04-07

After the `git-safe` cleanup:

- `logs/`, `memory/`, `memory_speicher/`, and `docs/session-handoff*.md` are
  now treated as local runtime or handoff artifacts for Git purposes
- tracked `__pycache__` and `*.pyc` artifacts were also removed from the index
- `.gitignore` was tightened for these classes
- `sanitize_for_publish.sh --check` is green afterwards:
  - `No tracked sensitive files matched the denylist.`

Important:

- the cleanup removes these files from Git, not from the local working tree
- for already published commits, history hygiene remains a separate step

## History Cleanup Preparation 2026-04-07

The actual rewrite for old Git history was intentionally prepared in a separate
mirror clone, not in the active worktree.

State:

- mirror rewrite completed successfully for:
  - `logs/`
  - `memory/`
  - `memory_speicher/`
  - `docs/session-handoff*.md`
  - `__pycache__/`, `*.pyc`, `*.pyo`
  - historical `*.bak.*` artifacts
- verification in the rewrite mirror:
  - no commits remain that still contain these paths
  - no index entries remain for these paths
- the rewrite was then force-pushed to `danny094/Jarvis` through a separate
  mirror

That means not only the local preparation but also the public remote history is
clean for these path classes. The local bundle backup is stored at:

- `/tmp/Jarvis-pre-force-push-history-backup-2026-04-07.bundle`

## Git-Safety Hardening For New Files 2026-04-07

In the follow-up cleanup for the next full push, new unpublished files were
also reviewed for host-bound defaults and publish-unfriendly paths.

Updated:

- `container_commander/host_companions.py`
  - no more fixed `danny` user assumption
  - default user, home, and UID are now derived generically from the host
    context
- `container_commander/host_runtime_discovery.py`
  - Sunshine AppImage candidates now use the generic host-home path instead of
    a user-bound default
- `marketplace/packages/gaming-station/package.json`
- `marketplace/packages/gaming-station-shadow/package.json`
  - no more fixed `/home/danny/...` paths in host-runtime defaults
- new tests and Obsidian notes:
  - user-bound host paths were moved to `$HOME/...`, `<repo-root>/...`, or
    generic test paths
  - private example IPs in new tests were replaced with documentation-safe
    example ranges

Verified:

- `sanitize_for_publish.sh --check` green
- focused regression tests for the updated host-companion and resolver paths
  green

Short summary for repo and GitHub readers:

- `FIX.md`
