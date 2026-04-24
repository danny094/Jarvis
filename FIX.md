# FIX

Short summary of the main changes that were completed. Detailed analysis and
verification live in the linked Obsidian notes.

## Container / TRION

- Container query-class separation and addon contract work was completed for:
  `container_inventory`, `container_blueprint_catalog`,
  `container_state_binding`, `container_request`
  Source: [2026-04-05-container-query-klassentrennung-und-addon-contract-implementationsplan.md](docs/obsidian/2026-04-05-container-query-klassentrennung-und-addon-contract-implementationsplan.md)
- `TRION Home` now uses a real `home_start` fast path instead of drifting
  through the generic `request_container` path.
  Source: [2026-04-05-container-query-klassentrennung-und-addon-contract-implementationsplan.md](docs/obsidian/2026-04-05-container-query-klassentrennung-und-addon-contract-implementationsplan.md)
- `container_inventory` and `container_state_binding` were hardened around
  grounding and fallback responses.
  Source: [2026-04-05-container-query-klassentrennung-und-addon-contract-implementationsplan.md](docs/obsidian/2026-04-05-container-query-klassentrennung-und-addon-contract-implementationsplan.md)
- `ConversationContainerState` is now persistent enough to survive API
  restarts more cleanly.
  Source: [2026-04-05-container-query-klassentrennung-und-addon-contract-implementationsplan.md](docs/obsidian/2026-04-05-container-query-klassentrennung-und-addon-contract-implementationsplan.md)

## Portability / Publish Hygiene

- A central endpoint resolver was introduced, and fixed bridge-IP assumptions
  such as `172.17.0.1` were removed from productive runtime and gateway paths.
  Source: [2026-04-07-portable-endpoints-und-publish-hygiene.md](docs/obsidian/2026-04-07-portable-endpoints-und-publish-hygiene.md)
- Product paths for `runtime-hardware`, `admin-api`, `ollama`, and UI defaults
  were moved to portable service, gateway, and public-host resolution.
  Source: [2026-04-07-portable-endpoints-und-publish-hygiene.md](docs/obsidian/2026-04-07-portable-endpoints-und-publish-hygiene.md)
- `.gitignore` and `scripts/ops/sanitize_for_publish.sh` were tightened for
  runtime data, logs, memories, session handoffs, and cache artifacts.
  Source: [2026-04-07-portable-endpoints-und-publish-hygiene.md](docs/obsidian/2026-04-07-portable-endpoints-und-publish-hygiene.md)
- Tracked `logs/`, `memory/`, `memory_speicher/`, `session-handoff` files, and
  `__pycache__` / `*.pyc` artifacts were removed from Git.
  Source: [2026-04-07-portable-endpoints-und-publish-hygiene.md](docs/obsidian/2026-04-07-portable-endpoints-und-publish-hygiene.md)
- Historical Git history for these artifact classes was also cleaned and
  updated on GitHub via force-push.
  Source: [2026-04-07-portable-endpoints-und-publish-hygiene.md](docs/obsidian/2026-04-07-portable-endpoints-und-publish-hygiene.md)

## Docs / Leak Audit

- Obsidian notes were audited and redacted for real host IPs, direct host URLs,
  user-specific host paths, and repo-absolute shell examples.
  Source: [2026-04-07-obsidian-doc-leak-audit.md](docs/obsidian/2026-04-07-obsidian-doc-leak-audit.md)
- Obsidian now explicitly follows a `git-safe` rule set: no passwords, no keys,
  no tokens, no session data, and no real host identifiers.
  Source: [2026-04-07-obsidian-doc-leak-audit.md](docs/obsidian/2026-04-07-obsidian-doc-leak-audit.md)

## Task Loop / Loop Trace

- Internal loop-analysis prompts now pass through a dedicated loop-trace
  normalizer, so runtime-tool drift, memory drift, and wrong strategy hints are
  corrected before the Task Loop or output guard runs.
  Source: [2026-04-09-trion-multistep-loop-implementationsplan.md](docs/obsidian/2026-04-09-trion-multistep-loop-implementationsplan.md)
- The stream path now exposes loop-trace and task-loop progress as first-class
  events (`loop_trace_*`, `task_loop_update`), and the existing WebUI plan box
  renders those steps without introducing a second UI system.
  Source: [2026-04-09-trion-multistep-loop-implementationsplan.md](docs/obsidian/2026-04-09-trion-multistep-loop-implementationsplan.md)
- Task Loop content is no longer limited to static step templates. The stream
  path now supports a per-step `Control + Output` runtime slice that builds a
  step contract, verifies it with `ControlLayer.verify(...)`, and generates the
  visible step response through `OutputLayer.generate_stream(...)`.
  Source: [2026-04-09-trion-multistep-loop-implementationsplan.md](docs/obsidian/2026-04-09-trion-multistep-loop-implementationsplan.md)
- The WebUI chat renderer was hardened for live Task Loop output: step bubbles
  are kept separate, and streaming updates now use a lightweight incremental
  render path instead of rebuilding the full HTML on every token.
  Source: [2026-04-09-trion-multistep-loop-implementationsplan.md](docs/obsidian/2026-04-09-trion-multistep-loop-implementationsplan.md)
- A duplicate outer timeout around per-step streaming was removed. The
  `OutputLayer` remains the single timeout authority for step output, which
  prevents mid-stream task-loop aborts and incomplete HTTP responses.
  Source: [2026-04-09-trion-multistep-loop-implementationsplan.md](docs/obsidian/2026-04-09-trion-multistep-loop-implementationsplan.md)

## Current Refactor Stand

- Prompt text centralization was started as a bounded architecture step:
  `intelligence_modules/prompt_manager/` now loads Markdown templates from
  `intelligence_modules/prompts/`, while behavior and routing logic stay in
  Python.
  Source: [prompts.md](docs/obsidian/prompts.md)
- Output, Task Loop, Control, Thinking, and Persona prompt texts were moved out
  of their runtime modules into central prompt templates, including contract
  tests for the migrated prompt surfaces.
  Source: [prompts.md](docs/obsidian/prompts.md)
- Current verification for this prompt migration is green:
  `333 passed, 9 warnings` across the focused Prompt Manager, Output, Task
  Loop, Control, Thinking, and Persona test set.
  Source: [prompts.md](docs/obsidian/prompts.md)
- The former root `config.py` monolith was split into the modular `config/`
  package (`infra`, `models`, `pipeline`, `output`, `autonomy`, `context`,
  `features`, `digest`, `skills`), and the legacy file was removed.
  Source: local worktree diff since `8501e6e`
- `core/layers/control.py` was split into the package
  `core/layers/control/` with dedicated submodules for runtime, prompting,
  policy, tools, strategy, verification, sequential logic, and CIM helpers.
  Source: local worktree diff since `8501e6e`
- `core/layers/output.py` was split into the package
  `core/layers/output/` with prompt, generation, grounding, contracts, and
  analysis modules.
  Source: local worktree diff since `8501e6e`
- `core/orchestrator_modules/` was extended further, including the Task-Loop
  integration surface and new policy helpers such as
  `task_loop_routing.py` and `policy/cron_mode_guard.py`.
  Source: local worktree diff since `8501e6e`
- `core/task_loop/` was expanded substantially: the old single-file planner,
  runner, and step-runtime modules were replaced by packages plus new policy,
  capability, action-resolution, recovery, and writeback helpers.
  Source: local worktree diff since `8501e6e`
- `intelligence_modules/system_addons/` and `mcp-servers/system-addons/` were
  prepared as the next system-knowledge / self-extension layer. This area is
  scaffolded and wired, but still in preparation rather than feature-complete.
  Source: local worktree diff since `8501e6e`
- SQL memory was extended with a `trion_artifact_registry`, which supports the
  new system-addons / artifact-registry direction without introducing tracked
  runtime database files into Git.
  Source: local worktree diff since `8501e6e`
- Frontend Task-Loop rendering and workspace event flow were updated further in
  `adapters/Jarvis/static/js/`, so plan / thinking / workspace streams align
  better with the new loop runtime.
  Source: local worktree diff since `8501e6e`
- Utility code was further decomposed into `utils/embedding/`,
  `utils/routing/`, `utils/settings/`, and `utils/text/`, replacing more of the
  previous broad helper surface.
  Source: local worktree diff since `8501e6e`

## Current Index

- Open issues / next steps:
  [05-Open-Issues-Next-Steps.md](docs/obsidian/2026-03-22-container-commander-trion/05-Open-Issues-Next-Steps.md)
