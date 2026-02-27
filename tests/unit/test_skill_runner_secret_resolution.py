from __future__ import annotations

import importlib.util
import json
import os
import sys
import asyncio
import tempfile
import unittest
from unittest.mock import patch


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_TOOL_EXECUTOR_DIR = os.path.join(_REPO_ROOT, "tool_executor")

if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
if _TOOL_EXECUTOR_DIR not in sys.path:
    sys.path.insert(0, _TOOL_EXECUTOR_DIR)


def _load_skill_runner_module():
    spec = importlib.util.spec_from_file_location(
        "skill_runner_secret_resolution_test_mod",
        os.path.join(_TOOL_EXECUTOR_DIR, "engine", "skill_runner.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


class TestSkillRunnerSecretResolution(unittest.TestCase):
    def setUp(self):
        self.mod = _load_skill_runner_module()

    def test_normalize_secret_name(self):
        self.assertEqual(self.mod._normalize_secret_name(" test-key "), "TEST_KEY")
        self.assertEqual(self.mod._normalize_secret_name("OpenAI Api Key"), "OPENAI_API_KEY")
        self.assertEqual(self.mod._normalize_secret_name(""), "")

    def test_extract_secret_names_from_payload(self):
        payload = {
            "secrets": [{"name": "TEST_KEY"}, {"name": "SECOND_API_KEY"}],
            "data": ["THIRD_KEY"],
        }
        names = self.mod._extract_secret_names(payload)
        self.assertEqual(names, ["TEST_KEY", "SECOND_API_KEY", "THIRD_KEY"])

    def test_find_secret_alias_api_key_to_key(self):
        alias = self.mod._find_secret_alias("OPENAI_API_KEY", ["OPENAI_KEY", "OTHER_KEY"])
        self.assertEqual(alias, "OPENAI_KEY")

    def test_find_secret_alias_base_unique(self):
        alias = self.mod._find_secret_alias("OPENAI", ["OPENAI_KEY", "OTHER_KEY"])
        self.assertEqual(alias, "OPENAI_KEY")

    def test_find_secret_alias_base_ambiguous(self):
        alias = self.mod._find_secret_alias("OPENAI", ["OPENAI_KEY", "OPENAI_API_KEY"])
        self.assertEqual(alias, "")

    def test_resolve_secret_value_uses_token_and_normalized_name(self):
        captured = {}

        def _fake_urlopen(req, timeout=0):
            captured["url"] = req.full_url
            captured["auth"] = req.get_header("Authorization")
            captured["timeout"] = timeout
            return _FakeResponse({"value": "dummy-value"})

        with patch.object(self.mod.urllib.request, "urlopen", side_effect=_fake_urlopen):
            value = self.mod._resolve_secret_value(
                "http://jarvis-admin-api:8200/api/secrets/resolve",
                "internal-token",
                "test-key",
                timeout=7,
            )

        self.assertEqual(value, "dummy-value")
        self.assertEqual(
            captured["url"],
            "http://jarvis-admin-api:8200/api/secrets/resolve/TEST_KEY",
        )
        self.assertEqual(captured["auth"], "Bearer internal-token")
        self.assertEqual(captured["timeout"], 7)

    def test_fetch_secret_names(self):
        def _fake_urlopen(req, timeout=0):
            self.assertEqual(req.full_url, "http://jarvis-admin-api:8200/api/secrets")
            self.assertEqual(req.get_header("Authorization"), "Bearer internal-token")
            self.assertEqual(timeout, 4)
            return _FakeResponse({"secrets": [{"name": "TEST_KEY"}]})

        with patch.object(self.mod.urllib.request, "urlopen", side_effect=_fake_urlopen):
            names = self.mod._fetch_secret_names(
                "http://jarvis-admin-api:8200/api/secrets",
                "internal-token",
                timeout=4,
            )
        self.assertEqual(names, ["TEST_KEY"])

    def test_resolve_secret_value_error_returns_empty(self):
        with patch.object(self.mod.urllib.request, "urlopen", side_effect=RuntimeError("boom")):
            value = self.mod._resolve_secret_value(
                "http://jarvis-admin-api:8200/api/secrets/resolve",
                "internal-token",
                "TEST_KEY",
                timeout=4,
            )
        self.assertEqual(value, "")

    def test_fetch_secret_names_error_returns_empty_list(self):
        with patch.object(self.mod.urllib.request, "urlopen", side_effect=RuntimeError("boom")):
            names = self.mod._fetch_secret_names(
                "http://jarvis-admin-api:8200/api/secrets",
                "internal-token",
                timeout=4,
            )
        self.assertEqual(names, [])

    def test_skill_runner_get_secret_uses_alias_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo")
            os.makedirs(skill_dir, exist_ok=True)
            with open(os.path.join(skill_dir, "main.py"), "w", encoding="utf-8") as f:
                f.write(
                    "def run():\n"
                    "    return get_secret('TEST_API_KEY')\n"
                )

            runner = self.mod.SkillRunner(skills_dir=tmpdir, timeout_seconds=5)

            def _fake_resolve(_url, _token, name, timeout=5):
                if name == "TEST_API_KEY":
                    return ""
                if name == "TEST_KEY":
                    return "resolved-via-alias"
                return ""

            with (
                patch.object(self.mod, "_resolve_secret_value", side_effect=_fake_resolve),
                patch.object(self.mod, "_fetch_secret_names", return_value=["TEST_KEY"]),
                patch.dict(os.environ, {"SKILL_SECRET_ALIAS_MODE": "safe"}, clear=False),
            ):
                result = asyncio.run(runner.run("demo"))

            self.assertTrue(result.success)
            self.assertEqual(result.result, "resolved-via-alias")

    def test_skill_runner_get_secret_alias_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "demo")
            os.makedirs(skill_dir, exist_ok=True)
            with open(os.path.join(skill_dir, "main.py"), "w", encoding="utf-8") as f:
                f.write(
                    "def run():\n"
                    "    return get_secret('TEST_API_KEY')\n"
                )

            runner = self.mod.SkillRunner(skills_dir=tmpdir, timeout_seconds=5)

            with (
                patch.object(self.mod, "_resolve_secret_value", return_value=""),
                patch.object(self.mod, "_fetch_secret_names", return_value=["TEST_KEY"]),
                patch.dict(os.environ, {"SKILL_SECRET_ALIAS_MODE": "off"}, clear=False),
            ):
                result = asyncio.run(runner.run("demo"))

            self.assertTrue(result.success)
            self.assertEqual(result.result, "")
