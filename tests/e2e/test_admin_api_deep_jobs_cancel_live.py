"""
tests/e2e/test_admin_api_deep_jobs_cancel_live.py
=================================================
Live behavior check for deep-job cancel semantics.

Opt-in:
  AI_TEST_LIVE=1

Config:
  AI_TEST_TRION_URL or AI_TEST_BASE_URL or default http://127.0.0.1:8200
  AI_TEST_MODEL optional, default ministral-3:3b
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any, Dict

import httpx
import pytest


def _base_url() -> str:
    raw = (os.getenv("AI_TEST_TRION_URL") or os.getenv("AI_TEST_BASE_URL") or "http://127.0.0.1:8200").rstrip("/")
    if raw.startswith("http://localhost:"):
        return raw.replace("http://localhost:", "http://127.0.0.1:", 1)
    if raw == "http://localhost":
        return "http://127.0.0.1"
    return raw


def _is_live_enabled() -> bool:
    return str(os.getenv("AI_TEST_LIVE", "")).strip().lower() in {"1", "true", "yes", "on"}


@pytest.mark.e2e
def test_deep_job_cancel_transitions_to_cancelled_live():
    if not _is_live_enabled():
        pytest.skip("Set AI_TEST_LIVE=1 to run live deep-job cancel behavior test.")

    base_url = _base_url()
    model = os.getenv("AI_TEST_MODEL", "ministral-3:3b")
    conv_id = f"deep-cancel-{uuid.uuid4().hex[:10]}"

    payload: Dict[str, Any] = {
        "model": model,
        "stream": False,
        "response_mode": "deep",
        "conversation_id": conv_id,
        "messages": [
            {
                "role": "user",
                "content": "Please think for a while and produce a long analysis with many bullet points.",
            }
        ],
    }

    timeout_s = float(os.getenv("AI_TEST_TIMEOUT_S", "20"))
    with httpx.Client(timeout=timeout_s) as client:
        submit = client.post(f"{base_url}/api/chat/deep-jobs", json=payload)
        submit.raise_for_status()
        submit_data = submit.json()
        job_id = str(submit_data.get("job_id") or "")
        assert job_id, f"missing job_id in submit response: {submit_data}"

        cancel = client.post(f"{base_url}/api/chat/deep-jobs/{job_id}/cancel")
        cancel.raise_for_status()
        cancel_data = cancel.json()
        assert cancel_data.get("status") in {"cancel_requested", "cancelled"}, cancel_data

        final_status = None
        deadline = time.time() + 20.0
        while time.time() < deadline:
            status = client.get(f"{base_url}/api/chat/deep-jobs/{job_id}")
            status.raise_for_status()
            status_data = status.json()
            final_status = str(status_data.get("status") or "").lower()
            if final_status == "cancelled":
                assert status_data.get("error_code") == "cancelled"
                return
            time.sleep(0.25)

    raise AssertionError(f"deep job did not reach cancelled in time (last_status={final_status})")
