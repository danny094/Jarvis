"""
tests/harness/providers/mock_provider.py — Commit B
=====================================================
MockProvider: deterministic, no external dependencies.

Response selection:
  1. Keyword lookup in _MOCK_LIBRARY (longest matching key wins).
  2. Hash-based fallback: same prompt → same response, always.

Temperature=0 equivalent: the response function is pure (prompt → text).
Stream mode splits the same text into word-level chunks.
"""
from __future__ import annotations

import hashlib
from typing import Dict, Iterable

# ─────────────────────────────────────────────────────────────────────────────
# Keyword library — maps prompt substrings to canned responses
# Key = lowercase substring to match against prompt.lower()
# Entries sorted by length (longer = more specific, checked first in lookup).
# ─────────────────────────────────────────────────────────────────────────────
_MOCK_LIBRARY: Dict[str, str] = {
    # Phase 0 – basic sanity
    "hello":                "Hallo! Ich bin TRION. Wie kann ich dir helfen?",
    "ping":                 "pong",
    "liveness":             "OK — TRION Liveness-Check bestanden.",
    # Phase 2 – Single Truth Channel / dedup
    "single truth channel": "Single Truth Channel aktiv: Kontext wird einmalig injiziert.",
    "single truth":         "Single Truth Channel aktiv.",
    "no duplication":       "Kein Duplikat im Kontext gefunden.",
    "double injection":     "Kein Duplikat gefunden — Single Truth Channel verhindert Doppel-Injection.",
    "dedup":                "Deduplizierung erfolgreich — jede Quelle erscheint genau einmal.",
    # Phase 3 – TypedState V1 / CompactContext
    "compact context":      "NOW: focus_entity=TestEntity | RULES: keine | NEXT: await",
    "typedstate":           "TypedState V1 aktiv. Compact-NOW-Block injiziert.",
    "fail-closed":          "Fail-Closed: leerer NOW-Block zurückgegeben (keine Events).",
    "now block":            "NOW: leer | RULES: default | NEXT: await",
    # Phase 4 – Container Restart Recovery
    "restart recovery":     "Container-Restart erkannt. TTL-Labels wiederhergestellt.",
    "ttl rearm":            "TTL-Rearm erfolgreich. Container läuft stabil weiter.",
    "ttl":                  "TTL-Label gesetzt und validiert.",
    "recovery":             "Recovery abgeschlossen. Systemzustand wiederhergestellt.",
    # Phase 5 – Graph Hygiene
    "dedupe blueprint":     "Duplikate pro blueprint_id entfernt. Neueste Revision beibehalten.",
    "graph hygiene":        "Graph-Index bereinigt. SQLite = Truth.",
    "stale node":           "Stale-Node entfernt. Nicht in SQLite-Active-Set.",
    "blueprint_id":         "blueprint_id dedupliziert. Neueste (updated_at, node_id) beibehalten.",
    "blueprint":            "Blueprint-Lookup abgeschlossen. Stale Nodes via SQLite gefiltert.",
    "sqlite":               "SQLite-Cross-Check: fail-closed aktiv.",
    # Memory roundtrip
    "roundtrip store":      "Kontext gespeichert unter key: roundtrip-test.",
    "roundtrip recall":     "Kontext aus vorheriger Anfrage gefunden: roundtrip-test.",
    "roundtrip":            "Roundtrip-Kontext verfügbar.",
}

# Sort by key length descending so longer (more specific) keys match first
_SORTED_LIBRARY = sorted(_MOCK_LIBRARY.items(), key=lambda kv: len(kv[0]), reverse=True)


def _mock_response(prompt: str) -> str:
    """Return a deterministic mock response for the given prompt."""
    prompt_lower = prompt.lower()
    for keyword, response in _SORTED_LIBRARY:
        if keyword in prompt_lower:
            return response
    # Hash-based deterministic fallback
    h = hashlib.md5(prompt.encode("utf-8", errors="replace")).hexdigest()[:8]
    return f"Mock-Antwort [{h}]: Kein Keyword-Match für '{prompt[:60]}'"


def _mock_markers(prompt: str, mode: str) -> Dict:
    return {
        "mode": mode,
        "context_sources": ["mock_memory"],
        "context_chars_final": len(prompt) * 2,
        "retrieval_count": 1,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Provider
# ─────────────────────────────────────────────────────────────────────────────

class MockProvider:
    """
    Deterministic mock provider.
    Same prompt always yields the same response (temperature=0 equivalent).
    No external calls, no I/O, no random state.
    """
    name = "mock"

    def run_sync(
        self, prompt: str, conversation_id: str = "test", extra: Dict = None
    ) -> Dict:
        text = _mock_response(prompt)
        return {
            "text": text,
            "markers": _mock_markers(prompt, "sync"),
            "error": None,
        }

    def run_stream(
        self, prompt: str, conversation_id: str = "test", extra: Dict = None
    ) -> Iterable[Dict]:
        """
        Simulate streaming: all words are emitted as 'chunk' events (done=False),
        followed by a single empty 'done' event carrying the final markers.
        This matches real Ollama streaming where the done=True chunk has no text.
        """
        text = _mock_response(prompt)
        words = text.split()
        for i, word in enumerate(words):
            chunk_text = (" " + word) if i > 0 else word
            yield {
                "text": chunk_text,
                "done": False,
                "markers": {},
                "error": None,
            }
        # Final done event — empty text, carries markers
        yield {
            "text": "",
            "done": True,
            "markers": _mock_markers(prompt, "stream"),
            "error": None,
        }
