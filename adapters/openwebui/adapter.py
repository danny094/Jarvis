# adapters/openwebui/adapter.py
"""
Open WebUI Adapter (Template).

Open WebUI nutzt auch das Ollama-Format, aber mit leichten Unterschieden.
Dieses Template zeigt, wie einfach ein neuer Adapter erstellt wird.

TODO: Anpassen an das exakte Open WebUI Format falls nötig.
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


class OpenWebUIAdapter(BaseAdapter):
    """
    Adapter für Open WebUI.
    
    Open WebUI ist sehr ähnlich zu LobeChat (beide Ollama-kompatibel),
    aber es gibt kleine Unterschiede die hier behandelt werden können.
    """
    
    @property
    def name(self) -> str:
        return "openwebui"
    
    def transform_request(self, raw_request: Dict[str, Any]) -> CoreChatRequest:
        """
        Open WebUI Request-Format:
        {
            "model": "...",
            "messages": [...],
            "stream": true,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
                ...
            }
        }
        
        Unterschied zu LobeChat: options-Objekt statt flache Parameter.
        """
        raw_messages = raw_request.get("messages", [])
        messages: List[Message] = []
        
        for msg in raw_messages:
            role_str = msg.get("role", "user").lower()
            content = msg.get("content", "")
            
            if role_str == "assistant":
                role = MessageRole.ASSISTANT
            elif role_str == "system":
                role = MessageRole.SYSTEM
            else:
                role = MessageRole.USER
                
            messages.append(Message(role=role, content=content))
        
        # Options extrahieren (Open WebUI Style)
        options = raw_request.get("options", {})
        
        return CoreChatRequest(
            model=raw_request.get("model", ""),
            messages=messages,
            conversation_id=raw_request.get("conversation_id", "global"),
            temperature=options.get("temperature") or raw_request.get("temperature"),
            top_p=options.get("top_p") or raw_request.get("top_p"),
            max_tokens=options.get("num_predict") or raw_request.get("max_tokens"),
            stream=raw_request.get("stream", False),
            source_adapter=self.name,
            raw_request=raw_request,
        )
    
    def transform_response(self, response: CoreChatResponse) -> Dict[str, Any]:
        """Open WebUI Response-Format (Ollama-kompatibel)."""
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


# Singleton
_adapter_instance = None

def get_adapter() -> OpenWebUIAdapter:
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = OpenWebUIAdapter()
    return _adapter_instance
