"""
tests/unit/test_skill_package_policy.py — C7 Package-Policy as Event/State
============================================================================

DoD:
  - Non-allowlisted packages NEVER auto-installed.
  - Fail-closed: any non-allowlisted → pending_package_approval (no partial installs).
  - Rollback: SKILL_PACKAGE_INSTALL_MODE=manual_only → old behavior (needs_package_install).
  - needs_package_install compat field preserved in non-allowlisted response.
  - AutonomousTaskResult.to_dict() emits full approval signal (Finding 2 fix).
  - Orchestrator stores entry_type="approval_requested" for pending_package_approval (Finding 1 fix).

Test coverage (28 tests):
  Part 1 — Config getter (3 tests)
  Part 2 — Non-allowlisted → pending_package_approval (3 tests)
  Part 3 — Allowlisted → auto-install → create continues (3 tests)
  Part 4 — Mixed list fail-closed (2 tests)
  Part 5 — manual_only rollback (2 tests)
  Part 6 — Fail-closed allowlist fetch (2 tests)
  Part 7 — Source inspection (6 tests)
  Part 8 — Finding fixes: to_dict() signal + orchestrator event routing (8 tests)

Gate: python -m pytest tests/unit/test_skill_package_policy.py -q
Expected: 29 passed, 0 failures
"""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# ── Repo paths ──────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_SKILL_SERVER = os.path.join(_REPO_ROOT, "mcp-servers", "skill-server")

for _path in [_REPO_ROOT, _SKILL_SERVER]:
    if not os.path.isdir(_path):
        _REPO_ROOT = "/DATA/AppData/MCP/Jarvis/Jarvis"
        _SKILL_SERVER = os.path.join(_REPO_ROOT, "mcp-servers", "skill-server")
        break

for p in [_REPO_ROOT, _SKILL_SERVER]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ── Shared helpers ──────────────────────────────────────────────────────────

def _load_config():
    """Load config.py with stubbed utils.settings."""
    _settings_mod = MagicMock()
    _settings_mod.settings = MagicMock()
    _settings_mod.settings.get = lambda key, default="": default
    with patch.dict(sys.modules, {"utils.settings": _settings_mod}):
        spec = importlib.util.spec_from_file_location(
            "config_c7", os.path.join(_REPO_ROOT, "config.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


def _build_server_mocks(
    pkg_mode="allowlist_auto",
    allowlist=None,
    install_result=None,
    missing_pkgs=None,
):
    """
    Build mocks_dict for loading server.py.
    Returns (mocks_dict, ctrl_mock, manager_mock).
    """
    if allowlist is None:
        allowlist = set()
    if install_result is None:
        install_result = {"success": True}
    if missing_pkgs is None:
        missing_pkgs = []

    ctrl_mock = MagicMock()
    ctrl_mock._check_missing_packages = AsyncMock(return_value=missing_pkgs)
    ctrl_mock._get_package_allowlist = AsyncMock(return_value=allowlist)
    ctrl_mock._auto_install_packages = AsyncMock(return_value=install_result)
    ctrl_mock.process_request = AsyncMock(
        return_value=MagicMock(
            passed=True,
            reason="All checks passed",
            action=MagicMock(value="approve"),
            warnings=[],
            validation_result=MagicMock(score=0.95),
        )
    )

    mcl_mod = MagicMock()
    mcl_mod.get_mini_control = MagicMock(return_value=ctrl_mock)
    mcl_mod.SkillRequest = MagicMock(return_value=MagicMock())

    manager_mock = MagicMock()
    manager_mock.create_skill = AsyncMock(
        return_value={"passed": True, "installation": {"success": True}}
    )

    skill_manager_mod = MagicMock()
    skill_manager_mod.SkillManager = MagicMock(return_value=manager_mock)

    skill_knowledge_mod = MagicMock()
    skill_knowledge_mod.get_categories = MagicMock(return_value=[])
    skill_knowledge_mod.search = MagicMock(return_value=[])
    skill_knowledge_mod.handle_query_skill_knowledge = MagicMock(return_value={})

    config_mod = MagicMock()
    config_mod.get_skill_package_install_mode = MagicMock(return_value=pkg_mode)

    mocks_dict = {
        "mini_control_layer": mcl_mod,
        "skill_manager": skill_manager_mod,
        "skill_memory": MagicMock(),
        "skill_knowledge": skill_knowledge_mod,
        "uvicorn": MagicMock(),
        "config": config_mod,
    }
    return mocks_dict, ctrl_mock, manager_mock


def _load_server(mocks_dict):
    """Load server.py with mocks active."""
    spec = importlib.util.spec_from_file_location(
        "server_c7", os.path.join(_SKILL_SERVER, "server.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_DEFAULT_SKILL_ARGS = {
    "name": "test_skill",
    "code": "def run(**kwargs): return {}",
    "description": "A test skill for C7 package policy tests.",
    "triggers": ["test"],
    "auto_promote": True,
}


# ══════════════════════════════════════════════════════════════════════════════
# Part 1 — Config getter
# ══════════════════════════════════════════════════════════════════════════════

class TestPackagePolicyConfigGetter(unittest.TestCase):
    """get_skill_package_install_mode() contract."""

    def test_default_is_allowlist_auto(self):
        cfg = _load_config()
        saved = os.environ.pop("SKILL_PACKAGE_INSTALL_MODE", None)
        try:
            self.assertEqual(cfg.get_skill_package_install_mode(), "allowlist_auto")
        finally:
            if saved is not None:
                os.environ["SKILL_PACKAGE_INSTALL_MODE"] = saved

    def test_env_override_manual_only(self):
        cfg = _load_config()
        with patch.dict(os.environ, {"SKILL_PACKAGE_INSTALL_MODE": "manual_only"}):
            self.assertEqual(cfg.get_skill_package_install_mode(), "manual_only")

    def test_unknown_value_falls_back_to_allowlist_auto(self):
        cfg = _load_config()
        with patch.dict(os.environ, {"SKILL_PACKAGE_INSTALL_MODE": "super_secret_mode"}):
            self.assertEqual(cfg.get_skill_package_install_mode(), "allowlist_auto")


# ══════════════════════════════════════════════════════════════════════════════
# Part 2 — Non-allowlisted → pending_package_approval
# ══════════════════════════════════════════════════════════════════════════════

class TestPackagePolicyNonAllowlisted(unittest.IsolatedAsyncioTestCase):
    """Non-allowlisted packages must NEVER auto-install → pending_package_approval."""

    def setUp(self):
        self.mocks_dict, self.ctrl_mock, self.manager_mock = _build_server_mocks(
            pkg_mode="allowlist_auto",
            allowlist=set(),       # empty → all non-allowlisted
            missing_pkgs=["numpy"],
        )
        self.patcher = patch.dict(sys.modules, self.mocks_dict)
        self.patcher.start()
        self.mod = _load_server(self.mocks_dict)

    def tearDown(self):
        self.patcher.stop()

    async def test_non_allowlisted_returns_pending_approval(self):
        result = await self.mod.handle_create_skill(_DEFAULT_SKILL_ARGS)
        self.assertFalse(result["success"])
        self.assertEqual(result.get("action_taken"), "pending_package_approval")
        self.assertTrue(result.get("needs_package_install"),
                        "compat field needs_package_install must be True")
        self.assertTrue(result.get("needs_package_approval"))
        self.assertIn("numpy", result["missing_packages"])
        self.assertIn("numpy", result["non_allowlisted_packages"])

    async def test_non_allowlisted_does_not_auto_install(self):
        await self.mod.handle_create_skill(_DEFAULT_SKILL_ARGS)
        self.ctrl_mock._auto_install_packages.assert_not_called()

    async def test_non_allowlisted_does_not_call_create_skill(self):
        await self.mod.handle_create_skill(_DEFAULT_SKILL_ARGS)
        self.manager_mock.create_skill.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# Part 3 — Allowlisted → auto-install → create continues
# ══════════════════════════════════════════════════════════════════════════════

class TestPackagePolicyAllowlisted(unittest.IsolatedAsyncioTestCase):
    """Allowlisted packages are auto-installed and skill creation continues."""

    def setUp(self):
        self.mocks_dict, self.ctrl_mock, self.manager_mock = _build_server_mocks(
            pkg_mode="allowlist_auto",
            allowlist={"numpy"},   # numpy IS allowlisted
            missing_pkgs=["numpy"],
            install_result={"success": True},
        )
        self.patcher = patch.dict(sys.modules, self.mocks_dict)
        self.patcher.start()
        self.mod = _load_server(self.mocks_dict)

    def tearDown(self):
        self.patcher.stop()

    async def test_allowlisted_calls_auto_install(self):
        await self.mod.handle_create_skill(_DEFAULT_SKILL_ARGS)
        self.ctrl_mock._auto_install_packages.assert_called_once_with(["numpy"])

    async def test_allowlisted_create_skill_called(self):
        await self.mod.handle_create_skill(_DEFAULT_SKILL_ARGS)
        self.manager_mock.create_skill.assert_called_once()

    async def test_allowlisted_install_failure_blocks_create(self):
        self.ctrl_mock._auto_install_packages = AsyncMock(
            return_value={"success": False, "error": "pip timeout"}
        )
        result = await self.mod.handle_create_skill(_DEFAULT_SKILL_ARGS)
        self.assertFalse(result["success"])
        self.manager_mock.create_skill.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# Part 4 — Mixed list fail-closed
# ══════════════════════════════════════════════════════════════════════════════

class TestPackagePolicyMixedList(unittest.IsolatedAsyncioTestCase):
    """Any non-allowlisted package → pending_package_approval (fail-closed)."""

    def setUp(self):
        self.mocks_dict, self.ctrl_mock, self.manager_mock = _build_server_mocks(
            pkg_mode="allowlist_auto",
            allowlist={"numpy"},   # numpy=allowlisted; malicious_pkg=NOT
            missing_pkgs=["numpy", "malicious_pkg"],
        )
        self.patcher = patch.dict(sys.modules, self.mocks_dict)
        self.patcher.start()
        self.mod = _load_server(self.mocks_dict)

    def tearDown(self):
        self.patcher.stop()

    async def test_mixed_any_non_allowlisted_pending_approval(self):
        result = await self.mod.handle_create_skill(_DEFAULT_SKILL_ARGS)
        self.assertFalse(result["success"])
        self.assertEqual(result.get("action_taken"), "pending_package_approval")
        self.assertIn("malicious_pkg", result["non_allowlisted_packages"])
        self.assertIn("numpy", result.get("allowlisted_missing_packages", []))

    async def test_mixed_no_auto_install_when_any_non_allowlisted(self):
        await self.mod.handle_create_skill(_DEFAULT_SKILL_ARGS)
        self.ctrl_mock._auto_install_packages.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# Part 5 — manual_only rollback
# ══════════════════════════════════════════════════════════════════════════════

class TestPackagePolicyManualOnly(unittest.IsolatedAsyncioTestCase):
    """SKILL_PACKAGE_INSTALL_MODE=manual_only restores original behavior."""

    def setUp(self):
        self.mocks_dict, self.ctrl_mock, self.manager_mock = _build_server_mocks(
            pkg_mode="manual_only",
            allowlist={"numpy"},   # allowlist available but must NOT be used
            missing_pkgs=["numpy"],
        )
        self.patcher = patch.dict(sys.modules, self.mocks_dict)
        self.patcher.start()
        self.mod = _load_server(self.mocks_dict)

    def tearDown(self):
        self.patcher.stop()

    async def test_manual_only_returns_needs_package_install(self):
        result = await self.mod.handle_create_skill(_DEFAULT_SKILL_ARGS)
        self.assertFalse(result["success"])
        self.assertTrue(result.get("needs_package_install"),
                        "manual_only must return needs_package_install=True")
        self.assertIn("numpy", result["missing_packages"])
        self.assertNotEqual(result.get("action_taken"), "pending_package_approval",
                            "manual_only must not return pending_package_approval shape")

    async def test_manual_only_does_not_call_allowlist(self):
        await self.mod.handle_create_skill(_DEFAULT_SKILL_ARGS)
        self.ctrl_mock._get_package_allowlist.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# Part 6 — Fail-closed allowlist fetch
# ══════════════════════════════════════════════════════════════════════════════

class TestPackagePolicyFailClosedAllowlist(unittest.IsolatedAsyncioTestCase):
    """Allowlist fetch error (→ empty set) means all packages non-allowlisted → pending approval."""

    def setUp(self):
        self.mocks_dict, self.ctrl_mock, self.manager_mock = _build_server_mocks(
            pkg_mode="allowlist_auto",
            allowlist=set(),       # simulates fetch-error → empty set
            missing_pkgs=["requests"],
        )
        self.patcher = patch.dict(sys.modules, self.mocks_dict)
        self.patcher.start()
        self.mod = _load_server(self.mocks_dict)

    def tearDown(self):
        self.patcher.stop()

    async def test_empty_allowlist_all_packages_non_allowlisted(self):
        result = await self.mod.handle_create_skill(_DEFAULT_SKILL_ARGS)
        self.assertFalse(result["success"])
        self.assertEqual(result.get("action_taken"), "pending_package_approval")

    async def test_empty_allowlist_no_auto_install(self):
        await self.mod.handle_create_skill(_DEFAULT_SKILL_ARGS)
        self.ctrl_mock._auto_install_packages.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# Part 7 — Source inspection
# ══════════════════════════════════════════════════════════════════════════════

class TestPackagePolicySourceInspection(unittest.TestCase):
    """Verify C7 methods exist in production source files."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(_SKILL_SERVER, "mini_control_layer.py")) as f:
            cls._mcl_source = f.read()
        with open(os.path.join(_SKILL_SERVER, "server.py")) as f:
            cls._server_source = f.read()

    def test_get_package_allowlist_in_mini_control_layer(self):
        self.assertIn("_get_package_allowlist", self._mcl_source)

    def test_auto_install_packages_in_mini_control_layer(self):
        self.assertIn("_auto_install_packages", self._mcl_source)

    def test_server_uses_get_package_allowlist(self):
        self.assertIn("_get_package_allowlist", self._server_source)

    def test_server_uses_auto_install_packages(self):
        self.assertIn("_auto_install_packages", self._server_source)

    def test_server_pending_package_approval_shape(self):
        self.assertIn("pending_package_approval", self._server_source)

    def test_mini_control_layer_pending_package_approval(self):
        self.assertIn("pending_package_approval", self._mcl_source)


# ══════════════════════════════════════════════════════════════════════════════
# Part 8 — Finding fixes
# ══════════════════════════════════════════════════════════════════════════════

class TestAutonomousTaskResultToDict(unittest.TestCase):
    """
    Finding 2 fix: AutonomousTaskResult.to_dict() must emit full approval signal
    when action_taken == 'pending_package_approval'.
    """

    @classmethod
    def setUpClass(cls):
        """Load mini_control_layer via importlib with minimal mocks."""
        sys_mocks = {
            "skill_cim_light": MagicMock(
                SkillCIMLight=MagicMock,
                ValidationResult=MagicMock,
                get_skill_cim=MagicMock(return_value=MagicMock()),
            ),
            "cim_rag": MagicMock(
                cim_kb=MagicMock(
                    load=MagicMock(),
                    get_template_by_intent=MagicMock(return_value=None),
                    get_persona=MagicMock(return_value=""),
                )
            ),
            "httpx": MagicMock(),
        }
        with patch.dict(sys.modules, sys_mocks):
            spec = importlib.util.spec_from_file_location(
                "mcl_finding2", os.path.join(_SKILL_SERVER, "mini_control_layer.py")
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        cls._mcl = mod

    def _make_result(self, action_taken, error="", skill_name="test_skill"):
        return self._mcl.AutonomousTaskResult(
            success=False,
            action_taken=action_taken,
            skill_name=skill_name,
            error=error,
            message="test",
        )

    def test_pending_package_approval_needs_package_install(self):
        r = self._make_result("pending_package_approval",
                              error="missing_packages:numpy,requests")
        d = r.to_dict()
        self.assertTrue(d.get("needs_package_install"),
                        "to_dict must set needs_package_install=True")

    def test_pending_package_approval_needs_package_approval(self):
        r = self._make_result("pending_package_approval",
                              error="missing_packages:numpy")
        d = r.to_dict()
        self.assertTrue(d.get("needs_package_approval"),
                        "to_dict must set needs_package_approval=True")

    def test_pending_package_approval_event_type(self):
        r = self._make_result("pending_package_approval",
                              error="missing_packages:numpy")
        d = r.to_dict()
        self.assertEqual(d.get("event_type"), "approval_requested",
                         "to_dict must set event_type='approval_requested'")

    def test_pending_package_approval_missing_packages_list(self):
        r = self._make_result("pending_package_approval",
                              error="missing_packages:numpy,pandas")
        d = r.to_dict()
        self.assertIn("numpy", d.get("missing_packages", []))
        self.assertIn("pandas", d.get("missing_packages", []))

    def test_needs_package_install_action_unaffected(self):
        """Original needs_package_install branch must still work."""
        r = self._make_result("needs_package_install",
                              error="missing_packages:scipy")
        d = r.to_dict()
        self.assertTrue(d.get("needs_package_install"))
        self.assertNotIn("needs_package_approval", d)
        self.assertNotIn("event_type", d)


class TestOrchestratorApprovalEventRouting(unittest.TestCase):
    """
    Finding 1 fix: orchestrator._build_tool_result_card must store
    entry_type='approval_requested' when tool result contains event_type/action_taken
    indicating a pending_package_approval.
    """

    @classmethod
    def setUpClass(cls):
        """Load orchestrator source to verify the fix is present."""
        _orch_path = os.path.join(_REPO_ROOT, "core", "orchestrator.py")
        with open(_orch_path) as f:
            cls._orch_source = f.read()

    def test_orchestrator_detects_approval_requested_event(self):
        self.assertIn("approval_requested", self._orch_source,
                      "orchestrator must detect approval_requested event_type")

    def test_orchestrator_detects_pending_package_approval_action(self):
        self.assertIn("pending_package_approval", self._orch_source,
                      "orchestrator must handle pending_package_approval action_taken")

    def test_orchestrator_uses_dynamic_entry_type(self):
        """entry_type must not be hardcoded 'tool_result' in _build_tool_result_card."""
        # The fix introduces _entry_type variable; hardcoded string must not be sole path
        self.assertIn("_entry_type", self._orch_source,
                      "orchestrator must use dynamic _entry_type variable")


if __name__ == "__main__":
    unittest.main()
