"""
Fast Lane Executor - Native tool execution without MCP overhead
"""
from typing import Dict, Any
import time
from .definitions import (
    HomeReadTool, HomeWriteTool, HomeListTool,
    MemorySaveTool, MemorySearchTool,
    WorkspaceEventSaveTool, WorkspaceEventListTool,
)
from .security import SecurePathValidator
from .resource_lock import ResourceLockManager
from core.tools.tool_result import ToolResult
from utils.logger import log_info, log_error, log_warning
import threading


class FastLaneExecutor:
    """
    Executes Fast Lane tools natively (50ms instead of 3.5s!)
    
    Features:
    - Native Python execution (no containers)
    - Security validation (Symlink protection)
    - Resource-based locking (no race conditions)
    - Returns ToolResult for consistent Output Layer handling
    """
    
    def __init__(self):
        self.path_validator = SecurePathValidator()
        self.lock_manager = ResourceLockManager()
        
        # Map tool names to Pydantic models
        self.tools = {
            "home_read": HomeReadTool,
            "home_write": HomeWriteTool,
            "home_list": HomeListTool,
            "memory_save": MemorySaveTool,
            "memory_search": MemorySearchTool,
            "workspace_event_save": WorkspaceEventSaveTool,
            "workspace_event_list": WorkspaceEventListTool,
        }
        
        log_info("[FastLaneExecutor] Initialized with tools: " + ", ".join(self.tools.keys()))
    
    def execute(self, tool_name: str, args: Dict[str, Any]) -> ToolResult:
        """
        Execute tool natively with full security checks
        
        Args:
            tool_name: Name of the tool (e.g., "home_read")
            args: Tool arguments (e.g., {"path": "notes/test.md"})
        
        Returns:
            ToolResult with execution metadata for streaming
        """
        start_time = time.time()
        
        if tool_name not in self.tools:
            error_msg = f"Fast Lane tool not found: {tool_name}. Available: {list(self.tools.keys())}"
            log_error(f"[FastLane] {error_msg}")
            return ToolResult.from_error(
                error=error_msg,
                tool_name=tool_name,
                execution_mode="fast_lane"
            )
        
        log_info(f"[FastLane] Executing {tool_name} with args: {args}")
        
        # ════════════════════════════════════════════════════
        # SECURITY: Path Validation (Symlink Protection!)
        # ════════════════════════════════════════════════════
        if "path" in args:
            is_valid, resolved, error = self.path_validator.validate(args["path"])
            if not is_valid:
                log_error(f"[FastLane] Security check failed: {error}")
                return ToolResult.from_error(
                    error=f"Security Error: {error}",
                    tool_name=tool_name,
                    execution_mode="fast_lane"
                )
            
            # Use RESOLVED path (follows symlinks and checks containment!)
            args["path"] = resolved
            log_info(f"[FastLane] Path validated: {args['path']}")
        
        # ════════════════════════════════════════════════════
        # RESOURCE LOCKING: Prevent race conditions
        # ════════════════════════════════════════════════════
        resource_id = self._get_resource_id(tool_name, args)
        
        # Execute with sync lock (avoids asyncio.run() in running event loop)
        try:
            tool_class = self.tools[tool_name]
            
            with self.lock_manager.get_sync_lock(resource_id):
                # Instantiate Pydantic model (validates args!)
                tool_instance = tool_class(**args)
                
                # Execute the tool
                content = tool_instance.execute()
            
            # Calculate latency
            latency_ms = (time.time() - start_time) * 1000
            
            log_info(f"[FastLane] {tool_name} completed in {latency_ms:.1f}ms")
            
            # Return ToolResult for Output Layer
            return ToolResult.from_fast_lane(
                content=content,
                tool_name=tool_name,
                latency_ms=latency_ms,
                metadata={
                    "resource_id": resource_id,
                    "args": args
                }
            )
            
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            error_msg = f"Fast Lane execution failed: {str(e)}"
            log_error(f"[FastLane] {error_msg} (after {latency_ms:.1f}ms)")
            
            return ToolResult.from_error(
                error=error_msg,
                tool_name=tool_name,
                execution_mode="fast_lane"
            )
    
    def _get_resource_id(self, tool_name: str, args: Dict[str, Any]) -> str:
        """
        Get resource ID for locking
        
        File operations lock the specific file
        Other operations use global lock
        """
        if tool_name in ["home_read", "home_write"]:
            # Lock specific file
            path = args.get("path", "unknown")
            return f"file:{path}"
        
        elif tool_name in ["home_list"]:
            # Lock directory
            path = args.get("path", "unknown")
            return f"dir:{path}"
        
        elif tool_name in ["memory_save", "memory_search"]:
            # Lock based on conversation_id
            conv_id = args.get("conversation_id", "unknown")
            return f"memory:{conv_id}"
        
        elif tool_name in ["workspace_event_save", "workspace_event_list"]:
            # Lock based on conversation_id
            conv_id = args.get("conversation_id", "unknown")
            return f"workspace_event:{conv_id}"
        
        else:
            # Global lock for unknown tools
            return f"global:{tool_name}"


# Singleton instance
_executor = None

def get_fast_lane_executor() -> FastLaneExecutor:
    """Get singleton FastLaneExecutor instance"""
    global _executor
    if _executor is None:
        _executor = FastLaneExecutor()
    return _executor
