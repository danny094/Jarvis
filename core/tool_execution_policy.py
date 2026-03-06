"""
Tool execution policy loader + helpers.
Reads policy from core/mapping_rules.yaml and merges with safe defaults.
"""

from __future__ import annotations

import copy
import os
from functools import lru_cache
from typing import Any, Dict, List

from utils.logger import log_warn

try:
    import yaml
except Exception:  # pragma: no cover - optional dependency guard
    yaml = None


_DEFAULT_TOOL_EXECUTION_POLICY: Dict[str, Any] = {
    "semantic_error": {
        "enabled": True,
        "keys": [
            "error",
            "errors",
            "exception",
            "traceback",
            "failure",
            "failure_reason",
        ],
        "max_depth": 4,
        "max_hits": 3,
        "ignore_paths": [],
    },
    "conversational_guard": {
        "suppress_dialogue_acts": ["ack", "feedback", "smalltalk"],
        "suppress_tools": ["run_skill", "create_skill", "autonomous_skill_task"],
        "allow_question_suffix_bypass": False,
    },
}


def _deep_merge(base: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (incoming or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _normalize_str_list(value: Any, fallback: List[str]) -> List[str]:
    if not isinstance(value, list):
        value = fallback
    out: List[str] = []
    for item in value:
        text = str(item or "").strip().lower()
        if text:
            out.append(text)
    return out or [str(x).strip().lower() for x in fallback if str(x).strip()]


def _normalize(policy: Dict[str, Any]) -> Dict[str, Any]:
    sem = policy.setdefault("semantic_error", {})
    sem["enabled"] = bool(sem.get("enabled", True))
    sem["keys"] = _normalize_str_list(
        sem.get("keys"),
        _DEFAULT_TOOL_EXECUTION_POLICY["semantic_error"]["keys"],
    )
    sem["ignore_paths"] = _normalize_str_list(sem.get("ignore_paths"), [])
    try:
        sem["max_depth"] = max(1, int(sem.get("max_depth", 4)))
    except Exception:
        sem["max_depth"] = 4
    try:
        sem["max_hits"] = max(1, int(sem.get("max_hits", 3)))
    except Exception:
        sem["max_hits"] = 3

    conv = policy.setdefault("conversational_guard", {})
    conv["suppress_dialogue_acts"] = _normalize_str_list(
        conv.get("suppress_dialogue_acts"),
        _DEFAULT_TOOL_EXECUTION_POLICY["conversational_guard"]["suppress_dialogue_acts"],
    )
    conv["suppress_tools"] = _normalize_str_list(
        conv.get("suppress_tools"),
        _DEFAULT_TOOL_EXECUTION_POLICY["conversational_guard"]["suppress_tools"],
    )
    conv["allow_question_suffix_bypass"] = bool(
        conv.get("allow_question_suffix_bypass", False)
    )
    return policy


@lru_cache(maxsize=1)
def load_tool_execution_policy() -> Dict[str, Any]:
    policy = copy.deepcopy(_DEFAULT_TOOL_EXECUTION_POLICY)
    rules_path = os.path.join(os.path.dirname(__file__), "mapping_rules.yaml")

    if yaml is None:
        return policy

    try:
        with open(rules_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        incoming = data.get("tool_execution") or {}
        if isinstance(incoming, dict):
            policy = _deep_merge(policy, incoming)
    except Exception as e:  # pragma: no cover - defensive
        log_warn(f"[ToolExecutionPolicy] Could not load mapping_rules.yaml: {e}")

    return _normalize(policy)
