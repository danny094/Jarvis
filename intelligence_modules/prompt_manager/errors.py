"""Exceptions for prompt loading and rendering."""


class PromptManagerError(Exception):
    """Base error for prompt manager failures."""


class PromptNotFoundError(PromptManagerError):
    """Raised when a prompt template cannot be found."""


class PromptFrontmatterError(PromptManagerError):
    """Raised when prompt frontmatter is missing or invalid."""


class PromptRenderError(PromptManagerError):
    """Raised when a prompt cannot be rendered with the provided values."""
