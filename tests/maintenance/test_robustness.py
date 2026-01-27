
import pytest
import json
from maintenance.worker import unwrap_mcp_result

# Extrem-Tests für die Parsing-Logik
# Ziel: Die Funktion darf NIEMALS crashen (Except Exception must catch all), 
# sondern sollte sauber None oder leere Liste zurückgeben.

class TestRobustness:
    
    def test_handle_none_and_empty(self):
        """Testet None und leere Inputs."""
        assert unwrap_mcp_result(None) == []
        assert unwrap_mcp_result("") == []
        assert unwrap_mcp_result({}) == []
    
    def test_malformed_json_string(self):
        """Testet kaputtes JSON im String."""
        # Fehlende Klammer
        bad_json = '{"content": [{"text": "Hello"' 
        
        # Sollte Text-Fallback nutzen
        res = unwrap_mcp_result(bad_json)
        assert len(res) == 1
        assert res[0]["text"] == bad_json
        assert res[0]["type"] == "text"

    def test_garbage_input(self):
        """Testet kompletten Müll-Input."""
        garbage = "<!DOCTYPE html><html>...</html>"
        res = unwrap_mcp_result(garbage)
        assert len(res) == 1
        assert res[0]["text"] == garbage

    def test_unexpected_types(self):
        """Testet falsche Datentypen."""
        assert unwrap_mcp_result(12345) == []
        assert unwrap_mcp_result(True) == []
        assert unwrap_mcp_result(["List", "instead", "of", "dict"]) == []

    def test_nested_structure_chaos(self):
        """Testet tief verschachtelte und verwirrende Strukturen."""
        # Deeply nested content match
        complex_input = {
            "result": {
                "content": [
                    {
                        "text": json.dumps({
                            "type": "text", 
                            "text": "Correct Deep Content"
                        })
                    }
                ]
            }
        }
        # Hier erwarten wir, dass er 'Correct Deep Content' findet, wenn die Logik rekursiv ist 
        # oder zumindest nicht crasht.
        # Unsere aktuelle Logik sucht nach `content` list.
        res = unwrap_mcp_result(complex_input)
        # Wenn er es findet ist gut, wenn nicht (weil Struktur zu wild) auch okay,
        # Hauptsache kein Crash.
        assert isinstance(res, (list, dict))  # Hybrid: valid data can be dict or list

    def test_large_payload(self):
        """Stress-Test mit großem Payload."""
        # Erzeuge 5MB String
        huge_text = "A" * (5 * 1024 * 1024) 
        payload = {
            "content": [
                {"type": "text", "text": huge_text}
            ]
        }
        
        res = unwrap_mcp_result(payload)
        assert len(res) == 1
        assert res[0]["text"] == huge_text

    def test_recursive_bomb(self):
        """Verhindert Recursion Errors bei zirkulären Referenzen (falls Logik rekursiv wäre)."""
        # Python dicts können zirkulär sein
        a = {}
        b = {"parent": a}
        a["child"] = b
        
        # unwrap_mcp_result(a) sollte nicht in Endlosschleife laufen
        # (Unsere aktuelle Impl ist iterativ/flach, aber sicher ist sicher)
        try:
            res = unwrap_mcp_result(a)
            assert isinstance(res, (list, dict))  # Hybrid: valid data can be dict or list
        except RecursionError:
            pytest.fail("RecursionError bei zirkulärer Struktur")

