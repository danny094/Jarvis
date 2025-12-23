# languages/__init__.py
"""
Language Configuration Module.

Definiert Sprach-Mappings für Code-Ausführung.
"""

from .config import (
    LANGUAGE_CONFIG,
    get_language_config,
    is_language_supported,
    get_supported_languages,
)

__all__ = [
    "LANGUAGE_CONFIG",
    "get_language_config",
    "is_language_supported",
    "get_supported_languages",
]
