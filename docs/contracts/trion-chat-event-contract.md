# TRION Chat Event Contract

Status date: 2026-03-01

## Scope

This contract defines stable stream events for:
- Chat activity rendering in the WebUI.
- Planning persistence and planning reload behavior.

## NDJSON Envelope

Every `/api/chat` stream line is JSON and includes:
- `model`: string
- `created_at`: ISO-8601 string
- `done`: boolean

Terminal line (`done=true`) additionally includes:
- `done_reason`: string (`stop`, `error`, etc.)

## Typed Event Pass-Through

For non-content events, admin-api forwards typed metadata as-is:
- input: backend metadata event with `type`
- output: flat NDJSON object with all metadata fields

Frontend (`api.js`) forwards any typed event (`data.type`) unchanged to `chat.js`.

## Activity Events (UI)

`chat.js` maps these event types to user-visible activity states:
- `tool_start`
- `tool_result`
- `response_mode`
- `workspace_update`
- `thinking_stream`
- `sequential_start`
- `sequential_step`
- `content`
- `done`

On request completion (success/error/abort), UI resets to:
- `Ready for input`
- profile busy indicator off

## Planning Persistence Contract

Planning milestones are persisted as `workspace_update` events with:
- `source`: `"event"`
- `source_layer`: `"sequential"`
- `entry_type`: one of
  - `planning_start`
  - `planning_step`
  - `planning_done`
  - `planning_error`
- `content`: compact pipe summary (e.g. `task_id=... | step=... | title=...`)
- `conversation_id`
- `timestamp`

## Planning Reload Contract

`workspace.js` replays persisted planning events as synthetic `sse-event` payloads:
- same `workspace_update` shape
- additional `replay: true`

`sequential-thinking` plugin accepts only replayed planning events for hydration and reconstructs:
- planning checklist state
- last task metadata
- completion/error state
