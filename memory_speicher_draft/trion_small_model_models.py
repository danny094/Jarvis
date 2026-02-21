from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class EventRecord(BaseModel):
    event_id: str
    conversation_id: str
    timestamp: datetime
    source_type: Literal["system", "tool", "user", "signed", "external"]
    source_reliability: float = Field(ge=0.0, le=1.0)
    entity_ids: List[str]
    entity_match_type: Literal["exact", "same_name", "semantic_alias", "none"]
    action: str
    raw_text: str
    parameters: Optional[dict] = None
    fact_type: str
    fact_attributes: Optional[dict] = None
    confidence_overall: Literal["high", "medium", "low"]
    confidence_numeric: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    confidence_breakdown: Optional[dict] = None
    scenario_type: Optional[str] = None


class EntityState(BaseModel):
    type: Literal["container", "blueprint", "deployment", "user", "memory"]
    id: str
    state: str
    runtime: Optional[str] = None
    image: Optional[str] = None
    blueprint_id: Optional[str] = None
    last_action: str
    last_exit_code: Optional[int] = None
    last_error: Optional[str] = None
    last_change_ts: datetime
    stability_score: Literal["high", "medium", "low"] = "medium"
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    source_event_ids: List[str] = Field(default_factory=list, max_length=20)


class TypedState(BaseModel):
    entities: Dict[str, EntityState] = Field(default_factory=dict)
    focus_entity: Optional[str] = None
    active_gates: List[str] = Field(default_factory=list, max_length=10)
    open_issues: List[str] = Field(default_factory=list, max_length=20)
    user_constraints: List[str] = Field(default_factory=list, max_length=20)
    last_error: Optional[str] = None
    updated_at: datetime
    source_event_ids: List[str] = Field(default_factory=list, max_length=100)


class ContextSnippet(BaseModel):
    title: str
    lines: List[str] = Field(default_factory=list, max_length=6)
    source_event_ids: List[str] = Field(default_factory=list, max_length=10)


class CompactMeta(BaseModel):
    small_model_mode: bool = True
    retrieval_used: bool = False
    retrieval_count: int = Field(default=0, ge=0, le=2)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    generated_at: datetime
    source_event_ids: List[str] = Field(default_factory=list, max_length=50)


class CompactContext(BaseModel):
    now: List[str] = Field(default_factory=list, max_length=5)
    rules: List[str] = Field(default_factory=list, max_length=3)
    next: List[str] = Field(default_factory=list, min_length=1, max_length=2)
    snippets: List[ContextSnippet] = Field(default_factory=list, max_length=2)
    meta: CompactMeta


class ContextLimits(BaseModel):
    now_max: int = 5
    rules_max: int = 3
    next_max: int = 2
    snippets_max: int = 2
    retrieval_max_per_turn: int = 1
    retrieval_max_on_failure: int = 2
