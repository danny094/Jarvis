"""
tests/unit/test_live_model_resolution.py — Live Model Resolution

Tests:
  LR-1  ThinkingLayer — default (no env, no override)
  LR-2  ThinkingLayer — env var beats default
  LR-3  ThinkingLayer — settings override beats env
  LR-4  ThinkingLayer — explicit init model beats settings
  LR-5  ControlLayer._resolve_model() — same precedence
  LR-6  ControlLayer._resolve_sequential_model() — always get_thinking_model()
  LR-7  ControlLayer — explicit init model beats settings
  LR-8  OutputLayer.generate_stream_sync(model=None) → get_output_model() called
  LR-9  OutputLayer.generate_stream_sync(model="x") → getter NOT called
  LR-10 Whitespace-only model treated as no-override (falls through to getter)
  LR-11 Source inspection: frozen constants removed from call sites

Gate: python -m pytest tests/unit/test_live_model_resolution.py -q
Expected: 21 passed, 0 failures
"""
from __future__ import annotations

import os
import sys
import importlib.util
import unittest
from unittest.mock import patch, MagicMock, call

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
# Fallback when running from /tmp (dev/CI)
if not os.path.isfile(os.path.join(_REPO_ROOT, "config.py")):
    _REPO_ROOT = "/DATA/AppData/MCP/Jarvis/Jarvis"
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _read_source(rel: str) -> str:
    path = os.path.join(_REPO_ROOT, rel)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _empty_settings(key, default=None):
    """Simulate a settings store with no persisted overrides."""
    return default


_MODEL_ENV_KEYS = {"THINKING_MODEL", "CONTROL_MODEL", "OUTPUT_MODEL", "EMBEDDING_MODEL"}


# ─────────────────────────────────────────────────────────────────────────────
# Shared helper: mock httpx.Client for sync streaming
# ─────────────────────────────────────────────────────────────────────────────

def _setup_mock_sync_client(mock_httpx):
    """Configure mock_httpx.Client so generate_stream_sync completes without network."""
    mock_resp = MagicMock()
    mock_resp.iter_lines.return_value = iter([])
    mock_resp.raise_for_status.return_value = None

    mock_stream = MagicMock()
    mock_stream.__enter__.return_value = mock_resp
    mock_stream.__exit__.return_value = False

    mock_client_inst = MagicMock()
    mock_client_inst.stream.return_value = mock_stream

    mock_httpx.Client.return_value.__enter__.return_value = mock_client_inst
    mock_httpx.Client.return_value.__exit__.return_value = False

    return mock_client_inst  # caller can inspect .stream.call_args


# ─────────────────────────────────────────────────────────────────────────────
# LR-1 … LR-4  ThinkingLayer
# ─────────────────────────────────────────────────────────────────────────────

class TestThinkingLayerResolution(unittest.TestCase):

    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in _MODEL_ENV_KEYS}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def _make_layer(self, model=None):
        with patch.dict("sys.modules", {
            "mcp.hub": MagicMock(),
            "utils.logger": MagicMock(),
            "utils.json_parser": MagicMock(),
        }):
            from core.layers.thinking import ThinkingLayer
            return ThinkingLayer(model=model)

    def test_lr1_default_when_no_env_no_settings(self):
        """LR-1: No env, no settings → default from config."""
        with patch("config.settings.get", side_effect=_empty_settings):
            layer = self._make_layer()
            result = layer._resolve_model()
        self.assertEqual(result, "ministral-3:8b")

    def test_lr2_env_beats_default(self):
        """LR-2: Env var → model comes from env."""
        os.environ["THINKING_MODEL"] = "env-think:7b"
        with patch("config.settings.get", side_effect=_empty_settings):
            layer = self._make_layer()
            result = layer._resolve_model()
        self.assertEqual(result, "env-think:7b")

    def test_lr3_settings_override_beats_env(self):
        """LR-3: Settings override > env var."""
        os.environ["THINKING_MODEL"] = "env-think:7b"

        def settings_with_override(key, default=None):
            if key == "THINKING_MODEL":
                return "settings-think:14b"
            return default

        with patch("config.settings.get", side_effect=settings_with_override):
            layer = self._make_layer()
            result = layer._resolve_model()
        self.assertEqual(result, "settings-think:14b")

    def test_lr4_explicit_init_model_beats_settings(self):
        """LR-4: Explicit model at ThinkingLayer(model=...) always wins."""
        os.environ["THINKING_MODEL"] = "env-think:7b"

        def settings_with_override(key, default=None):
            return "settings-think:14b" if key == "THINKING_MODEL" else default

        with patch("config.settings.get", side_effect=settings_with_override):
            layer = self._make_layer(model="explicit-think:32b")
            result = layer._resolve_model()
        self.assertEqual(result, "explicit-think:32b")

    def test_lr4b_none_model_falls_through_to_getter(self):
        """LR-4b: ThinkingLayer(model=None) falls through to getter."""
        with patch("config.settings.get", side_effect=_empty_settings):
            layer = self._make_layer(model=None)
            result = layer._resolve_model()
        self.assertEqual(result, "ministral-3:8b")


# ─────────────────────────────────────────────────────────────────────────────
# LR-5 … LR-7  ControlLayer
# ─────────────────────────────────────────────────────────────────────────────

class TestControlLayerResolution(unittest.TestCase):

    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in _MODEL_ENV_KEYS}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def _make_layer(self, model=None):
        mocks = {
            "core.safety": MagicMock(),
            "core.safety.light_cim": MagicMock(),
            "core.sequential_registry": MagicMock(),
            "core.autonomous": MagicMock(),
            "core.autonomous.master": MagicMock(),
            "intelligence_modules": MagicMock(),
            "intelligence_modules.cim_policy": MagicMock(),
            "intelligence_modules.cim_policy.cim_policy_engine": MagicMock(),
            "utils.logger": MagicMock(),
            "utils.json_parser": MagicMock(),
        }
        path = os.path.join(_REPO_ROOT, "core", "layers", "control.py")
        with patch.dict("sys.modules", mocks):
            spec = importlib.util.spec_from_file_location("_ctrl_test", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.ControlLayer(model=model)

    def test_lr5_control_default(self):
        """LR-5: No env, no settings → get_control_model() default."""
        with patch("config.settings.get", side_effect=_empty_settings):
            layer = self._make_layer()
            result = layer._resolve_model()
        self.assertEqual(result, "ministral-3:8b")

    def test_lr5b_control_env(self):
        """LR-5b: Env set → control model from env."""
        os.environ["CONTROL_MODEL"] = "env-ctrl:3b"
        with patch("config.settings.get", side_effect=_empty_settings):
            layer = self._make_layer()
            result = layer._resolve_model()
        self.assertEqual(result, "env-ctrl:3b")

    def test_lr6_sequential_model_always_uses_getter(self):
        """LR-6: _resolve_sequential_model() always calls get_thinking_model()."""
        os.environ["THINKING_MODEL"] = "seq-think:7b"
        with patch("config.settings.get", side_effect=_empty_settings):
            layer = self._make_layer()
            result = layer._resolve_sequential_model()
        self.assertEqual(result, "seq-think:7b")

    def test_lr7_explicit_init_model_beats_all(self):
        """LR-7: Explicit model at ControlLayer(model=...) always wins."""
        def settings_with_ctrl(key, default=None):
            return "settings-ctrl:8b" if key == "CONTROL_MODEL" else default

        with patch("config.settings.get", side_effect=settings_with_ctrl):
            layer = self._make_layer(model="explicit-ctrl:14b")
            result = layer._resolve_model()
        self.assertEqual(result, "explicit-ctrl:14b")


# ─────────────────────────────────────────────────────────────────────────────
# LR-8 … LR-10  OutputLayer — real layer method calls
# ─────────────────────────────────────────────────────────────────────────────

class TestOutputLayerResolution(unittest.TestCase):

    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in _MODEL_ENV_KEYS}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def _run_sync(self, layer, model_arg):
        """
        Call generate_stream_sync with mocked httpx; return the model
        that was passed to the Ollama payload.
        """
        import core.layers.output as out_mod

        with patch.object(layer, "_build_full_prompt", return_value="test-prompt"), \
             patch.object(out_mod, "httpx") as mock_httpx:
            mock_client_inst = _setup_mock_sync_client(mock_httpx)
            gen = layer.generate_stream_sync("hello", {}, model=model_arg)
            list(gen)  # exhaust generator
            mock_client_inst.stream.assert_called_once()
            json_payload = mock_client_inst.stream.call_args[1].get("json", {})
            return json_payload.get("model")

    def test_lr8_none_model_uses_getter(self):
        """LR-8: generate_stream_sync(model=None) → get_output_model() value used."""
        from core.layers.output import OutputLayer
        layer = OutputLayer()
        with patch("config.settings.get", side_effect=_empty_settings):
            model = self._run_sync(layer, model_arg=None)
        self.assertEqual(model, "ministral-3:3b")

    def test_lr9_explicit_model_beats_getter(self):
        """LR-9: generate_stream_sync(model='x:7b') → getter NOT called, arg value used."""
        from core.layers.output import OutputLayer
        import core.layers.output as out_mod
        layer = OutputLayer()

        with patch("config.get_output_model") as mock_getter, \
             patch.object(layer, "_build_full_prompt", return_value="p"), \
             patch.object(out_mod, "httpx") as mock_httpx:
            _setup_mock_sync_client(mock_httpx)
            gen = layer.generate_stream_sync("hello", {}, model="explicit-out:7b")
            list(gen)

        mock_getter.assert_not_called()

    def test_lr10_whitespace_model_falls_through_to_getter(self):
        """LR-10: generate_stream_sync(model='   ') → treated as absent, getter used."""
        from core.layers.output import OutputLayer
        layer = OutputLayer()
        with patch("config.settings.get", side_effect=_empty_settings):
            model = self._run_sync(layer, model_arg="   ")
        self.assertEqual(model, "ministral-3:3b")


# ─────────────────────────────────────────────────────────────────────────────
# LR-10b  Whitespace stripping in ThinkingLayer / ControlLayer __init__
# ─────────────────────────────────────────────────────────────────────────────

class TestWhitespaceOverride(unittest.TestCase):

    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in _MODEL_ENV_KEYS}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def test_thinking_whitespace_model_falls_through(self):
        """Whitespace-only model at ThinkingLayer(model='   ') falls through to getter."""
        with patch.dict("sys.modules", {
            "mcp.hub": MagicMock(),
            "utils.logger": MagicMock(),
            "utils.json_parser": MagicMock(),
        }), patch("config.settings.get", side_effect=_empty_settings):
            from core.layers.thinking import ThinkingLayer
            layer = ThinkingLayer(model="   ")
            result = layer._resolve_model()
        self.assertEqual(result, "ministral-3:8b")

    def test_control_whitespace_model_falls_through(self):
        """Whitespace-only model at ControlLayer(model='   ') falls through to getter."""
        mocks = {
            "core.safety": MagicMock(), "core.safety.light_cim": MagicMock(),
            "core.sequential_registry": MagicMock(), "core.autonomous": MagicMock(),
            "core.autonomous.master": MagicMock(), "intelligence_modules": MagicMock(),
            "intelligence_modules.cim_policy": MagicMock(),
            "intelligence_modules.cim_policy.cim_policy_engine": MagicMock(),
            "utils.logger": MagicMock(), "utils.json_parser": MagicMock(),
        }
        path = os.path.join(_REPO_ROOT, "core", "layers", "control.py")
        with patch.dict("sys.modules", mocks):
            spec = importlib.util.spec_from_file_location("_ctrl_ws", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            with patch("config.settings.get", side_effect=_empty_settings):
                layer = mod.ControlLayer(model="   ")
                result = layer._resolve_model()
        self.assertEqual(result, "ministral-3:8b")


# ─────────────────────────────────────────────────────────────────────────────
# LR-11  Source inspection
# ─────────────────────────────────────────────────────────────────────────────

class TestSourceInspection(unittest.TestCase):
    """Frozen constants must not appear in call-site code paths."""

    def test_thinking_import_uses_getter(self):
        src = _read_source("core/layers/thinking.py")
        self.assertIn("get_thinking_model", src)
        self.assertNotIn("from config import OLLAMA_BASE, THINKING_MODEL", src)

    def test_thinking_payload_uses_resolve_method(self):
        src = _read_source("core/layers/thinking.py")
        self.assertIn("_resolve_model()", src)

    def test_control_import_uses_getters(self):
        src = _read_source("core/layers/control.py")
        self.assertIn("get_control_model", src)
        self.assertNotIn("from config import OLLAMA_BASE, CONTROL_MODEL, THINKING_MODEL", src)

    def test_control_call_sites_use_resolve(self):
        src = _read_source("core/layers/control.py")
        self.assertIn("_resolve_model()", src)
        self.assertIn("_resolve_sequential_model()", src)

    def test_output_import_uses_getter(self):
        src = _read_source("core/layers/output.py")
        self.assertIn("get_output_model", src)

    def test_output_no_frozen_fallback(self):
        src = _read_source("core/layers/output.py")
        self.assertNotIn("model or OUTPUT_MODEL", src)


if __name__ == "__main__":
    unittest.main()
