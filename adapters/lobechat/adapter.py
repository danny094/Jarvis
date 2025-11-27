# adapters/lobechat/adapter.py
"""
LobeChat Adapter.

LobeChat nutzt das Ollama-kompatible Format:
- Request: {"model": "...", "messages": [...], "stream": true/false}
- Response: NDJSON mit {"model": "...", "message": {...}, "done": true/false}
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


class LobeChatAdapter(BaseAdapter):
    """
    Adapter für LobeChat.
    Transformiert zwischen Ollama-Format und CoreBridge-Format.
    """
    
    @property
    def name(self) -> str:
        return "lobechat"
    
    def transform_request(self, raw_request: Dict[str, Any]) -> CoreChatRequest:
        """
        LobeChat sendet im Ollama-Format:
        {
            "model": "deepseek-r1:14b",
            "messages": [
                {"role": "user", "content": "Hallo"},
                {"role": "assistant", "content": "Hi!"},
                ...
            ],
            "stream": true,
            "temperature": 0.7,
            ...
        }
        """
        # Messages parsen
        raw_messages = raw_request.get("messages", [])
        messages: List[Message] = []
        
        for msg in raw_messages:
            role_str = msg.get("role", "user").lower()
            content = msg.get("content", "")
            
            # Role mapping
            if role_str == "assistant":
                role = MessageRole.ASSISTANT
            elif role_str == "system":
                role = MessageRole.SYSTEM
            else:
                role = MessageRole.USER
                
            messages.append(Message(role=role, content=content))

        # Conversation-ID aus LobeChat extrahieren (falls vorhanden)
        conversation_id = raw_request.get("conversation_id") or \
                          raw_request.get("session_id") or \
                          "global"
        
        return CoreChatRequest(
            model=raw_request.get("model", ""),
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
        Transformiert CoreChatResponse ins LobeChat/Ollama NDJSON-Format:
        {
            "model": "...",
            "created_at": "2024-...",
            "message": {"role": "assistant", "content": "..."},
            "done": true,
            "done_reason": "stop"
        }
        """
        created_at = datetime.utcnow().isoformat() + "Z"
        
        return {
            "model": response.model,
            "created_at": created_at,
            "message": {
                "role": "assistant",
                "content": response.content,
            },
            "done": response.done,
            "done_reason": response.done_reason,
        }
    
    def transform_error(self, error: Exception) -> Dict[str, Any]:
        """LobeChat-kompatibles Error-Format."""
        created_at = datetime.utcnow().isoformat() + "Z"
        
        return {
            "model": "error",
            "created_at": created_at,
            "message": {
                "role": "assistant",
                "content": f"Fehler: {str(error)}",
            },
            "done": True,
            "done_reason": "error",
        }


# Singleton-Instanz
_adapter_instance = None

def get_adapter() -> LobeChatAdapter:
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = LobeChatAdapter()
    return _adapter_instance
