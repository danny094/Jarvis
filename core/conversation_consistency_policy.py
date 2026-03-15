"""
Conversation consistency policy loader.

Policy lives in core/mapping_rules.yaml under:
conversation_consistency: {...}
"""

from __future__ import annotations

import copy
import os
from functools import lru_cache
from typing import Any, Dict

from utils.logger import log_warn

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


_DEFAULT_POLICY: Dict[str, Any] = {
    "enabled": True,
    "history_ttl_s": 3600,
    "max_entries_per_conversation": 24,
    "require_evidence_on_stance_change": True,
    "min_successful_evidence_on_stance_change": 1,
    "embedding_enable": True,
    "embedding_similarity_threshold": 0.78,
    "fallback_mode": "explicit_uncertainty",
}


def _deep_merge(base: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (incoming or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _normalize(policy: Dict[str, Any]) -> Dict[str, Any]:
    policy["enabled"] = bool(policy.get("enabled", True))
    policy["require_evidence_on_stance_change"] = bool(
        policy.get("require_evidence_on_stance_change", True)
    )
    policy["embedding_enable"] = bool(policy.get("embedding_enable", True))
    try:
        policy["history_ttl_s"] = max(60, int(policy.get("history_ttl_s", 3600)))
    except Exception:
        policy["history_ttl_s"] = 3600
    try:
        policy["max_entries_per_conversation"] = max(
            4, int(policy.get("max_entries_per_conversation", 24))
        )
    except Exception:
        policy["max_entries_per_conversation"] = 24
    try:
        policy["min_successful_evidence_on_stance_change"] = max(
            0, int(policy.get("min_successful_evidence_on_stance_change", 1))
        )
    except Exception:
        policy["min_successful_evidence_on_stance_change"] = 1
    try:
        policy["embedding_similarity_threshold"] = min(
            1.0, max(0.0, float(policy.get("embedding_similarity_threshold", 0.78)))
        )
    except Exception:
        policy["embedding_similarity_threshold"] = 0.78
    policy["fallback_mode"] = str(
        policy.get("fallback_mode", "explicit_uncertainty")
    ).strip().lower() or "explicit_uncertainty"
    return policy


@lru_cache(maxsize=1)
def load_conversation_consistency_policy() -> Dict[str, Any]:
    policy = copy.deepcopy(_DEFAULT_POLICY)
    rules_path = os.path.join(os.path.dirname(__file__), "mapping_rules.yaml")
    if yaml is None:
        return policy
    try:
        with open(rules_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        incoming = data.get("conversation_consistency") or {}
        if isinstance(incoming, dict):
            policy = _deep_merge(policy, incoming)
    except Exception as exc:  # pragma: no cover
        log_warn(f"[ConversationConsistencyPolicy] Could not load mapping_rules.yaml: {exc}")
    return _normalize(policy)

