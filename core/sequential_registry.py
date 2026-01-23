# core/sequential_registry.py
"""
Sequential Task Registry

Global In-Memory Storage für Sequential Thinking Tasks.
Speichert Results und Status für Live-Monitoring.
"""

import uuid
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from utils.logger import log_info, log_debug, log_warn


class SequentialTaskRegistry:
    """
    Global Registry für Sequential Thinking Tasks.
    
    Speichert:
    - task_id → task_data
    - Auto-Cleanup nach 1 Stunde
    - Thread-safe (single-process, async-safe)
    """
    
    def __init__(self):
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._cleanup_threshold = 3600  # 1 hour in seconds
    
    def create_task(self, user_message: str, complexity: int = 5) -> str:
        """
        Erstellt neue Task und gibt Task-ID zurück.
        
        Args:
            user_message: Original User Query
            complexity: Sequential Complexity (1-10)
        
        Returns:
            task_id: UUID string
        """
        task_id = str(uuid.uuid4())
        
        self._tasks[task_id] = {
            "task_id": task_id,
            "user_message": user_message,
            "complexity": complexity,
            "status": "pending",  # pending, running, completed, failed
            "steps": [],
            "result": None,
            "error": None,
            "created_at": time.time(),
            "started_at": None,
            "completed_at": None,
        }
        
        log_info(f"[SequentialRegistry] Created task {task_id[:8]}... (complexity={complexity})")
        return task_id
    
    def update_status(self, task_id: str, status: str) -> bool:
        """Updates task status"""
        if task_id not in self._tasks:
            log_warn(f"[SequentialRegistry] Task {task_id[:8]} not found")
            return False
        
        self._tasks[task_id]["status"] = status
        
        if status == "running" and self._tasks[task_id]["started_at"] is None:
            self._tasks[task_id]["started_at"] = time.time()
        
        if status in ["completed", "failed"]:
            self._tasks[task_id]["completed_at"] = time.time()
        
        log_debug(f"[SequentialRegistry] Task {task_id[:8]} → {status}")
        return True
    
    def add_step(self, task_id: str, step: Dict[str, Any]) -> bool:
        """Fügt Step hinzu (für Live-Monitoring)"""
        if task_id not in self._tasks:
            return False
        
        self._tasks[task_id]["steps"].append({
            **step,
            "timestamp": time.time()
        })
        
        return True
    
    def set_result(self, task_id: str, result: Dict[str, Any]) -> bool:
        """Speichert Sequential Thinking Result"""
        if task_id not in self._tasks:
            return False
        
        self._tasks[task_id]["result"] = result
        self._tasks[task_id]["status"] = "completed"
        self._tasks[task_id]["completed_at"] = time.time()
        
        # Extract steps from result if present
        if "steps" in result and isinstance(result["steps"], list):
            self._tasks[task_id]["steps"] = result["steps"]
        
        log_info(f"[SequentialRegistry] Task {task_id[:8]} completed with {len(self._tasks[task_id]['steps'])} steps")
        return True
    
    def set_error(self, task_id: str, error: str) -> bool:
        """Markiert Task als failed"""
        if task_id not in self._tasks:
            return False
        
        self._tasks[task_id]["error"] = error
        self._tasks[task_id]["status"] = "failed"
        self._tasks[task_id]["completed_at"] = time.time()
        
        log_warn(f"[SequentialRegistry] Task {task_id[:8]} failed: {error}")
        return True
    
    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Holt Task-Daten"""
        return self._tasks.get(task_id)
    
    def get_status(self, task_id: str) -> Optional[str]:
        """Holt nur Status"""
        task = self._tasks.get(task_id)
        return task["status"] if task else None
    
    def get_steps(self, task_id: str) -> List[Dict[str, Any]]:
        """Holt Steps für Live-Monitoring"""
        task = self._tasks.get(task_id)
        return task["steps"] if task else []
    
    def cleanup_old_tasks(self) -> int:
        """
        Löscht Tasks älter als 1 Stunde.
        
        Returns:
            Anzahl gelöschter Tasks
        """
        now = time.time()
        threshold = now - self._cleanup_threshold
        
        old_tasks = [
            task_id 
            for task_id, task in self._tasks.items()
            if task["created_at"] < threshold
        ]
        
        for task_id in old_tasks:
            del self._tasks[task_id]
        
        if old_tasks:
            log_info(f"[SequentialRegistry] Cleaned up {len(old_tasks)} old tasks")
        
        return len(old_tasks)
    
    def get_all_tasks(self) -> List[Dict[str, Any]]:
        """Returns all tasks (für Debug)"""
        return list(self._tasks.values())


# Global Singleton Instance
_registry = SequentialTaskRegistry()


def get_registry() -> SequentialTaskRegistry:
    """Returns global registry instance"""
    return _registry
