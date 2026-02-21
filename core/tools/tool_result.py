"""
Tool Result Data Classes - Unified result format for all tool executions
"""
from typing import Dict, Any, Optional, Literal
from dataclasses import dataclass
import time


@dataclass
class ToolResult:
    """
    Unified result format for both Fast Lane and MCP tools
    
    This ensures consistent handling in Output Layer for streaming,
    regardless of execution path.
    
    Attributes:
        content: The actual result content (string, dict, list, etc.)
        tool_name: Name of the tool that was executed
        execution_mode: "fast_lane" or "mcp" 
        latency_ms: Execution time in milliseconds
        success: Whether execution succeeded
        error: Error message if failed
        metadata: Additional execution metadata
    """
    content: Any
    tool_name: str
    execution_mode: Literal["fast_lane", "mcp"] = "mcp"
    latency_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        """Initialize metadata if not provided"""
        if self.metadata is None:
            self.metadata = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "content": self.content,
            "tool_name": self.tool_name,
            "execution_mode": self.execution_mode,
            "latency_ms": self.latency_ms,
            "success": self.success,
            "error": self.error,
            "metadata": self.metadata
        }
    
    def is_fast_lane(self) -> bool:
        """Check if this was a fast lane execution"""
        return self.execution_mode == "fast_lane"
    
    @classmethod
    def from_fast_lane(
        cls,
        content: Any,
        tool_name: str,
        latency_ms: float,
        metadata: Optional[Dict[str, Any]] = None
    ) -> "ToolResult":
        """
        Create ToolResult from Fast Lane execution
        
        Example:
            result = ToolResult.from_fast_lane(
                content="File written successfully",
                tool_name="home_write",
                latency_ms=0.4,
                metadata={"bytes": 1024}
            )
        """
        return cls(
            content=content,
            tool_name=tool_name,
            execution_mode="fast_lane",
            latency_ms=latency_ms,
            success=True,
            metadata=metadata or {}
        )
    
    @classmethod
    def from_error(
        cls,
        error: str,
        tool_name: str,
        execution_mode: Literal["fast_lane", "mcp"] = "mcp"
    ) -> "ToolResult":
        """
        Create ToolResult for failed execution
        
        Example:
            result = ToolResult.from_error(
                error="File not found",
                tool_name="home_read",
                execution_mode="fast_lane"
            )
        """
        return cls(
            content=None,
            tool_name=tool_name,
            execution_mode=execution_mode,
            latency_ms=0.0,
            success=False,
            error=error
        )
