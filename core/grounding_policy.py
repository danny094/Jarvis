"""
Grounding policy loader + helpers.
Reads policy from core/mapping_rules.yaml and merges with safe defaults.
"""

from __future__ import annotations

import copy
import os
from functools import lru_cache
from typing import Any, Dict

from utils.logger import log_warn

try:
    import yaml
except Exception:  # pragma: no cover - optional dependency guard
    yaml = None


_DEFAULT_GROUNDING_POLICY: Dict[str, Any] = {
    "control": {
        "force_verify_for_fact_query": True,
    },
    "output": {
        "enforce_evidence_for_fact_query": True,
        "enforce_evidence_when_tools_used": True,
        "enforce_evidence_when_tools_suggested": True,
        "min_successful_evidence": 1,
        "allowed_evidence_statuses": ["ok"],
        "fact_query_response_mode": "hybrid",
        "fallback_mode": "explicit_uncertainty",
        "enable_postcheck_repair_once": True,
        "forbid_new_numeric_claims": True,
        "forbid_unverified_qualitative_claims": True,
        "qualitative_claim_guard": {
            "min_token_length": 5,
            "max_overall_novelty_ratio": 0.72,
            "max_sentence_novelty_ratio": 0.82,
            "min_sentence_tokens": 4,
            "min_assertive_sentence_violations": 1,
            "assertive_cues": [
                "is",
                "are",
                "runs",
                "running",
                "uses",
                "using",
                "has",
                "have",
                "läuft",
                "nutzt",
                "hat",
                "ist",
                "besteht",
                "verfügt",
                "befindet",
            ],
            "ignored_tokens": [
                "system",
                "assistant",
                "modell",
                "model",
                "response",
                "antwort",
                "tool",
                "tools",
                "fakten",
                "faktenlage",
                "daten",
                "information",
                "informationen",
                "verifiziert",
                "nicht",
                "ohne",
                "direkt",
                "aktuell",
                "heute",
            ],
        },
    },
    "memory": {
        "autosave_requires_evidence_for_fact_query": True,
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


def _normalize(policy: Dict[str, Any]) -> Dict[str, Any]:
    output = policy.setdefault("output", {})
    allowed = output.get("allowed_evidence_statuses", ["ok"])
    if not isinstance(allowed, list):
        allowed = ["ok"]
    output["allowed_evidence_statuses"] = [
        str(x).strip().lower() for x in allowed if str(x).strip()
    ] or ["ok"]
    try:
        output["min_successful_evidence"] = max(
            0, int(output.get("min_successful_evidence", 1))
        )
    except Exception:
        output["min_successful_evidence"] = 1
    output["fallback_mode"] = str(
        output.get("fallback_mode", "explicit_uncertainty")
    ).strip().lower() or "explicit_uncertainty"
    output["fact_query_response_mode"] = str(
        output.get("fact_query_response_mode", "model")
    ).strip().lower() or "model"
    output["enable_postcheck_repair_once"] = bool(
        output.get("enable_postcheck_repair_once", True)
    )

    output["forbid_unverified_qualitative_claims"] = bool(
        output.get("forbid_unverified_qualitative_claims", True)
    )
    guard = output.setdefault("qualitative_claim_guard", {})
    try:
        guard["min_token_length"] = max(2, int(guard.get("min_token_length", 5)))
    except Exception:
        guard["min_token_length"] = 5
    try:
        guard["max_overall_novelty_ratio"] = min(
            1.0, max(0.0, float(guard.get("max_overall_novelty_ratio", 0.72)))
        )
    except Exception:
        guard["max_overall_novelty_ratio"] = 0.72
    try:
        guard["max_sentence_novelty_ratio"] = min(
            1.0, max(0.0, float(guard.get("max_sentence_novelty_ratio", 0.82)))
        )
    except Exception:
        guard["max_sentence_novelty_ratio"] = 0.82
    try:
        guard["min_sentence_tokens"] = max(1, int(guard.get("min_sentence_tokens", 4)))
    except Exception:
        guard["min_sentence_tokens"] = 4
    try:
        guard["min_assertive_sentence_violations"] = max(
            1, int(guard.get("min_assertive_sentence_violations", 1))
        )
    except Exception:
        guard["min_assertive_sentence_violations"] = 1

    cues = guard.get("assertive_cues", [])
    if not isinstance(cues, list):
        cues = []
    guard["assertive_cues"] = [
        str(cue).strip().lower()
        for cue in cues
        if str(cue).strip()
    ]
    ignored_tokens = guard.get("ignored_tokens", [])
    if not isinstance(ignored_tokens, list):
        ignored_tokens = []
    guard["ignored_tokens"] = [
        str(token).strip().lower()
        for token in ignored_tokens
        if str(token).strip()
    ]
    return policy


@lru_cache(maxsize=1)
def load_grounding_policy() -> Dict[str, Any]:
    policy = copy.deepcopy(_DEFAULT_GROUNDING_POLICY)
    rules_path = os.path.join(os.path.dirname(__file__), "mapping_rules.yaml")

    if yaml is None:
        return policy

    try:
        with open(rules_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        incoming = data.get("grounding") or {}
        if isinstance(incoming, dict):
            policy = _deep_merge(policy, incoming)
    except Exception as e:  # pragma: no cover - defensive
        log_warn(f"[GroundingPolicy] Could not load mapping_rules.yaml: {e}")

    return _normalize(policy)
