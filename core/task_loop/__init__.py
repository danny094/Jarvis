"""Chat-first task loop contracts and pure runtime helpers."""

from core.task_loop.contracts import (
    RiskLevel,
    StopReason,
    TaskLoopSnapshot,
    TaskLoopState,
    TaskLoopTransitionError,
    transition_task_loop,
)
from core.task_loop.events import (
    TASK_LOOP_EVENT_TYPES,
    TaskLoopEventType,
    build_task_loop_workspace_summary,
    make_task_loop_event,
    persist_task_loop_workspace_event,
)
from core.task_loop.guards import (
    StopDecision,
    detect_loop,
    evaluate_stop_conditions,
    fingerprint_action,
)
from core.task_loop.planner import (
    TaskLoopStep,
    build_task_loop_steps,
    clean_task_loop_objective,
    create_task_loop_snapshot_from_plan,
)
from core.task_loop.reflection import ReflectionAction, ReflectionDecision, reflect_after_chat_step
from core.task_loop.runner import (
    TaskLoopRunResult,
    TaskLoopStreamChunk,
    run_chat_auto_loop,
    stream_chat_auto_loop,
)
from core.task_loop.store import TaskLoopStore, get_task_loop_store

__all__ = [
    "RiskLevel",
    "ReflectionAction",
    "ReflectionDecision",
    "StopDecision",
    "StopReason",
    "TASK_LOOP_EVENT_TYPES",
    "TaskLoopEventType",
    "TaskLoopSnapshot",
    "TaskLoopState",
    "TaskLoopStep",
    "TaskLoopStore",
    "TaskLoopTransitionError",
    "TaskLoopRunResult",
    "TaskLoopStreamChunk",
    "build_task_loop_workspace_summary",
    "build_task_loop_steps",
    "clean_task_loop_objective",
    "create_task_loop_snapshot_from_plan",
    "detect_loop",
    "evaluate_stop_conditions",
    "fingerprint_action",
    "get_task_loop_store",
    "make_task_loop_event",
    "persist_task_loop_workspace_event",
    "reflect_after_chat_step",
    "run_chat_auto_loop",
    "stream_chat_auto_loop",
    "transition_task_loop",
]
