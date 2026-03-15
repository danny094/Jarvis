"""
Autosave deduplication guard.

Goal:
- prevent duplicate assistant autosaves in short windows per conversation
- keep behavior deterministic and policy-driven (config/env)
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from collections import OrderedDict
from typing import Dict, Tuple

from config import (
    get_autosave_dedupe_enable,
    get_autosave_dedupe_max_entries,
    get_autosave_dedupe_window_s,
)


def _normalize_content(text: str) -> str:
    raw = str(text or "").strip().lower()
    if not raw:
        return ""
    return re.sub(r"\s+", " ", raw)


def _make_key(conversation_id: str, content: str) -> str:
    conv = str(conversation_id or "").strip()
    normalized = _normalize_content(content)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"{conv}:{digest}"


class AutosaveDedupeGuard:
    def __init__(self, *, window_s: int, max_entries: int):
        self.window_s = max(1, int(window_s or 1))
        self.max_entries = max(128, int(max_entries or 128))
        self._lock = threading.Lock()
        self._seen: "OrderedDict[str, float]" = OrderedDict()

    def _prune(self, now: float) -> None:
        # TTL prune
        expired: list[str] = []
        for key, ts in self._seen.items():
            if (now - ts) > self.window_s:
                expired.append(key)
            else:
                break
        for key in expired:
            self._seen.pop(key, None)

        # Size prune
        while len(self._seen) > self.max_entries:
            self._seen.popitem(last=False)

    def should_skip(self, *, conversation_id: str, content: str) -> bool:
        normalized = _normalize_content(content)
        if not normalized:
            return False
        now = time.time()
        key = _make_key(conversation_id, normalized)
        with self._lock:
            self._prune(now)
            prev = self._seen.get(key)
            if prev is not None and (now - prev) <= self.window_s:
                return True
            self._seen[key] = now
            self._seen.move_to_end(key, last=True)
            self._prune(now)
            return False


_guard_lock = threading.Lock()
_guard: AutosaveDedupeGuard | None = None
_guard_cfg: Tuple[int, int] | None = None


def get_autosave_dedupe_guard() -> AutosaveDedupeGuard | None:
    if not get_autosave_dedupe_enable():
        return None
    window_s = get_autosave_dedupe_window_s()
    max_entries = get_autosave_dedupe_max_entries()
    cfg = (int(window_s), int(max_entries))

    global _guard, _guard_cfg
    with _guard_lock:
        if _guard is None or _guard_cfg != cfg:
            _guard = AutosaveDedupeGuard(window_s=cfg[0], max_entries=cfg[1])
            _guard_cfg = cfg
        return _guard

