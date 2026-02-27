"""
tests/unit/test_skill_discovery_drift_parity.py — C10 (Rest)
============================================================

DoD focus:
  - Read-only discovery can improve recall without accepting graph drift.
  - Ghost graph candidates are filtered against truth (installed/drafts).
  - Rollback flag SKILL_DISCOVERY_ENABLE disables discovery path.
  - Local fallback remains deterministic (parity when graph is unavailable).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if not os.path.isdir(os.path.join(_REPO_ROOT, "mcp-servers")):
    _REPO_ROOT = "/DATA/AppData/MCP/Jarvis/Jarvis"
_SKILL_SERVER = os.path.join(_REPO_ROOT, "mcp-servers", "skill-server")

for p in (_REPO_ROOT, _SKILL_SERVER):
    if p not in sys.path:
        sys.path.insert(0, p)


def _load_config():
    settings_mod = MagicMock()
    settings_mod.settings = MagicMock()
    settings_mod.settings.get = lambda _k, default="": default
    with patch.dict(sys.modules, {"utils.settings": settings_mod}):
        spec = importlib.util.spec_from_file_location(
            "config_c10_discovery", os.path.join(_REPO_ROOT, "config.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


def _load_mcl():
    sys_mocks = {
        "skill_cim_light": MagicMock(
            SkillCIMLight=MagicMock,
            ValidationResult=MagicMock,
            get_skill_cim=MagicMock(return_value=MagicMock()),
        ),
        "cim_rag": MagicMock(
            cim_kb=MagicMock(
                load=MagicMock(),
                get_template_by_intent=MagicMock(return_value=None),
                get_persona=MagicMock(return_value=""),
            )
        ),
        "httpx": MagicMock(),
    }
    with patch.dict(sys.modules, sys_mocks):
        spec = importlib.util.spec_from_file_location(
            "skill_server_mcl_c10",
            os.path.join(_SKILL_SERVER, "mini_control_layer.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


class TestSkillDiscoveryConfigGetter(unittest.TestCase):
    def test_default_true(self):
        cfg = _load_config()
        saved = os.environ.pop("SKILL_DISCOVERY_ENABLE", None)
        try:
            self.assertTrue(cfg.get_skill_discovery_enable())
        finally:
            if saved is not None:
                os.environ["SKILL_DISCOVERY_ENABLE"] = saved

    def test_env_override_false(self):
        cfg = _load_config()
        with patch.dict(os.environ, {"SKILL_DISCOVERY_ENABLE": "false"}):
            self.assertFalse(cfg.get_skill_discovery_enable())


class TestDiscoveryDriftAndParity(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.mcl = _load_mcl()

    def _build_ctrl(self):
        cim_mock = MagicMock()
        return self.mcl.SkillMiniControl(cim=cim_mock)

    async def test_graph_discovery_filters_ghost_and_uses_truth_skill(self):
        ctrl = self._build_ctrl()
        ctrl._is_skill_discovery_enabled = MagicMock(return_value=True)
        ctrl._load_installed_skills = MagicMock(return_value={
            "weather_skill": {"description": "weather checks", "triggers": ["weather"]},
        })
        ctrl._load_draft_skills = MagicMock(return_value={})
        ctrl._fetch_skill_graph_candidates = AsyncMock(return_value=[
            {"similarity": 0.99, "metadata": json.dumps({"skill_name": "ghost_skill"})},
            {"similarity": 0.83, "metadata": json.dumps({"skill_name": "weather_skill"})},
        ])

        match = await ctrl._find_matching_skill("weather", "show weather in berlin")
        self.assertIsNotNone(match)
        self.assertEqual(match["name"], "weather_skill")
        self.assertEqual(match.get("discovery_source"), "graph_truth_filtered")

    async def test_discovery_disabled_skips_graph_path(self):
        ctrl = self._build_ctrl()
        ctrl._is_skill_discovery_enabled = MagicMock(return_value=False)
        ctrl._load_installed_skills = MagicMock(return_value={
            "weather_skill": {"description": "weather checks", "triggers": ["weather"]},
        })
        ctrl._load_draft_skills = MagicMock(return_value={})
        ctrl._fetch_skill_graph_candidates = AsyncMock(return_value=[
            {"similarity": 0.99, "metadata": json.dumps({"skill_name": "weather_skill"})},
        ])

        match = await ctrl._find_matching_skill("weather", "weather today")
        self.assertIsNotNone(match)
        self.assertEqual(match["name"], "weather_skill")
        ctrl._fetch_skill_graph_candidates.assert_not_called()

    async def test_graph_unavailable_falls_back_to_local_matching(self):
        ctrl = self._build_ctrl()
        ctrl._is_skill_discovery_enabled = MagicMock(return_value=True)
        ctrl._load_installed_skills = MagicMock(return_value={
            "weather_skill": {"description": "weather checks", "triggers": ["weather", "forecast"]},
        })
        ctrl._load_draft_skills = MagicMock(return_value={})
        ctrl._fetch_skill_graph_candidates = AsyncMock(return_value=[])

        match = await ctrl._find_matching_skill("weather", "weather forecast")
        self.assertIsNotNone(match, "must fall back to local matching when graph has no candidates")
        self.assertEqual(match["name"], "weather_skill")
        self.assertNotEqual(match.get("discovery_source"), "graph_truth_filtered")

    async def test_enabled_disabled_parity_when_graph_empty(self):
        base_skills = {
            "math_helper": {"description": "math helper", "triggers": ["math", "calculate"]},
        }

        c_enabled = self._build_ctrl()
        c_enabled._is_skill_discovery_enabled = MagicMock(return_value=True)
        c_enabled._load_installed_skills = MagicMock(return_value=base_skills)
        c_enabled._load_draft_skills = MagicMock(return_value={})
        c_enabled._fetch_skill_graph_candidates = AsyncMock(return_value=[])
        m1 = await c_enabled._find_matching_skill("calculate", "calculate 2+2")

        c_disabled = self._build_ctrl()
        c_disabled._is_skill_discovery_enabled = MagicMock(return_value=False)
        c_disabled._load_installed_skills = MagicMock(return_value=base_skills)
        c_disabled._load_draft_skills = MagicMock(return_value={})
        c_disabled._fetch_skill_graph_candidates = AsyncMock(return_value=[])
        m2 = await c_disabled._find_matching_skill("calculate", "calculate 2+2")

        self.assertIsNotNone(m1)
        self.assertIsNotNone(m2)
        self.assertEqual(m1["name"], m2["name"])


class TestOrchestratorDiscoveryGateSource(unittest.TestCase):
    def test_orchestrator_contains_discovery_gate(self):
        orch_path = os.path.join(_REPO_ROOT, "core", "orchestrator.py")
        with open(orch_path, "r", encoding="utf-8") as f:
            src = f.read()
        self.assertIn("get_skill_discovery_enable", src)
        self.assertIn("SKILL_DISCOVERY_ENABLE", src)


if __name__ == "__main__":
    unittest.main()
