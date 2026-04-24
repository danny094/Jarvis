---
scope: output_contract
target: output_layer
variables: []
status: index
---

# Output Prompt Contracts

Output prompt text is split into focused templates. The Python builder keeps activation order, runtime decisions, and variable preparation.

## General Output Guards

- `output_grounding.md` contains evidence-grounding wording.
- `output_analysis_guard.md` contains conceptual-analysis guard wording.
- `output_anti_hallucination.md` contains missing-memory anti-hallucination wording.
- `output_chat_history.md` contains the chat-history context hint.
- `output_budget_interactive.md` and `output_budget_deep.md` contain response-budget wording.
- `output_sequential_summary.md` contains the post-analysis summary instruction.
- `output_style.md` contains the suggested response style wording.
- `output_dialogue_*.md`, `output_tone_*.md`, and `output_length_*.md` contain dialogue guidance wording.
- `output_legacy_*.md` contains labels for the legacy `/api/generate` full prompt format.
- `grounding_fallback_*.md` and `tool_failure_fallback_*.md` contain grounding fallback wording.
- `output_error_*.md`, `output_sync_cloud_provider.md`, `output_truncation_*.md`, and
  `output_grounding_correction_marker.md` contain stream/user-facing notices.

## Domain Contracts

- `container_inventory.md` contains runtime container inventory answer rules.
- `container_blueprint_catalog.md` contains blueprint catalog answer rules.
- `container_state_binding.md` contains active container and session-binding answer rules.
- `skill_catalog.md` contains skill catalog answer rules.

## Boundary

Prompt files define wording only. The output layer still decides when a block applies, which variables are passed, and how postchecks or repairs run.
