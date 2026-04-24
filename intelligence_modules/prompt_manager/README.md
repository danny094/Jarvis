# Prompt Manager

Infrastructure for loading and rendering prompt templates from `intelligence_modules/prompts`.

The prompt manager should stay small and deterministic:

- read frontmatter
- load prompt bodies
- validate required variables
- render simple `{variable}` placeholders
- fail clearly on missing files, invalid metadata, or missing variables

It should not decide which prompt is semantically correct for a layer or task. Calling code keeps that responsibility.
