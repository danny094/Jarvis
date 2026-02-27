"""
tests/unit/test_scope31_embedding_policy.py — Scope 3.1: GPU vs RAM/CPU robust

Test classes:
  P1  TestContractPolicy          — contract/validation (embedding_runtime_policy field)
  P2  TestRoutingDecisionShape    — RoutingDecision has all required fields
  P3  TestRouterMatrix            — full policy × availability matrix (12 cases)
  P4  TestStructuredLogging       — structured log format
  P5  TestMetrics                 — counters increment correctly
  P6  TestRegressionCallSites     — source inspection: all paths use same resolver
  P7  TestIntegrationPolicy       — runtime policy change wires through

Gate: python -m pytest tests/unit/test_scope31_embedding_policy.py -q
Expected: ≥ 42 passed, 0 failures
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import sys
import unittest
from typing import Dict
from unittest.mock import MagicMock, patch

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if not os.path.isfile(os.path.join(_REPO_ROOT, "config.py")):
    _REPO_ROOT = "/DATA/AppData/MCP/Jarvis/Jarvis"
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_VALID_POLICIES = ("auto", "prefer_gpu", "cpu_only")

# admin-api uses hyphen in dir name, not importable as package — load via sys.path
_ADMIN_API_PATH = os.path.join(_REPO_ROOT, "adapters", "admin-api")


def _read_source(rel: str) -> str:
    with open(os.path.join(_REPO_ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _load_sqlmem_embedding():
    """Fresh module load of sql-memory/embedding.py."""
    path = os.path.join(_REPO_ROOT, "sql-memory", "embedding.py")
    spec = importlib.util.spec_from_file_location("_sqlmem_embed_p31", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_settings_routes():
    """Load admin-api/settings_routes.py as isolated module."""
    if _ADMIN_API_PATH not in sys.path:
        sys.path.insert(0, _ADMIN_API_PATH)
    import importlib as _il
    if "settings_routes" in sys.modules:
        return sys.modules["settings_routes"]
    path = os.path.join(_ADMIN_API_PATH, "settings_routes.py")
    spec = importlib.util.spec_from_file_location("_settings_routes_p31", path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        pass  # import errors handled per-test
    return mod


def _empty_settings(key, default=None):
    """Mock for config.settings.get that returns the default."""
    return default


# ─────────────────────────────────────────────────────────────────────────────
# P1 — Contract / Validation
# ─────────────────────────────────────────────────────────────────────────────

class TestContractPolicy(unittest.TestCase):

    def setUp(self):
        self._saved_env = {
            k: os.environ.pop(k, None)
            for k in ("EMBEDDING_EXECUTION_MODE",)
        }

    def tearDown(self):
        for k, v in self._saved_env.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def test_p1_get_embedding_runtime_policy_default_is_auto(self):
        """get_embedding_runtime_policy() → 'auto' by default (no env, no settings)."""
        os.environ.pop("EMBEDDING_EXECUTION_MODE", None)
        with patch("config.settings.get", side_effect=_empty_settings):
            from config import get_embedding_runtime_policy
            result = get_embedding_runtime_policy()
        self.assertEqual(result, "auto")

    def test_p1_env_execution_mode_respected(self):
        """EMBEDDING_EXECUTION_MODE env var → used as policy fallback."""
        os.environ["EMBEDDING_EXECUTION_MODE"] = "cpu_only"
        with patch("config.settings.get", side_effect=_empty_settings):
            from config import get_embedding_runtime_policy
            result = get_embedding_runtime_policy()
        self.assertEqual(result, "cpu_only")

    def test_p1_persisted_setting_beats_env(self):
        """Persisted 'embedding_runtime_policy' beats env EMBEDDING_EXECUTION_MODE."""
        os.environ["EMBEDDING_EXECUTION_MODE"] = "auto"

        def _settings_get(key, default=None):
            if key == "embedding_runtime_policy":
                return "prefer_gpu"
            return default

        with patch("config.settings.get", side_effect=_settings_get):
            from config import get_embedding_runtime_policy
            result = get_embedding_runtime_policy()
        self.assertEqual(result, "prefer_gpu")

    def test_p1_api_model_unknown_field_422(self):
        """EmbeddingRuntimeUpdate with unknown field → ValidationError (extra=forbid)."""
        from pydantic import ValidationError
        if _ADMIN_API_PATH not in sys.path:
            sys.path.insert(0, _ADMIN_API_PATH)
        try:
            import settings_routes as _sr
        except Exception as e:
            self.skipTest(f"Could not import settings_routes: {e}")
        with self.assertRaises(ValidationError):
            _sr.EmbeddingRuntimeUpdate(**{"UNKNOWN_KEY": "auto"})

    def test_p1_api_model_invalid_policy_422(self):
        """embedding_runtime_policy with bad value → ValidationError (Literal types)."""
        from pydantic import ValidationError
        if _ADMIN_API_PATH not in sys.path:
            sys.path.insert(0, _ADMIN_API_PATH)
        try:
            import settings_routes as _sr
        except Exception as e:
            self.skipTest(f"Could not import settings_routes: {e}")
        with self.assertRaises(ValidationError):
            _sr.EmbeddingRuntimeUpdate(**{"embedding_runtime_policy": "bad_value"})

    def test_p1_api_model_invalid_execution_mode_422(self):
        """EMBEDDING_EXECUTION_MODE with bad value → ValidationError."""
        from pydantic import ValidationError
        if _ADMIN_API_PATH not in sys.path:
            sys.path.insert(0, _ADMIN_API_PATH)
        try:
            import settings_routes as _sr
        except Exception as e:
            self.skipTest(f"Could not import settings_routes: {e}")
        with self.assertRaises(ValidationError):
            _sr.EmbeddingRuntimeUpdate(**{"EMBEDDING_EXECUTION_MODE": "invalid_value"})

    def test_p1_all_valid_policies_accepted(self):
        """All three valid policy values are accepted by EmbeddingRuntimeUpdate."""
        if _ADMIN_API_PATH not in sys.path:
            sys.path.insert(0, _ADMIN_API_PATH)
        try:
            import settings_routes as _sr
        except Exception as e:
            self.skipTest(f"Could not import settings_routes: {e}")
        for policy in _VALID_POLICIES:
            obj = _sr.EmbeddingRuntimeUpdate(**{"embedding_runtime_policy": policy})
            self.assertEqual(obj.embedding_runtime_policy, policy)

    def test_p1_config_has_get_embedding_runtime_policy(self):
        """config.py must define get_embedding_runtime_policy()."""
        src = _read_source("config.py")
        self.assertIn("def get_embedding_runtime_policy()", src)

    def test_p1_settings_routes_has_embedding_runtime_policy_field(self):
        """settings_routes.py EmbeddingRuntimeUpdate must have embedding_runtime_policy."""
        src = _read_source("adapters/admin-api/settings_routes.py")
        self.assertIn("embedding_runtime_policy", src)
        self.assertIn('extra="forbid"', src)


# ─────────────────────────────────────────────────────────────────────────────
# P2 — RoutingDecision shape
# ─────────────────────────────────────────────────────────────────────────────

class TestRoutingDecisionShape(unittest.TestCase):

    def _resolve(self, mode="auto", availability=None):
        from utils.embedding_resolver import resolve_embedding_target
        return resolve_embedding_target(
            mode=mode,
            endpoint_mode="single",
            base_endpoint="http://ollama:11434",
            gpu_endpoint="",
            cpu_endpoint="",
            fallback_policy="best_effort",
            availability=availability,
        )

    def test_p2_all_required_fields_present(self):
        """RoutingDecision must contain all Scope 3.1 required keys."""
        required = {
            "requested_policy", "requested_target", "effective_target",
            "fallback_reason", "hard_error", "error_code",
            "endpoint", "options", "fallback_endpoint", "fallback_policy",
            "reason", "target",
        }
        dec = self._resolve("auto")
        for key in required:
            self.assertIn(key, dec, f"Missing key: {key}")

    def test_p2_hard_error_false_on_normal_routing(self):
        dec = self._resolve("auto")
        self.assertFalse(dec["hard_error"])
        self.assertIsNone(dec["error_code"])

    def test_p2_hard_error_true_on_all_down(self):
        dec = self._resolve("auto", availability={"gpu": False, "cpu": False})
        self.assertTrue(dec["hard_error"])
        self.assertEqual(dec["error_code"], 503)
        self.assertIsNone(dec["endpoint"])

    def test_p2_backward_compat_target_key_present(self):
        """Old 'target' key still present for backward-compat callers."""
        dec = self._resolve("auto")
        self.assertIn("target", dec)
        self.assertEqual(dec["target"], dec["effective_target"])

    def test_p2_requested_policy_matches_input(self):
        for policy in _VALID_POLICIES:
            dec = self._resolve(policy)
            self.assertEqual(dec["requested_policy"], policy)


# ─────────────────────────────────────────────────────────────────────────────
# P3 — Full policy × availability matrix
# ─────────────────────────────────────────────────────────────────────────────

class TestRouterMatrix(unittest.TestCase):
    """
    Matrix: 3 policies × 4 availability states = 12 core cases.
    """

    BASE = "http://ollama:11434"
    GPU_EP = "http://ollama-gpu:11434"
    CPU_EP = "http://ollama-cpu:11434"

    def _r(self, mode, avail=None, endpoint_mode="single", gpu_ep="", cpu_ep="",
           fp="best_effort"):
        from utils.embedding_resolver import resolve_embedding_target
        return resolve_embedding_target(
            mode=mode, endpoint_mode=endpoint_mode,
            base_endpoint=self.BASE, gpu_endpoint=gpu_ep,
            cpu_endpoint=cpu_ep, fallback_policy=fp,
            availability=avail,
        )

    # ── cpu_only ──────────────────────────────────────────────────────────

    def test_p3_cpu_only_gpu_healthy_uses_cpu_not_gpu(self):
        """cpu_only + GPU healthy → still uses CPU (never GPU)."""
        dec = self._r("cpu_only", {"gpu": True, "cpu": True})
        self.assertEqual(dec["effective_target"], "cpu")
        self.assertFalse(dec["hard_error"])
        self.assertIsNone(dec["fallback_reason"])
        # In single mode: num_gpu=0 applied
        self.assertEqual(dec["options"].get("num_gpu"), 0)

    def test_p3_cpu_only_gpu_down_still_cpu(self):
        """cpu_only + GPU down → still uses CPU (GPU irrelevant for cpu_only)."""
        dec = self._r("cpu_only", {"gpu": False, "cpu": True})
        self.assertEqual(dec["effective_target"], "cpu")
        self.assertFalse(dec["hard_error"])

    def test_p3_cpu_only_cpu_down_hard_error(self):
        """cpu_only + CPU unavailable → hard_error=True, 503, no GPU fallback."""
        dec = self._r("cpu_only", {"gpu": True, "cpu": False})
        self.assertTrue(dec["hard_error"])
        self.assertEqual(dec["error_code"], 503)
        self.assertEqual(dec["fallback_reason"], "cpu_unavailable")
        self.assertIsNone(dec["endpoint"])

    def test_p3_cpu_only_all_down_hard_error(self):
        """cpu_only + all down → hard_error, no GPU fallback."""
        dec = self._r("cpu_only", {"gpu": False, "cpu": False})
        self.assertTrue(dec["hard_error"])
        self.assertEqual(dec["fallback_reason"], "cpu_unavailable")

    # ── prefer_gpu ────────────────────────────────────────────────────────

    def test_p3_prefer_gpu_gpu_healthy_uses_gpu(self):
        """prefer_gpu + GPU healthy → effective_target=gpu, no fallback."""
        dec = self._r("prefer_gpu", {"gpu": True, "cpu": True})
        self.assertEqual(dec["effective_target"], "gpu")
        self.assertFalse(dec["hard_error"])
        self.assertIsNone(dec["fallback_reason"])

    def test_p3_prefer_gpu_gpu_down_cpu_fallback_with_reason(self):
        """prefer_gpu + GPU down + CPU ok → CPU fallback + fallback_reason set."""
        dec = self._r("prefer_gpu", {"gpu": False, "cpu": True})
        self.assertEqual(dec["effective_target"], "cpu")
        self.assertFalse(dec["hard_error"])
        self.assertEqual(dec["fallback_reason"], "gpu_unavailable")

    def test_p3_prefer_gpu_all_down_hard_error(self):
        """prefer_gpu + all down → hard_error=True."""
        dec = self._r("prefer_gpu", {"gpu": False, "cpu": False})
        self.assertTrue(dec["hard_error"])
        self.assertEqual(dec["error_code"], 503)
        self.assertEqual(dec["fallback_reason"], "all_unavailable")

    def test_p3_prefer_gpu_gpu_down_cpu_also_down_503(self):
        """prefer_gpu + GPU down + CPU down → hard error 503."""
        dec = self._r("prefer_gpu", {"gpu": False, "cpu": False})
        self.assertEqual(dec["error_code"], 503)

    # ── auto ──────────────────────────────────────────────────────────────

    def test_p3_auto_gpu_healthy_picks_gpu(self):
        """auto + GPU healthy → effective_target=gpu."""
        dec = self._r("auto", {"gpu": True, "cpu": True})
        self.assertEqual(dec["effective_target"], "gpu")
        self.assertFalse(dec["hard_error"])

    def test_p3_auto_gpu_down_fallback_to_cpu(self):
        """auto + GPU down → effective_target=cpu + fallback_reason."""
        dec = self._r("auto", {"gpu": False, "cpu": True})
        self.assertEqual(dec["effective_target"], "cpu")
        self.assertFalse(dec["hard_error"])
        self.assertEqual(dec["fallback_reason"], "gpu_unavailable")

    def test_p3_auto_cpu_only_down_uses_gpu(self):
        """auto + CPU down but GPU up → effective_target=gpu (GPU still available)."""
        dec = self._r("auto", {"gpu": True, "cpu": False})
        self.assertEqual(dec["effective_target"], "gpu")
        self.assertFalse(dec["hard_error"])

    def test_p3_auto_all_down_503(self):
        """auto + all down → hard_error=True, 503."""
        dec = self._r("auto", {"gpu": False, "cpu": False})
        self.assertTrue(dec["hard_error"])
        self.assertEqual(dec["error_code"], 503)

    # ── dual endpoint mode ────────────────────────────────────────────────

    def test_p3_cpu_only_dual_uses_cpu_endpoint(self):
        """cpu_only + dual + cpu_endpoint configured → uses cpu_endpoint directly."""
        dec = self._r("cpu_only", {"gpu": True, "cpu": True},
                      endpoint_mode="dual", cpu_ep=self.CPU_EP)
        self.assertEqual(dec["endpoint"], self.CPU_EP)
        self.assertEqual(dec["options"], {})  # no num_gpu=0 needed for dedicated endpoint

    def test_p3_prefer_gpu_dual_with_best_effort_has_fallback(self):
        """prefer_gpu + dual + best_effort → fallback_endpoint set on GPU path."""
        dec = self._r("prefer_gpu", {"gpu": True, "cpu": True},
                      endpoint_mode="dual", gpu_ep=self.GPU_EP, cpu_ep=self.CPU_EP,
                      fp="best_effort")
        self.assertEqual(dec["endpoint"], self.GPU_EP)
        self.assertIsNotNone(dec["fallback_endpoint"])

    def test_p3_prefer_gpu_dual_strict_no_fallback_endpoint(self):
        """prefer_gpu + dual + strict → no fallback_endpoint (fail hard on GPU failure)."""
        dec = self._r("prefer_gpu", {"gpu": True, "cpu": True},
                      endpoint_mode="dual", gpu_ep=self.GPU_EP, cpu_ep=self.CPU_EP,
                      fp="strict")
        self.assertEqual(dec["endpoint"], self.GPU_EP)
        self.assertIsNone(dec["fallback_endpoint"])

    # ── None availability = backward-compat (assume all available) ─────────

    def test_p3_none_availability_defaults_to_all_available(self):
        """availability=None → optimistic routing (all targets assumed healthy)."""
        dec = self._r("prefer_gpu", avail=None)
        self.assertEqual(dec["effective_target"], "gpu")
        self.assertFalse(dec["hard_error"])


# ─────────────────────────────────────────────────────────────────────────────
# P4 — Structured logging
# ─────────────────────────────────────────────────────────────────────────────

class TestStructuredLogging(unittest.TestCase):
    """Verify structured log fields are emitted by archive._get_embedding."""

    def _make_fake_post(self, embedding=None):
        def _fake(url, json=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"embedding": embedding or [0.1, 0.2]}
            return resp
        return _fake

    def test_p4_log_contains_role_policy_fields(self):
        """_get_embedding() log must include role=, policy=, requested_target=, effective_target=."""
        import core.lifecycle.archive as _arch

        log_messages = []

        with patch.object(_arch, "log_info", side_effect=lambda m: log_messages.append(m)), \
             patch.object(_arch, "log_warning", side_effect=lambda m: log_messages.append(m)), \
             patch.object(_arch, "log_error", side_effect=lambda m: log_messages.append(m)), \
             patch("config.settings.get", return_value=None), \
             patch("core.lifecycle.archive.requests.post",
                   side_effect=self._make_fake_post([0.1])):
            _arch._get_embedding("test text")

        combined = " ".join(log_messages)
        self.assertIn("role=", combined, "Missing role= in log")
        self.assertIn("policy=", combined, "Missing policy= in log")
        self.assertIn("requested_target=", combined, "Missing requested_target= in log")
        self.assertIn("effective_target=", combined, "Missing effective_target= in log")

    def test_p4_prefer_gpu_with_gpu_down_logs_warning(self):
        """prefer_gpu + GPU unavailable → log_warning called (not just log_info)."""
        import core.lifecycle.archive as _arch

        warnings = []

        def _settings_get(key, default=None):
            if key == "embedding_runtime_policy":
                return "prefer_gpu"
            return default

        _fallback_decision = {
            "requested_policy": "prefer_gpu", "requested_target": "gpu",
            "effective_target": "cpu", "fallback_reason": "gpu_unavailable",
            "hard_error": False, "error_code": None,
            "endpoint": "http://ollama:11434", "options": {"num_gpu": 0},
            "fallback_endpoint": None, "fallback_policy": "best_effort",
            "reason": "prefer_gpu→gpu_unavailable→cpu_fallback",
            "target": "cpu",
        }

        with patch("config.settings.get", side_effect=_settings_get), \
             patch.object(_arch, "log_warning", side_effect=lambda m: warnings.append(m)), \
             patch("core.lifecycle.archive.resolve_embedding_target",
                   return_value=_fallback_decision), \
             patch("core.lifecycle.archive.requests.post",
                   side_effect=self._make_fake_post([0.1])):
            _arch._get_embedding("test")

        self.assertTrue(len(warnings) > 0,
                        "No warnings logged for prefer_gpu with gpu_unavailable fallback")

    def test_p4_hard_error_logs_error(self):
        """hard_error=True → log_error called, None returned."""
        import core.lifecycle.archive as _arch

        errors = []

        _hard_error_decision = {
            "requested_policy": "auto", "requested_target": "gpu",
            "effective_target": None, "fallback_reason": "all_unavailable",
            "hard_error": True, "error_code": 503,
            "endpoint": None, "options": {}, "fallback_endpoint": None,
            "fallback_policy": "best_effort",
            "reason": "auto→all_unavailable→hard_error_503",
            "target": "gpu",
        }

        with patch("config.settings.get", side_effect=_empty_settings), \
             patch.object(_arch, "log_error", side_effect=lambda m: errors.append(m)), \
             patch("core.lifecycle.archive.resolve_embedding_target",
                   return_value=_hard_error_decision):
            result = _arch._get_embedding("test")

        self.assertIsNone(result)
        self.assertTrue(len(errors) > 0, "No error logged for hard_error case")

    def test_p4_sqlmem_structured_log_format(self):
        """sql-memory get_embedding() log includes Scope 3.1 required fields."""
        mod = _load_sqlmem_embedding()
        mod.OLLAMA_URL = "http://fake-ollama:11434"
        mod.SETTINGS_API_URL = ""

        log_records = []

        class _Handler(logging.Handler):
            def emit(self, record):
                log_records.append(record.getMessage())

        handler = _Handler()
        mod.logger.addHandler(handler)
        mod.logger.setLevel(logging.DEBUG)

        try:
            fake_resp = MagicMock()
            fake_resp.raise_for_status.return_value = None
            fake_resp.json.return_value = {"embedding": [0.1, 0.2]}

            with patch.object(mod.requests, "post", return_value=fake_resp):
                mod.get_embedding("hello world")

            combined = " ".join(log_records)
            self.assertIn("role=", combined)
            self.assertIn("policy=", combined)
        finally:
            mod.logger.removeHandler(handler)


# ─────────────────────────────────────────────────────────────────────────────
# P5 — Metrics
# ─────────────────────────────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):

    def setUp(self):
        from utils.embedding_metrics import reset_metrics
        reset_metrics()

    def test_p5_increment_fallback(self):
        from utils.embedding_metrics import increment_fallback, get_metrics
        increment_fallback()
        increment_fallback()
        self.assertEqual(get_metrics()["routing_fallback_total"], 2)

    def test_p5_increment_error(self):
        from utils.embedding_metrics import increment_error, get_metrics
        increment_error()
        self.assertEqual(get_metrics()["routing_target_errors_total"], 1)

    def test_p5_record_latency_per_target(self):
        from utils.embedding_metrics import record_latency, get_metrics
        record_latency("gpu", 50.0)
        record_latency("gpu", 100.0)
        record_latency("cpu", 200.0)
        m = get_metrics()
        self.assertIn("gpu", m["embedding_latency_by_target"])
        self.assertIn("cpu", m["embedding_latency_by_target"])
        self.assertAlmostEqual(m["embedding_latency_by_target"]["gpu"], 75.0)

    def test_p5_reset_clears_all(self):
        from utils.embedding_metrics import increment_fallback, increment_error, reset_metrics, get_metrics
        increment_fallback()
        increment_error()
        reset_metrics()
        m = get_metrics()
        self.assertEqual(m["routing_fallback_total"], 0)
        self.assertEqual(m["routing_target_errors_total"], 0)
        self.assertEqual(m["embedding_latency_by_target"], {})

    def test_p5_metrics_keys_always_present(self):
        """get_metrics() always contains required keys even when empty."""
        from utils.embedding_metrics import get_metrics
        m = get_metrics()
        self.assertIn("routing_fallback_total", m)
        self.assertIn("routing_target_errors_total", m)
        self.assertIn("embedding_latency_by_target", m)

    def test_p5_archive_hard_error_increments_counter(self):
        """archive._get_embedding() with hard_error → increments routing_target_errors_total."""
        from utils.embedding_metrics import reset_metrics, get_metrics
        reset_metrics()

        import core.lifecycle.archive as _arch

        _hard_dec = {
            "requested_policy": "auto", "requested_target": "gpu",
            "effective_target": None, "fallback_reason": "all_unavailable",
            "hard_error": True, "error_code": 503,
            "endpoint": None, "options": {}, "fallback_endpoint": None,
            "fallback_policy": "best_effort",
            "reason": "auto→all_unavailable→hard_error_503",
            "target": "gpu",
        }

        with patch("config.settings.get", side_effect=_empty_settings), \
             patch.object(_arch, "log_error"), \
             patch("core.lifecycle.archive.resolve_embedding_target",
                   return_value=_hard_dec):
            _arch._get_embedding("test")

        self.assertEqual(get_metrics()["routing_target_errors_total"], 1)


# ─────────────────────────────────────────────────────────────────────────────
# P6 — Regression: callsite source inspection
# ─────────────────────────────────────────────────────────────────────────────

class TestRegressionCallSites(unittest.TestCase):

    def test_p6_archive_imports_embedding_resolver(self):
        """archive.py must import from utils.embedding_resolver."""
        src = _read_source("core/lifecycle/archive.py")
        self.assertIn("from utils.embedding_resolver import resolve_embedding_target", src)

    def test_p6_archive_uses_get_embedding_runtime_policy(self):
        """archive._get_embedding() uses get_embedding_runtime_policy(), not frozen constant."""
        src = _read_source("core/lifecycle/archive.py")
        self.assertIn("get_embedding_runtime_policy()", src)

    def test_p6_archive_imports_metrics(self):
        """archive.py must import embedding_metrics."""
        src = _read_source("core/lifecycle/archive.py")
        self.assertIn("embedding_metrics", src)

    def test_p6_sqlmem_has_inline_resolve_with_availability(self):
        """sql-memory/embedding.py inline resolver must accept availability param."""
        src = _read_source("sql-memory/embedding.py")
        self.assertIn("availability", src)
        self.assertIn("hard_error", src)
        self.assertIn("requested_policy", src)

    def test_p6_sqlmem_get_embedding_emits_structured_log(self):
        """sql-memory/embedding.py get_embedding() must log role= and policy= fields."""
        src = _read_source("sql-memory/embedding.py")
        self.assertIn("role=", src)
        self.assertIn("policy=", src)
        self.assertIn("requested_target=", src)
        self.assertIn("effective_target=", src)

    def test_p6_embedding_resolver_has_routing_decision(self):
        """utils/embedding_resolver.py must define RoutingDecision."""
        src = _read_source("utils/embedding_resolver.py")
        self.assertIn("RoutingDecision", src)
        self.assertIn("hard_error", src)
        self.assertIn("effective_target", src)
        self.assertIn("fallback_reason", src)

    def test_p6_health_module_exists(self):
        """utils/embedding_health.py must exist."""
        path = os.path.join(_REPO_ROOT, "utils", "embedding_health.py")
        self.assertTrue(os.path.isfile(path))

    def test_p6_metrics_module_exists(self):
        """utils/embedding_metrics.py must exist."""
        path = os.path.join(_REPO_ROOT, "utils", "embedding_metrics.py")
        self.assertTrue(os.path.isfile(path))


# ─────────────────────────────────────────────────────────────────────────────
# P7 — Integration: policy change wires through
# ─────────────────────────────────────────────────────────────────────────────

class TestIntegrationPolicy(unittest.TestCase):

    def _make_fake_post(self, embedding=None):
        def _fake(url, json=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"embedding": embedding or [0.1, 0.2, 0.3]}
            return resp
        return _fake

    def test_p7_cpu_only_policy_sends_num_gpu_0_to_ollama(self):
        """cpu_only policy → requests.post payload has options.num_gpu=0 (single mode)."""
        import core.lifecycle.archive as _arch

        captured_payloads = []

        def _fake_post(url, json=None, timeout=None):
            captured_payloads.append(json or {})
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"embedding": [0.5]}
            return resp

        def _settings_with_cpu_only(key, default=None):
            if key == "embedding_runtime_policy":
                return "cpu_only"
            return default

        with patch("config.settings.get", side_effect=_settings_with_cpu_only), \
             patch("core.lifecycle.archive.requests.post", side_effect=_fake_post), \
             patch.object(_arch, "log_info"), patch.object(_arch, "log_warning"):
            _arch._get_embedding("test cpu only")

        self.assertTrue(len(captured_payloads) > 0, "No request made")
        opts = captured_payloads[0].get("options", {})
        self.assertEqual(opts.get("num_gpu"), 0,
                         f"cpu_only should set num_gpu=0 in single mode, got options={opts}")

    def test_p7_auto_policy_does_not_set_num_gpu_0(self):
        """auto policy → no num_gpu=0 option sent (GPU is preferred)."""
        import core.lifecycle.archive as _arch

        captured_payloads = []

        def _fake_post(url, json=None, timeout=None):
            captured_payloads.append(json or {})
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"embedding": [0.5]}
            return resp

        with patch("config.settings.get", return_value=None), \
             patch("core.lifecycle.archive.requests.post", side_effect=_fake_post), \
             patch.object(_arch, "log_info"), patch.object(_arch, "log_warning"):
            _arch._get_embedding("test auto")

        self.assertTrue(len(captured_payloads) > 0, "No request made")
        opts = captured_payloads[0].get("options", {})
        self.assertNotEqual(opts.get("num_gpu"), 0,
                            "auto policy should NOT force num_gpu=0")

    def test_p7_hard_error_returns_none(self):
        """When router signals hard_error, _get_embedding() returns None."""
        import core.lifecycle.archive as _arch

        _hard_dec = {
            "requested_policy": "cpu_only", "requested_target": "cpu",
            "effective_target": None, "fallback_reason": "cpu_unavailable",
            "hard_error": True, "error_code": 503,
            "endpoint": None, "options": {}, "fallback_endpoint": None,
            "fallback_policy": "best_effort",
            "reason": "cpu_only→cpu_unavailable→hard_error_503",
            "target": "cpu",
        }

        with patch("config.settings.get", side_effect=_empty_settings), \
             patch.object(_arch, "log_error"), \
             patch("core.lifecycle.archive.resolve_embedding_target",
                   return_value=_hard_dec):
            result = _arch._get_embedding("test")
        self.assertIsNone(result)

    def test_p7_sqlmem_cpu_only_sets_num_gpu_0(self):
        """sql-memory _inline_resolve_target cpu_only single → options={num_gpu: 0}."""
        mod = _load_sqlmem_embedding()
        dec = mod._inline_resolve_target(
            mode="cpu_only", endpoint_mode="single",
            base_endpoint="http://ollama:11434",
            gpu_endpoint="", cpu_endpoint="",
            fallback_policy="best_effort",
        )
        self.assertEqual(dec["effective_target"], "cpu")
        self.assertEqual(dec["options"].get("num_gpu"), 0)

    def test_p7_sqlmem_prefer_gpu_down_cpu_fallback(self):
        """sql-memory _inline_resolve_target prefer_gpu + GPU down → cpu fallback."""
        mod = _load_sqlmem_embedding()
        dec = mod._inline_resolve_target(
            mode="prefer_gpu", endpoint_mode="single",
            base_endpoint="http://ollama:11434",
            gpu_endpoint="", cpu_endpoint="",
            fallback_policy="best_effort",
            availability={"gpu": False, "cpu": True},
        )
        self.assertEqual(dec["effective_target"], "cpu")
        self.assertEqual(dec["fallback_reason"], "gpu_unavailable")
        self.assertFalse(dec["hard_error"])

    def test_p7_sqlmem_all_down_hard_error(self):
        """sql-memory _inline_resolve_target all_down → hard_error=True."""
        mod = _load_sqlmem_embedding()
        dec = mod._inline_resolve_target(
            mode="auto", endpoint_mode="single",
            base_endpoint="http://ollama:11434",
            gpu_endpoint="", cpu_endpoint="",
            fallback_policy="best_effort",
            availability={"gpu": False, "cpu": False},
        )
        self.assertTrue(dec["hard_error"])
        self.assertEqual(dec["error_code"], 503)


if __name__ == "__main__":
    unittest.main()
