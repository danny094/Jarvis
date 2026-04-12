from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.task_loop.pipeline_adapter import build_task_loop_planning_context


@pytest.mark.asyncio
async def test_build_task_loop_planning_context_calls_thinking_layer():
    analyze = AsyncMock(return_value={"intent": "Loop pruefen"})
    orch = SimpleNamespace(thinking=SimpleNamespace(analyze=analyze))

    out = await build_task_loop_planning_context(
        orch,
        "Bitte schrittweise arbeiten",
        tone_signal={"tone": "neutral"},
    )

    assert out == {"intent": "Loop pruefen"}
    analyze.assert_awaited_once()


@pytest.mark.asyncio
async def test_build_task_loop_planning_context_fails_closed_to_empty_plan():
    logs = []
    analyze = AsyncMock(side_effect=RuntimeError("model unavailable"))
    orch = SimpleNamespace(thinking=SimpleNamespace(analyze=analyze))

    out = await build_task_loop_planning_context(
        orch,
        "Bitte schrittweise arbeiten",
        log_warn_fn=logs.append,
    )

    assert out == {}
    assert logs
