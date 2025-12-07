# tests/test_json_parser.py
"""
Tests für den robusten JSON-Parser.

Der JSON-Parser ist KRITISCH - wenn er failt, failt alles.
Diese Tests stellen sicher, dass er mit allen LLM-Outputs umgehen kann.
"""

import pytest
from utils.json_parser import safe_parse_json, extract_json_array, _attempt_json_repair


class TestSafeParseJson:
    """Tests für die Hauptfunktion safe_parse_json."""
    
    # ═══════════════════════════════════════════════════════════
    # HAPPY PATH - Alles funktioniert
    # ═══════════════════════════════════════════════════════════
    
    def test_valid_json_simple(self, valid_json_simple):
        """Einfaches JSON sollte direkt parsen."""
        result = safe_parse_json(valid_json_simple)
        
        assert result["intent"] == "test"
        assert result["needs_memory"] is True
    
    def test_valid_json_complex(self, valid_json_complex):
        """Komplexes JSON mit Arrays und nested values."""
        result = safe_parse_json(valid_json_complex)
        
        assert result["intent"] == "User fragt nach Alter"
        assert result["needs_memory"] is True
        assert "age" in result["memory_keys"]
        assert "birthday" in result["memory_keys"]
        assert result["hallucination_risk"] == "high"
    
    # ═══════════════════════════════════════════════════════════
    # EDGE CASES - LLM-typische Probleme
    # ═══════════════════════════════════════════════════════════
    
    def test_json_in_markdown_codeblock(self, json_in_markdown):
        """JSON in ```json ... ``` Codeblock."""
        result = safe_parse_json(json_in_markdown)
        
        assert result["intent"] == "test"
        assert result["needs_memory"] is False
    
    def test_json_with_surrounding_text(self, json_with_text):
        """JSON mit Text davor und danach."""
        result = safe_parse_json(json_with_text)
        
        assert result["intent"] == "analyse"
        assert result["needs_memory"] is False
    
    def test_json_trailing_comma(self, broken_json_trailing_comma):
        """JSON mit trailing comma sollte repariert werden."""
        result = safe_parse_json(broken_json_trailing_comma)
        
        assert result["intent"] == "test"
        assert result["needs_memory"] is True
    
    def test_thinking_layer_full_response(self, thinking_layer_response):
        """Volle ThinkingLayer Antwort mit <think> Tags."""
        result = safe_parse_json(thinking_layer_response)
        
        assert result["intent"] == "User fragt nach seinem Alter"
        assert result["needs_memory"] is True
        assert result["hallucination_risk"] == "high"
        assert "age" in result["memory_keys"]
    
    # ═══════════════════════════════════════════════════════════
    # FALLBACK CASES - Wenn nichts klappt
    # ═══════════════════════════════════════════════════════════
    
    def test_empty_input_returns_default(self):
        """Leerer Input sollte Default zurückgeben."""
        assert safe_parse_json("") == {}
        assert safe_parse_json(None) == {}
        assert safe_parse_json("   ") == {}
    
    def test_custom_default(self):
        """Custom Default sollte bei Fehler zurückkommen."""
        default = {"fallback": True}
        result = safe_parse_json("totally broken {{{", default=default)
        
        assert result["fallback"] is True
    
    def test_garbage_input(self):
        """Kompletter Müll sollte Default zurückgeben."""
        result = safe_parse_json("askjdhaksjd no json here!!!")
        assert result == {}
    
    # ═══════════════════════════════════════════════════════════
    # REPAIR CASES - JSON-Reparatur
    # ═══════════════════════════════════════════════════════════
    
    def test_python_booleans(self):
        """Python True/False statt JSON true/false."""
        result = safe_parse_json('{"active": True, "deleted": False}')
        
        assert result["active"] is True
        assert result["deleted"] is False
    
    def test_python_none(self):
        """Python None statt JSON null."""
        result = safe_parse_json('{"value": None}')
        
        assert result["value"] is None
    
    def test_single_quotes(self):
        """Single quotes statt double quotes."""
        result = safe_parse_json("{'name': 'test'}")
        
        assert result["name"] == "test"
    
    def test_unquoted_keys(self):
        """Keys ohne Quotes."""
        result = safe_parse_json('{name: "test", age: 25}')
        
        assert result["name"] == "test"
        assert result["age"] == 25


class TestExtractJsonArray:
    """Tests für Array-Extraktion."""
    
    def test_valid_array(self):
        """Einfaches Array."""
        result = extract_json_array('["a", "b", "c"]')
        assert result == ["a", "b", "c"]
    
    def test_array_in_text(self):
        """Array mit Text drumherum."""
        result = extract_json_array('Die Keys sind: ["key1", "key2"] fertig.')
        assert result == ["key1", "key2"]
    
    def test_comma_separated_fallback(self):
        """Comma-separated values als Fallback."""
        result = extract_json_array('key1, key2, key3')
        assert result == ["key1", "key2", "key3"]
    
    def test_empty_returns_default(self):
        """Leerer Input gibt Default."""
        assert extract_json_array("") == []
        assert extract_json_array("", default=["fallback"]) == ["fallback"]


class TestJsonRepair:
    """Tests für die interne Reparatur-Funktion."""
    
    def test_removes_trailing_comma_object(self):
        """Entfernt ,} am Ende."""
        result = _attempt_json_repair('{"a": 1,}')
        assert result == '{"a": 1}'
    
    def test_removes_trailing_comma_array(self):
        """Entfernt ,] am Ende."""
        result = _attempt_json_repair('{"arr": [1, 2,]}')
        assert '2,]' not in result


class TestRealWorldExamples:
    """Tests mit echten LLM-Outputs die Probleme gemacht haben."""
    
    def test_deepseek_thinking_output(self):
        """DeepSeek R1 Output mit <think> Tags."""
        raw = '''<think>
Hmm, der User fragt nach Tools. Lass mich überlegen...
Das ist eine System-Frage.
</think>

Hier ist meine Analyse:

```json
{
    "intent": "User fragt nach Tools",
    "needs_memory": true,
    "memory_keys": ["available_mcp_tools"],
    "hallucination_risk": "high"
}
```'''
        
        result = safe_parse_json(raw)
        assert result["intent"] == "User fragt nach Tools"
        assert result["needs_memory"] is True
    
    def test_multiline_with_newlines_in_values(self):
        """JSON mit Newlines in String-Values."""
        raw = '''{
    "reasoning": "Der User will wissen\\nwas wir besprochen haben",
    "intent": "chat history"
}'''
        result = safe_parse_json(raw)
        assert result["intent"] == "chat history"
    
    def test_german_umlauts(self):
        """JSON mit deutschen Umlauten."""
        raw = '{"intent": "Größe abfragen", "value": "größer"}'
        result = safe_parse_json(raw)
        assert "Größe" in result["intent"]
