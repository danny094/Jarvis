"""
TRION laws retrieval policy loader.

Policy location: core/mapping_rules.yaml -> trion_laws
"""

from __future__ import annotations

import copy
import os
from functools import lru_cache
from typing import Any, Dict, List

from utils.logger import log_warn

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


_DEFAULT_POLICY: Dict[str, Any] = {
    "enabled": True,
    "query": "hardware limits laws constraints",
    "graph_depth": 0,
    "graph_limit": 20,
    "semantic_enable": True,
    "semantic_limit": 8,
    "max_output_lines": 8,
    "noise_metadata_keys": ["tool_name", "execution", "mcp", "task_id", "archive_id"],
    "noise_prefixes": ["memory_search:"],
    "noise_contains_any": ["execution", "search memory", "tool registry", "observability"],
    "allow_name_colon_exec_pattern": True,
    "law_markers": [
        "gesetz",
        "law",
        "regel",
        "muss",
        "darf",
        "niemals",
        "immer",
        "constraint",
        "limit",
        "safety",
        "sicherheit",
        "policy",
        "forbidden",
        "must",
        "never",
        "always",
        "allowed",
    ],
    "require_law_marker": True,
}


def _deep_merge(base: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (incoming or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _to_str_list(value: Any, default: List[str]) -> List[str]:
    if not isinstance(value, list):
        return list(default)
    out: List[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            out.append(text)
    return out or list(default)


def _normalize(policy: Dict[str, Any]) -> Dict[str, Any]:
    policy["enabled"] = bool(policy.get("enabled", True))
    policy["semantic_enable"] = bool(policy.get("semantic_enable", True))
    policy["allow_name_colon_exec_pattern"] = bool(
        policy.get("allow_name_colon_exec_pattern", True)
    )
    policy["require_law_marker"] = bool(policy.get("require_law_marker", True))

    try:
        policy["graph_depth"] = max(0, min(3, int(policy.get("graph_depth", 0))))
    except Exception:
        policy["graph_depth"] = 0
    try:
        policy["graph_limit"] = max(1, min(50, int(policy.get("graph_limit", 20))))
    except Exception:
        policy["graph_limit"] = 20
    try:
        policy["semantic_limit"] = max(1, min(30, int(policy.get("semantic_limit", 8))))
    except Exception:
        policy["semantic_limit"] = 8
    try:
        policy["max_output_lines"] = max(1, min(20, int(policy.get("max_output_lines", 8))))
    except Exception:
        policy["max_output_lines"] = 8

    policy["query"] = str(policy.get("query") or _DEFAULT_POLICY["query"]).strip() or _DEFAULT_POLICY["query"]
    policy["noise_metadata_keys"] = _to_str_list(
        policy.get("noise_metadata_keys"),
        _DEFAULT_POLICY["noise_metadata_keys"],
    )
    policy["noise_prefixes"] = _to_str_list(
        policy.get("noise_prefixes"),
        _DEFAULT_POLICY["noise_prefixes"],
    )
    policy["noise_contains_any"] = _to_str_list(
        policy.get("noise_contains_any"),
        _DEFAULT_POLICY["noise_contains_any"],
    )
    policy["law_markers"] = [x.lower() for x in _to_str_list(
        policy.get("law_markers"),
        _DEFAULT_POLICY["law_markers"],
    )]
    return policy


@lru_cache(maxsize=1)
def load_trion_laws_policy() -> Dict[str, Any]:
    policy = copy.deepcopy(_DEFAULT_POLICY)
    if yaml is None:
        return policy

    rules_path = os.path.join(os.path.dirname(__file__), "mapping_rules.yaml")
    try:
        with open(rules_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        incoming = data.get("trion_laws") or {}
        if isinstance(incoming, dict):
            policy = _deep_merge(policy, incoming)
    except Exception as exc:  # pragma: no cover
        log_warn(f"[TrionLawsPolicy] Could not load mapping_rules.yaml: {exc}")

    return _normalize(policy)
