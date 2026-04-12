from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.orchestrator_modules.task_loop import stream_task_loop_events
from core.orchestrator_stream_flow_utils import process_stream_with_events
from core.task_loop.store import get_task_loop_store


@pytest.mark.asyncio
async def test_stream_task_loop_events_yield_incremental_updates_and_content():
    conversation_id = "conv-task-loop-stream-events"
    get_task_loop_store().clear(conversation_id)

    orch = MagicMock()
    orch._save_workspace_entry = MagicMock(
        side_effect=lambda **kwargs: {
            "type": "workspace_update",
            "entry_id": kwargs["entry_type"],
            "content": kwargs["content"],
        }
    )
    orch.thinking = MagicMock()
    orch.thinking.analyze = AsyncMock(return_value={})

    request = SimpleNamespace(
        model="test-model",
        conversation_id=conversation_id,
        raw_request={},
    )

    out = []
    async for item in stream_task_loop_events(
        orch,
        request,
        "Task-Loop: Bitte schrittweise einen Plan machen",
        conversation_id,
        log_info_fn=lambda _msg: None,
        log_warn_fn=lambda _msg: None,
        tone_signal=None,
    ):
        out.append(item)

    content_events = [item for item in out if item[2].get("type") == "content"]
    update_events = [item for item in out if item[2].get("type") == "task_loop_update"]

    assert len(content_events) >= 2
    assert content_events[0][0].startswith("Task-Loop gestartet.\n\nPlan:\n")
    assert content_events[1][0].startswith("\nZwischenstand:\n")
    assert len(update_events) >= 2
    assert update_events[0][2]["is_final"] is False
    assert update_events[-1][2]["is_final"] is True
    assert out[-1][1] is True
    assert out[-1][2]["done_reason"] == "task_loop_completed"


@pytest.mark.asyncio
async def test_process_stream_with_events_uses_incremental_task_loop_streaming():
    conversation_id = "conv-task-loop-stream-process"
    get_task_loop_store().clear(conversation_id)

    orch = MagicMock()
    orch.lifecycle = MagicMock()
    orch._requested_response_mode = MagicMock(return_value=None)
    orch._classify_tone_signal = AsyncMock(return_value=None)
    orch._save_workspace_entry = MagicMock(
        side_effect=lambda **kwargs: {
            "type": "workspace_update",
            "entry_id": kwargs["entry_type"],
            "content": kwargs["content"],
        }
    )
    orch._post_task_processing = MagicMock()
    orch.thinking = MagicMock()
    orch.thinking.analyze = AsyncMock(return_value={})
    orch.control = MagicMock()
    orch.output = MagicMock()

    request = SimpleNamespace(
        model="test-model",
        conversation_id=conversation_id,
        messages=[],
        raw_request={},
        source_adapter="test",
        get_last_user_message=lambda: "Task-Loop: Bitte schrittweise einen Plan machen",
    )

    out = []
    async for item in process_stream_with_events(
        orch,
        request,
        intent_system_available=False,
        enable_chunking=False,
        chunking_threshold=100000,
        get_master_settings_fn=lambda: {},
        thinking_plan_cache=MagicMock(),
        sequential_result_cache=MagicMock(),
        soften_control_deny_fn=MagicMock(),
        skill_creation_intent_cls=None,
        intent_origin_cls=None,
        get_intent_store_fn=lambda: None,
        log_info_fn=lambda _msg: None,
        log_warn_fn=lambda _msg: None,
        log_error_fn=lambda _msg: None,
        log_debug_fn=lambda _msg: None,
        log_warning_fn=lambda _msg: None,
    ):
        out.append(item)

    content_events = [item for item in out if item[2].get("type") == "content"]
    assert len(content_events) >= 2
    assert content_events[0][0].startswith("Task-Loop gestartet.\n\nPlan:\n")
    assert content_events[1][0].startswith("\nZwischenstand:\n")
    assert out[-1][1] is True
    assert out[-1][2]["done_reason"] == "task_loop_completed"
    assert orch.control.verify.call_count >= 1
    assert orch.output.generate_stream.call_count >= 1
