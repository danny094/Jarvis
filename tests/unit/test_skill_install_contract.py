"""
tests/unit/test_skill_install_contract.py — C2 Install/Contract in Executor
=============================================================================

Covers:
  1. test_skill_install_from_registry_happy_path
       Registry returns valid skill → save_skill called with manifest_data + is_draft=False
  2. test_skill_install_contract_error
       Registry payload violates create_skill.json → ContractViolation,
       save_skill NOT called, error_type=contract_violation
  3. test_registry_install_disabled_by_flag
       ENABLE_SKILL_REGISTRY_INSTALL=false → success=False, error_type=disabled_by_flag
  4. test_contract_violation_class_defined
  5. test_validate_contract_raises_contract_violation
  6. test_create_skill_returns_400_on_contract_violation
     (validate_contract patched directly — never depends on schema file path)

Gate: python -m pytest tests/unit/test_skill_install_contract.py -q
Expected: ≥ 10 passed, 0 failures
"""
from __future__ import annotations

import json
import os
import sys
import unittest
import importlib.util
from unittest.mock import AsyncMock, MagicMock, patch

# ── Repo paths ─────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_TOOL_EXECUTOR = os.path.join(_REPO_ROOT, "tool_executor")

# Fallback when running from /tmp
if not os.path.isdir(os.path.join(_REPO_ROOT, "tool_executor")):
    _REPO_ROOT = "/DATA/AppData/MCP/Jarvis/Jarvis"
    _TOOL_EXECUTOR = os.path.join(_REPO_ROOT, "tool_executor")

if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
if _TOOL_EXECUTOR not in sys.path:
    sys.path.insert(0, _TOOL_EXECUTOR)


# ── Load tool_executor/api.py with mocked deps ────────────────────────────────

def _load_api_module():
    """Load api.py with problematic module-level dependencies mocked.

    Critical: get_mini_control() must return a mock whose process_request is an
    AsyncMock. Using a plain MagicMock causes Python 3.8+ to loop forever when
    the endpoint tries to `await control.process_request(...)`.
    """
    # ── mini_control_layer ───────────────────────────────────────────────────
    # process_request is async in production; AsyncMock prevents the await-hang
    _control_instance = MagicMock()
    _control_instance.process_request = AsyncMock(
        return_value=MagicMock(
            action=object(),          # won't match APPROVE or WARN enums
            to_dict=lambda: {"action": "reject", "success": False},
        )
    )

    _mcl_mock = MagicMock()
    _mcl_mock.get_mini_control.return_value = _control_instance
    _mcl_mock.SkillRequest = MagicMock
    _mcl_mock.ControlAction = MagicMock()

    # ── observability ────────────────────────────────────────────────────────
    _obs_events_mock = MagicMock()
    _obs_events_mock.EventLogger = MagicMock()
    _obs_events_mock.EventLogger.emit = MagicMock()

    _obs_mock = MagicMock()
    _obs_mock.events = _obs_events_mock

    # ── engine sub-packages ──────────────────────────────────────────────────
    _skill_installer_mock = MagicMock()
    _skill_installer_mock.SkillInstaller = MagicMock()

    _skill_runner_mock = MagicMock()
    _skill_runner_mock.get_skill_runner.return_value = MagicMock()

    for mod_name, mock_obj in [
        ("mini_control_layer", _mcl_mock),
        ("engine.skill_installer", _skill_installer_mock),
        ("engine.skill_runner", _skill_runner_mock),
        ("observability.events", _obs_events_mock),
        ("observability", _obs_mock),
        ("engine", MagicMock()),
    ]:
        sys.modules.setdefault(mod_name, mock_obj)

    spec = importlib.util.spec_from_file_location(
        "tool_executor_api_for_c2_test",
        os.path.join(_TOOL_EXECUTOR, "api.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_SKIP_REASON = ""
_api_mod = None
try:
    _api_mod = _load_api_module()
    _HAS_API = True
except Exception as _load_err:
    _HAS_API = False
    _SKIP_REASON = f"API module load failed: {_load_err}"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _mock_registry_response(skill_data: dict, status_code: int = 200):
    """Async httpx mock returning skill_data from GET /skills/{name}."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = skill_data

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


def _mock_installer(save_result: dict | None = None):
    """Mock SkillInstaller class + instance with controlled save_skill return."""
    instance = MagicMock()
    instance.save_skill.return_value = save_result or {
        "success": True,
        "path": "/skills/test_skill",
        "status": "active",
    }
    cls = MagicMock(return_value=instance)
    return cls, instance


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

@unittest.skipUnless(_HAS_API, _SKIP_REASON)
class TestSkillInstallContract(unittest.TestCase):
    """C2 contract tests for tool_executor/api.py install endpoint."""

    @staticmethod
    def _run(coro):
        import asyncio

        return asyncio.run(coro)

    def _install_from_registry(self, name: str):
        req = _api_mod.InstallSkillRequest(name=name)
        return self._run(_api_mod.install_skill_from_registry(req))

    def _create_skill(self, payload: dict):
        req = _api_mod.CreateSkillRequest(**payload)
        return self._run(_api_mod.create_skill(req))

    # ── Test 1: Happy path ────────────────────────────────────────────────────

    def test_skill_install_from_registry_happy_path(self):
        """Valid registry payload → save_skill(manifest_data, is_draft=False), success=True."""
        valid_skill = {
            "name": "test_skill",
            "script": "def run(**kwargs): return {'result': 'ok'}",
            "description": "Test skill that is long enough for the contract",
            "triggers": ["test", "check"],
            "gap_patterns": [],
            "gap_question": None,
            "preferred_model": None,
            "default_params": {},
        }
        installer_cls, installer_instance = _mock_installer()
        mock_client = _mock_registry_response(valid_skill)

        with patch.object(_api_mod, "SkillInstaller", installer_cls), \
             patch("httpx.AsyncClient", return_value=mock_client):
            data = self._install_from_registry("test_skill")
        self.assertTrue(data.get("success"), f"Expected success=True, got: {data}")
        self.assertEqual(data.get("action"), "installed")

        # ── Assert correct save_skill call signature ──────────────────────
        installer_instance.save_skill.assert_called_once()
        args, kwargs = installer_instance.save_skill.call_args
        param_order = ["name", "code", "manifest_data", "is_draft"]
        all_kw = dict(zip(param_order, args))
        all_kw.update(kwargs)

        self.assertIn("manifest_data", all_kw,
                      "save_skill must be called with manifest_data kwarg")
        self.assertIn("is_draft", all_kw,
                      "save_skill must be called with is_draft kwarg")
        self.assertFalse(all_kw["is_draft"],
                         "is_draft must be False for registry installs")

        # Old-style kwargs must be absent
        self.assertNotIn("description", all_kw,
                         "Old-style 'description' kwarg must not be passed")
        self.assertNotIn("metadata", all_kw,
                         "Old-style 'metadata' kwarg must not be passed")

        # manifest_data must carry expected fields
        md = all_kw["manifest_data"]
        self.assertIn("description", md)
        self.assertIn("triggers", md)

    # ── Test 2: Contract violation ────────────────────────────────────────────

    def test_skill_install_contract_error(self):
        """Registry payload violates create_skill.json → ContractViolation, save_skill NOT called."""
        invalid_skill = {
            "name": "bad_skill",
            "script": "def run(**kwargs): return {}",
            "description": "short",   # violates minLength: 10
            "triggers": [],
        }
        installer_cls, installer_instance = _mock_installer()
        mock_client = _mock_registry_response(invalid_skill)

        with patch.object(_api_mod, "SkillInstaller", installer_cls), \
             patch("httpx.AsyncClient", return_value=mock_client):
            data = self._install_from_registry("bad_skill")
        self.assertFalse(data.get("success"), f"Expected success=False, got: {data}")
        self.assertEqual(
            data.get("error_type"), "contract_violation",
            f"Expected error_type=contract_violation, got: {data}"
        )
        self.assertIn("contract violation", data.get("error", "").lower())
        installer_instance.save_skill.assert_not_called()

    # ── Test 3: Rollback flag ─────────────────────────────────────────────────

    def test_registry_install_disabled_by_flag(self):
        """ENABLE_SKILL_REGISTRY_INSTALL=false → success=False, error_type=disabled_by_flag."""
        with patch.dict(os.environ, {"ENABLE_SKILL_REGISTRY_INSTALL": "false"}):
            data = self._install_from_registry("any_skill")
        self.assertFalse(data.get("success"))
        self.assertEqual(data.get("error_type"), "disabled_by_flag")

    def test_registry_install_enabled_by_flag_true(self):
        """ENABLE_SKILL_REGISTRY_INSTALL=true (explicit) → proceeds normally."""
        valid_skill = {
            "name": "enabled_skill",
            "script": "def run(**k): return {}",
            "description": "Long enough description for the contract check",
            "triggers": [],
        }
        installer_cls, installer_instance = _mock_installer()
        mock_client = _mock_registry_response(valid_skill)

        with patch.object(_api_mod, "SkillInstaller", installer_cls), \
             patch("httpx.AsyncClient", return_value=mock_client), \
             patch.dict(os.environ, {"ENABLE_SKILL_REGISTRY_INSTALL": "true"}):
            data = self._install_from_registry("enabled_skill")
        self.assertTrue(data.get("success"), f"Expected success=True: {data}")

    # ── Test 4: ContractViolation class ──────────────────────────────────────

    def test_contract_violation_class_defined(self):
        """ContractViolation must be defined and be an Exception subclass."""
        self.assertTrue(
            hasattr(_api_mod, "ContractViolation"),
            "ContractViolation class must exist in api.py"
        )
        cv = _api_mod.ContractViolation("test")
        self.assertIsInstance(cv, Exception)

    # ── Test 5: validate_contract raises ContractViolation ───────────────────

    def test_validate_contract_raises_contract_violation(self):
        """validate_contract must raise ContractViolation (not HTTPException)."""
        bad_payload = {
            "name": "test",
            "script": "pass",
            "description": "short",   # violates minLength: 10
        }
        with self.assertRaises(_api_mod.ContractViolation):
            _api_mod.validate_contract(bad_payload, "create_skill.json")

    def test_validate_contract_valid_payload_no_raise(self):
        """validate_contract must not raise for a valid payload."""
        good_payload = {
            "name": "valid_skill",
            "script": "def run(**k): return {}",
            "description": "This description is definitely long enough",
        }
        _api_mod.validate_contract(good_payload, "create_skill.json")  # must not raise

    # ── Test 6: create_skill returns 400 ─────────────────────────────────────
    #
    # validate_contract is patched directly so this test never depends on the
    # schema file being readable — the only thing it verifies is that the
    # endpoint maps ContractViolation to HTTP 400 (not 500 or hang).

    def test_create_skill_returns_400_on_contract_violation(self):
        """create_skill endpoint returns HTTP 400 on ContractViolation."""
        from fastapi import HTTPException

        payload = {
            "name": "badskill",
            "code": "def run(**k): return {}",
            "description": "short",
            "triggers": [],
        }
        with patch.object(
            _api_mod, "validate_contract",
            side_effect=_api_mod.ContractViolation("description is too short"),
        ):
            with self.assertRaises(HTTPException) as exc:
                self._create_skill(payload)
        self.assertEqual(exc.exception.status_code, 400)

    # ── Test 7: registry 404 → structured error ───────────────────────────────

    def test_registry_skill_not_found(self):
        """Registry returns 404 → success=False, no crash."""
        mock_client = _mock_registry_response({}, status_code=404)

        with patch("httpx.AsyncClient", return_value=mock_client):
            data = self._install_from_registry("missing_skill")
        self.assertFalse(data.get("success"))
        self.assertIn("missing_skill", data.get("error", ""))

    # ── Test 8: registry 500 → structured error ───────────────────────────────

    def test_registry_server_error(self):
        """Registry returns 500 → success=False, not propagated to caller."""
        mock_client = _mock_registry_response({}, status_code=500)

        with patch("httpx.AsyncClient", return_value=mock_client):
            data = self._install_from_registry("any_skill")
        self.assertFalse(data.get("success"))

    # ── Test 9: save_skill is_draft=False assertion ───────────────────────────

    def test_save_skill_is_draft_false(self):
        """Registry install always saves with is_draft=False."""
        valid_skill = {
            "name": "draft_check",
            "script": "def run(**k): pass",
            "description": "Long enough description for this test to pass checks",
            "triggers": [],
        }
        installer_cls, installer_instance = _mock_installer()
        mock_client = _mock_registry_response(valid_skill)

        with patch.object(_api_mod, "SkillInstaller", installer_cls), \
             patch("httpx.AsyncClient", return_value=mock_client):
            data = self._install_from_registry("draft_check")
        self.assertTrue(data.get("success"))

        installer_instance.save_skill.assert_called_once()
        _, kw = installer_instance.save_skill.call_args
        is_draft = kw.get("is_draft", installer_instance.save_skill.call_args[0][3]
                          if len(installer_instance.save_skill.call_args[0]) > 3 else None)
        self.assertFalse(is_draft, "Registry installs must always use is_draft=False")

    # ── Test 10: manifest_data fields complete ────────────────────────────────

    def test_manifest_data_contains_extended_fields(self):
        """manifest_data passed to save_skill must contain extended fields from registry."""
        skill_with_extras = {
            "name": "extended_skill",
            "script": "def run(**k): pass",
            "description": "Long enough description for this test to work",
            "triggers": ["run_ext"],
            "gap_patterns": ["pattern_a"],
            "gap_question": "Which mode?",
            "preferred_model": "qwen2.5-coder:3b",
            "default_params": {"timeout": 30},
        }
        installer_cls, installer_instance = _mock_installer()
        mock_client = _mock_registry_response(skill_with_extras)

        with patch.object(_api_mod, "SkillInstaller", installer_cls), \
             patch("httpx.AsyncClient", return_value=mock_client):
            data = self._install_from_registry("extended_skill")
        self.assertTrue(data.get("success"))

        _, kw = installer_instance.save_skill.call_args
        md = kw.get("manifest_data") or installer_instance.save_skill.call_args[0][2]
        self.assertEqual(md.get("gap_patterns"), ["pattern_a"])
        self.assertEqual(md.get("gap_question"), "Which mode?")
        self.assertEqual(md.get("preferred_model"), "qwen2.5-coder:3b")
        self.assertEqual(md.get("default_params"), {"timeout": 30})


if __name__ == "__main__":
    unittest.main()
