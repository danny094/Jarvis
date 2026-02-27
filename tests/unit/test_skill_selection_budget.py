"""
tests/unit/test_skill_selection_budget.py — C10 budgeted selection

Coverage:
  - config rollback/default for SKILL_SELECTION_MODE
  - lazy detail fetch in budgeted mode
  - eager detail fetch in legacy mode
  - char-cap limiting detail fetch count
  - budgeted vs legacy parity for final rendered output
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
import unittest
from urllib.parse import unquote, urlparse
from unittest.mock import MagicMock, patch

_PROJECT_ROOT = "/DATA/AppData/MCP/Jarvis/Jarvis"
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config.py")
_CM_PATH = os.path.join(_PROJECT_ROOT, "core", "context_manager.py")

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _load_config_fresh():
    for k in list(sys.modules):
        if k == "config":
            del sys.modules[k]
    _utils_pkg = types.ModuleType("utils")
    _settings_mod = types.ModuleType("utils.settings")
    _settings_obj = MagicMock()
    _settings_obj.get = MagicMock(side_effect=lambda key, default=None: default)
    _settings_mod.settings = _settings_obj
    _utils_pkg.settings = _settings_mod
    orig = {k: sys.modules.get(k) for k in ("utils", "utils.settings")}
    sys.modules["utils"] = _utils_pkg
    sys.modules["utils.settings"] = _settings_mod
    try:
        spec = importlib.util.spec_from_file_location("config", _CONFIG_PATH)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["config"] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in orig.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def _load_cm_class():
    _mcp_pkg = types.ModuleType("mcp")
    _mcp_client = types.ModuleType("mcp.client")
    _mcp_client.get_fact_for_query = MagicMock(return_value="")
    _mcp_client.graph_search = MagicMock(return_value=[])
    _mcp_client.semantic_search = MagicMock(return_value=[])
    _mcp_client.search_memory_fallback = MagicMock(return_value="")
    _mcp_pkg.client = _mcp_client

    _utils_logger = types.ModuleType("utils.logger")
    _utils_logger.log_info = lambda *a, **k: None
    _utils_logger.log_warn = lambda *a, **k: None
    _utils_logger.log_error = lambda *a, **k: None

    _stub_keys = ("mcp", "mcp.client", "utils.logger")
    saved = {k: sys.modules.get(k) for k in _stub_keys}

    _utils_existed = "utils" in sys.modules
    saved_utils = sys.modules.get("utils")
    if not _utils_existed:
        _mini_utils = types.ModuleType("utils")
        _mini_utils.logger = _utils_logger
        sys.modules["utils"] = _mini_utils

    sys.modules["mcp"] = _mcp_pkg
    sys.modules["mcp.client"] = _mcp_client
    sys.modules["utils.logger"] = _utils_logger

    try:
        sys.modules.pop("_cm_c10_test", None)
        spec = importlib.util.spec_from_file_location("_cm_c10_test", _CM_PATH)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_cm_c10_test"] = mod
        spec.loader.exec_module(mod)
        return mod.ContextManager
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        if not _utils_existed:
            sys.modules.pop("utils", None)
        else:
            sys.modules["utils"] = saved_utils


def _resp(data):
    r = MagicMock()
    r.read.return_value = json.dumps(data).encode()
    r.__enter__ = MagicMock(return_value=r)
    r.__exit__ = MagicMock(return_value=False)
    return r


class TestSkillSelectionConfig(unittest.TestCase):

    def setUp(self):
        for k in ("SKILL_SELECTION_MODE", "SKILL_SELECTION_TOP_K", "SKILL_SELECTION_CHAR_CAP"):
            os.environ.pop(k, None)
        sys.modules.pop("config", None)

    def tearDown(self):
        for k in ("SKILL_SELECTION_MODE", "SKILL_SELECTION_TOP_K", "SKILL_SELECTION_CHAR_CAP"):
            os.environ.pop(k, None)
        sys.modules.pop("config", None)

    def test_selection_mode_default_budgeted(self):
        cfg = _load_config_fresh()
        self.assertEqual(cfg.get_skill_selection_mode(), "budgeted")

    def test_selection_mode_rollback_legacy(self):
        with patch.dict(os.environ, {"SKILL_SELECTION_MODE": "legacy"}):
            cfg = _load_config_fresh()
            self.assertEqual(cfg.get_skill_selection_mode(), "legacy")

    def test_selection_mode_invalid_falls_back_budgeted(self):
        with patch.dict(os.environ, {"SKILL_SELECTION_MODE": "invalid"}):
            cfg = _load_config_fresh()
            self.assertEqual(cfg.get_skill_selection_mode(), "budgeted")


class TestSkillSelectionBudgetedVsLegacy(unittest.TestCase):

    def setUp(self):
        for k in ("SKILL_SELECTION_MODE", "SKILL_SELECTION_TOP_K", "SKILL_SELECTION_CHAR_CAP"):
            os.environ.pop(k, None)
        sys.modules.pop("config", None)

    def tearDown(self):
        for k in ("SKILL_SELECTION_MODE", "SKILL_SELECTION_TOP_K", "SKILL_SELECTION_CHAR_CAP"):
            os.environ.pop(k, None)
        sys.modules.pop("config", None)

    def _run_build(self, *, mode: str, top_k: int, char_cap: int, active, drafts, details):
        ContextManager = _load_cm_class()
        inst = ContextManager.__new__(ContextManager)
        inst._protocol_cache = {}

        all_urls = []
        detail_names = []

        def _urlopen_side_effect(req, timeout=0):
            url = getattr(req, "full_url", req)
            all_urls.append(url)
            parsed = urlparse(url)
            path = parsed.path

            if path.endswith("/v1/skills"):
                return _resp({"active": active, "drafts": drafts})

            if "/v1/skills/" in path:
                name = unquote(path.rsplit("/", 1)[-1])
                detail_names.append(name)
                return _resp(details.get(name, {}))

            raise AssertionError(f"Unexpected URL called: {url}")

        env = {
            "SKILL_SERVER_URL": "http://skill-server.test",
            "SKILL_SELECTION_MODE": mode,
            "SKILL_SELECTION_TOP_K": str(top_k),
            "SKILL_SELECTION_CHAR_CAP": str(char_cap),
        }
        with patch.dict(os.environ, env, clear=False):
            sys.modules.pop("config", None)
            with patch("urllib.request.urlopen", side_effect=_urlopen_side_effect):
                result = inst._build_typedstate_skill_context("test query")
        return result, detail_names, all_urls

    def test_budgeted_fetches_only_selected_active_details(self):
        details = {
            "alpha": {"description": "alpha desc", "triggers": ["a"]},
            "beta": {"description": "beta desc", "triggers": ["b"]},
            "gamma": {"description": "gamma desc", "triggers": ["g"]},
        }
        result, detail_names, _ = self._run_build(
            mode="budgeted",
            top_k=2,
            char_cap=2000,
            active=["alpha", "beta", "gamma"],
            drafts=[],
            details=details,
        )
        self.assertEqual(detail_names, ["alpha", "beta"])
        self.assertIn("SKILLS:", result)
        self.assertIn("alpha", result)
        self.assertIn("beta", result)
        self.assertNotIn("gamma", result)

    def test_legacy_fetches_all_active_details(self):
        details = {
            "alpha": {"description": "alpha desc", "triggers": ["a"]},
            "beta": {"description": "beta desc", "triggers": ["b"]},
            "gamma": {"description": "gamma desc", "triggers": ["g"]},
        }
        result, detail_names, _ = self._run_build(
            mode="legacy",
            top_k=2,
            char_cap=2000,
            active=["alpha", "beta", "gamma"],
            drafts=[],
            details=details,
        )
        self.assertEqual(detail_names, ["alpha", "beta", "gamma"])
        self.assertIn("SKILLS:", result)
        self.assertIn("alpha", result)
        self.assertIn("beta", result)
        self.assertNotIn("gamma", result)

    def test_budgeted_char_cap_limits_detail_fetch(self):
        long_a = "a" * 110
        long_b = "b" * 110
        long_c = "c" * 110
        details = {
            long_a: {"description": "A"},
            long_b: {"description": "B"},
            long_c: {"description": "C"},
        }
        result, detail_names, _ = self._run_build(
            mode="budgeted",
            top_k=3,
            char_cap=200,
            active=[long_a, long_b, long_c],
            drafts=[],
            details=details,
        )
        self.assertEqual(detail_names, [long_a])
        self.assertIn("SKILLS:", result)
        self.assertIn(long_a, result)
        self.assertNotIn(long_b, result)
        self.assertNotIn(long_c, result)

    def test_budgeted_does_not_fetch_draft_details(self):
        details = {"alpha_active": {"description": "active"}}
        result, detail_names, _ = self._run_build(
            mode="budgeted",
            top_k=2,
            char_cap=2000,
            active=["alpha_active"],
            drafts=["alpha_draft"],
            details=details,
        )
        self.assertEqual(detail_names, ["alpha_active"])
        self.assertIn("alpha_active", result)
        self.assertIn("alpha_draft", result)

    def test_budgeted_legacy_parity_for_same_caps(self):
        details = {
            "alpha": {"description": "alpha desc", "triggers": ["a"]},
            "beta": {"description": "beta desc", "triggers": ["b"]},
            "gamma": {"description": "gamma desc", "triggers": ["g"]},
        }
        budgeted_result, _, _ = self._run_build(
            mode="budgeted",
            top_k=2,
            char_cap=2000,
            active=["alpha", "beta", "gamma"],
            drafts=[],
            details=details,
        )
        legacy_result, _, _ = self._run_build(
            mode="legacy",
            top_k=2,
            char_cap=2000,
            active=["alpha", "beta", "gamma"],
            drafts=[],
            details=details,
        )
        self.assertEqual(budgeted_result, legacy_result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
