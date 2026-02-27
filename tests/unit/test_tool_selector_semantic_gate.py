import asyncio
import unittest
from unittest.mock import patch

from core.tool_selector import ToolSelector


class _HubMissingSemantic:
    def get_mcp_for_tool(self, _name):
        return None

    def call_tool(self, *_args, **_kwargs):
        raise AssertionError("call_tool must not be called when semantic tool is unavailable")


class _HubSemanticOk:
    def get_mcp_for_tool(self, name):
        if name == "memory_semantic_search":
            return "sql-memory"
        return None

    def call_tool(self, _name, _args):
        return {
            "results": [
                {"metadata": {"key": "tool_list_skills", "description": "list"}},
                {"metadata": {"key": "tool_run_skill", "description": "run"}},
                {"metadata": {"key": "tool_list_skills", "description": "dup"}},
            ]
        }


class _HubSemanticWithScores:
    def __init__(self):
        self.last_args = None

    def get_mcp_for_tool(self, name):
        if name == "memory_semantic_search":
            return "sql-memory"
        return None

    def call_tool(self, _name, args):
        self.last_args = args
        return {
            "results": [
                {"similarity": 0.22, "metadata": {"key": "tool_list_skills", "description": "low"}},
                {"similarity": 0.61, "metadata": {"key": "tool_run_skill", "description": "ok"}},
                {"similarity": "0.49", "metadata": {"key": "tool_memory_graph_search", "description": "edge"}},
            ]
        }


class TestToolSelectorSemanticGate(unittest.TestCase):
    @patch("core.tool_selector.get_hub", return_value=_HubMissingSemantic())
    def test_returns_none_when_semantic_tool_unavailable(self, _mock_hub):
        selector = ToolSelector()
        out = asyncio.run(selector.select_tools("zeige skills"))
        self.assertIsNone(out)

    @patch("core.tool_selector.get_tool_selector_candidate_limit", return_value=1)
    @patch("core.tool_selector.get_hub", return_value=_HubSemanticOk())
    def test_applies_limit_and_dedup(self, _mock_hub, _mock_limit):
        selector = ToolSelector()
        out = asyncio.run(selector.select_tools("skill ausfuehren"))
        self.assertEqual(out, ["list_skills"])

    @patch("core.tool_selector.get_tool_selector_min_similarity", return_value=0.5)
    @patch("core.tool_selector.get_tool_selector_candidate_limit", return_value=5)
    def test_applies_similarity_threshold_and_forwards_query_threshold(self, _mock_limit, _mock_sim):
        hub = _HubSemanticWithScores()
        with patch("core.tool_selector.get_hub", return_value=hub):
            selector = ToolSelector()
            out = asyncio.run(selector.select_tools("führe skill aus"))
        self.assertEqual(out, ["run_skill"])
        self.assertIsNotNone(hub.last_args)
        self.assertEqual(hub.last_args.get("min_similarity"), 0.5)


if __name__ == "__main__":
    unittest.main()
