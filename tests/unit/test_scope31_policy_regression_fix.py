from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import unittest
from unittest.mock import MagicMock, patch


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_ADMIN_API_PATH = os.path.join(_REPO_ROOT, "adapters", "admin-api")


def _load_sqlmem_embedding():
    path = os.path.join(_REPO_ROOT, "sql-memory", "embedding.py")
    spec = importlib.util.spec_from_file_location("_sqlmem_embed_scope31_fix", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSettingsRuntimePolicySource(unittest.TestCase):
    def test_legacy_persisted_execution_mode_reflected_as_override(self):
        if _ADMIN_API_PATH not in sys.path:
            sys.path.insert(0, _ADMIN_API_PATH)
        import settings_routes as sr

        prev_settings = dict(sr.settings.settings)
        sr.settings.settings.clear()
        sr.settings.settings["EMBEDDING_EXECUTION_MODE"] = "cpu_only"

        try:
            fake_rt = {
                "endpoint": "http://ollama:11434",
                "target": "cpu",
                "reason": "test",
                "options": {"num_gpu": 0},
            }
            with patch.object(sr, "resolve_embedding_target", return_value=fake_rt):
                payload = asyncio.run(sr.get_embedding_runtime())

            policy = payload["effective"]["embedding_runtime_policy"]
            self.assertEqual(policy["value"], "cpu_only")
            self.assertEqual(policy["source"], "override")
            self.assertEqual(payload["runtime"]["active_policy"], "cpu_only")
        finally:
            sr.settings.settings.clear()
            sr.settings.settings.update(prev_settings)


class TestSqlMemoryCanonicalPolicy(unittest.TestCase):
    def test_resolve_runtime_config_prefers_active_policy(self):
        mod = _load_sqlmem_embedding()
        mod.SETTINGS_API_URL = "http://settings-api"
        mod._rt_cache = {"config": None, "ts": 0.0}

        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = {
            "effective": {
                "EMBEDDING_EXECUTION_MODE": {"value": "auto"},
                "EMBEDDING_FALLBACK_POLICY": {"value": "best_effort"},
                "EMBEDDING_GPU_ENDPOINT": {"value": ""},
                "EMBEDDING_CPU_ENDPOINT": {"value": ""},
                "EMBEDDING_ENDPOINT_MODE": {"value": "single"},
                "embedding_runtime_policy": {"value": "prefer_gpu"},
            },
            "runtime": {"active_policy": "cpu_only"},
        }

        with patch.object(mod.requests, "get", return_value=fake_resp):
            cfg = mod._resolve_runtime_config()

        self.assertEqual(cfg["embedding_runtime_policy"], "cpu_only")

    def test_get_embedding_uses_canonical_policy_over_legacy_mode(self):
        mod = _load_sqlmem_embedding()

        captured_payloads = []

        def _fake_post(url, json=None, timeout=None):
            captured_payloads.append(json or {})
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"embedding": [0.1, 0.2]}
            return resp

        rt_cfg = {
            "embedding_runtime_policy": "cpu_only",
            "EMBEDDING_EXECUTION_MODE": "auto",
            "EMBEDDING_FALLBACK_POLICY": "best_effort",
            "EMBEDDING_GPU_ENDPOINT": "",
            "EMBEDDING_CPU_ENDPOINT": "",
            "EMBEDDING_ENDPOINT_MODE": "single",
        }

        with patch.object(mod, "_resolve_runtime_config", return_value=rt_cfg), patch.object(
            mod, "_resolve_embedding_model", return_value="test-model"
        ), patch.object(mod.requests, "post", side_effect=_fake_post):
            embedding = mod.get_embedding("policy-check")

        self.assertIsNotNone(embedding)
        self.assertTrue(captured_payloads, "No embedding request made")
        options = captured_payloads[0].get("options", {})
        self.assertEqual(options.get("num_gpu"), 0, f"Expected cpu_only routing, got {options}")


if __name__ == "__main__":
    unittest.main()
