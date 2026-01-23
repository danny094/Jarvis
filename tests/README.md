# tests/README.md
# 🧪 Test Suite für Jarvis

## Quick Start

```bash
# Dependencies installieren
pip install -r requirements-dev.txt

# Alle Tests ausführen
pytest

# Mit Coverage
pytest --cov=. --cov-report=html

# Nur bestimmte Tests
pytest tests/test_json_parser.py
pytest -k "test_valid"  # Nur Tests mit "test_valid" im Namen
```

## Test-Struktur

```
tests/
├── conftest.py          # Fixtures (wiederverwendbare Test-Daten)
├── test_json_parser.py  # JSON-Parser Tests (KRITISCH)
├── test_models.py       # Datenmodell Tests
├── test_api.py          # API-Endpoint Tests
└── test_persona.py      # Persona-System Tests
```

## Was wird getestet?

### 🔴 Kritisch (test_json_parser.py)
- Valides JSON parsing
- JSON in Markdown-Codeblocks
- Trailing commas
- Python True/False/None → JSON
- LLM-typische Probleme

### 🟡 Wichtig (test_models.py)
- Message Konvertierungen
- Request/Response Erstellung
- get_last_user_message()

### 🟢 Nice-to-have (test_api.py)
- Endpoint-Existenz
- CORS-Konfiguration
- Error Handling

## Lokale Tests vs CI

```bash
# Lokal (ohne Ollama/MCP)
pytest tests/test_json_parser.py tests/test_models.py

# Mit laufenden Services
pytest  # Alle Tests
```

## Neue Tests hinzufügen

1. Erstelle `tests/test_<modul>.py`
2. Benutze Fixtures aus `conftest.py`
3. Prefix: `test_` für Funktionen
4. Beschreibende Namen!

```python
def test_what_it_does_when_given_this():
    """Docstring erklärt was getestet wird."""
    result = function_under_test(input)
    assert result == expected
```

## Coverage anzeigen

```bash
pytest --cov=. --cov-report=term-missing
```
