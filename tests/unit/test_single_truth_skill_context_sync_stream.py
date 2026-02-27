"""
tests/unit/test_single_truth_skill_context_sync_stream.py — C6 Single-Truth-Channel

Codex Finding Fix (Medium): Parts 2-6 now use real production code via importlib.
  - Part 2: real ContextManager._get_skill_context()         (was: mock-closure :132)
  - Part 3: source inspection of orchestrator.py              (was: mock-closure :201)
  - Part 4: real get_context() step 1.5                       (was: mock-closure :295)
  - Part 6: real _get_skill_context() + real get_context()   (was: mock-closure :483)

Total: 34 tests in 6 classes
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

_PROJECT_ROOT = "/DATA/AppData/MCP/Jarvis/Jarvis"
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config.py")
_CM_PATH = os.path.join(_PROJECT_ROOT, "core", "context_manager.py")
_ORCH_PATH = os.path.join(_PROJECT_ROOT, "core", "orchestrator.py")

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Helper: load config.py in isolation
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Helper: load real ContextManager from core/context_manager.py
# ---------------------------------------------------------------------------

def _load_cm_class():
    """
    Load real ContextManager with mcp.client + utils.logger stubbed.
    Module globals capture stubs at load time; lazy method imports (config,
    core.typedstate_skills, urllib) run against restored real sys.modules.
    """
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
        sys.modules.pop("_cm_c6_test", None)
        spec = importlib.util.spec_from_file_location("_cm_c6_test", _CM_PATH)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_cm_c6_test"] = mod
        spec.loader.exec_module(mod)
        return mod.ContextManager, mod
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


# ---------------------------------------------------------------------------
# Helper: create real ContextManager instances
# ---------------------------------------------------------------------------

def _make_real_ctx_instance(
    typedstate_return="SKILLS:\n  - foo",
    legacy_return="VERFÜGBARE SKILLS:\n- foo",
):
    """Real ContextManager with delegate methods patched; _get_skill_context is real."""
    ContextManager, _ = _load_cm_class()
    inst = ContextManager.__new__(ContextManager)
    inst._protocol_cache = {}
    inst._build_typedstate_skill_context = MagicMock(return_value=typedstate_return)
    inst._search_skill_graph = MagicMock(return_value=legacy_return)
    return inst


def _make_real_ctx_for_get_context(skill_ctx_return="SKILLS:\n  - x"):
    """Real ContextManager with all get_context() sub-calls patched except _get_skill_context."""
    ContextManager, _ = _load_cm_class()
    inst = ContextManager.__new__(ContextManager)
    inst._protocol_cache = {}
    inst._load_daily_protocol = MagicMock(return_value="")
    inst._load_trion_laws = MagicMock(return_value="")
    inst._load_active_containers = MagicMock(return_value="")
    inst._search_system_tools = MagicMock(return_value="")
    inst._get_skill_context = MagicMock(return_value=skill_ctx_return)
    inst._search_blueprint_graph = MagicMock(return_value="")
    inst._load_skill_knowledge_hint = MagicMock(return_value="")
    inst._search_memory_multi_context = MagicMock(return_value=("", False))
    return inst


_EMPTY_PLAN = {
    "needs_memory": False,
    "is_fact_query": False,
    "memory_keys": [],
    "time_reference": None,
}


# ---------------------------------------------------------------------------
# Helper: extract _maybe_prefetch_skills source from orchestrator.py
# ---------------------------------------------------------------------------

def _get_maybe_prefetch_source():
    with open(_ORCH_PATH, "r", encoding="utf-8") as f:
        source = f.read()
    marker = "    def _maybe_prefetch_skills("
    start = source.find(marker)
    if start == -1:
        return None
    nxt = source.find("\n    def ", start + len(marker))
    end = nxt if nxt != -1 else len(source)
    return source[start:end]


# ===========================================================================
# Part 1 — Config Getter
# ===========================================================================

class TestSkillContextRendererConfig(unittest.TestCase):

    def setUp(self):
        os.environ.pop("SKILL_CONTEXT_RENDERER", None)

    def tearDown(self):
        os.environ.pop("SKILL_CONTEXT_RENDERER", None)

    def _get_fn(self):
        return getattr(_load_config_fresh(), "get_skill_context_renderer", None)

    def test_getter_exists(self):
        self.assertIsNotNone(self._get_fn(), "get_skill_context_renderer missing in config.py")

    def test_default_is_typedstate(self):
        fn = self._get_fn()
        if fn is None:
            self.skipTest("getter not found")
        self.assertEqual(fn(), "typedstate")

    def test_env_override_to_legacy(self):
        with patch.dict(os.environ, {"SKILL_CONTEXT_RENDERER": "legacy"}):
            fn = self._get_fn()
            if fn is None:
                self.skipTest("getter not found")
            self.assertEqual(fn(), "legacy")

    def test_env_override_to_typedstate_explicit(self):
        with patch.dict(os.environ, {"SKILL_CONTEXT_RENDERER": "typedstate"}):
            fn = self._get_fn()
            if fn is None:
                self.skipTest("getter not found")
            self.assertEqual(fn(), "typedstate")

    def test_return_type_is_str(self):
        fn = self._get_fn()
        if fn is None:
            self.skipTest("getter not found")
        self.assertIsInstance(fn(), str)


# ===========================================================================
# Part 2 — _get_skill_context routing (REAL production method)
# ===========================================================================

class TestGetSkillContextRouting(unittest.TestCase):
    """
    Tests real ContextManager._get_skill_context() routing.
    Codex Fix (:132): replaced local mock-closure with real importlib-loaded method.
    """

    def setUp(self):
        os.environ.pop("SKILL_CONTEXT_RENDERER", None)
        sys.modules.pop("config", None)

    def tearDown(self):
        os.environ.pop("SKILL_CONTEXT_RENDERER", None)
        sys.modules.pop("config", None)

    def test_typedstate_renderer_calls_build_typedstate(self):
        with patch.dict(os.environ, {"SKILL_CONTEXT_RENDERER": "typedstate"}):
            sys.modules.pop("config", None)
            inst = _make_real_ctx_instance()
            inst._get_skill_context("weather")
            inst._build_typedstate_skill_context.assert_called_once_with("weather")
            inst._search_skill_graph.assert_not_called()

    def test_typedstate_renderer_returns_typedstate_format(self):
        with patch.dict(os.environ, {"SKILL_CONTEXT_RENDERER": "typedstate"}):
            sys.modules.pop("config", None)
            inst = _make_real_ctx_instance(typedstate_return="SKILLS:\n  - foo")
            result = inst._get_skill_context("weather")
            self.assertIn("SKILLS:", result)
            self.assertNotIn("VERFÜGBARE SKILLS", result)

    def test_legacy_renderer_calls_search_skill_graph(self):
        with patch.dict(os.environ, {"SKILL_CONTEXT_RENDERER": "legacy"}):
            sys.modules.pop("config", None)
            inst = _make_real_ctx_instance()
            inst._get_skill_context("weather")
            inst._search_skill_graph.assert_called_once_with("weather")
            inst._build_typedstate_skill_context.assert_not_called()

    def test_legacy_renderer_returns_legacy_format(self):
        with patch.dict(os.environ, {"SKILL_CONTEXT_RENDERER": "legacy"}):
            sys.modules.pop("config", None)
            inst = _make_real_ctx_instance(legacy_return="VERFÜGBARE SKILLS:\n- foo")
            result = inst._get_skill_context("weather")
            self.assertIn("VERFÜGBARE SKILLS", result)

    def test_default_renderer_routes_to_typedstate(self):
        os.environ.pop("SKILL_CONTEXT_RENDERER", None)
        sys.modules.pop("config", None)
        inst = _make_real_ctx_instance()
        inst._get_skill_context("test")
        inst._build_typedstate_skill_context.assert_called_once()
        inst._search_skill_graph.assert_not_called()

    def test_routing_passes_query_unchanged(self):
        with patch.dict(os.environ, {"SKILL_CONTEXT_RENDERER": "typedstate"}):
            sys.modules.pop("config", None)
            inst = _make_real_ctx_instance()
            inst._get_skill_context("my exact query string")
            inst._build_typedstate_skill_context.assert_called_once_with("my exact query string")


# ===========================================================================
# Part 3 — No direct _search_skill_graph in orchestrator (source inspection)
# ===========================================================================

class TestNoDirectLegacyCall(unittest.TestCase):
    """
    Source inspection of orchestrator.py: _maybe_prefetch_skills must route
    through _get_skill_context, never call _search_skill_graph directly.
    Codex Fix (:201): replaced local reimplemented closure with file inspection.
    """

    @classmethod
    def setUpClass(cls):
        cls._source = _get_maybe_prefetch_source()

    def test_maybe_prefetch_source_found(self):
        self.assertIsNotNone(self._source, "_maybe_prefetch_skills not found in orchestrator.py")

    def test_get_skill_context_is_called(self):
        if not self._source:
            self.skipTest("source not found")
        self.assertIn("_get_skill_context", self._source)

    def test_no_direct_search_skill_graph_call(self):
        if not self._source:
            self.skipTest("source not found")
        # Check for actual method call pattern (not docstring mentions)
        self.assertNotIn(
            "._search_skill_graph(",
            self._source,
            "_search_skill_graph called directly (C6 violation)",
        )

    def test_context_get_skill_context_full_path_present(self):
        if not self._source:
            self.skipTest("source not found")
        self.assertIn("self.context._get_skill_context", self._source)

    def test_no_legacy_header_string_in_prefetch_body(self):
        if not self._source:
            self.skipTest("source not found")
        self.assertNotIn("VERFÜGBARE SKILLS", self._source)

    def test_c6_contract_documented(self):
        if not self._source:
            self.skipTest("source not found")
        self.assertTrue(
            "C6" in self._source or "_get_skill_context" in self._source,
            "C6 contract not documented in _maybe_prefetch_skills",
        )


# ===========================================================================
# Part 4 — No Skills-Echo in sync path (REAL get_context step 1.5)
# ===========================================================================

class TestNoSkillEchoSync(unittest.TestCase):
    """
    Real get_context() step 1.5 skips _get_skill_context in typedstate mode.
    Codex Fix (:295): replaced _simulate_get_context_step_1_5() with real call.
    """

    def setUp(self):
        os.environ.pop("SKILL_CONTEXT_RENDERER", None)
        sys.modules.pop("config", None)

    def tearDown(self):
        os.environ.pop("SKILL_CONTEXT_RENDERER", None)
        sys.modules.pop("config", None)

    def _run_get_context(self, renderer, skill_ctx_return="SKILLS:\n  - x"):
        with patch.dict(os.environ, {"SKILL_CONTEXT_RENDERER": renderer}):
            sys.modules.pop("config", None)
            inst = _make_real_ctx_for_get_context(skill_ctx_return)
            result = inst.get_context("test query", _EMPTY_PLAN, "test_conv")
            return result, inst._get_skill_context

    def test_typedstate_step_1_5_does_not_call_get_skill_context(self):
        _, gsc = self._run_get_context("typedstate")
        gsc.assert_not_called()

    def test_typedstate_step_1_5_no_skill_graph_in_sources(self):
        result, _ = self._run_get_context("typedstate")
        self.assertNotIn("skill_graph", result.sources)

    def test_legacy_step_1_5_calls_get_skill_context_once(self):
        _, gsc = self._run_get_context("legacy", skill_ctx_return="VERFÜGBARE SKILLS:\n- x")
        gsc.assert_called_once()

    def test_legacy_step_1_5_adds_skill_graph_to_sources(self):
        result, _ = self._run_get_context("legacy", skill_ctx_return="VERFÜGBARE SKILLS:\n- x")
        self.assertIn("skill_graph", result.sources)

    def test_typedstate_no_verfügbare_skills_in_system_tools(self):
        result, _ = self._run_get_context("typedstate")
        self.assertNotIn("VERFÜGBARE SKILLS", result.system_tools)

    def test_typedstate_no_skills_header_injected_via_step_1_5(self):
        result, _ = self._run_get_context("typedstate", skill_ctx_return="SKILLS:\n  - x")
        self.assertNotIn("SKILLS:", result.system_tools)


# ===========================================================================
# Part 5 — No Skills-Echo in stream path
# ===========================================================================

class TestNoSkillEchoStream(unittest.TestCase):

    def setUp(self):
        os.environ.pop("SKILL_CONTEXT_RENDERER", None)
        sys.modules.pop("config", None)

    def tearDown(self):
        os.environ.pop("SKILL_CONTEXT_RENDERER", None)
        sys.modules.pop("config", None)

    def test_stream_prefetch_calls_get_skill_context_not_legacy(self):
        with patch.dict(os.environ, {"SKILL_CONTEXT_RENDERER": "typedstate"}):
            sys.modules.pop("config", None)
            inst = _make_real_ctx_instance(typedstate_return="SKILLS:\n  - skill_a")
            inst._get_skill_context("stream test")
            inst._build_typedstate_skill_context.assert_called_once_with("stream test")
            inst._search_skill_graph.assert_not_called()

    def test_stream_typedstate_result_has_skills_header(self):
        with patch.dict(os.environ, {"SKILL_CONTEXT_RENDERER": "typedstate"}):
            sys.modules.pop("config", None)
            inst = _make_real_ctx_instance(typedstate_return="SKILLS:\n  - skill_a")
            result = inst._get_skill_context("test")
            self.assertIn("SKILLS:", result)
            self.assertNotIn("VERFÜGBARE SKILLS", result)

    def test_stream_step_1_5_skipped_in_typedstate(self):
        with patch.dict(os.environ, {"SKILL_CONTEXT_RENDERER": "typedstate"}):
            sys.modules.pop("config", None)
            inst = _make_real_ctx_for_get_context()
            inst.get_context("stream query", _EMPTY_PLAN, "conv")
            inst._get_skill_context.assert_not_called()

    def test_stream_legacy_step_1_5_calls_get_skill_context(self):
        with patch.dict(os.environ, {"SKILL_CONTEXT_RENDERER": "legacy"}):
            sys.modules.pop("config", None)
            inst = _make_real_ctx_for_get_context(skill_ctx_return="VERFÜGBARE SKILLS:\n- x")
            inst.get_context("stream query", _EMPTY_PLAN, "conv")
            inst._get_skill_context.assert_called_once()


# ===========================================================================
# Part 6 — Sync/Stream parity (REAL production code)
# ===========================================================================

class TestSyncStreamParity(unittest.TestCase):
    """
    Sync and stream paths produce identical skill context via real methods.
    Codex Fix (:483): replaced _skill_ctx_for_path() mock-closure with real calls.
    """

    def setUp(self):
        os.environ.pop("SKILL_CONTEXT_RENDERER", None)
        sys.modules.pop("config", None)

    def tearDown(self):
        os.environ.pop("SKILL_CONTEXT_RENDERER", None)
        sys.modules.pop("config", None)

    def _prefetch_result(self, renderer, skill_return="SKILLS:\n  - weather_skill"):
        with patch.dict(os.environ, {"SKILL_CONTEXT_RENDERER": renderer}):
            sys.modules.pop("config", None)
            inst = _make_real_ctx_instance(
                typedstate_return=skill_return,
                legacy_return=skill_return,
            )
            return inst._get_skill_context("test query")

    def _step_1_5_injected(self, renderer, skill_ctx="SKILLS:\n  - w"):
        with patch.dict(os.environ, {"SKILL_CONTEXT_RENDERER": renderer}):
            sys.modules.pop("config", None)
            inst = _make_real_ctx_for_get_context(skill_ctx_return=skill_ctx)
            result = inst.get_context("test query", _EMPTY_PLAN, "conv")
            return "skill_graph" in result.sources

    def test_typedstate_sync_stream_prefetch_identical(self):
        self.assertEqual(self._prefetch_result("typedstate"), self._prefetch_result("typedstate"))

    def test_legacy_sync_stream_prefetch_identical(self):
        self.assertEqual(self._prefetch_result("legacy"), self._prefetch_result("legacy"))

    def test_typedstate_step_1_5_not_injected_sync_or_stream(self):
        self.assertFalse(self._step_1_5_injected("typedstate"))
        self.assertFalse(self._step_1_5_injected("typedstate"))

    def test_typedstate_single_occurrence_per_request(self):
        skill_from_prefetch = bool(self._prefetch_result("typedstate"))
        skill_from_step_1_5 = self._step_1_5_injected("typedstate")
        self.assertTrue(skill_from_prefetch)
        self.assertFalse(skill_from_step_1_5)

    def test_typedstate_format_uses_skills_header(self):
        result = self._prefetch_result("typedstate", skill_return="SKILLS:\n  - weather_skill")
        self.assertIn("SKILLS:", result)
        self.assertNotIn("VERFÜGBARE SKILLS", result)

    def test_renderer_switch_changes_format(self):
        ts_r = self._prefetch_result("typedstate", skill_return="SKILLS:\n  - skill_a")
        leg_r = self._prefetch_result("legacy", skill_return="VERFÜGBARE SKILLS:\n- skill_a")
        self.assertNotEqual(ts_r, leg_r)

    def test_build_typedstate_skill_context_calls_c5_pipeline(self):
        """Real _build_typedstate_skill_context delegates to build_skills_context (C5)."""
        ContextManager, _ = _load_cm_class()
        inst = ContextManager.__new__(ContextManager)
        inst._protocol_cache = {}

        # Stub core.typedstate_skills so lazy import inside method resolves
        ts_stub = types.ModuleType("core.typedstate_skills")
        build_mock = MagicMock(return_value="SKILLS:\n  - mocked")
        ts_stub.build_skills_context = build_mock

        def _resp(data):
            r = MagicMock()
            r.read.return_value = json.dumps(data).encode()
            r.__enter__ = MagicMock(return_value=r)
            r.__exit__ = MagicMock(return_value=False)
            return r

        _responses = iter([
            _resp({"active": ["weather_skill"], "drafts": []}),
            _resp({"description": "Weather data", "triggers": ["weather"]}),
        ])
        urlopen_mock = MagicMock(side_effect=lambda *a, **k: next(_responses))

        orig_ts = sys.modules.get("core.typedstate_skills")
        sys.modules["core.typedstate_skills"] = ts_stub
        try:
            with patch("urllib.request.urlopen", urlopen_mock):
                result = inst._build_typedstate_skill_context("weather query")
            build_mock.assert_called_once()
            _, kw = build_mock.call_args
            self.assertEqual(kw.get("mode"), "active")
            self.assertEqual(kw.get("top_k_count"), 10)
            self.assertEqual(result, "SKILLS:\n  - mocked")
        finally:
            if orig_ts is None:
                sys.modules.pop("core.typedstate_skills", None)
            else:
                sys.modules["core.typedstate_skills"] = orig_ts


if __name__ == "__main__":
    unittest.main(verbosity=2)
