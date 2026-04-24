"""Prompt template rendering helpers."""

from __future__ import annotations

import string
from typing import Any

from .errors import PromptFrontmatterError, PromptRenderError


def render_prompt(body: str, metadata: dict[str, Any], values: dict[str, Any]) -> str:
    """Render a prompt body with simple ``str.format`` placeholders."""
    declared_variables = _declared_variables(metadata)
    placeholders = _placeholders(body)

    undeclared = sorted(placeholders - declared_variables)
    if undeclared:
        raise PromptRenderError(
            "Prompt body uses undeclared variable(s): " + ", ".join(undeclared)
        )

    missing = sorted(declared_variables - values.keys())
    if missing:
        raise PromptRenderError(
            "Missing required prompt variable(s): " + ", ".join(missing)
        )

    try:
        return body.format(**values)
    except (KeyError, IndexError, ValueError) as exc:
        raise PromptRenderError(f"Failed to render prompt: {exc}") from exc


def _declared_variables(metadata: dict[str, Any]) -> set[str]:
    variables = metadata.get("variables", [])
    if variables is None:
        return set()
    if not isinstance(variables, list) or not all(isinstance(item, str) for item in variables):
        raise PromptFrontmatterError("Frontmatter field 'variables' must be a list of strings.")
    return set(variables)


def _placeholders(body: str) -> set[str]:
    placeholders: set[str] = set()
    try:
        parsed = string.Formatter().parse(body)
        for _, field_name, _, _ in parsed:
            if not field_name:
                continue
            root_name = field_name.split(".", 1)[0].split("[", 1)[0]
            if root_name:
                placeholders.add(root_name)
    except ValueError as exc:
        raise PromptRenderError(f"Invalid prompt placeholder syntax: {exc}") from exc
    return placeholders
