# core/sequential_cache.py
"""
Sequential Thinking Results Cache

In-Memory Cache für Sequential Thinking Tasks:
- Task ID Generation (UUID)
- Result Storage
- Status Tracking
"""

from typing import Dict, Any, Optional
from datetime import datetime
import uuid
from utils.logger import log_info, log_debug


class SequentialCache:
    """
    In-Memory Cache für Sequential Thinking Results.
    
    Thread-safe (für Single-Process Usage).
    """
    
    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        log_info("[SequentialCache] Initialized")
    
    def create_task(self, user_query: str, complexity: int) -> str:
        """
        Erstellt eine neue Task und gibt die Task ID zurück.
        
        Args:
            user_query: Die User-Anfrage
            complexity: Sequential Complexity (1-10)
            
        Returns:
            task_id (UUID string)
        """
        task_id = str(uuid.uuid4())
        
        self._cache[task_id] = {
            "task_id": task_id,
            "query": user_query,
            "complexity": complexity,
            "status": "pending",  # pending, running, completed, failed
            "steps": [],
            "result": None,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "error": None
        }
        
        log_info(f"[SequentialCache] Created task {task_id} (complexity={complexity})")
        return task_id
    
    def update_status(self, task_id: str, status: str):
        """Updates task status."""
        if task_id in self._cache:
            self._cache[task_id]["status"] = status
            self._cache[task_id]["updated_at"] = datetime.utcnow().isoformat()
            log_debug(f"[SequentialCache] Task {task_id} status: {status}")
    
    def set_result(self, task_id: str, result: Dict[str, Any]):
        """
        Speichert das Sequential Thinking Result.
        
        Args:
            task_id: Task ID
            result: Sequential Thinking MCP Result
        """
        if task_id not in self._cache:
            log_debug(f"[SequentialCache] Task {task_id} not found, cannot set result")
            return
        
        # Extract steps from result
        steps = []
        if isinstance(result, dict):
            # Check structuredContent first (MCP response format)
            structured = result.get("structuredContent", {})
            if "steps" in structured:
                steps = structured["steps"]
            # Fallback: direct steps field
            elif "steps" in result:
                steps = result["steps"]
        
        self._cache[task_id]["steps"] = steps
        self._cache[task_id]["result"] = result
        self._cache[task_id]["status"] = "completed"
        self._cache[task_id]["updated_at"] = datetime.utcnow().isoformat()
        
        log_info(f"[SequentialCache] Task {task_id} completed with {len(steps)} steps")
    
    def set_error(self, task_id: str, error: str):
        """Markiert Task als failed mit Fehlermeldung."""
        if task_id in self._cache:
            self._cache[task_id]["status"] = "failed"
            self._cache[task_id]["error"] = error
            self._cache[task_id]["updated_at"] = datetime.utcnow().isoformat()
            log_info(f"[SequentialCache] Task {task_id} failed: {error}")
    
    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Holt komplette Task-Info."""
        return self._cache.get(task_id)
    
    def get_status(self, task_id: str) -> Optional[str]:
        """Holt nur den Status."""
        task = self._cache.get(task_id)
        return task["status"] if task else None
    
    def get_steps(self, task_id: str) -> Optional[list]:
        """Holt nur die Steps."""
        task = self._cache.get(task_id)
        return task["steps"] if task else None
    
    def cleanup_old_tasks(self, max_age_hours: int = 24):
        """
        Löscht alte Tasks (older than max_age_hours).
        
        TODO: Implementieren wenn nötig.
        """
        pass


# Global Singleton Instance
_sequential_cache = None

def get_sequential_cache() -> SequentialCache:
    """Returns the global SequentialCache singleton."""
    global _sequential_cache
    if _sequential_cache is None:
        _sequential_cache = SequentialCache()
    return _sequential_cache
