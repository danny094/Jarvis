"""
tests/unit/test_model_settings.py — Single Source of Truth: Model Config

Tests:
  MS-1  Default-only  (no override, no env)
  MS-2  Env beats default
  MS-3  Override beats env
  MS-4  get_model_overrides() -> only persisted overrides
  MS-5  get_model_settings_effective() -> correct value + source
  MS-6  update_model_settings(valid) -> persisted
  MS-7  update_model_settings(empty value) -> 422
  MS-8  update_model_settings(no fields) -> 422
  MS-9  ModelSettingsUpdate unknown field -> validation error (extra=forbid)
  MS-10 update_settings(old generic endpoint) still works
  MS-11..16 Source-inspection: no hardcoded model names in renderModels JS

Gate: python -m pytest tests/unit/test_model_settings.py -q
Expected: 19 passed, 0 failures
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_HERE = os.path.dirname(__file__)
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ---------------------------------------------------------------------------
# Load settings_routes via importlib (directory has a hyphen — not importable
# via normal dot-notation)
# ---------------------------------------------------------------------------
_ROUTES_PATH = os.path.join(_REPO_ROOT, "adapters", "admin-api", "settings_routes.py")


def _load_routes_module():
    """Load adapters/admin-api/settings_routes.py as a fresh module."""
    spec = importlib.util.spec_from_file_location("_settings_routes_test", _ROUTES_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read_source(rel: str) -> str:
    path = os.path.join(_REPO_ROOT, rel)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# MS-1 / MS-2 / MS-3  — utils/model_settings.py precedence
# ---------------------------------------------------------------------------

from utils.model_settings import (
    ALLOWED_MODEL_KEYS,
    MODEL_DEFAULTS,
    get_effective_model_settings,
)


class TestEffectivePrecedenceDefaultOnly(unittest.TestCase):
    """MS-1: no override, no env -> all sources == 'default'"""

    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in ALLOWED_MODEL_KEYS}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v

    def test_all_sources_are_default(self):
        result = get_effective_model_settings({})
        for key in ALLOWED_MODEL_KEYS:
            self.assertIn(key, result)
            self.assertEqual(result[key]["source"], "default", f"{key} source")
            self.assertEqual(result[key]["value"], MODEL_DEFAULTS[key], f"{key} value")

    def test_returns_all_four_keys(self):
        result = get_effective_model_settings({})
        self.assertEqual(set(result.keys()), ALLOWED_MODEL_KEYS)


class TestEffectivePrecedenceEnvBeatsDefault(unittest.TestCase):
    """MS-2: env var set -> source == 'env'"""

    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in ALLOWED_MODEL_KEYS}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def test_env_beats_default_for_thinking(self):
        os.environ["THINKING_MODEL"] = "my-env-model:7b"
        result = get_effective_model_settings({})
        self.assertEqual(result["THINKING_MODEL"]["source"], "env")
        self.assertEqual(result["THINKING_MODEL"]["value"], "my-env-model:7b")

    def test_other_keys_still_default_when_only_one_env_set(self):
        os.environ["THINKING_MODEL"] = "my-env-model:7b"
        result = get_effective_model_settings({})
        self.assertEqual(result["CONTROL_MODEL"]["source"], "default")


class TestEffectivePrecedenceOverrideBeatsEnv(unittest.TestCase):
    """MS-3: persisted override beats env"""

    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in ALLOWED_MODEL_KEYS}
        os.environ["THINKING_MODEL"] = "env-model:7b"

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def test_override_beats_env(self):
        result = get_effective_model_settings({"THINKING_MODEL": "override-model:14b"})
        self.assertEqual(result["THINKING_MODEL"]["source"], "override")
        self.assertEqual(result["THINKING_MODEL"]["value"], "override-model:14b")

    def test_env_still_used_for_unoverridden_keys(self):
        result = get_effective_model_settings({"THINKING_MODEL": "override-model:14b"})
        self.assertEqual(result["CONTROL_MODEL"]["source"], "default")


# ---------------------------------------------------------------------------
# MS-4 … MS-10 — API contracts (direct async handler calls)
# ---------------------------------------------------------------------------

def _mock_settings(store: dict):
    m = MagicMock()
    m.settings = store
    m.get.side_effect = lambda k, d=None: store.get(k, d)
    m.set.side_effect = lambda k, v: store.update({k: v})
    return m


class TestModelSettingsAPI(unittest.TestCase):

    def _build_routes(self, store=None):
        """Return (routes_module, mock_settings, store) with isolated route module."""
        routes = _load_routes_module()
        store = dict(store or {})
        ms = _mock_settings(store)
        routes.settings = ms
        return routes, ms, store

    def test_ms4_get_models_returns_only_overrides(self):
        """get_model_overrides() returns only persisted model keys."""
        routes, _ms, _store = self._build_routes(
            {"THINKING_MODEL": "my-override:7b", "CONTEXT_COMPRESSION_ENABLED": True}
        )
        data = asyncio.run(routes.get_model_overrides())
        self.assertIn("THINKING_MODEL", data)
        self.assertNotIn("CONTEXT_COMPRESSION_ENABLED", data)
        self.assertEqual(data["THINKING_MODEL"], "my-override:7b")

    def test_ms5_get_models_effective_sources(self):
        """get_model_settings_effective() returns correct value + source."""
        routes, _ms, _store = self._build_routes({"THINKING_MODEL": "override-think:14b"})
        with patch.dict(os.environ, {k: "" for k in ALLOWED_MODEL_KEYS}):
            body = asyncio.run(routes.get_model_settings_effective())
        eff = body["effective"]
        self.assertEqual(eff["THINKING_MODEL"]["source"], "override")
        self.assertEqual(eff["THINKING_MODEL"]["value"], "override-think:14b")
        self.assertEqual(eff["CONTROL_MODEL"]["source"], "default")
        self.assertIn("defaults", body)

    def test_ms6_post_models_valid_persists(self):
        """update_model_settings(valid) persists values."""
        routes, _ms, store = self._build_routes()
        payload = routes.ModelSettingsUpdate(
            THINKING_MODEL="new-model:7b",
            CONTROL_MODEL="ctrl:3b",
        )
        result = asyncio.run(routes.update_model_settings(payload))
        self.assertTrue(result["success"])
        self.assertEqual(store.get("THINKING_MODEL"), "new-model:7b")
        self.assertEqual(store.get("CONTROL_MODEL"), "ctrl:3b")

    def test_ms7_post_models_empty_value_returns_422(self):
        """update_model_settings() with whitespace-only value raises HTTPException(422)."""
        from fastapi import HTTPException

        routes, _ms, _store = self._build_routes()
        payload = routes.ModelSettingsUpdate(THINKING_MODEL="   ")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(routes.update_model_settings(payload))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_ms8_post_models_no_fields_returns_422(self):
        """update_model_settings() with no fields raises HTTPException(422)."""
        from fastapi import HTTPException

        routes, _ms, _store = self._build_routes()
        payload = routes.ModelSettingsUpdate()
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(routes.update_model_settings(payload))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_ms9_post_models_unknown_field_returns_422(self):
        """ModelSettingsUpdate unknown field raises validation error (extra=forbid)."""
        from pydantic import ValidationError

        routes, _ms, _store = self._build_routes()
        with self.assertRaises(ValidationError):
            routes.ModelSettingsUpdate.model_validate({"THINKING_MODEL": "x", "FOO": "bar"})

    def test_ms10_old_post_settings_still_works(self):
        """update_settings() (old generic endpoint) remains functional."""
        routes, _ms, store = self._build_routes()
        result = asyncio.run(routes.update_settings({"THINKING_MODEL": "compat-model:3b"}))
        self.assertTrue(result["success"])
        self.assertEqual(store.get("THINKING_MODEL"), "compat-model:3b")


# ---------------------------------------------------------------------------
# MS-11..16 — Source inspection: no hardcoded model names in settings.js
# ---------------------------------------------------------------------------

class TestJSSourceNoHardcodedDefaults(unittest.TestCase):
    """Verify settings.js has no hardcoded model preselects."""

    def _src(self):
        return _read_source("adapters/Jarvis/js/apps/settings.js")

    def test_no_deepseek_hardcoded(self):
        self.assertNotIn("deepseek-r1:8b", self._src())

    def test_no_qwen3_hardcoded(self):
        self.assertNotIn("qwen3:4b", self._src())

    def test_no_llama3_hardcoded(self):
        self.assertNotIn("llama3.2:3b", self._src())

    def test_no_todo_fetch_comment(self):
        self.assertNotIn("TODO: Fetch actual current setting", self._src())

    def test_uses_effective_endpoint(self):
        self.assertIn("/api/settings/models/effective", self._src())

    def test_saves_to_typed_endpoint(self):
        self.assertIn("/api/settings/models", self._src())


if __name__ == "__main__":
    unittest.main()
