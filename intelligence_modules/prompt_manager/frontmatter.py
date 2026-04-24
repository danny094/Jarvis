"""Frontmatter parsing for prompt templates."""

from __future__ import annotations

import ast
from typing import Any

from .errors import PromptFrontmatterError


FRONTMATTER_DELIMITER = "---"


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return parsed frontmatter metadata and markdown body."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
        raise PromptFrontmatterError("Prompt template must start with frontmatter delimiter '---'.")

    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == FRONTMATTER_DELIMITER:
            closing_index = index
            break

    if closing_index is None:
        raise PromptFrontmatterError("Prompt template frontmatter is not closed with '---'.")

    metadata = _parse_metadata_lines(lines[1:closing_index])
    body = "\n".join(lines[closing_index + 1 :]).strip()
    return metadata, body


def _parse_metadata_lines(lines: list[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for line_number, raw_line in enumerate(lines, start=2):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise PromptFrontmatterError(f"Invalid frontmatter line {line_number}: missing ':'.")

        key, raw_value = line.split(":", 1)
        key = key.strip()
        if not key:
            raise PromptFrontmatterError(f"Invalid frontmatter line {line_number}: empty key.")
        metadata[key] = _parse_value(raw_value.strip(), line_number)

    return metadata


def _parse_value(raw_value: str, line_number: int) -> Any:
    if raw_value == "":
        return ""
    try:
        return ast.literal_eval(raw_value)
    except (SyntaxError, ValueError):
        if raw_value.startswith(("[", "{", "(", "'", '"')):
            raise PromptFrontmatterError(
                f"Invalid frontmatter value on line {line_number}: {raw_value}"
            ) from None
        return raw_value
