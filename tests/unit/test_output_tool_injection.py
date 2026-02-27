import unittest
from unittest.mock import patch

from core.layers.output import OutputLayer


_TOOLS = [
    {"name": "list_skills", "mcp": "skill-server", "description": "List skills"},
    {"name": "memory_graph_search", "mcp": "sql-memory", "description": "Search memory"},
]


class TestOutputToolInjection(unittest.TestCase):
    @patch("core.layers.output.get_enabled_tools", return_value=_TOOLS)
    @patch("core.layers.output.get_output_tool_prompt_limit", return_value=10)
    @patch("core.layers.output.get_output_tool_injection_mode", return_value="selected")
    def test_selected_mode_injects_only_selected_tools(self, *_mocks):
        layer = OutputLayer()
        plan = {"_selected_tools_for_prompt": ["list_skills"]}
        prompt = layer._build_system_prompt(plan, memory_data="")
        self.assertIn("list_skills", prompt)
        self.assertNotIn("memory_graph_search", prompt)

    @patch("core.layers.output.get_enabled_tools", return_value=_TOOLS)
    @patch("core.layers.output.get_output_tool_prompt_limit", return_value=10)
    @patch("core.layers.output.get_output_tool_injection_mode", return_value="none")
    def test_none_mode_disables_tool_injection(self, *_mocks):
        layer = OutputLayer()
        prompt = layer._build_system_prompt({}, memory_data="")
        self.assertNotIn("VERFÜGBARE TOOLS", prompt)
        self.assertNotIn("list_skills", prompt)

    @patch("core.layers.output.get_enabled_tools", return_value=_TOOLS)
    @patch("core.layers.output.get_output_tool_prompt_limit", return_value=10)
    @patch("core.layers.output.get_output_tool_injection_mode", return_value="selected")
    def test_interactive_mode_adds_output_budget_hint(self, *_mocks):
        layer = OutputLayer()
        prompt = layer._build_system_prompt({"_response_mode": "interactive"}, memory_data="")
        self.assertIn("ANTWORT-BUDGET", prompt)

    @patch("core.layers.output.get_enabled_tools", return_value=_TOOLS)
    @patch("core.layers.output.get_output_tool_prompt_limit", return_value=10)
    @patch("core.layers.output.get_output_tool_injection_mode", return_value="selected")
    def test_deep_mode_omits_output_budget_hint(self, *_mocks):
        layer = OutputLayer()
        prompt = layer._build_system_prompt({"_response_mode": "deep"}, memory_data="")
        self.assertNotIn("ANTWORT-BUDGET", prompt)


if __name__ == "__main__":
    unittest.main()
