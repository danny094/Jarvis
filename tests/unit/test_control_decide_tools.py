import asyncio
import unittest
from unittest.mock import patch

from core.layers.control import ControlLayer


class _FakeHub:
    def __init__(self):
        self._tool_definitions = {}
        self.available = {
            "memory_graph_search": "sql-memory",
            "list_skills": "skill-server",
            "analyze": "cim",
            "think": "sequential",
        }

    def get_mcp_for_tool(self, name):
        return self.available.get(name)


class _BrokenDiscoveryHub:
    _tool_definitions = {}

    def get_mcp_for_tool(self, _name):
        raise RuntimeError("hub discovery unavailable")


class TestControlDecideTools(unittest.TestCase):
    def test_decide_tools_filters_unavailable_and_dedupes(self):
        layer = ControlLayer()
        layer.set_mcp_hub(_FakeHub())

        plan = {
            "suggested_tools": [
                "memory_graph_search",
                "unknown_tool",
                "memory_graph_search",
            ]
        }

        decided = asyncio.run(layer.decide_tools("test", plan))
        self.assertEqual(len(decided), 1)
        self.assertEqual(decided[0]["name"], "memory_graph_search")
        self.assertEqual(decided[0]["arguments"], {})

    def test_decide_tools_preserves_explicit_arguments(self):
        layer = ControlLayer()
        layer.set_mcp_hub(_FakeHub())

        plan = {
            "suggested_tools": [
                {"tool": "memory_graph_search", "args": {"query": "abc"}},
            ]
        }

        decided = asyncio.run(layer.decide_tools("abc", plan))
        self.assertEqual(decided, [{"name": "memory_graph_search", "arguments": {"query": "abc"}}])

    def test_decide_tools_parses_json_string_arguments(self):
        layer = ControlLayer()
        layer.set_mcp_hub(_FakeHub())

        plan = {
            "suggested_tools": [
                {"tool": "memory_graph_search", "args": "{\"query\": \"abc\"}"},
            ]
        }

        decided = asyncio.run(layer.decide_tools("abc", plan))
        self.assertEqual(decided, [{"name": "memory_graph_search", "arguments": {"query": "abc"}}])

    def test_decide_tools_extracts_tool_name_from_noisy_string(self):
        layer = ControlLayer()
        layer.set_mcp_hub(_FakeHub())

        plan = {
            "suggested_tools": [
                "// Für historische Pipeline-Daten\n        \"list_skills",
            ]
        }

        decided = asyncio.run(layer.decide_tools("zeige skills", plan))
        self.assertEqual(decided, [{"name": "list_skills", "arguments": {}}])

    def test_decide_tools_drops_unstructured_prose_tool_string(self):
        layer = ControlLayer()
        layer.set_mcp_hub(_FakeHub())

        plan = {"suggested_tools": ["bitte nutze tools fuer analyse"]}
        decided = asyncio.run(layer.decide_tools("test", plan))
        self.assertEqual(decided, [])

    def test_decide_tools_uses_cim_skill_name_for_get_skill_info(self):
        layer = ControlLayer()
        layer.set_mcp_hub(_FakeHub())

        plan = {
            "suggested_tools": ["get_skill_info"],
            "_cim_decision": {"skill_name": "file-organizer"},
        }

        decided = asyncio.run(layer.decide_tools("skill info", plan))
        self.assertEqual(len(decided), 1)
        self.assertEqual(decided[0]["name"], "get_skill_info")
        self.assertEqual(decided[0]["arguments"], {"skill_name": "file-organizer"})

    def test_decide_tools_autofills_analyze_query(self):
        layer = ControlLayer()
        layer.set_mcp_hub(_FakeHub())

        plan = {"suggested_tools": ["analyze"]}
        decided = asyncio.run(layer.decide_tools("prüfe gpu bottleneck", plan))
        self.assertEqual(len(decided), 1)
        self.assertEqual(decided[0]["name"], "analyze")
        self.assertEqual(decided[0]["arguments"], {"query": "prüfe gpu bottleneck"})

    def test_decide_tools_autofills_think_message(self):
        layer = ControlLayer()
        layer.set_mcp_hub(_FakeHub())

        plan = {"suggested_tools": ["think"]}
        decided = asyncio.run(layer.decide_tools("denke in schritten", plan))
        self.assertEqual(len(decided), 1)
        self.assertEqual(decided[0]["name"], "think")
        self.assertEqual(decided[0]["arguments"], {"message": "denke in schritten"})

    def test_decide_tools_uses_cim_skill_name_for_create_skill(self):
        layer = ControlLayer()
        layer.set_mcp_hub(_FakeHub())

        plan = {
            "suggested_tools": ["create_skill"],
            "_cim_decision": {"skill_name": "health-check"},
        }

        decided = asyncio.run(layer.decide_tools("baue skill für health checks", plan))
        self.assertEqual(len(decided), 1)
        self.assertEqual(decided[0]["name"], "create_skill")
        args = decided[0]["arguments"]
        self.assertEqual(args.get("name"), "health-check")
        self.assertTrue(isinstance(args.get("description"), str) and args["description"])
        self.assertTrue(isinstance(args.get("code"), str) and "def main" in args["code"])

    def test_control_prompt_payload_is_compact(self):
        layer = ControlLayer()
        long_memory = "X" * 8000
        plan = {
            "intent": "analyse pipeline",
            "needs_memory": True,
            "memory_keys": [f"k{i}" for i in range(10)],
            "suggested_tools": [{"tool": "analyze"}, {"tool": "think"}],
            "hallucination_risk": "low",
        }
        payload = layer._build_control_prompt_payload(
            user_text="analysiere die pipeline",
            thinking_plan=plan,
            retrieved_memory=long_memory,
        )
        self.assertIn("user_request", payload)
        self.assertIn("thinking_plan_compact", payload)
        self.assertIn("memory_excerpt", payload)
        self.assertTrue(len(payload["memory_excerpt"]) < len(long_memory))
        self.assertIn("truncated", payload["memory_excerpt"])

    def test_is_tool_available_fail_closed_when_hub_unavailable(self):
        layer = ControlLayer()
        layer.mcp_hub = None
        with patch("mcp.hub.get_hub", side_effect=RuntimeError("hub down")):
            self.assertFalse(layer._is_tool_available("memory_graph_search"))

    def test_is_tool_available_keeps_native_when_hub_unavailable(self):
        layer = ControlLayer()
        layer.mcp_hub = None
        with patch("mcp.hub.get_hub", side_effect=RuntimeError("hub down")):
            self.assertTrue(layer._is_tool_available("create_skill"))

    def test_decide_tools_filters_non_native_on_discovery_error(self):
        layer = ControlLayer()
        layer.set_mcp_hub(_BrokenDiscoveryHub())
        plan = {"suggested_tools": ["memory_graph_search", "autonomous_skill_task"]}
        decided = asyncio.run(layer.decide_tools("test", plan))
        self.assertEqual(len(decided), 1)
        self.assertEqual(decided[0]["name"], "autonomous_skill_task")
        self.assertEqual(decided[0]["arguments"], {})


if __name__ == "__main__":
    unittest.main()
