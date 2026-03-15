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
    def test_deep_mode_includes_output_budget_hint(self, *_mocks):
        layer = OutputLayer()
        prompt = layer._build_system_prompt({"_response_mode": "deep"}, memory_data="")
        self.assertIn("ANTWORT-BUDGET", prompt)
        self.assertIn("Deep-Modus", prompt)

    @patch("core.layers.output.get_enabled_tools", return_value=_TOOLS)
    @patch("core.layers.output.get_output_tool_prompt_limit", return_value=10)
    @patch("core.layers.output.get_output_tool_injection_mode", return_value="selected")
    def test_dialog_guidance_for_feedback_turn(self, *_mocks):
        layer = OutputLayer()
        prompt = layer._build_system_prompt(
            {
                "_response_mode": "interactive",
                "dialogue_act": "feedback",
                "response_tone": "mirror_user",
                "response_length_hint": "short",
                "tone_confidence": 0.88,
            },
            memory_data="",
        )
        self.assertIn("DIALOG-FÜHRUNG", prompt)
        self.assertIn("1-3 Sätze", prompt)
        self.assertIn("Spiegle Ton", prompt)

    @patch("core.layers.output.get_enabled_tools", return_value=_TOOLS)
    @patch("core.layers.output.get_output_tool_prompt_limit", return_value=10)
    @patch("core.layers.output.get_output_tool_injection_mode", return_value="selected")
    def test_smalltalk_prompt_adds_no_fabricated_experience_guard(self, *_mocks):
        layer = OutputLayer()
        prompt = layer._build_system_prompt(
            {
                "_response_mode": "interactive",
                "dialogue_act": "smalltalk",
                "response_tone": "warm",
                "response_length_hint": "short",
            },
            memory_data="",
        )
        self.assertIn("keine erfundenen persönlichen Erlebnisse", prompt)
        self.assertIn("ohne menschlichen Alltag", prompt)


if __name__ == "__main__":
    unittest.main()
