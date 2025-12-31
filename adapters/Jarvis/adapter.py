# adapters/jarvis/adapter.py
"""
Jarvis Adapter - Native API Format.

Jarvis nutzt ein einfaches, direktes JSON-Format:
- Request: {"query": "...", "conversation_id": "...", "stream": true/false}
- Response: {"response": "...", "done": true, "metadata": {...}}
"""

from datetime import datetime
from typing import Any, Dict, List

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from adapters.base import BaseAdapter
from core.models import (
    CoreChatRequest,
    CoreChatResponse,
    Message,
    MessageRole,
)


class JarvisAdapter(BaseAdapter):
    """
    Adapter für Jarvis - Einfaches, natives API-Format.
    Optimiert für direkte Integration ohne Format-Overhead.
    """
    
    @property
    def name(self) -> str:
        return "jarvis"
    
    def transform_request(self, raw_request: Dict[str, Any]) -> CoreChatRequest:
        """
        Jarvis sendet im simplen Format:
        {
            "query": "Was ist mein Name?",
            "conversation_id": "user_123",
            "model": "llama3.1:8b",  # optional
            "stream": true,
            "context": {  # optional
                "user_id": "...",
                "session_id": "..."
            }
        }
        """
        query = raw_request.get("query", "")
        conversation_id = raw_request.get("conversation_id", "global")
        
        # Messages erstellen - Jarvis nutzt nur User-Query
        messages = [Message(role=MessageRole.USER, content=query)]
        
        # Optional: System-Context aus raw_request
        context = raw_request.get("context", {})
        if context:
            system_msg = f"User Context: {context}"
            messages.insert(0, Message(role=MessageRole.SYSTEM, content=system_msg))
        
        return CoreChatRequest(
            model=raw_request.get("model", "llama3.1:8b"),
            messages=messages,
            conversation_id=conversation_id,
            temperature=raw_request.get("temperature"),
            top_p=raw_request.get("top_p"),
            max_tokens=raw_request.get("max_tokens"),
            stream=raw_request.get("stream", False),
            source_adapter=self.name,
            raw_request=raw_request,
        )
    
    def transform_response(self, response: CoreChatResponse) -> Dict[str, Any]:
        """
        Transformiert CoreChatResponse ins Jarvis-Format:
        {
            "response": "Dein Name ist Danny.",
            "done": true,
            "metadata": {
                "model": "llama3.1:8b",
                "timestamp": "2024-...",
                "conversation_id": "user_123",
                "memory_used": true
            }
        }
        """
        timestamp = datetime.utcnow().isoformat() + "Z"
        
        return {
            "response": response.content,
            "done": response.done,
            "metadata": {
                "model": response.model,
                "timestamp": timestamp,
                "conversation_id": response.conversation_id or "unknown",
                "done_reason": response.done_reason,
            }
        }
    
    def transform_error(self, error: Exception) -> Dict[str, Any]:
        """Jarvis-kompatibles Error-Format."""
        timestamp = datetime.utcnow().isoformat() + "Z"
        
        return {
            "response": "",
            "done": True,
            "error": str(error),
            "metadata": {
                "timestamp": timestamp,
                "done_reason": "error",
            }
        }


# Singleton-Instanz
_adapter_instance = None

def get_adapter() -> JarvisAdapter:
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = JarvisAdapter()
    return _adapter_instance
