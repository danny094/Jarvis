# core/models.py
"""
Interne Datenmodelle für die Core-Bridge.
Alle Adapter transformieren zu/von diesen Modellen.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


@dataclass
class Message:
    """Eine einzelne Chat-Nachricht."""
    role: MessageRole
    content: str
    
    def to_dict(self) -> Dict[str, str]:
        return {
            "role": self.role.value,
            "content": self.content
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "Message":
        return cls(
            role=MessageRole(data.get("role", "user")),
            content=data.get("content", "")
        )


@dataclass
class CoreChatRequest:
    """
    Einheitliches internes Request-Format.
    Alle Adapter transformieren ihre Requests hierzu.
    """
    model: str
    messages: List[Message]
    conversation_id: str = "global"
    
    # Optionale Parameter
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    stream: bool = False
    
    # Adapter-Metadaten (für Logging/Debugging)
    source_adapter: str = "unknown"
    raw_request: Dict[str, Any] = field(default_factory=dict)
    
    def get_last_user_message(self) -> str:
        """Holt die letzte User-Nachricht."""
        for msg in reversed(self.messages):
            if msg.role == MessageRole.USER:
                return msg.content
        return ""
    
    def get_messages_as_dicts(self) -> List[Dict[str, str]]:
        """Konvertiert Messages zu Liste von Dicts."""
        return [m.to_dict() for m in self.messages]


@dataclass
class CoreChatResponse:
    """
    Einheitliches internes Response-Format.
    Alle Adapter transformieren dies zurück in ihr Format.
    """
    model: str
    content: str
    conversation_id: str = "global"
    
    # Metadaten
    done: bool = True
    done_reason: str = "stop"
    
    # Optional: Debugging-Infos
    classifier_result: Optional[Dict[str, Any]] = None
    memory_used: bool = False
    validation_passed: Optional[bool] = None
    
    # Für Streaming (später)
    is_partial: bool = False


@dataclass 
class CoreStreamChunk:
    """Für Streaming-Responses."""
    model: str
    content: str
    done: bool = False
    done_reason: Optional[str] = None
