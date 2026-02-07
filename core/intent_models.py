#!/usr/bin/env python3
"""
Intent Models - First-Class Intent Objects für Skill-Erstellung.
================================================================

Definiert SkillCreationIntent als State-Machine für robuste Skill-Erstellung.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime
import uuid


class IntentState(Enum):
    """Zustände eines SkillCreationIntent."""
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


class IntentOrigin(Enum):
    """Wer hat den Intent ausgelöst?"""
    USER = "user"
    AI = "ai"


@dataclass
class SkillCreationIntent:
    """First-Class Intent Object für Skill-Erstellung."""
    
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    skill_name: str = ""
    origin: IntentOrigin = IntentOrigin.USER
    reason: str = ""
    state: IntentState = IntentState.PENDING_CONFIRMATION
    
    created_at: datetime = field(default_factory=datetime.now)
    conversation_id: str = ""
    user_text: str = ""
    
    proposed_code: Optional[str] = None
    proposed_description: Optional[str] = None
    
    # NEW: ThinkingLayer context for autonomous skill creation
    thinking_plan: Optional[dict] = None
    complexity: int = 5
    
    def confirm(self) -> "SkillCreationIntent":
        self.state = IntentState.CONFIRMED
        return self
    
    def reject(self) -> "SkillCreationIntent":
        self.state = IntentState.REJECTED
        return self
    
    def mark_executed(self) -> "SkillCreationIntent":
        self.state = IntentState.EXECUTED
        return self
    
    def mark_failed(self) -> "SkillCreationIntent":
        self.state = IntentState.FAILED
        return self
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "skill_name": self.skill_name,
            "origin": self.origin.value,
            "reason": self.reason,
            "state": self.state.value,
            "conversation_id": self.conversation_id,
            "user_text": self.user_text,
            "proposed_code": self.proposed_code,
            "created_at": self.created_at.isoformat(),
            "thinking_plan": self.thinking_plan,
            "complexity": self.complexity
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "SkillCreationIntent":
        intent = cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            skill_name=data.get("skill_name", ""),
            origin=IntentOrigin(data.get("origin", "user")),
            reason=data.get("reason", ""),
            state=IntentState(data.get("state", "pending_confirmation")),
            conversation_id=data.get("conversation_id", ""),
            user_text=data.get("user_text", ""),
            proposed_code=data.get("proposed_code"),
            proposed_description=data.get("proposed_description")
        )
        if data.get("created_at"):
            intent.created_at = datetime.fromisoformat(data["created_at"])
        return intent
