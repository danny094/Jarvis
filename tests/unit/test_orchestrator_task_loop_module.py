from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.orchestrator_modules.task_loop import (
    maybe_build_task_loop_stream_events,
    maybe_handle_task_loop_sync,
)
from core.task_loop.store import TaskLoopStore


@pytest.mark.asyncio
async def test_maybe_handle_task_loop_sync_returns_none_for_normal_turn(monkeypatch):
    store = TaskLoopStore()

    monkeypatch.setattr(
        "core.orchestrator_modules.task_loop.get_task_loop_store",
        lambda: store,
    )

    out = await maybe_handle_task_loop_sync(
        SimpleNamespace(
            _save_workspace_entry=lambda **_kwargs: None,
            thinking=SimpleNamespace(analyze=AsyncMock(return_value={"intent": "unused"})),
        ),
        SimpleNamespace(model="m", raw_request={}),
        "was ist 2+2?",
        "conv-loop",
        core_chat_response_cls=lambda **kwargs: kwargs,
        log_info_fn=lambda _msg: None,
    )

    assert out is None


@pytest.mark.asyncio
async def test_maybe_handle_task_loop_sync_builds_response_for_candidate(monkeypatch):
    store = TaskLoopStore()

    monkeypatch.setattr(
        "core.orchestrator_modules.task_loop.get_task_loop_store",
        lambda: store,
    )

    logs = []
    out = await maybe_handle_task_loop_sync(
        SimpleNamespace(
            _save_workspace_entry=lambda **_kwargs: None,
            thinking=SimpleNamespace(
                analyze=AsyncMock(
                    return_value={
                        "intent": "Multistep Loop pruefen",
                        "hallucination_risk": "low",
                        "suggested_tools": [],
                        "reasoning": "Chat-only Test",
                    }
                )
            ),
        ),
        SimpleNamespace(model="m", raw_request={}),
        "Task-Loop: Bitte schrittweise bearbeiten",
        "conv-loop",
        core_chat_response_cls=lambda **kwargs: kwargs,
        log_info_fn=logs.append,
    )

    assert out["done_reason"] == "task_loop_completed"
    assert out["conversation_id"] == "conv-loop"
    assert "Task-Loop gestartet" in out["content"]
    assert "Pruefziel festlegen: Multistep Loop pruefen" in out["content"]
    assert "Pruefziel: Multistep Loop pruefen" in out["content"]
    assert "konkreten Befund statt nur eine Statusfloskel" in out["content"]
    assert logs


@pytest.mark.asyncio
async def test_maybe_build_task_loop_stream_events_emits_workspace_content_and_done(monkeypatch):
    store = TaskLoopStore()

    monkeypatch.setattr(
        "core.orchestrator_modules.task_loop.get_task_loop_store",
        lambda: store,
    )

    workspace_calls = []

    def save_workspace_entry(**kwargs):
        workspace_calls.append(kwargs)
        return {"type": "workspace_update", "entry_id": f"evt-{len(workspace_calls)}"}

    events = await maybe_build_task_loop_stream_events(
        SimpleNamespace(
            _save_workspace_entry=save_workspace_entry,
            thinking=SimpleNamespace(
                analyze=AsyncMock(
                    return_value={
                        "intent": "Stream Loop pruefen",
                        "hallucination_risk": "low",
                        "suggested_tools": [],
                    }
                )
            ),
        ),
        SimpleNamespace(model="m", raw_request={}),
        "Task-Loop: Bitte schrittweise bearbeiten",
        "conv-loop-stream",
        log_info_fn=lambda _msg: None,
    )

    assert events is not None
    assert events[0][2]["type"] == "task_loop_update"
    assert any(item[2].get("type") == "workspace_update" for item in events)
    assert any(item[2].get("type") == "content" and "Task-Loop gestartet" in item[0] for item in events)
    assert events[-1][1] is True
    assert events[-1][2]["done_reason"] == "task_loop_completed"
    assert workspace_calls
