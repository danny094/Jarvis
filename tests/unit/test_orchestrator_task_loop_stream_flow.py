from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.orchestrator_stream_flow_utils import process_stream_with_events
from core.task_loop.store import get_task_loop_store


@pytest.mark.asyncio
async def test_stream_path_task_loop_short_circuits_before_pipeline():
    conversation_id = "conv-stream-task-loop"
    get_task_loop_store().clear(conversation_id)

    orch = MagicMock()
    orch.lifecycle = MagicMock()
    orch._requested_response_mode = MagicMock(return_value=None)
    orch._classify_tone_signal = AsyncMock(return_value=None)
    orch._save_workspace_entry = MagicMock(
        side_effect=lambda **kwargs: {
            "type": "workspace_update",
            "entry_id": kwargs["entry_type"],
        }
    )
    orch._post_task_processing = MagicMock()
    orch.thinking = MagicMock()
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

    assert out[0][2]["type"] == "task_loop_update"
    assert any(item[2].get("type") == "workspace_update" for item in out)
    assert any(item[2].get("type") == "content" and "Task-Loop gestartet" in item[0] for item in out)
    assert out[-1][1] is True
    assert out[-1][2]["done_reason"] == "task_loop_completed"
    orch.thinking.analyze_stream.assert_not_called()
    assert orch.control.verify.call_count >= 1
    assert orch.output.generate_stream.call_count >= 1
    orch.lifecycle.finish_task.assert_called_once()
    orch._post_task_processing.assert_called_once()
