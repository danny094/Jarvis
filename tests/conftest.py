# tests/conftest.py
"""
Pytest Fixtures - Wiederverwendbare Test-Komponenten.
"""

import pytest
import sys
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


# ═══════════════════════════════════════════════════════════
# SAMPLE DATA FIXTURES
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def valid_json_simple():
    """Einfaches valides JSON."""
    return '{"intent": "test", "needs_memory": true}'


@pytest.fixture
def valid_json_complex():
    """Komplexes valides JSON."""
    return '''{
        "intent": "User fragt nach Alter",
        "needs_memory": true,
        "memory_keys": ["age", "birthday"],
        "hallucination_risk": "high",
        "reasoning": "Persönlicher Fakt"
    }'''


@pytest.fixture
def json_in_markdown():
    """JSON in Markdown Codeblock."""
    return '''Hier ist meine Analyse:
    
```json
{
    "intent": "test",
    "needs_memory": false
}
```

Das war meine Überlegung.'''


@pytest.fixture
def broken_json_trailing_comma():
    """JSON mit trailing comma."""
    return '{"intent": "test", "needs_memory": true,}'


@pytest.fixture
def json_with_text():
    """JSON mit Text drumherum."""
    return '''Okay, ich analysiere das:
    
{"intent": "analyse", "needs_memory": false}

Das ist mein Ergebnis.'''


@pytest.fixture
def thinking_layer_response():
    """Typische ThinkingLayer Antwort."""
    return '''<think>
Der User fragt nach seinem Alter. Das ist ein persönlicher Fakt.
Ich muss im Memory nachschauen, sonst halluziniere ich.
</think>

```json
{
    "intent": "User fragt nach seinem Alter",
    "needs_memory": true,
    "memory_keys": ["age", "alter", "birthday"],
    "needs_chat_history": false,
    "is_fact_query": true,
    "is_new_fact": false,
    "new_fact_key": null,
    "new_fact_value": null,
    "hallucination_risk": "high",
    "suggested_response_style": "kurz",
    "reasoning": "Alter ist persönlicher Fakt, muss aus Memory kommen"
}
```'''


@pytest.fixture
def sample_messages():
    """Sample Chat Messages."""
    from core.models import Message, MessageRole
    return [
        Message(role=MessageRole.USER, content="Ich heiße Danny"),
        Message(role=MessageRole.ASSISTANT, content="Hallo Danny!"),
        Message(role=MessageRole.USER, content="Wie alt bin ich?"),
    ]


@pytest.fixture
def sample_request(sample_messages):
    """Sample CoreChatRequest."""
    from core.models import CoreChatRequest
    return CoreChatRequest(
        model="qwen2.5:14b",
        messages=sample_messages,
        conversation_id="test-123",
        stream=False,
        source_adapter="test"
    )
