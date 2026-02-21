# TRION Changelog — Fixes, Bugfixes & News (2026-02)

## Scope
This document is the consolidated February 2026 stabilization log for TRION.
It includes the full multi-phase hardening track (Phase 0 to Phase 8), major bugfix chains, operational tooling, and release discipline updates.

---

## Executive Summary
- Core context pipeline was unified and hardened (single entry-point, hard caps, fail-closed behavior).
- Sync/Stream parity became a first-class gate with dedicated test coverage.
- Tool output de-dup moved to a single-truth-channel model.
- TypedState V1 was introduced with shadow/active rollout behavior and fail-safe rendering.
- Container restart recovery and TTL rearm were implemented and tested.
- Graph hygiene was centralized with SQLite-as-truth / Graph-as-index enforcement.
- Security hardening shipped (signature verification modes, sanitization centralization, deploy parity IDs).
- Full test/release discipline was expanded (quick/full/live gates, golden regressions, phase suites).
- Phase 8 digest pipeline was made operational (state, locking, worker, catch-up, runtime API/UI telemetry).
- Ops reliability was upgraded with dedicated reset/restore/permissions tooling.

---

## Stabilization Phases (0–8)

### Phase 0 — Baseline & Guardrails
- Standardized logging/markers:
  - `mode`
  - `context_sources`
  - `context_chars_final`
  - `retrieval_count`
- Established Sync/Stream parity checks for equivalent context type.

### Phase 1 — Single Context Entry-Point
- Consolidated context construction behind `build_effective_context()`.
- Routed extra lookups/control correction through the same path.
- Removed side-path context builders outside the central entry chain.

### Phase 1.5 — End-to-End Determinism
- Enforced hard cap at final prompt assembly after all appends.
- Bounded/clipped `tool_context` to avoid unbounded growth.
- Integrated failure-compact in the same builder path (no bypass).

### Phase 2 — Output De-Dup / Single Truth Channel
- Enforced single truth channel for tool results.
- Removed duplicate injection across memory vs user-visible channels.
- Hardened small-model mode for strict de-dup behavior.

### Phase 3 — TypedState V1
- Introduced TypedState V1 with Facts/Entities and source event references.
- Added processing pipeline:
  - normalize -> dedupe(window) -> correlate -> select_top(budget) -> render NOW/RULES/NEXT
- Added fail-closed fallback (minimal NOW + clarify).
- Added observability metadata for TypedState.

### Phase 4 — Restart Recovery
- Rebuilt active container state from Docker scan on startup.
- Reconstructed TTL timers from durable labels.
- Added recovery tests for ACTIVE_CONTAINER and TTL behavior.

### Phase 5 — Graph Hygiene
- Added central graph hygiene pipeline (`core/graph_hygiene.py`).
- Unified router + context to use same hygiene path.
- Enforced dedupe by `blueprint_id` and latest revision selection.
- Added SQLite active-set cross-check for stale/soft-deleted node filtering.
- Added tombstone + reconcile flow for delete consistency.

### Phase 6 — Security Hardening
- Replaced signature verification stub with real verification modes (`off`, `opt_in`, `strict`).
- Added runtime wiring in deploy path with block handling/audit signal.
- Centralized markdown/XSS sanitization (workspace + protocol).
- Added REST deploy parity for `session_id` / `conversation_id` pass-through.

### Phase 7 — Test/Release Discipline
- Added test harness for sync/stream and provider variants (mock/live).
- Expanded dataset schema + validator + cases.
- Added golden regressions for small-model mode.
- Added phase-specific E2E suites (2–6).
- Formalized quick/full/live gate discipline in docs/scripts.

### Phase 8 — Digest Pipeline Operationalization
- Added operational digest core:
  - runtime state
  - locking
  - worker loop
  - daily/weekly/archive schedulers
  - store/keys
- Added sidecar worker path and runtime API telemetry endpoint.
- Added catch-up controls, idempotency hardening, and JIT telemetry behavior.
- Added frontend/runtime visibility path for digest observability.

---

## TypedState V1 Commit 4 (Detailed)
- `core/context_cleanup.py`
  - Added V1 meta bullets in compact context metadata (`v1_extra_now`, `v1_last_errors`, `v1_last_tool_results`).
  - Added `_log_typedstate_diff(legacy_now, v1_now)` with robust fail-safe logging.
  - Added `format_typedstate_v1(ctx, char_cap=None)` with NOW extension and cap-respecting fallback behavior.
- `core/context_manager.py`
  - Added `TYPEDSTATE_MODE` branching in small-model context path:
    - `off`: legacy output
    - `shadow`: compute/log V1 diff, return legacy output
    - `active`: return V1 renderer output
- `tests/unit/test_typedstate_v1_wiring.py`
  - Added broad wiring tests for diff logging, renderer behavior, metadata plumbing, and mode branching.

---

## Phase 8 Operational Hardening (Key Fix Chain)
- Added/expanded:
  - `core/digest/runtime_state.py`
  - `core/digest/locking.py`
  - `core/digest/worker.py`
  - `scripts/digest_worker.py`
  - `adapters/admin-api/runtime_routes.py`
- Added runtime telemetry endpoint:
  - `GET /api/runtime/digest-state`
- Added feature-flagged frontend runtime panel support.

### Notable Bugfixes During Hardening
- Locking reliability fixes for stale takeover/concurrency edge cases.
- Fixed restore lock default path handling (repo-local lockfiles, not `/tmp` dependence).
- Fixed live restore ordering where admin was paused before required exec phases.
- Added readiness wait + retry for smoke checks.
- Fixed heredoc execution in restore paths by using `docker exec -i` for Python heredoc calls.
- Added stronger seed/home diagnostics and explicit fail markers.
- Added TRION home ensure flow in restore scripts so UI container view is valid after hard restore.

---

## Ops Script Expansion

### Added / Expanded scripts
- `scripts/ops/trion_reset.sh`
- `scripts/ops/trion_live_reset.sh`
- `scripts/ops/trion_restore.sh`
- `scripts/ops/trion_live_restore.sh`
- `scripts/ops/check_digest_state.sh`
- `scripts/ops/trion_permissions_doctor.sh`

### Current operational intent
- `reset` scripts: clear runtime state for clean test/release baselines.
- `restore` scripts: deterministic rebuild of baseline state with optional smoke checks.
- `permissions_doctor`: detect/fix write/lock/exec preconditions.

---

## UI / Runtime Contract Updates
- Runtime API v2 shape stabilized for digest telemetry (`daily_digest`, `weekly_digest`, `archive_digest`, `locking`, `catch_up`, `jit`, `flags`).
- Runtime route integration completed in admin API.
- Frontend panel wiring and status mapping updates for digest/runtime observability.
- Additional frontend integration fixes applied for API base handling and settings/runtime wiring consistency.

---

## Reported Gate Progress (as logged during rollout)
During the February rollout cycle, multiple green snapshots were reported across targeted and full suites (including values such as 702, 753, 772, 776, 785, 824 and a later 578-scope gate run), with phase-specific suites repeatedly green after patch cycles.

Note: these values came from different gate scopes/times; use the project’s current gate scripts for the definitive latest baseline.

---

## Verification Matrix (Next Checks 1–12)
A structured 1–12 verification matrix was defined to keep post-rollout quality high, covering:
- frontend contract checks
- advanced compression wiring
- runtime API contract
- orchestrator entry-point hygiene
- single-truth + budget enforcement
- sync/stream parity
- digest operational tests
- container commander recovery
- graph hygiene consistency
- skills/security contract
- split live testing (provider vs TRION API)
- final release gate + SHA snapshot

Recommended go/no-go rule retained:
- Go only if critical checks for budget/single-truth, digest ops, security, and final gate are green.

---

## Known Notes
- Archive behavior depends on historical windows by design.
- Docker socket/daemon access remains environment-dependent.
- For environment-side permission issues, run:
  - `bash scripts/ops/trion_permissions_doctor.sh --check`
  - `bash scripts/ops/trion_permissions_doctor.sh --fix-safe --fix-docker`

---

## Recommended Post-Upgrade Commands
- `bash scripts/ops/trion_permissions_doctor.sh --check`
- `bash scripts/ops/trion_live_restore.sh --hard --reseed-skills --pause-admin --smoke-test`
- `bash scripts/ops/check_digest_state.sh`
- `./scripts/test_gate.sh full`

