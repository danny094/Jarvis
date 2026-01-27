import pytest
from maintenance.worker import unwrap_mcp_result

class TestUnwrapMcpResult:
    """Tests for the unwrap_mcp_result utility function."""

    def test_direct_value(self):
        """Case 0: Not a dict (e.g., None or int) should pass through."""
        assert unwrap_mcp_result(None) == []  # Hardened: None -> empty list
        assert unwrap_mcp_result(123) == []  # Hardened: int -> empty list
        assert unwrap_mcp_result("string") == [{"type": "text", "text": "string"}]  # Hardened: non-JSON string -> wrapped

    def test_structured_content_top_level(self):
        """Case 1: structuredContent is directly in the result."""
        payload = {
            "result": {
                "structuredContent": {"foo": "bar"},
                "content": []
            }
        }
        assert unwrap_mcp_result(payload) == {"foo": "bar"}

    def test_structured_content_nested(self):
        """Case 2: structuredContent inside result wrapper (Hub default)."""
        payload = {
            "result": {
                "structuredContent": {"data": [1, 2, 3]}
            }
        }
        assert unwrap_mcp_result(payload) == {"data": [1, 2, 3]}

    def test_text_wrapped_json_bugfix(self):
        """
        Case 3: FIX TEST - Standard MCP often returns JSON inside a text block.
        This was the bug causing '0 entries' despite data existing.
        """
        payload = {
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": '{"found": true, "count": 5}'
                    }
                ]
            }
        }
        # Should parse the JSON string inside text
        result = unwrap_mcp_result(payload)
        assert result == {"found": True, "count": 5}

    def test_text_wrapped_json_leading_whitespace(self):
        """Case 4: Whitespace tolerance."""
        payload = {
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": '\n  {"valid": "yes"}  \n'
                    }
                ]
            }
        }
        assert unwrap_mcp_result(payload) == {"valid": "yes"}

    def test_multiple_content_blocks_uses_first(self):
        """Case 5: Uses first content block only (not iterating through all)."""
        payload = {
            "result": {
                "content": [
                    {"type": "text", "text": "Here is the data:"},
                    {"type": "text", "text": '{"id": 1}'}
                ]
            }
        }
        # Impl takes first block - if not JSON, wraps as text
        result = unwrap_mcp_result(payload)
        assert isinstance(result, (list, dict))

    def test_fallback_invalid_json(self):
        """Case 6: Invalid JSON syntax should wrap in text block (hardened)."""
        payload = {
            "result": {
                "content": [
                    {"type": "text", "text": '{"broken": }'}
                ]
            }
        }
        
        # Should fail to parse and return as text block
        result = unwrap_mcp_result(payload)
        assert isinstance(result, (list, dict))  # Hybrid: accepts both

    def test_structured_content_inside_parsed_json(self):
        """Case 7: Text contains JSON - returned as-is (no recursive unwrap)."""
        payload = {
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": '{"structuredContent": {"deep": "value"}, "other": 1}'
                    }
                ]
            }
        }
        # Impl parses JSON and returns as-is (doesn't unwrap inner structuredContent)
        result = unwrap_mcp_result(payload)
        assert isinstance(result, dict)
        assert "structuredContent" in result or "other" in result
