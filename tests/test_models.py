# tests/test_models.py
"""
Tests für die Core-Datenmodelle.

Stellt sicher, dass Messages und Requests korrekt funktionieren.
"""

import pytest
from core.models import Message, MessageRole, CoreChatRequest, CoreChatResponse


class TestMessage:
    """Tests für die Message-Klasse."""
    
    def test_create_user_message(self):
        """User-Message erstellen."""
        msg = Message(role=MessageRole.USER, content="Hallo")
        
        assert msg.role == MessageRole.USER
        assert msg.content == "Hallo"
    
    def test_create_assistant_message(self):
        """Assistant-Message erstellen."""
        msg = Message(role=MessageRole.ASSISTANT, content="Hi!")
        
        assert msg.role == MessageRole.ASSISTANT
        assert msg.content == "Hi!"
    
    def test_to_dict(self):
        """Message zu Dict konvertieren."""
        msg = Message(role=MessageRole.USER, content="Test")
        result = msg.to_dict()
        
        assert result == {"role": "user", "content": "Test"}
    
    def test_from_dict(self):
        """Message aus Dict erstellen."""
        data = {"role": "assistant", "content": "Antwort"}
        msg = Message.from_dict(data)
        
        assert msg.role == MessageRole.ASSISTANT
        assert msg.content == "Antwort"
    
    def test_from_dict_defaults(self):
        """Message aus Dict mit fehlenden Feldern."""
        msg = Message.from_dict({})
        
        assert msg.role == MessageRole.USER  # Default
        assert msg.content == ""


class TestMessageRole:
    """Tests für das MessageRole Enum."""
    
    def test_role_values(self):
        """Role-Werte sind korrekte Strings."""
        assert MessageRole.USER.value == "user"
        assert MessageRole.ASSISTANT.value == "assistant"
        assert MessageRole.SYSTEM.value == "system"
    
    def test_role_from_string(self):
        """Role aus String erstellen."""
        assert MessageRole("user") == MessageRole.USER
        assert MessageRole("assistant") == MessageRole.ASSISTANT


class TestCoreChatRequest:
    """Tests für CoreChatRequest."""
    
    def test_create_request(self, sample_messages):
        """Request erstellen."""
        request = CoreChatRequest(
            model="test-model",
            messages=sample_messages,
            conversation_id="test-123"
        )
        
        assert request.model == "test-model"
        assert len(request.messages) == 3
        assert request.conversation_id == "test-123"
    
    def test_get_last_user_message(self, sample_messages):
        """Letzte User-Nachricht holen."""
        request = CoreChatRequest(
            model="test",
            messages=sample_messages
        )
        
        last = request.get_last_user_message()
        assert last == "Wie alt bin ich?"
    
    def test_get_last_user_message_empty(self):
        """Keine Messages = leerer String."""
        request = CoreChatRequest(model="test", messages=[])
        
        assert request.get_last_user_message() == ""
    
    def test_get_last_user_message_only_assistant(self):
        """Nur Assistant-Messages = leerer String."""
        messages = [
            Message(role=MessageRole.ASSISTANT, content="Hi")
        ]
        request = CoreChatRequest(model="test", messages=messages)
        
        assert request.get_last_user_message() == ""
    
    def test_get_messages_as_dicts(self, sample_messages):
        """Messages als Dict-Liste."""
        request = CoreChatRequest(model="test", messages=sample_messages)
        
        dicts = request.get_messages_as_dicts()
        
        assert len(dicts) == 3
        assert dicts[0]["role"] == "user"
        assert dicts[0]["content"] == "Ich heiße Danny"
    
    def test_default_values(self):
        """Default-Werte werden gesetzt."""
        request = CoreChatRequest(model="test", messages=[])
        
        assert request.conversation_id == "global"
        assert request.stream is False
        assert request.source_adapter == "unknown"
        assert request.temperature is None


class TestCoreChatResponse:
    """Tests für CoreChatResponse."""
    
    def test_create_response(self):
        """Response erstellen."""
        response = CoreChatResponse(
            model="test-model",
            content="Die Antwort",
            conversation_id="test-123"
        )
        
        assert response.model == "test-model"
        assert response.content == "Die Antwort"
        assert response.done is True
    
    def test_response_with_metadata(self):
        """Response mit Metadaten."""
        response = CoreChatResponse(
            model="test",
            content="Test",
            memory_used=True,
            validation_passed=True,
            classifier_result={"intent": "test"}
        )
        
        assert response.memory_used is True
        assert response.validation_passed is True
        assert response.classifier_result["intent"] == "test"


class TestMessageConversions:
    """Tests für Konvertierungen zwischen Formaten."""
    
    def test_roundtrip_message(self):
        """Message → Dict → Message sollte identisch sein."""
        original = Message(role=MessageRole.USER, content="Test äöü 🎉")
        
        as_dict = original.to_dict()
        restored = Message.from_dict(as_dict)
        
        assert restored.role == original.role
        assert restored.content == original.content
    
    def test_message_with_special_chars(self):
        """Message mit Sonderzeichen."""
        content = 'Test mit "Quotes" und\nNewlines'
        msg = Message(role=MessageRole.USER, content=content)
        
        assert msg.content == content
        assert '"Quotes"' in msg.to_dict()["content"]
