"""
utils/model_settings.py — Single Source of Truth for Model Configuration

Precedence (highest wins):
  1. persisted override  (config/settings.json via SettingsManager)
  2. environment variable
  3. code default

Usage:
    from utils.model_settings import ALLOWED_MODEL_KEYS, MODEL_DEFAULTS, get_effective_model_settings
"""
from __future__ import annotations

import os
from typing import Dict

# ---------------------------------------------------------------------------
# Canonical field names
# ---------------------------------------------------------------------------
ALLOWED_MODEL_KEYS: frozenset[str] = frozenset({
    "THINKING_MODEL",
    "CONTROL_MODEL",
    "OUTPUT_MODEL",
    "EMBEDDING_MODEL",
})

# ---------------------------------------------------------------------------
# Code-level defaults  (fallback of last resort)
# ---------------------------------------------------------------------------
MODEL_DEFAULTS: Dict[str, str] = {
    "THINKING_MODEL":  "ministral-3:8b",
    "CONTROL_MODEL":   "ministral-3:8b",
    "OUTPUT_MODEL":    "ministral-3:3b",
    "EMBEDDING_MODEL": "hellord/mxbai-embed-large-v1:f16",
}


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------
def get_effective_model_settings(
    persisted: Dict[str, str],
) -> Dict[str, Dict[str, str]]:
    """
    Resolve effective model settings with source tracking.

    Args:
        persisted: Dict of key→value from SettingsManager (already-filtered or full).

    Returns:
        {
          "THINKING_MODEL": {"value": "...", "source": "override"|"env"|"default"},
          ...
        }
    """
    result: Dict[str, Dict[str, str]] = {}
    for key in ALLOWED_MODEL_KEYS:
        p = persisted.get(key, "")
        if p:
            result[key] = {"value": p, "source": "override"}
            continue
        env_val = os.getenv(key, "")
        if env_val:
            result[key] = {"value": env_val, "source": "env"}
            continue
        result[key] = {"value": MODEL_DEFAULTS[key], "source": "default"}
    return result
