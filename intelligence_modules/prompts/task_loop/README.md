# Task Loop Prompts

Task-loop wording blocks for status, recovery, clarification, and step-level messages.

Execution flow, retries, approvals, and recovery decisions stay in code.

## Active Templates

- `step_runtime.md` contains the final prompt scaffold for one task-loop step.
- `status.md` contains the final completion status message.
- `clarification.md` contains the concrete-input clarification message.
- `risk_gate.md`, `control_soft_block.md`, `hard_block.md`, `waiting.md`, and `verify_before_complete.md` contain runner-facing user messages.
- `chat_default_step_*.md` and `chat_default_fallback.md` contain default chat-loop step answers.
- `chat_analysis_step_*.md` and `chat_analysis_fallback.md` contain analysis chat-loop step answers.
- `chat_validation_step_*.md` and `chat_validation_fallback.md` contain validation chat-loop step answers.
- `chat_implementation_step_*.md` and `chat_implementation_fallback.md` contain implementation chat-loop step answers.
- `container_*.md` contains container request waiting and clarification wording.

## Boundary

Prompt files define wording and layout only. Step selection, recovery decisions, auto-clarify routing, tool selection, and verified context assembly stay in Python code.
