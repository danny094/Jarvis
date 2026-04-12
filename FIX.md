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

## Current Index

- Open issues / next steps:
  [05-Open-Issues-Next-Steps.md](docs/obsidian/2026-03-22-container-commander-trion/05-Open-Issues-Next-Steps.md)
