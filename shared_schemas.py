"""
Shared Data Schemas for TRION
Ensures consistent data structures across MCP Server, Adapters, and Frontend
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime


class CIMValidation(BaseModel):
    """CIM Validation result for a step"""
    priors_checked: int = Field(default=0, description="Number of cognitive priors checked")
    patterns_matched: int = Field(default=0, description="Number of patterns matched")
    bias_flags: List[str] = Field(default_factory=list, description="Detected cognitive biases")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Validation confidence")
    warnings: List[str] = Field(default_factory=list, description="Validation warnings")


class StepSchema(BaseModel):
    """Single step in Sequential Thinking workflow"""
    id: str = Field(..., description="Unique step identifier")
    description: str = Field(..., description="Human-readable step description")
    status: str = Field(
        default="pending",
        description="Step status: verified | executing | failed | pending"
    )
    cim_validation: Optional[CIMValidation] = Field(
        default=None,
        description="CIM validation results for this step"
    )
    result: Optional[str] = Field(default=None, description="Step execution result")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    timestamp: Optional[str] = Field(default=None, description="ISO timestamp")


class SequentialResponse(BaseModel):
    """Response from Sequential Thinking MCP Server"""
    task_id: str = Field(..., description="Unique task identifier")
    success: bool = Field(..., description="Whether task started successfully")
    steps: List[StepSchema] = Field(
        default_factory=list,
        description="List of workflow steps"
    )
    progress: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Task progress (0.0-1.0)"
    )
    message: Optional[str] = Field(default=None, description="Status message")
    started_at: Optional[str] = Field(default=None, description="Task start time (ISO)")
    completed_at: Optional[str] = Field(default=None, description="Task completion time (ISO)")


class SequentialStatusResponse(BaseModel):
    """Response for status polling"""
    task_id: str
    status: str = Field(
        description="Task status: running | complete | stopped | failed"
    )
    progress: float = Field(ge=0.0, le=1.0)
    steps: List[StepSchema]
    current_step: Optional[int] = Field(
        default=None,
        description="Index of currently executing step"
    )


# Export all schemas
__all__ = [
    "CIMValidation",
    "StepSchema", 
    "SequentialResponse",
    "SequentialStatusResponse"
]
