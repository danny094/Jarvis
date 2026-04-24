# Prompt Templates

Central source of truth for static prompt text.

This directory contains wording, contracts, and reusable text blocks that can be loaded by `intelligence_modules.prompt_manager`.

Keep behavior in Python code. Prompt files may define wording and static instructions, but they must not hide routing, policy, orchestration, or layer decision logic.

## Structure

- `layers/` contains large layer prompts.
- `contracts/` contains textual output and answer contracts.
- `task_loop/` contains task-loop wording, status text, recovery text, and clarification text.
- `personas/` contains persona and style blocks.

## Template Rules

- Use simple `{variable}` placeholders only.
- Declare expected variables in frontmatter.
- Do not use template branching or conditional behavior.
- Prefer one clear prompt file over scattered inline strings.
