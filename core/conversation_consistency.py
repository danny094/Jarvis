"""
Conversation consistency helpers (rules + optional embeddings).
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

from core.embedding_client import cosine_similarity

_TOPIC_PATTERNS: Dict[str, List[re.Pattern[str]]] = {
    "host_network_access": [
        re.compile(r"\b(hostnetzwerk|host network|outside docker|au[ßs]erhalb .*docker)\b", re.I),
        re.compile(r"\b(externes hostnetz|external host network)\b", re.I),
    ],
    "host_runtime_ip_disclosure": [
        re.compile(r"\b(host[-\s]?runtime[-\s]?ip|host[-\s]?ip|container[-\s]?ip)\b", re.I),
        re.compile(r"\b(ip[-\s]?adresse|ip address)\b", re.I),
    ],
}

_ALLOW_CUES = (
    "ich kann",
    "kann ich",
    "i can",
    "ermittelt",
    "gefunden",
    "ist ",
    "available",
)
_DENY_CUES = (
    "ich kann nicht",
    "kann nicht",
    "cannot",
    "can't",
    "darf nicht",
    "nicht möglich",
    "nicht preisgeben",
    "keine details",
    "forbidden",
)


def _split_sentences(text: str) -> List[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    parts = re.split(r"[\n\r]+|(?<=[\.\!\?])\s+", raw)
    return [p.strip() for p in parts if p and p.strip()]


def _resolve_stance(sentence: str) -> str:
    s = str(sentence or "").lower()
    has_allow = any(cue in s for cue in _ALLOW_CUES)
    has_deny = any(cue in s for cue in _DENY_CUES)
    if has_allow and not has_deny:
        return "allow"
    if has_deny and not has_allow:
        return "deny"
    return "unknown"


def extract_stance_signals(text: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for sentence in _split_sentences(text):
        stance = _resolve_stance(sentence)
        if stance == "unknown":
            continue
        for topic, patterns in _TOPIC_PATTERNS.items():
            if any(p.search(sentence) for p in patterns):
                out.append({
                    "topic": topic,
                    "stance": stance,
                    "snippet": sentence[:260],
                })
    # dedupe topic+stance+snippet
    seen = set()
    deduped: List[Dict[str, str]] = []
    for item in out:
        key = (item["topic"], item["stance"], item["snippet"].lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def make_entries(
    *,
    signals: List[Dict[str, str]],
    embedding: Optional[List[float]],
    now_ts: Optional[float] = None,
) -> List[Dict[str, Any]]:
    ts = float(now_ts if now_ts is not None else time.time())
    return [
        {
            "topic": str(item.get("topic") or ""),
            "stance": str(item.get("stance") or ""),
            "snippet": str(item.get("snippet") or ""),
            "ts": ts,
            "embedding": list(embedding) if isinstance(embedding, list) else None,
        }
        for item in (signals or [])
        if str(item.get("topic") or "").strip() and str(item.get("stance") or "").strip()
    ]


def prune_entries(
    entries: List[Dict[str, Any]],
    *,
    now_ts: Optional[float] = None,
    ttl_s: int = 3600,
    max_entries: int = 24,
) -> List[Dict[str, Any]]:
    now = float(now_ts if now_ts is not None else time.time())
    ttl = max(60, int(ttl_s or 3600))
    keep: List[Dict[str, Any]] = []
    for item in entries or []:
        ts = float(item.get("ts") or 0.0)
        if ts <= 0.0 or (now - ts) > ttl:
            continue
        keep.append(item)
    keep.sort(key=lambda x: float(x.get("ts") or 0.0))
    if len(keep) > max_entries:
        keep = keep[-max_entries:]
    return keep


def detect_conflicts(
    *,
    prior_entries: List[Dict[str, Any]],
    current_signals: List[Dict[str, str]],
    current_embedding: Optional[List[float]],
    similarity_threshold: float,
) -> List[Dict[str, Any]]:
    conflicts: List[Dict[str, Any]] = []
    threshold = max(0.0, min(1.0, float(similarity_threshold or 0.0)))
    for signal in current_signals or []:
        topic = str(signal.get("topic") or "")
        stance = str(signal.get("stance") or "")
        if stance not in {"allow", "deny"}:
            continue
        for prev in reversed(prior_entries or []):
            if str(prev.get("topic") or "") != topic:
                continue
            prev_stance = str(prev.get("stance") or "")
            if prev_stance not in {"allow", "deny"}:
                continue
            if prev_stance == stance:
                break
            similarity = 0.0
            prev_vec = prev.get("embedding")
            if isinstance(current_embedding, list) and isinstance(prev_vec, list):
                similarity = cosine_similarity(current_embedding, prev_vec)
                if similarity < threshold:
                    continue
            conflicts.append({
                "topic": topic,
                "previous_stance": prev_stance,
                "current_stance": stance,
                "previous_snippet": str(prev.get("snippet") or "")[:180],
                "current_snippet": str(signal.get("snippet") or "")[:180],
                "similarity": round(float(similarity), 4),
            })
            break
    return conflicts

