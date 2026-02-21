import asyncio
import threading
from contextlib import contextmanager
from typing import Dict, Any, Callable
from collections import defaultdict

class ResourceLockManager:
    """
    Resource-Based Locking System.
    
    Provides async locks for specific resources (files, containers, etc.) to allow
    parallel execution of non-conflicting operations while ensuring safety for
    conflicting ones.
    """
    
    def __init__(self):
        # Dictionary mapping resource IDs to asyncio Locks
        self.locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        # Track active operations for debugging/monitoring
        self.active_operations: Dict[str, str] = {}
        # Sync locks for use in running event loops
        self._sync_locks: Dict[str, threading.Lock] = defaultdict(threading.Lock)
        
    def get_resource_id(self, tool_name: str, tool_args: Dict[str, Any]) -> str:
        """
        Determines the unique resource ID for a given tool call.
        
        Args:
            tool_name: The name of the tool being called.
            tool_args: The arguments passed to the tool.
            
        Returns:
            A string identifier for the resource (e.g. 'file:/trion-home/notes.txt').
            Defaults to a global lock for unknown tools.
        """
        # File Operations
        if tool_name in ["home_read", "home_write", "home_list"]:
            path = tool_args.get("path", "")
            # Normalize path could happen here, or rely on caller to be consistent.
            # For locking, strict correctness matters less than collision avoidance.
            return f"file:{path}"
            
        # Container Operations
        elif tool_name in ["exec_in_container", "container_stats", "stop_container", "container_logs"]:
            container_id = tool_args.get("container_id", "")
            return f"container:{container_id}"
            
        # Memory Operations
        elif tool_name in ["memory_save", "memory_search", "recall_fact", "store_fact"]:
            # Lock by query or key to prevent race conditions on specific memory items
            key = tool_args.get("key") or tool_args.get("query", "")
            return f"memory:{key}"
            
        # Fallback: Global lock for unknown/unsafe operations
        return f"global:{tool_name}"
        
    @contextmanager
    def get_sync_lock(self, resource_id: str):
        """Sync context manager for locking resources (thread-safe)."""
        lock = self._sync_locks[resource_id]
        lock.acquire()
        try:
            yield lock
        finally:
            lock.release()

    async def execute_with_lock(
        self, 
        resource_id: str, 
        operation_fn: Callable[[], Any],
        operation_name: str = "unknown"
    ) -> Any:
        """
        Executes an async operation while holding the lock for the specified resource.
        
        Args:
            resource_id: The unique ID of the resource to lock.
            operation_fn: The async function to execute.
            operation_name: Name of the operation for tracking.
            
        Returns:
            The result of the operation_fn.
        """
        lock = self.locks[resource_id]
        
        async with lock:
            self.active_operations[resource_id] = operation_name
            try:
                return await operation_fn()
            finally:
                if resource_id in self.active_operations:
                    del self.active_operations[resource_id]
