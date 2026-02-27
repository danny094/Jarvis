"""
tests/unit/test_embedding_resolver.py — Embedding Model Runtime Resolution

Tests:
  EM-1  config.get_embedding_model() — default (no env, no settings)
  EM-2  config.get_embedding_model() — env beats default
  EM-3  config.get_embedding_model() — settings override beats env
  EM-4  archive._get_embedding() uses get_embedding_model() per call
  EM-5  sql-memory _resolve_embedding_model() — default (no API URL)
  EM-6  sql-memory _resolve_embedding_model() — API ok → uses effective value
  EM-7  sql-memory _resolve_embedding_model() — API down → env/default fallback
  EM-8  sql-memory TTL cache: second call within TTL skips API
  EM-9  sql-memory env var beats default when no API URL
  EM-10 Source inspection: no frozen EMBEDDING_MODEL at call sites

Gate: python -m pytest tests/unit/test_embedding_resolver.py -q
Expected: 13 passed, 0 failures
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if not os.path.isfile(os.path.join(_REPO_ROOT, "config.py")):
    _REPO_ROOT = "/DATA/AppData/MCP/Jarvis/Jarvis"
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_MODEL_ENV_KEYS = {"THINKING_MODEL", "CONTROL_MODEL", "OUTPUT_MODEL", "EMBEDDING_MODEL"}
_EMBED_DEFAULT = "hellord/mxbai-embed-large-v1:f16"


def _empty_settings(key, default=None):
    return default


def _load_sqlmem_embedding():
    """Load sql-memory/embedding.py as an isolated fresh module (avoids cache state leakage)."""
    path = os.path.join(_REPO_ROOT, "sql-memory", "embedding.py")
    spec = importlib.util.spec_from_file_location("_sqlmem_embedding_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read_source(rel: str) -> str:
    path = os.path.join(_REPO_ROOT, rel)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ─────────────────────────────────────────────────────────────────────────────
# EM-1 … EM-3  config.get_embedding_model() precedence
# ─────────────────────────────────────────────────────────────────────────────

class TestConfigEmbeddingResolver(unittest.TestCase):

    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in _MODEL_ENV_KEYS}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def test_em1_default_when_no_env_no_settings(self):
        """EM-1: No env, no settings → hardcoded default."""
        with patch("config.settings.get", side_effect=_empty_settings):
            from config import get_embedding_model
            result = get_embedding_model()
        self.assertEqual(result, _EMBED_DEFAULT)

    def test_em2_env_beats_default(self):
        """EM-2: Env var → model from env."""
        os.environ["EMBEDDING_MODEL"] = "custom-embed:7b"
        with patch("config.settings.get", side_effect=_empty_settings):
            from config import get_embedding_model
            result = get_embedding_model()
        self.assertEqual(result, "custom-embed:7b")

    def test_em3_settings_override_beats_env(self):
        """EM-3: Settings override > env var."""
        os.environ["EMBEDDING_MODEL"] = "env-embed:7b"

        def settings_with_override(key, default=None):
            return "settings-embed:14b" if key == "EMBEDDING_MODEL" else default

        with patch("config.settings.get", side_effect=settings_with_override):
            from config import get_embedding_model
            result = get_embedding_model()
        self.assertEqual(result, "settings-embed:14b")


# ─────────────────────────────────────────────────────────────────────────────
# EM-4  archive._get_embedding() uses getter per call
# ─────────────────────────────────────────────────────────────────────────────

class TestArchiveEmbeddingCallSite(unittest.TestCase):

    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in _MODEL_ENV_KEYS}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def test_em4_archive_uses_getter_not_frozen_constant(self):
        """EM-4: _get_embedding() passes get_embedding_model() value to Ollama."""
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured.update(json or {})
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
            return mock_resp

        def settings_with_override(key, default=None):
            return "live-embed:8b" if key == "EMBEDDING_MODEL" else default

        with patch("config.settings.get", side_effect=settings_with_override), \
             patch("core.lifecycle.archive.requests.post", side_effect=fake_post):
            import core.lifecycle.archive as archive_mod
            archive_mod._get_embedding("hello world")

        self.assertEqual(captured.get("model"), "live-embed:8b")

    def test_em4b_archive_model_changes_between_calls(self):
        """EM-4b: Model is re-resolved on every call (not frozen at import time)."""
        models_used = []

        call_count = [0]

        def fake_post(url, json=None, timeout=None):
            models_used.append((json or {}).get("model"))
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {"embedding": [0.1]}
            return mock_resp

        def settings_dynamic(key, default=None):
            call_count[0] += 1
            if key == "EMBEDDING_MODEL":
                return f"model-call-{call_count[0]}:v1"
            return default

        with patch("config.settings.get", side_effect=settings_dynamic), \
             patch("core.lifecycle.archive.requests.post", side_effect=fake_post):
            import core.lifecycle.archive as archive_mod
            archive_mod._get_embedding("first")
            archive_mod._get_embedding("second")

        # The two calls should have resolved different model names
        self.assertEqual(len(models_used), 2)
        self.assertNotEqual(models_used[0], models_used[1],
                            "Both calls used same frozen model — getter not called per-request")


# ─────────────────────────────────────────────────────────────────────────────
# EM-5 … EM-9  sql-memory embedding resolver
# ─────────────────────────────────────────────────────────────────────────────

class TestSqlMemoryEmbeddingResolver(unittest.TestCase):

    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in _MODEL_ENV_KEYS}
        os.environ.pop("SETTINGS_API_URL", None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)
        os.environ.pop("SETTINGS_API_URL", None)

    def _load_fresh(self):
        """Fresh module load with clean cache."""
        return _load_sqlmem_embedding()

    def test_em5_default_when_no_api_url(self):
        """EM-5: No SETTINGS_API_URL → returns env/default."""
        mod = self._load_fresh()
        result = mod._resolve_embedding_model()
        self.assertEqual(result, _EMBED_DEFAULT)

    def test_em6_api_ok_returns_effective_value(self):
        """EM-6: API responds with effective value → resolver returns it."""
        mod = self._load_fresh()
        mod.SETTINGS_API_URL = "http://fake-admin:8200/api/settings"
        mod._CACHE_TTL = 60
        mod._cache = {"value": None, "ts": 0.0}

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "effective": {
                "EMBEDDING_MODEL": {"value": "api-embed:4b", "source": "override"}
            }
        }

        with patch.object(mod.requests, "get", return_value=mock_resp):
            result = mod._resolve_embedding_model()

        self.assertEqual(result, "api-embed:4b")

    def test_em7_api_down_falls_back_to_env_default(self):
        """EM-7: API raises exception → falls back to env/default."""
        mod = self._load_fresh()
        mod.SETTINGS_API_URL = "http://fake-admin:8200/api/settings"
        mod._cache = {"value": None, "ts": 0.0}
        os.environ["EMBEDDING_MODEL"] = "env-embed-fallback:7b"
        mod._EMBED_DEFAULT = "env-embed-fallback:7b"

        with patch.object(mod.requests, "get", side_effect=ConnectionError("down")):
            result = mod._resolve_embedding_model()

        self.assertEqual(result, "env-embed-fallback:7b")

    def test_em8_ttl_cache_skips_api_on_second_call(self):
        """EM-8: Second call within TTL hits cache, not the API."""
        mod = self._load_fresh()
        mod.SETTINGS_API_URL = "http://fake-admin:8200/api/settings"
        mod._CACHE_TTL = 60
        mod._cache = {"value": None, "ts": 0.0}

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "effective": {"EMBEDDING_MODEL": {"value": "cached-embed:4b", "source": "override"}}
        }

        with patch.object(mod.requests, "get", return_value=mock_resp) as mock_get:
            mod._resolve_embedding_model()  # first call — hits API
            mod._resolve_embedding_model()  # second call — should use cache

        self.assertEqual(mock_get.call_count, 1, "API was called more than once within TTL")

    def test_em9_env_var_beats_default_when_no_api(self):
        """EM-9: SETTINGS_API_URL not set, EMBEDDING_MODEL env set → env value used."""
        os.environ["EMBEDDING_MODEL"] = "env-only-embed:3b"
        mod = self._load_fresh()
        # _EMBED_DEFAULT is set at module load time from os.getenv
        result = mod._resolve_embedding_model()
        self.assertEqual(result, "env-only-embed:3b")

    def test_em7b_api_returns_empty_value_falls_through(self):
        """EM-7b: API returns empty value for EMBEDDING_MODEL → falls back to default."""
        mod = self._load_fresh()
        mod.SETTINGS_API_URL = "http://fake-admin:8200/api/settings"
        mod._cache = {"value": None, "ts": 0.0}

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "effective": {"EMBEDDING_MODEL": {"value": "", "source": "default"}}
        }

        with patch.object(mod.requests, "get", return_value=mock_resp):
            result = mod._resolve_embedding_model()

        self.assertEqual(result, _EMBED_DEFAULT)


# ─────────────────────────────────────────────────────────────────────────────
# EM-10  Source inspection
# ─────────────────────────────────────────────────────────────────────────────

class TestSourceInspection(unittest.TestCase):

    def test_archive_no_frozen_embedding_model_constant(self):
        """archive.py must not define a frozen EMBEDDING_MODEL = os.getenv(...)."""
        src = _read_source("core/lifecycle/archive.py")
        self.assertNotIn("EMBEDDING_MODEL = os.getenv", src)
        self.assertIn("get_embedding_model()", src)

    def test_archive_imports_getter(self):
        src = _read_source("core/lifecycle/archive.py")
        self.assertIn("from config import get_embedding_model", src)

    def test_sqlmem_no_frozen_embedding_model_in_get_embedding(self):
        """sql-memory/embedding.py must not use a frozen module-level constant in get_embedding."""
        src = _read_source("sql-memory/embedding.py")
        # get_embedding() must call _resolve_embedding_model(), not use module-level EMBEDDING_MODEL
        self.assertIn("_resolve_embedding_model()", src)
        # The function body must not reference the old frozen constant
        # (it may appear in _resolve_embedding_model itself as _EMBED_DEFAULT, that's ok)
        import re
        # Find the get_embedding function body
        fn_match = re.search(r"def get_embedding\(.*?\n(?=def |\Z)", src, re.DOTALL)
        self.assertIsNotNone(fn_match, "get_embedding function not found")
        fn_body = fn_match.group(0)
        self.assertNotIn('"EMBEDDING_MODEL"', fn_body,
                         "get_embedding() still references EMBEDDING_MODEL directly")

    def test_config_has_get_embedding_model_function(self):
        src = _read_source("config.py")
        self.assertIn("def get_embedding_model():", src)

    def test_sqlmem_has_resolver_function(self):
        src = _read_source("sql-memory/embedding.py")
        self.assertIn("def _resolve_embedding_model()", src)
        self.assertIn("SETTINGS_API_URL", src)


if __name__ == "__main__":
    unittest.main()
