import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_orchestrator():
    from core.orchestrator import PipelineOrchestrator

    with patch("core.orchestrator.ThinkingLayer", return_value=MagicMock()), \
         patch("core.orchestrator.ControlLayer", return_value=MagicMock()), \
         patch("core.orchestrator.OutputLayer", return_value=MagicMock()), \
         patch("core.orchestrator.ToolSelector", return_value=MagicMock()), \
         patch("core.orchestrator.ContextManager", return_value=MagicMock()), \
         patch("core.orchestrator.get_hub", return_value=MagicMock()), \
         patch("core.orchestrator.get_registry", return_value=MagicMock()), \
         patch("core.orchestrator.get_master_orchestrator", return_value=MagicMock()):
        return PipelineOrchestrator()


def _prepare_sync_happy_path(orch):
    orch._classify_tone_signal = AsyncMock(return_value={
        "dialogue_act": "request",
        "response_tone": "neutral",
        "response_length_hint": "medium",
        "tone_confidence": 0.9,
    })
    orch.tool_selector.select_tools = AsyncMock(return_value=[])
    orch.thinking.analyze = AsyncMock(return_value={
        "intent": "analysis",
        "needs_memory": False,
        "memory_keys": [],
        "hallucination_risk": "medium",
        "needs_sequential_thinking": False,
        "suggested_tools": [],
    })
    orch._route_skill_request = MagicMock(return_value=None)
    orch._route_blueprint_request = MagicMock(return_value=None)
    orch.build_effective_context = MagicMock(return_value=("", {
        "memory_used": False,
        "small_model_mode": False,
        "context_chars": 0,
        "retrieval_count": 0,
        "context_sources": [],
        "context_chars_final": 0,
    }))
    orch._execute_control_layer = AsyncMock(return_value=(
        {"approved": True, "corrections": {}},
        {"suggested_tools": []},
    ))
    orch._collect_control_tool_decisions = AsyncMock(return_value={})
    orch._resolve_execution_suggested_tools = MagicMock(return_value=[])
    orch._execute_output_layer = AsyncMock(return_value="ok")
    orch._save_memory = MagicMock()


@pytest.mark.asyncio
async def test_sync_deep_mode_runs_context_compression_sync():
    from core.models import CoreChatRequest, Message, MessageRole

    orch = _make_orchestrator()
    _prepare_sync_happy_path(orch)

    compressor = MagicMock()
    compressor.check_and_compress = AsyncMock()
    settings_map = {
        "CONTEXT_COMPRESSION_ENABLED": True,
        "COMPRESSION_THRESHOLD": 100000,
        "CONTEXT_COMPRESSION_MODE": "sync",
    }

    with patch("core.orchestrator.INTENT_SYSTEM_AVAILABLE", False), \
         patch("core.context_compressor.estimate_protocol_tokens", return_value=140000), \
         patch("core.context_compressor.get_compressor", return_value=compressor), \
         patch("utils.settings.settings.get", side_effect=lambda key, default=None: settings_map.get(key, default)):
        request = CoreChatRequest(
            model="test-model",
            messages=[Message(role=MessageRole.USER, content="/deep analysiere die gpu queues")],
            conversation_id="conv-sync-compress",
            source_adapter="test",
        )
        response = await orch.process(request)

    assert response.done is True
    compressor.check_and_compress.assert_awaited_once()
    assert orch._execute_control_layer.await_args.kwargs.get("response_mode") == "deep"


@pytest.mark.asyncio
async def test_sync_deep_mode_runs_context_compression_async():
    from core.models import CoreChatRequest, Message, MessageRole

    orch = _make_orchestrator()
    _prepare_sync_happy_path(orch)

    compressor = MagicMock()
    compressor.check_and_compress = AsyncMock()
    settings_map = {
        "CONTEXT_COMPRESSION_ENABLED": True,
        "COMPRESSION_THRESHOLD": 100000,
        "CONTEXT_COMPRESSION_MODE": "async",
    }
    captured = {"scheduled": False}

    def _schedule(coro):
        captured["scheduled"] = True
        assert asyncio.iscoroutine(coro)
        coro.close()
        return MagicMock()

    with patch("core.orchestrator.INTENT_SYSTEM_AVAILABLE", False), \
         patch("core.context_compressor.estimate_protocol_tokens", return_value=140000), \
         patch("core.context_compressor.get_compressor", return_value=compressor), \
         patch("core.orchestrator.asyncio.create_task", side_effect=_schedule), \
         patch("utils.settings.settings.get", side_effect=lambda key, default=None: settings_map.get(key, default)):
        request = CoreChatRequest(
            model="test-model",
            messages=[Message(role=MessageRole.USER, content="/deep analysiere die gpu queues")],
            conversation_id="conv-sync-compress-async",
            source_adapter="test",
        )
        response = await orch.process(request)

    assert response.done is True
    assert captured["scheduled"] is True
    compressor.check_and_compress.assert_called_once()
    assert orch._execute_control_layer.await_args.kwargs.get("response_mode") == "deep"
