"""
Light CIM policy loader + helpers.
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


_DEFAULT_LIGHT_CIM_POLICY: Dict[str, Any] = {
    "logic": {
        "enforce_new_fact_completeness": True,
        "relax_new_fact_completeness": {
            "enabled": True,
            "dialogue_acts": ["smalltalk", "ack", "feedback"],
            "intent_regex": [
                r"\bselbstdarstellung\b",
                r"\bmetakogn",
                r"\bself[-\s]?description\b",
                r"\b(körper|body)\b",
            ],
            "user_text_regex": [
                r"\bwie fühlst du\b",
                r"\bdescribe your\b",
                r"\bbeschreib[e]? deinen\b",
                r"\bdein(?:e|en)? hardware\b",
            ],
        },
    }
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


def _normalize_regex_list(value: Any, fallback: List[str]) -> List[str]:
    if not isinstance(value, list):
        value = fallback
    out: List[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            out.append(text)
    return out or [str(x).strip() for x in fallback if str(x).strip()]


def _normalize(policy: Dict[str, Any]) -> Dict[str, Any]:
    logic = policy.setdefault("logic", {})
    logic["enforce_new_fact_completeness"] = bool(
        logic.get("enforce_new_fact_completeness", True)
    )

    relax = logic.setdefault("relax_new_fact_completeness", {})
    relax["enabled"] = bool(relax.get("enabled", True))
    relax["dialogue_acts"] = _normalize_str_list(
        relax.get("dialogue_acts"),
        _DEFAULT_LIGHT_CIM_POLICY["logic"]["relax_new_fact_completeness"]["dialogue_acts"],
    )
    relax["intent_regex"] = _normalize_regex_list(
        relax.get("intent_regex"),
        _DEFAULT_LIGHT_CIM_POLICY["logic"]["relax_new_fact_completeness"]["intent_regex"],
    )
    relax["user_text_regex"] = _normalize_regex_list(
        relax.get("user_text_regex"),
        _DEFAULT_LIGHT_CIM_POLICY["logic"]["relax_new_fact_completeness"]["user_text_regex"],
    )
    return policy


@lru_cache(maxsize=1)
def load_light_cim_policy() -> Dict[str, Any]:
    policy = copy.deepcopy(_DEFAULT_LIGHT_CIM_POLICY)
    rules_path = os.path.join(os.path.dirname(__file__), "mapping_rules.yaml")

    if yaml is None:
        return policy

    try:
        with open(rules_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        incoming = data.get("light_cim") or {}
        if isinstance(incoming, dict):
            policy = _deep_merge(policy, incoming)
    except Exception as e:  # pragma: no cover - defensive
        log_warn(f"[LightCIMPolicy] Could not load mapping_rules.yaml: {e}")

    return _normalize(policy)
