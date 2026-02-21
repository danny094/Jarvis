"""
tests/harness/providers/live_provider.py — Commit B
=====================================================
LiveProvider: calls an actual Ollama-compatible HTTP backend.

OPT-IN ONLY — requires:
    AI_TEST_LIVE=1            (guard flag)
    AI_TEST_BASE_URL=http://… (e.g. http://localhost:11434)
    AI_TEST_MODEL=qwen2.5:14b (optional, default: qwen2.5:14b)
    AI_TEST_API_KEY=…         (optional bearer token)

Without these vars the test is skipped via pytest.skip().

Determinism:
    temperature=0, seed=42 on every call.

Retry:
    Max 2 retries on transient HTTP / connection errors (1s backoff).
"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, Iterable

# pytest available in test context; imported lazily to avoid hard dep at module load
_PYTEST_SKIP = None


def _skip(reason: str) -> None:
    global _PYTEST_SKIP
    if _PYTEST_SKIP is None:
        try:
            import pytest
            _PYTEST_SKIP = pytest.skip
        except ImportError:
            raise RuntimeError(reason)
    _PYTEST_SKIP(reason)


_REQUIRED_ENV = ("AI_TEST_BASE_URL",)

MAX_RETRIES = 2
TIMEOUT_S = 60


def _check_live_env() -> None:
    """Skip the test if live ENV is not fully configured."""
    if os.environ.get("AI_TEST_LIVE") != "1":
        _skip("Live provider requires AI_TEST_LIVE=1")
    missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        _skip(f"Live provider requires ENV: {', '.join(missing)}")


class LiveProvider:
    """
    Live provider: calls Ollama /api/chat endpoint.
    Skips automatically if AI_TEST_LIVE is not set.
    """
    name = "live"

    def __init__(self) -> None:
        _check_live_env()
        self.base_url = os.environ["AI_TEST_BASE_URL"].rstrip("/")
        self.model = os.environ.get("AI_TEST_MODEL", "qwen2.5:14b")
        self.api_key = os.environ.get("AI_TEST_API_KEY", "")

    def _headers(self) -> Dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _payload(self, prompt: str, stream: bool) -> Dict:
        return {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": stream,
            "options": {"temperature": 0, "seed": 42},
        }

    def run_sync(
        self, prompt: str, conversation_id: str = "test", extra: Dict = None
    ) -> Dict:
        import httpx
        url = f"{self.base_url}/api/chat"
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = httpx.post(
                    url,
                    json=self._payload(prompt, stream=False),
                    headers=self._headers(),
                    timeout=TIMEOUT_S,
                )
                resp.raise_for_status()
                data = resp.json()
                text = data.get("message", {}).get("content", "")
                return {"text": text, "markers": {"mode": "sync"}, "error": None}
            except Exception as exc:
                if attempt == MAX_RETRIES:
                    return {"text": "", "markers": {}, "error": str(exc)}
                time.sleep(1.0)

    def run_stream(
        self, prompt: str, conversation_id: str = "test", extra: Dict = None
    ) -> Iterable[Dict]:
        import httpx
        url = f"{self.base_url}/api/chat"
        markers_sent = False
        try:
            with httpx.stream(
                "POST",
                url,
                json=self._payload(prompt, stream=True),
                headers=self._headers(),
                timeout=TIMEOUT_S,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    text = chunk.get("message", {}).get("content", "")
                    done = chunk.get("done", False)
                    m: Dict = {}
                    if done and not markers_sent:
                        m = {"mode": "stream"}
                        markers_sent = True
                    yield {"text": text, "done": done, "markers": m, "error": None}
        except Exception as exc:
            yield {"text": "", "done": True, "markers": {}, "error": str(exc)}
