from __future__ import annotations

import threading
from typing import Dict, Optional

from core.task_loop.contracts import TaskLoopSnapshot, TaskLoopState


class TaskLoopStore:
    """Small in-process store for active chat task-loop snapshots."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_conversation: Dict[str, TaskLoopSnapshot] = {}

    def get(self, conversation_id: str) -> Optional[TaskLoopSnapshot]:
        key = str(conversation_id or "").strip()
        if not key:
            return None
        with self._lock:
            return self._by_conversation.get(key)

    def put(self, snapshot: TaskLoopSnapshot) -> TaskLoopSnapshot:
        with self._lock:
            self._by_conversation[snapshot.conversation_id] = snapshot
        return snapshot

    def clear(self, conversation_id: str) -> None:
        key = str(conversation_id or "").strip()
        if not key:
            return
        with self._lock:
            self._by_conversation.pop(key, None)

    def get_active(self, conversation_id: str) -> Optional[TaskLoopSnapshot]:
        snapshot = self.get(conversation_id)
        if snapshot is None:
            return None
        if snapshot.state in {TaskLoopState.COMPLETED, TaskLoopState.CANCELLED}:
            return None
        return snapshot


_TASK_LOOP_STORE = TaskLoopStore()


def get_task_loop_store() -> TaskLoopStore:
    return _TASK_LOOP_STORE
