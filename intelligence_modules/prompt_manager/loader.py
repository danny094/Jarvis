"""Public prompt loading API."""

from __future__ import annotations

from pathlib import Path

from .errors import PromptNotFoundError
from .frontmatter import parse_frontmatter
from .rendering import render_prompt


PROMPTS_ROOT = Path(__file__).resolve().parents[1] / "prompts"


def load_prompt(category: str, template_name: str, **kwargs: object) -> str:
    """Load and render a prompt template.

    ``category`` maps to a directory under ``intelligence_modules/prompts``.
    ``template_name`` maps to a markdown file in that category. The ``.md``
    suffix is optional.
    """
    template_path = _template_path(category, template_name)
    if not template_path.is_file():
        raise PromptNotFoundError(f"Prompt template not found: {category}/{template_name}")

    metadata, body = parse_frontmatter(template_path.read_text(encoding="utf-8"))
    return render_prompt(body, metadata, kwargs)


def _template_path(category: str, template_name: str) -> Path:
    category_path = _safe_relative_path(category, "category")
    template_path = _safe_relative_path(template_name, "template_name")
    if template_path.suffix != ".md":
        template_path = template_path.with_suffix(".md")
    return (PROMPTS_ROOT / category_path / template_path).resolve()


def _safe_relative_path(value: str, field_name: str) -> Path:
    if not value or value.startswith(("/", "\\")):
        raise PromptNotFoundError(f"Invalid prompt {field_name}: {value!r}")

    path = Path(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise PromptNotFoundError(f"Invalid prompt {field_name}: {value!r}")
    return path
