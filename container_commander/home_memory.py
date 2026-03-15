"""
TRION Home Memory (Phase 1)

File-backed memory notes with deterministic save policy:
- forced keywords
- importance threshold
- sensitive content redaction block
"""

from __future__ import annotations

import json
import os
import re
import uuid
import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.trion_home_identity import load_home_identity, evaluate_home_status

logger = logging.getLogger(__name__)


class MemoryPolicyError(RuntimeError):
    def __init__(self, message: str, *, error_code: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _memory_paths(identity: Dict[str, Any]) -> Dict[str, Path]:
    home_path = str(identity.get("home_path") or "/trion-home").strip() or "/trion-home"
    base = Path(home_path) / "memory"
    return {
        "base": base,
        "notes": base / "notes.jsonl",
        "index": base / "index.json",
        "audit": base / "audit.jsonl",
    }


def _emit_ws_activity(event: str, level: str = "info", message: str = "", **data):
    """Best-effort websocket activity event emitter for TRION memory events."""
    try:
        from .ws_stream import emit_activity

        emit_activity(event, level=level, message=message, **data)
    except Exception as e:
        logger.debug(f"[HomeMemory] WS activity emit failed ({event}): {e}")


def _policy(identity: Dict[str, Any]) -> Dict[str, Any]:
    caps = identity.get("capabilities") if isinstance(identity, dict) else {}
    caps = caps if isinstance(caps, dict) else {}
    return {
        "importance_threshold": _safe_float(caps.get("importance_threshold", 0.72), 0.72),
        "forced_keywords": [str(x).strip().lower() for x in caps.get("forced_keywords", []) if str(x).strip()],
        "redact_patterns": [str(x).strip() for x in caps.get("redact_patterns", []) if str(x).strip()],
        "max_note_size_kb": max(1, _safe_int(caps.get("max_note_size_kb", 10), 10)),
    }


def _contains_forced_keyword(content: str, forced_keywords: List[str]) -> bool:
    text = str(content or "").lower()
    return any(k in text for k in forced_keywords if k)


def _contains_sensitive_pattern(content: str, patterns: List[str]) -> Optional[str]:
    text = str(content or "")
    for pattern in patterns:
        try:
            compiled = re.compile(re.escape(pattern), re.IGNORECASE)
            if compiled.search(text):
                return pattern
        except Exception:
            continue
    return None


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                out.append(row)
        except Exception:
            continue
    return out


def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _write_index(paths: Dict[str, Path], note: Dict[str, Any], *, max_items: int = 5000) -> None:
    index_path = paths["index"]
    index: List[Dict[str, Any]] = []
    if index_path.exists():
        try:
            raw = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                index = [x for x in raw if isinstance(x, dict)]
        except Exception:
            index = []

    entry = {
        "id": note["id"],
        "timestamp": note["timestamp"],
        "category": note.get("category", ""),
        "importance": note.get("importance", 0.0),
        "trigger": note.get("trigger", ""),
    }
    index.append(entry)
    if len(index) > max_items:
        index = index[-max_items:]
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def _check_home_writable(identity: Dict[str, Any]) -> Dict[str, Any]:
    require_connected = str(os.environ.get("TRION_HOME_REQUIRE_CONNECTED", "1")).strip().lower() not in {
        "0",
        "false",
        "no",
    }
    from container_commander.engine import list_containers

    status = evaluate_home_status(list_containers(), identity=identity)
    if require_connected and status.get("status") != "connected":
        raise MemoryPolicyError(
            "Home container is not connected",
            error_code=str(status.get("error_code") or "home_container_unavailable"),
            details={"home_status": status.get("status"), "home_error_code": status.get("error_code", "")},
        )
    return status


def remember_note(
    *,
    content: str,
    category: str = "note",
    importance: float = 0.5,
    trigger: str = "auto",
    context: str = "",
    why: str = "",
    identity_path: Optional[str] = None,
) -> Dict[str, Any]:
    identity = load_home_identity(identity_path=identity_path, create_if_missing=True)
    policy = _policy(identity)
    raw_content = str(content or "").strip()
    if not raw_content:
        _emit_ws_activity(
            "memory_denied",
            level="warn",
            message="Memory save denied: empty content",
            error_code="bad_request",
        )
        raise MemoryPolicyError("content is required", error_code="bad_request")

    max_bytes = policy["max_note_size_kb"] * 1024
    content_bytes = len(raw_content.encode("utf-8"))
    if content_bytes > max_bytes:
        _emit_ws_activity(
            "memory_denied",
            level="warn",
            message="Memory save denied: note exceeds size limit",
            error_code="bad_request",
            size_bytes=content_bytes,
            max_note_size_kb=policy["max_note_size_kb"],
        )
        raise MemoryPolicyError(
            "note exceeds max_note_size_kb",
            error_code="bad_request",
            details={"max_note_size_kb": policy["max_note_size_kb"], "size_bytes": content_bytes},
        )

    sensitive_match = _contains_sensitive_pattern(raw_content, policy["redact_patterns"])
    if sensitive_match:
        _emit_ws_activity(
            "memory_denied",
            level="error",
            message="Memory save denied: sensitive pattern detected",
            error_code="policy_denied",
            matched_pattern=sensitive_match,
        )
        raise MemoryPolicyError(
            "sensitive pattern detected",
            error_code="policy_denied",
            details={"matched_pattern": sensitive_match},
        )

    forced = _contains_forced_keyword(raw_content, policy["forced_keywords"])
    importance_value = max(0.0, min(1.0, _safe_float(importance, 0.5)))
    threshold = policy["importance_threshold"]
    should_save = forced or importance_value >= threshold

    decision = {
        "should_save": should_save,
        "forced": forced,
        "importance": importance_value,
        "threshold": threshold,
    }
    if not should_save:
        _emit_ws_activity(
            "memory_skipped",
            level="info",
            message="Memory note skipped: below threshold",
            category=str(category or "note"),
            importance=importance_value,
            threshold=threshold,
            reason="below_threshold",
        )
        return {
            "saved": False,
            "reason": "below_threshold",
            "decision": decision,
            "identity_container": identity.get("container_id", "trion-home"),
        }

    try:
        home_status = _check_home_writable(identity)
    except MemoryPolicyError as e:
        _emit_ws_activity(
            "memory_denied",
            level="error",
            message=f"Memory save denied: {e.error_code}",
            error_code=e.error_code,
            **(e.details or {}),
        )
        raise
    paths = _memory_paths(identity)
    note_id = f"note_{datetime.now(tz=timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    note = {
        "id": note_id,
        "timestamp": _utc_now_iso(),
        "content": raw_content,
        "category": str(category or "note"),
        "importance": importance_value,
        "trigger": "forced" if forced else str(trigger or "auto"),
        "context": str(context or ""),
        "why": str(why or ""),
        "redacted": False,
    }
    _append_jsonl(paths["notes"], note)
    _write_index(paths, note)
    _append_jsonl(
        paths["audit"],
        {
            "timestamp": _utc_now_iso(),
            "action": "saved",
            "note_id": note_id,
            "category": note["category"],
            "importance": importance_value,
            "trigger": note["trigger"],
            "rule": "forced_keyword" if forced else "importance_threshold",
        },
    )
    _emit_ws_activity(
        "memory_saved",
        level="success",
        message=f"Memory note saved ({note['category']})",
        note_id=note_id,
        category=note["category"],
        importance=importance_value,
        trigger=note["trigger"],
        home_status=home_status.get("status", ""),
    )
    return {
        "saved": True,
        "note": note,
        "decision": decision,
        "home_status": home_status.get("status", ""),
    }


def recent_notes(*, limit: int = 20, identity_path: Optional[str] = None) -> Dict[str, Any]:
    identity = load_home_identity(identity_path=identity_path, create_if_missing=True)
    paths = _memory_paths(identity)
    rows = _read_jsonl(paths["notes"])
    lim = max(1, min(200, _safe_int(limit, 20)))
    recent = list(deque(rows, maxlen=lim))
    recent.reverse()  # newest first
    return {"notes": recent, "count": len(recent)}


def recall_notes(
    *,
    query: str,
    limit: int = 10,
    category: str = "",
    identity_path: Optional[str] = None,
) -> Dict[str, Any]:
    q = str(query or "").strip().lower()
    if not q:
        raise MemoryPolicyError("query is required", error_code="bad_request")

    identity = load_home_identity(identity_path=identity_path, create_if_missing=True)
    rows = _read_jsonl(_memory_paths(identity)["notes"])
    lim = max(1, min(100, _safe_int(limit, 10)))
    category_filter = str(category or "").strip().lower()
    terms = [t for t in q.split() if t]

    scored = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_cat = str(row.get("category", "")).lower()
        if category_filter and row_cat != category_filter:
            continue
        haystack = " ".join(
            [
                str(row.get("content", "")),
                str(row.get("why", "")),
                str(row.get("context", "")),
                row_cat,
            ]
        ).lower()
        score = sum(1 for t in terms if t in haystack)
        if score > 0:
            scored.append((score, str(row.get("timestamp", "")), row))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    results = [row for _, _, row in scored[:lim]]
    return {"notes": results, "count": len(results), "query": q}


def memory_status(*, identity_path: Optional[str] = None) -> Dict[str, Any]:
    identity = load_home_identity(identity_path=identity_path, create_if_missing=True)
    paths = _memory_paths(identity)
    home_status = _check_home_writable(identity)
    notes_count = len(_read_jsonl(paths["notes"]))
    return {
        "ok": True,
        "home_status": home_status.get("status", ""),
        "home_error_code": home_status.get("error_code", ""),
        "identity_container": identity.get("container_id", "trion-home"),
        "notes_path": str(paths["notes"]),
        "notes_count": notes_count,
    }
