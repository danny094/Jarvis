# TRION Priority Implementation Plan (2026-03-03)

## Scope
This plan prioritizes what should be stabilized first across WebUI, API, memory/summary, MCP/tool execution, skills, and installer so TRION is push-ready without another rewrite.

## Current Snapshot
- Unit baseline for critical guards is green (`78 passed`):
  - `test_context_compressor_nightly_quality.py`
  - `test_protocol_routes_date_filter.py`
  - `test_output_grounding.py`
  - `test_orchestrator_runtime_safeguards.py`
  - `test_context_manager_memory_fallback.py`
  - `test_orchestrator_tool_suppress_split.py`
- Installer update path is already hardened:
  - `install.sh` supports `--force-update`, auto-stash, and hard sync.
- UX/event contract and planning/workspace replay path are already implemented.

## Priority Order

### P0 - Runtime Responsiveness (blocking production quality)
Why first:
- Sync MCP calls still run in async request paths and can stall `/health`, stream TTFT, and deep jobs.
- Confirmed hot spots:
  - `mcp/transports/http.py` (`requests.post` in `_smart_request`)
  - `mcp/hub.py` (`call_tool` sync)
  - `core/tool_selector.py` (async method calling sync hub)
  - `core/orchestrator.py` stream/sync tool execution calls
  - `core/layers/control.py` has additional sync MCP call in async streaming path (`analyze`)

Implementation:
1. Introduce async-safe tool call wrapper in hub (thread offload as transition layer).
2. Replace direct sync calls in async flows with `await asyncio.to_thread(...)` or new async wrapper.
3. Add timeout/cancellation propagation to avoid hanging request workers.
4. Keep behavior identical; no policy change in this phase.

Definition of done:
- `/health` remains responsive during 3 consecutive deep-job runs.
- No request-starvation during memory/tool latency spikes.
- TTFT p95 target under current gate (or documented new gate if intentionally adjusted).

---

### P1 - Nightly Summary Reliability + UI Truthfulness
Why second:
- Nightly run appears to execute, but summary content still contains low-trust statements.
- Observed drift risk: status file in runtime may still be legacy/minimal (`last_run`, `summarized_date`) even though code writes richer fields.
- User-facing confusion in Agent Workspace/Protocol view (`undefined.undefined` symptom history) must be explicitly closed.

Implementation:
1. Add explicit nightly status API endpoint (read `.daily_summary_status.json` with schema version).
2. In Protocol/Workspace UI, render robust fallback labels for non-date entries and invalid dates.
3. Add startup/self-check log that reports status schema version and summarizer code version.
4. Add integration test ensuring `rolling_summary.md` is never treated as protocol date tab.
5. Add nightly quality metric fields to status (counts of verified/unverified/fallback).

Definition of done:
- Protocol/Agent Workspace never shows `undefined.undefined`.
- Status API returns stable schema with validation/fallback telemetry.
- Nightly summary quality visible in UI (not only logs).

---

### P2 - True Cancel Semantics (especially deep jobs)
Why third:
- Frontend cancel exists for stream requests, but deep-job lifecycle has submit+poll without cancel endpoint.
- Running jobs can continue even after user intent changes.

Implementation:
1. Add `/api/chat/deep-jobs/{job_id}/cancel` endpoint.
2. Track cancellation token/state in deep job runner.
3. Extend frontend API + chat UI to call cancel for deep jobs.
4. Emit terminal event/state `cancelled` consistently.

Definition of done:
- User cancel stops backend work (not only UI polling).
- Job status transitions deterministically: `queued/running -> cancelled`.
- Contract tests for cancel path pass.

---

### P3 - Memory Fidelity and Grounded Output Hardening
Why fourth:
- Core safeguards are mostly in place, but this is where regression risk is highest (hallucination, missing recall, memory write mismatch).
- Recent fixes are good; now we need stronger integration coverage.

Implementation:
1. Add E2E regression suite covering:
   - reminder save -> structured memory write
   - follow-up recall in conversational turns
   - hardware fact query grounded to tool evidence
2. Add replay tests for planning/workspace persistence after restart.
3. Add one synthetic “no evidence available” run to verify strict fallback wording.

Definition of done:
- No ungrounded factual claims in guarded scenarios.
- No loss of key memory writes in standard chat flow.
- Recall tools still usable during conversational guard.

---

### P4 - Release Hygiene and Push Safety
Why fifth:
- Current tree shows many transient artifacts (`__pycache__`, traces, local files).
- This causes noisy diffs, merge friction, and review blind spots.

Implementation:
1. Add/restore root `.gitignore` with Python/node/log/temp patterns.
2. Add `make check` or script target for the agreed release gate.
3. Document “push checklist” (tests + health + smoke scenarios) in one file.

Definition of done:
- Clean, reviewable diffs with no artifact churn.
- Repeatable pre-push gate command.

## Execution Plan (recommended cadence)

### Phase 1 (Day 1-2)
- P0 async/sync hot-path mitigation (minimal intrusive).
- Live load probe: 3 deep jobs + concurrent `/health` checks.

### Phase 2 (Day 2-3)
- P1 nightly status endpoint + UI robustness fixes.
- Validate Protocol tabs/date rendering against mixed files.

### Phase 3 (Day 3-4)
- P2 deep-job cancel E2E.
- Add contract tests.

### Phase 4 (Day 4-5)
- P3 E2E memory/grounding regression pack.
- P4 hygiene + push checklist.

## Suggested Gate Commands
```bash
python -m pytest -q \
  tests/unit/test_context_compressor_nightly_quality.py \
  tests/unit/test_protocol_routes_date_filter.py \
  tests/unit/test_output_grounding.py \
  tests/unit/test_orchestrator_runtime_safeguards.py \
  tests/unit/test_context_manager_memory_fallback.py \
  tests/unit/test_orchestrator_tool_suppress_split.py
```

```bash
AI_PERF_ENABLE=1 ./scripts/test_full_pipeline_bottleneck_gate.sh
```

```bash
AI_PERF_ENABLE=1 ./scripts/test_embedding_cpu_gate.sh
```

## Notes on Install.sh
- Install update-blocker (“branch behind + local changes”) is already handled in `install.sh`:
  - auto-stash in normal update path
  - explicit hard sync via `--force-update`
- No further installer changes needed in this plan unless new field failures appear.
