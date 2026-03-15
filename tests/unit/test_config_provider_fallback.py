from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import config


class _SettingsStub:
    def __init__(self, store: dict):
        self._store = dict(store or {})

    def get(self, key, default=None):
        return self._store.get(key, default)


class TestConfigProviderFallback(unittest.TestCase):
    def test_thinking_and_control_fall_back_to_output_provider_when_unset(self):
        stub = _SettingsStub({"OUTPUT_PROVIDER": "ollama_cloud"})
        with patch.object(config, "settings", stub):
            with patch.dict(
                os.environ,
                {"THINKING_PROVIDER": "", "CONTROL_PROVIDER": "", "OUTPUT_PROVIDER": ""},
                clear=False,
            ):
                self.assertEqual(config.get_output_provider(), "ollama_cloud")
                self.assertEqual(config.get_thinking_provider(), "ollama_cloud")
                self.assertEqual(config.get_control_provider(), "ollama_cloud")

    def test_explicit_role_provider_overrides_output_provider(self):
        stub = _SettingsStub(
            {
                "OUTPUT_PROVIDER": "ollama_cloud",
                "THINKING_PROVIDER": "openai",
                "CONTROL_PROVIDER": "anthropic",
            }
        )
        with patch.object(config, "settings", stub):
            self.assertEqual(config.get_output_provider(), "ollama_cloud")
            self.assertEqual(config.get_thinking_provider(), "openai")
            self.assertEqual(config.get_control_provider(), "anthropic")


if __name__ == "__main__":
    unittest.main()
