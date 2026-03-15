# tests/conftest.py
"""
Pytest Fixtures - Wiederverwendbare Test-Komponenten.
"""

import pytest
import sys
import os
from pathlib import Path

# Add parent dir to path for imports
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

# Some legacy integration tests import modules directly from `sql-memory/`
# (e.g. `from vector_store import VectorStore`).
_SQL_MEMORY = _ROOT / "sql-memory"
if _SQL_MEMORY.exists():
    sys.path.insert(0, str(_SQL_MEMORY))

# Standalone runner scripts that are not proper pytest files (use exit() at module level).
# These cause INTERNALERROR during pytest collection because sys.exit() fires on import.
collect_ignore = [
    "integration/test_light_cim.py",
]
collect_ignore_glob = [
    "reliability/test_*.py",  # all reliability/ files are standalone runners
]


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


@pytest.fixture
def base_url():
    """Live CIM endpoint fixture (opt-in only)."""
    if str(os.getenv("RUN_CIM_LIVE_TESTS", "")).strip().lower() not in {"1", "true", "yes", "on"}:
        pytest.skip("CIM live tests disabled (set RUN_CIM_LIVE_TESTS=1)")
    return str(os.getenv("CIM_BASE_URL", "http://localhost:8086")).strip()


@pytest.fixture
def urls():
    """Live integration URL bundle for CIM/Sequential/API tests (opt-in only)."""
    if str(os.getenv("RUN_CIM_LIVE_TESTS", "")).strip().lower() not in {"1", "true", "yes", "on"}:
        pytest.skip("CIM live tests disabled (set RUN_CIM_LIVE_TESTS=1)")
    mode = str(os.getenv("CIM_LIVE_MODE", "external")).strip().lower()
    if mode == "internal":
        return {
            "cim": str(os.getenv("CIM_URL_INTERNAL", "http://cim-server:8086")).strip(),
            "sequential": str(os.getenv("SEQUENTIAL_URL_INTERNAL", "http://sequential-thinking:8085")).strip(),
            "api": str(os.getenv("API_URL_INTERNAL", "http://jarvis-admin-api:8200")).strip(),
        }
    return {
        "cim": str(os.getenv("CIM_URL_EXTERNAL", "http://localhost:8086")).strip(),
        "sequential": str(os.getenv("SEQUENTIAL_URL_EXTERNAL", "http://localhost:8085")).strip(),
        "api": str(os.getenv("API_URL_EXTERNAL", "http://localhost:8200")).strip(),
    }


@pytest.fixture
def results():
    """Result collector fixture for script-like integration tests."""
    from tests.test_cim_sequential_integration import TestResult

    return TestResult()
