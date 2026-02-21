"""
tests/harness/ai_client.py — Commit B
=======================================
AI Provider interface and factory.

Usage:
    from tests.harness.ai_client import get_provider
    provider = get_provider()          # auto: mock by default, live with AI_TEST_LIVE=1
    provider = get_provider("mock")    # explicit mock
    provider = get_provider("live")    # explicit live (raises skip if unconfigured)
"""
from __future__ import annotations

import os
from typing import Dict, Iterable, runtime_checkable

try:
    from typing import Protocol
except ImportError:
    from typing_extensions import Protocol  # type: ignore


# ─────────────────────────────────────────────────────────────────────────────
# Provider protocol
# ─────────────────────────────────────────────────────────────────────────────

@runtime_checkable
class AIProvider(Protocol):
    """
    Minimal provider protocol for the test harness.

    Both run_sync and run_stream must be deterministic:
      - temperature=0 / seed=42 for live
      - hash-based lookup for mock
    """
    name: str

    def run_sync(self, prompt: str, conversation_id: str, extra: Dict) -> Dict:
        """
        Execute a single synchronous AI call.
        Returns dict with keys:
            text     (str)       — response text
            markers  (dict)      — context markers
            error    (str|None)  — error message or None
        """
        ...

    def run_stream(self, prompt: str, conversation_id: str, extra: Dict) -> Iterable[Dict]:
        """
        Execute a streaming AI call, yielding chunk dicts.
        Each dict has keys:
            text     (str)   — chunk text
            done     (bool)  — True on final chunk
            markers  (dict)  — markers (usually only on done chunk)
            error    (str|None)
        """
        ...


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────

def get_provider(name: str = "auto") -> AIProvider:
    """
    Return the appropriate provider instance.

    name="auto"   → uses AI_TEST_LIVE=1 env for live, else mock
    name="mock"   → always MockProvider
    name="live"   → LiveProvider (pytest.skip if env not configured)
    """
    if name == "auto":
        name = "live" if os.environ.get("AI_TEST_LIVE") == "1" else "mock"

    if name == "mock":
        from tests.harness.providers.mock_provider import MockProvider
        return MockProvider()

    if name == "live":
        from tests.harness.providers.live_provider import LiveProvider
        return LiveProvider()

    raise ValueError(f"Unknown provider name {name!r}. Use 'mock', 'live', or 'auto'.")
