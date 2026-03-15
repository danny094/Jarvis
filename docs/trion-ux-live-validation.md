# TRION UX Live Validation

Status date: 2026-03-01

## Scope

Validated changes from:
- activity visibility and stop/cancel flow
- build lanes (skill/code/general)
- planning persistence and planning reload

## Runtime Checks

Environment:
- `jarvis-admin-api` healthy on `http://127.0.0.1:8200`
- container restarted once during validation to load latest local code

Health:
- `GET /health` returned `status=ok`

## Live Chat Validation

Interactive stream (`/api/chat`, stream=true):
- received content chunks
- received `workspace_update` (`entry_type=chat_done`)
- terminal event contained `done=true` and `done_reason=stop`

Deep jobs (`/api/chat/deep-jobs`):
- submit returned `202` with `job_id`
- polling reached `status=succeeded`
- result contains `done_reason=stop`

Planning persistence (`/api/chat`, `/deep` prompt):
- stream contained `sequential_start` and `sequential_error` (timeout case)
- stream contained persisted planning workspace events:
  - `workspace_update` with `entry_type=planning_start`
  - `workspace_update` with `entry_type=planning_error`

## Regression/Contract Checks

Executed test groups:
- `tests/unit/test_admin_api_stream_done_contract.py`
- `tests/unit/test_admin_api_deep_jobs_contract.py`
- `tests/unit/test_frontend_stream_activity_contract.py`
- `tests/unit/test_frontend_cancel_contract.py`
- `tests/workspace/test_e2e_workspace.py -k "plugin_event_dispatch_format or ndjson_pass_through_format"`
- `tests/workspace/test_orchestrator_emission.py`

All selected tests passed.

## Known Limits

- Deep sequential runs can hit `timeout_after_25s` (configured sequential stream timeout), producing `planning_error`.
- In blocked control outcomes (`done_reason=blocked`), no final assistant content is expected by design.
- Deno runtime checks should be executed via `./scripts/test_trion_deno_runtime_gate.sh` (local deno or container fallback).
