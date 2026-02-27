from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from utils.role_endpoint_resolver import (
    clear_ollama_discovery_cache,
    clear_role_routing_cache,
    _CACHE,
    resolve_ollama_base_endpoint,
    resolve_role_endpoint,
)


def _read(rel_path: str) -> str:
    with open(os.path.join(_REPO_ROOT, rel_path), encoding="utf-8") as fh:
        return fh.read()


class TestRoleEndpointResolver(unittest.TestCase):
    def setUp(self):
        clear_ollama_discovery_cache()

    def test_unknown_role_falls_back_to_default(self):
        with patch("utils.role_endpoint_resolver.resolve_ollama_base_endpoint", return_value="http://ollama:11434"):
            d = resolve_role_endpoint("unknown_role", default_endpoint="http://ollama:11434")
        self.assertFalse(d["hard_error"])
        self.assertEqual(d["endpoint"], "http://ollama:11434")
        self.assertEqual(d["endpoint_source"], "default")

    def test_snapshot_unavailable_falls_back_to_default(self):
        with patch("utils.role_endpoint_resolver._get_snapshot", return_value=None), \
             patch("utils.role_endpoint_resolver.resolve_ollama_base_endpoint", return_value="http://ollama:11434"):
            d = resolve_role_endpoint("output", default_endpoint="http://ollama:11434")
        self.assertFalse(d["hard_error"])
        self.assertEqual(d["endpoint"], "http://ollama:11434")
        self.assertEqual(d["fallback_reason"], "compute_snapshot_unavailable")

    def test_explicit_pin_without_endpoint_is_hard_error(self):
        snap = {
            "effective": {
                "output": {
                    "requested_target": "gpu1",
                    "effective_target": None,
                    "effective_endpoint": None,
                    "fallback_reason": "requested_unavailable",
                }
            }
        }
        with patch("utils.role_endpoint_resolver._get_snapshot", return_value=snap), \
             patch("utils.role_endpoint_resolver.resolve_ollama_base_endpoint", return_value="http://ollama:11434"):
            d = resolve_role_endpoint("output", default_endpoint="http://ollama:11434")
        self.assertTrue(d["hard_error"])
        self.assertEqual(d["error_code"], 503)
        self.assertIsNone(d["endpoint"])

    def test_auto_without_endpoint_uses_default(self):
        snap = {
            "effective": {
                "thinking": {
                    "requested_target": "auto",
                    "effective_target": None,
                    "effective_endpoint": None,
                    "fallback_reason": "no_target_available",
                }
            }
        }
        with patch("utils.role_endpoint_resolver._get_snapshot", return_value=snap), \
             patch("utils.role_endpoint_resolver.resolve_ollama_base_endpoint", return_value="http://ollama:11434"):
            d = resolve_role_endpoint("thinking", default_endpoint="http://ollama:11434")
        self.assertFalse(d["hard_error"])
        self.assertEqual(d["endpoint"], "http://ollama:11434")
        self.assertEqual(d["endpoint_source"], "default")

    def test_auto_without_effective_endpoint_recovers_from_instances(self):
        snap = {
            "instances": {
                "instances": [
                    {
                        "id": "cpu",
                        "target": "cpu",
                        "endpoint": "http://trion-ollama-cpu:11434",
                        "running": True,
                        "health": {"ok": True},
                    }
                ]
            },
            "effective": {
                "thinking": {
                    "requested_target": "auto",
                    "effective_target": None,
                    "effective_endpoint": None,
                    "fallback_reason": "no_target_available",
                }
            },
        }
        with patch("utils.role_endpoint_resolver._get_snapshot", return_value=snap), \
             patch("utils.role_endpoint_resolver.resolve_ollama_base_endpoint", return_value="http://ollama:11434"):
            d = resolve_role_endpoint("thinking", default_endpoint="http://ollama:11434")
        self.assertFalse(d["hard_error"])
        self.assertEqual(d["endpoint"], "http://trion-ollama-cpu:11434")
        self.assertEqual(d["endpoint_source"], "compute_manager_recovery")
        self.assertEqual(d["effective_target"], "cpu")
        self.assertEqual(d["fallback_reason"], "no_target_available")

    def test_explicit_pin_without_effective_endpoint_recovers_from_instances(self):
        snap = {
            "instances": {
                "instances": [
                    {
                        "id": "gpu1",
                        "target": "gpu",
                        "endpoint": "http://trion-ollama-gpu1:11434",
                        "running": True,
                        "health": {"ok": True},
                    }
                ]
            },
            "effective": {
                "output": {
                    "requested_target": "gpu1",
                    "effective_target": "gpu1",
                    "effective_endpoint": None,
                    "fallback_reason": "requested_unavailable",
                }
            },
        }
        with patch("utils.role_endpoint_resolver._get_snapshot", return_value=snap), \
             patch("utils.role_endpoint_resolver.resolve_ollama_base_endpoint", return_value="http://ollama:11434"):
            d = resolve_role_endpoint("output", default_endpoint="http://ollama:11434")
        self.assertFalse(d["hard_error"])
        self.assertEqual(d["endpoint"], "http://trion-ollama-gpu1:11434")
        self.assertEqual(d["endpoint_source"], "compute_manager_recovery")
        self.assertEqual(d["effective_target"], "gpu1")
        self.assertEqual(d["fallback_reason"], "requested_unavailable")

    def test_auto_does_not_recover_from_unhealthy_instances(self):
        snap = {
            "instances": {
                "instances": [
                    {
                        "id": "gpu2",
                        "target": "gpu",
                        "endpoint": "http://trion-ollama-gpu2:11434",
                        "running": False,
                        "health": {"ok": False},
                    }
                ]
            },
            "effective": {
                "thinking": {
                    "requested_target": "auto",
                    "effective_target": None,
                    "effective_endpoint": None,
                    "fallback_reason": "no_target_available",
                }
            },
        }
        with patch("utils.role_endpoint_resolver._get_snapshot", return_value=snap), \
             patch("utils.role_endpoint_resolver.resolve_ollama_base_endpoint", return_value="http://ollama:11434"):
            d = resolve_role_endpoint("thinking", default_endpoint="http://ollama:11434")
        self.assertFalse(d["hard_error"])
        self.assertEqual(d["endpoint"], "http://ollama:11434")
        self.assertEqual(d["endpoint_source"], "default")
        self.assertEqual(d["fallback_reason"], "no_target_available")

    def test_compute_endpoint_is_used_when_available(self):
        snap = {
            "effective": {
                "control": {
                    "requested_target": "gpu0",
                    "effective_target": "gpu0",
                    "effective_endpoint": "http://trion-ollama-gpu0:11434",
                    "fallback_reason": None,
                }
            }
        }
        with patch("utils.role_endpoint_resolver._get_snapshot", return_value=snap), \
             patch("utils.role_endpoint_resolver.resolve_ollama_base_endpoint", return_value="http://ollama:11434"):
            d = resolve_role_endpoint("control", default_endpoint="http://ollama:11434")
        self.assertFalse(d["hard_error"])
        self.assertEqual(d["endpoint"], "http://trion-ollama-gpu0:11434")
        self.assertEqual(d["endpoint_source"], "compute_manager")


class TestOllamaBaseDiscovery(unittest.TestCase):
    def setUp(self):
        clear_ollama_discovery_cache()

    def test_prefers_first_healthy_candidate(self):
        with patch("utils.role_endpoint_resolver._candidate_default_endpoints", return_value=[
            "http://ollama:11434",
            "http://host.docker.internal:11434",
        ]), patch("utils.role_endpoint_resolver._probe_ollama_tags", side_effect=[False, True]):
            resolved = resolve_ollama_base_endpoint("http://ollama:11434")
        self.assertEqual(resolved, "http://host.docker.internal:11434")

    def test_discovery_cache_reuses_previous_result(self):
        with patch("utils.role_endpoint_resolver._candidate_default_endpoints", return_value=[
            "http://ollama:11434",
            "http://host.docker.internal:11434",
        ]), patch("utils.role_endpoint_resolver._probe_ollama_tags", side_effect=[False, True]) as probe:
            first = resolve_ollama_base_endpoint("http://ollama:11434")
            second = resolve_ollama_base_endpoint("http://ollama:11434")
        self.assertEqual(first, "http://host.docker.internal:11434")
        self.assertEqual(second, "http://host.docker.internal:11434")
        self.assertEqual(probe.call_count, 2)


class TestRoleRoutingCacheFallback(unittest.TestCase):
    def setUp(self):
        clear_role_routing_cache()

    def tearDown(self):
        clear_role_routing_cache()

    def test_stale_snapshot_used_when_build_fails(self):
        stale = {
            "instances": {"instances": []},
            "effective": {
                "thinking": {
                    "requested_target": "auto",
                    "effective_target": "cpu",
                    "effective_endpoint": "http://trion-ollama-cpu:11434",
                    "fallback_reason": None,
                }
            },
        }
        _CACHE["snapshot"] = stale
        _CACHE["ts"] = 0.0  # force stale branch

        with patch("utils.role_endpoint_resolver._build_snapshot", side_effect=RuntimeError("boom")), \
             patch("utils.role_endpoint_resolver.resolve_ollama_base_endpoint", return_value="http://ollama:11434"):
            d = resolve_role_endpoint("thinking", default_endpoint="http://ollama:11434")

        self.assertFalse(d["hard_error"])
        self.assertEqual(d["endpoint"], "http://trion-ollama-cpu:11434")
        self.assertEqual(d["endpoint_source"], "compute_manager")


class TestScope4WiringSource(unittest.TestCase):
    def test_thinking_layer_uses_role_endpoint_resolver(self):
        src = _read("core/layers/thinking.py")
        self.assertIn("resolve_role_endpoint", src)
        self.assertIn("role=thinking", src)

    def test_control_layer_uses_role_endpoint_resolver(self):
        src = _read("core/layers/control.py")
        self.assertIn("resolve_role_endpoint", src)
        self.assertIn("role=control", src)

    def test_output_layer_uses_role_endpoint_resolver(self):
        src = _read("core/layers/output.py")
        self.assertIn("resolve_role_endpoint", src)
        self.assertIn("role=output", src)

    def test_embedding_archive_honors_layer_routing_pin(self):
        src = _read("core/lifecycle/archive.py")
        self.assertIn('resolve_role_endpoint("embedding"', src)
        self.assertIn("layer_routing_pin", src)

    def test_embedding_sql_memory_honors_runtime_compute_routing(self):
        src = _read("sql-memory/embedding.py")
        self.assertIn("/api/runtime/compute/routing", src)
        self.assertIn("layer_routing_pin", src)


if __name__ == "__main__":
    unittest.main()
