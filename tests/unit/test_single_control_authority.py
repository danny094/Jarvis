"""
tests/unit/test_single_control_authority.py — C4.5 Single Control Authority
=============================================================================

DoD (Definition of Done):
  - Kein divergentes Policy-Resultat zwischen skill-server und tool-executor.
  - Genau eine Authority für Entscheidungen im Create/Autonomous-Pfad.
  - Executor führt nur Side-Effects aus.
  - Rollback per Env ohne Code-Revert möglich.

Test coverage (23 Tests):
  Part 1 — Real server.py: blocks locally (executor NOT called)
    1.  test_real_server_blocks_on_cim_block
    2.  test_real_server_blocks_on_package_missing
    3.  test_real_server_block_does_not_call_skill_manager

  Part 2 — Real server.py: approves → control_decision forwarded to executor
    4.  test_real_server_approve_forwards_control_decision
    5.  test_real_server_warn_forwards_control_decision
    6.  test_real_server_control_decision_has_required_fields
    7.  test_real_server_control_decision_source_is_skill_server

  Part 3 — Executor in skill_server mode: installs without local Mini-Control call
    8.  test_executor_skill_server_mode_no_mini_control_call
    9.  test_executor_skill_server_mode_approve_installs
    10. test_executor_skill_server_mode_warn_installs

  Part 4 — Executor fail-closed: strict control_decision validation
    11. test_executor_missing_control_decision_returns_error
    12. test_executor_block_decision_returns_rejected
    13. test_executor_empty_control_decision_returns_error
    14. test_executor_invalid_action_returns_rejected
    15. test_executor_passed_false_returns_rejected
    16. test_executor_wrong_source_returns_rejected

  Part 5 — Rollback: legacy_dual uses executor local Mini-Control
    17. test_executor_legacy_dual_calls_mini_control
    18. test_executor_legacy_dual_approve_installs
    19. test_executor_legacy_dual_block_returns_decision

  Part 6 — config.py getter
    20. test_get_skill_control_authority_default_is_skill_server
    21. test_get_skill_control_authority_env_override
    22. test_get_skill_control_authority_legacy_dual

  Part 7 — autonomous flow passes control_decision to _install_skill
    23. test_autonomous_install_receives_control_decision

Gate: python -m pytest tests/unit/test_single_control_authority.py -q
Expected: ≥ 23 passed, 0 failures
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# ── Repo paths ─────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_TOOL_EXECUTOR = os.path.join(_REPO_ROOT, "tool_executor")
_SKILL_SERVER = os.path.join(_REPO_ROOT, "mcp-servers", "skill-server")

# Fallback for /tmp execution
for _path in [_REPO_ROOT, _TOOL_EXECUTOR]:
    if not os.path.isdir(_path):
        _REPO_ROOT = "/DATA/AppData/MCP/Jarvis/Jarvis"
        _TOOL_EXECUTOR = os.path.join(_REPO_ROOT, "tool_executor")
        _SKILL_SERVER = os.path.join(_REPO_ROOT, "mcp-servers", "skill-server")
        break

for p in [_REPO_ROOT, _TOOL_EXECUTOR, _SKILL_SERVER]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ── ControlAction enum (shared) ────────────────────────────────────────────────
from enum import Enum

class _CA(Enum):
    APPROVE = "approve"
    WARN = "warn"
    BLOCK = "block"
    ESCALATE = "escalate"


# ── Loader: tool_executor/api.py ───────────────────────────────────────────────

def _load_executor_api(authority: str = "skill_server"):
    """Load tool_executor/api.py with mocked deps + authority env."""
    _control_mock = MagicMock()
    _control_mock.process_request = AsyncMock(
        return_value=MagicMock(
            action=_CA("block"),
            passed=False,
            reason="mock",
            warnings=[],
            validation_result=None,
            to_dict=lambda: {"action": "block", "passed": False},
        )
    )
    _control_mock.validate_code_quick = MagicMock(return_value={"passed": True, "score": 0.9})
    _control_mock.get_applicable_priors = MagicMock(return_value=[])

    _mcl_mod = MagicMock()
    _mcl_mod.get_mini_control = MagicMock(return_value=_control_mock)
    _mcl_mod.SkillRequest = MagicMock()
    _mcl_mod.ControlAction = _CA

    _skill_installer_mock = MagicMock()
    _skill_installer_mock.return_value.save_skill = MagicMock(
        return_value={"success": True, "path": "/skills/test"}
    )

    _engine_mod = MagicMock()
    _engine_mod.SkillInstaller = _skill_installer_mock

    _event_logger_mod = MagicMock()
    _event_logger_mod.EventLogger = MagicMock()
    _event_logger_mod.EventLogger.emit = MagicMock()

    _jsonschema_mod = MagicMock()
    _jsonschema_mod.validate = MagicMock()
    _jsonschema_mod.ValidationError = Exception

    mocks = {
        "mini_control_layer": _mcl_mod,
        "engine.skill_installer": _engine_mod,
        "observability.events": _event_logger_mod,
        "jsonschema": _jsonschema_mod,
        "uvicorn": MagicMock(),
    }

    with patch.dict(os.environ, {"SKILL_CONTROL_AUTHORITY": authority}):
        with patch.dict(sys.modules, mocks):
            spec = importlib.util.spec_from_file_location(
                "tool_executor_api", os.path.join(_TOOL_EXECUTOR, "api.py")
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

    return mod, _control_mock, _skill_installer_mock


def _make_create_request(mod, control_decision=None, **overrides):
    """Create a CreateSkillRequest with sensible defaults."""
    defaults = dict(
        name="test_skill",
        code="def run(**kwargs): return {}",
        description="A test skill for unit testing purposes.",
        triggers=["test"],
        auto_promote=True,
        gap_patterns=[],
        gap_question=None,
        preferred_model=None,
        default_params={},
        control_decision=control_decision,
    )
    defaults.update(overrides)
    return mod.CreateSkillRequest(**defaults)


# ── Loader: mcp-servers/skill-server/server.py ────────────────────────────────

def _build_server_mocks(ctrl_mock_override=None):
    """
    Build sys.modules mock dict + return the ctrl and manager mocks.

    ctrl_mock_override: pre-configured ctrl mock (optional).
    The modules_patcher must be started by the caller.

    C7: adds _get_package_allowlist + _auto_install_packages to ctrl_mock,
    and mocks 'config' so get_skill_package_install_mode() is deterministic.
    """
    ctrl_mock = ctrl_mock_override or MagicMock()
    if ctrl_mock_override is None:
        ctrl_mock._check_missing_packages = AsyncMock(return_value=[])
        # C7: fail-closed defaults — empty allowlist means all pkgs non-allowlisted
        ctrl_mock._get_package_allowlist = AsyncMock(return_value=set())
        ctrl_mock._auto_install_packages = AsyncMock(return_value={"success": True})
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

    # C7: mock config so get_skill_package_install_mode() returns "allowlist_auto"
    config_mod = MagicMock()
    config_mod.get_skill_package_install_mode = MagicMock(return_value="allowlist_auto")

    mocks_dict = {
        "mini_control_layer": mcl_mod,
        "skill_manager": skill_manager_mod,
        "skill_memory": MagicMock(),
        "skill_knowledge": skill_knowledge_mod,
        "uvicorn": MagicMock(),
        "config": config_mod,  # C7
    }
    return mocks_dict, ctrl_mock, manager_mock


def _load_server_module(mocks_dict):
    """Load server.py given an active mocks_dict (caller must start patch first)."""
    spec = importlib.util.spec_from_file_location(
        "server_actual", os.path.join(_SKILL_SERVER, "server.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Shared valid control_decision ──────────────────────────────────────────────

_VALID_CD = {
    "action": "approve",
    "passed": True,
    "reason": "All checks passed",
    "warnings": [],
    "validation_score": 0.95,
    "source": "skill_server",
    "policy_version": "1.0",
}


# ═══════════════════════════════════════════════════════════════════════════════
# Part 1 — Real server.py: blocks locally (executor NOT called)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRealServerBlocksLocally(unittest.IsolatedAsyncioTestCase):
    """
    Load actual server.py and verify that CIM BLOCK decisions are handled locally
    — skill_manager.create_skill must NOT be called.
    """

    def setUp(self):
        mocks_dict, self.ctrl_mock, self.manager_mock = _build_server_mocks()
        self.patcher = patch.dict(sys.modules, mocks_dict)
        self.patcher.start()
        self.mod = _load_server_module(mocks_dict)

    def tearDown(self):
        self.patcher.stop()

    def _set_block_decision(self, reason="Critical security issue"):
        dec = MagicMock()
        dec.passed = False
        dec.reason = reason
        dec.action = MagicMock()
        dec.action.value = "block"
        dec.warnings = ["dangerous code"]
        dec.validation_result = None
        self.ctrl_mock.process_request = AsyncMock(return_value=dec)

    async def test_real_server_blocks_on_cim_block(self):
        self._set_block_decision("Critical security issue")
        result = await self.mod.handle_create_skill({
            "name": "bad_skill",
            "code": "def run(**k): return {}",
            "description": "Bad skill with dangerous code here",
            "triggers": [],
            "auto_promote": True,
        })
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Critical security issue")
        self.assertEqual(result["action"], "block")

    async def test_real_server_blocks_on_package_missing(self):
        """Package check: numpy not in empty allowlist → pending_package_approval (C7 fail-closed)."""
        self.ctrl_mock._check_missing_packages = AsyncMock(return_value=["numpy"])
        result = await self.mod.handle_create_skill({
            "name": "pkg_skill",
            "code": "import numpy; def run(**k): return {}",
            "description": "Skill requiring numpy package install",
            "triggers": [],
            "auto_promote": True,
        })
        self.assertFalse(result["success"])
        self.assertTrue(result.get("needs_package_install"))
        self.assertIn("numpy", result["missing_packages"])

    async def test_real_server_block_does_not_call_skill_manager(self):
        """On CIM block, skill_manager.create_skill must never be called."""
        self._set_block_decision("High severity issues found (1)")
        await self.mod.handle_create_skill({
            "name": "blocked_skill",
            "code": "def run(**k): return {}",
            "description": "Skill that is blocked by CIM validation check",
            "triggers": [],
            "auto_promote": True,
        })
        self.manager_mock.create_skill.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# Part 2 — Real server.py: approves → control_decision forwarded to executor
# ═══════════════════════════════════════════════════════════════════════════════

class TestRealServerForwardsDecision(unittest.IsolatedAsyncioTestCase):
    """
    Load actual server.py and verify that APPROVE/WARN decisions build and
    forward a complete control_decision to skill_manager.create_skill.
    """

    def setUp(self):
        mocks_dict, self.ctrl_mock, self.manager_mock = _build_server_mocks()
        self.patcher = patch.dict(sys.modules, mocks_dict)
        self.patcher.start()
        self.mod = _load_server_module(mocks_dict)

    def tearDown(self):
        self.patcher.stop()

    def _set_approve_decision(self, action_value="approve", score=0.95):
        dec = MagicMock()
        dec.passed = True
        dec.reason = "All checks passed"
        dec.action = MagicMock()
        dec.action.value = action_value
        dec.warnings = []
        dec.validation_result = MagicMock()
        dec.validation_result.score = score
        self.ctrl_mock.process_request = AsyncMock(return_value=dec)

    def _get_forwarded_skill_data(self):
        """Extract skill_data dict that was passed to manager.create_skill."""
        self.manager_mock.create_skill.assert_called_once()
        call_args = self.manager_mock.create_skill.call_args
        # create_skill(name, skill_data, draft=...)
        return call_args.args[1] if call_args.args else call_args[0][1]

    async def test_real_server_approve_forwards_control_decision(self):
        self._set_approve_decision("approve")
        await self.mod.handle_create_skill({
            "name": "good_skill",
            "code": "def run(**k): return {}",
            "description": "Good skill for approval forwarding test",
            "triggers": ["test"],
            "auto_promote": True,
        })
        self.manager_mock.create_skill.assert_called_once()
        skill_data = self._get_forwarded_skill_data()
        cd = skill_data.get("control_decision")
        self.assertIsNotNone(cd, "control_decision must be forwarded to skill_manager")
        self.assertEqual(cd["action"], "approve")

    async def test_real_server_warn_forwards_control_decision(self):
        self._set_approve_decision("warn", score=0.72)
        await self.mod.handle_create_skill({
            "name": "warn_skill",
            "code": "def run(**k): return {}",
            "description": "Skill with minor issues that gets forwarded",
            "triggers": [],
            "auto_promote": True,
        })
        skill_data = self._get_forwarded_skill_data()
        cd = skill_data.get("control_decision")
        self.assertIsNotNone(cd)
        self.assertEqual(cd["action"], "warn")

    async def test_real_server_control_decision_has_required_fields(self):
        self._set_approve_decision()
        await self.mod.handle_create_skill({
            "name": "field_check_skill",
            "code": "def run(**k): return {}",
            "description": "Skill for required field verification test",
            "triggers": [],
            "auto_promote": True,
        })
        skill_data = self._get_forwarded_skill_data()
        cd = skill_data["control_decision"]
        for field in ("action", "passed", "reason", "warnings",
                      "validation_score", "source", "policy_version"):
            self.assertIn(field, cd, f"control_decision missing field: {field}")

    async def test_real_server_control_decision_source_is_skill_server(self):
        self._set_approve_decision()
        await self.mod.handle_create_skill({
            "name": "source_check_skill",
            "code": "def run(**k): return {}",
            "description": "Skill to verify control_decision source field",
            "triggers": [],
            "auto_promote": True,
        })
        skill_data = self._get_forwarded_skill_data()
        cd = skill_data["control_decision"]
        self.assertEqual(cd["source"], "skill_server")
        self.assertEqual(cd["policy_version"], "1.0")
        self.assertTrue(cd["passed"])


# ═══════════════════════════════════════════════════════════════════════════════
# Part 3 — Executor: skill_server mode installs without Mini-Control call
# ═══════════════════════════════════════════════════════════════════════════════

class TestExecutorSkillServerMode(unittest.IsolatedAsyncioTestCase):
    """Executor in skill_server mode: pure side-effect, no local CIM decision."""

    def setUp(self):
        self.mod, self.ctrl_mock, self.installer_cls = _load_executor_api("skill_server")

    async def test_executor_skill_server_mode_no_mini_control_call(self):
        """In skill_server mode the executor must NOT call get_mini_control().process_request."""
        request = _make_create_request(self.mod, control_decision=_VALID_CD)
        with patch.dict(os.environ, {"SKILL_CONTROL_AUTHORITY": "skill_server"}):
            await self.mod.create_skill(request)
        self.ctrl_mock.process_request.assert_not_called()

    async def test_executor_skill_server_mode_approve_installs(self):
        request = _make_create_request(self.mod, control_decision=_VALID_CD)
        with patch.dict(os.environ, {"SKILL_CONTROL_AUTHORITY": "skill_server"}):
            result = await self.mod.create_skill(request)
        self.assertIn("installation", result)
        self.assertEqual(result["action"], "approve")

    async def test_executor_skill_server_mode_warn_installs(self):
        cd_warn = {**_VALID_CD, "action": "warn", "warnings": ["minor issue"]}
        request = _make_create_request(self.mod, control_decision=cd_warn)
        with patch.dict(os.environ, {"SKILL_CONTROL_AUTHORITY": "skill_server"}):
            result = await self.mod.create_skill(request)
        self.assertIn("installation", result)
        self.assertEqual(result["action"], "warn")


# ═══════════════════════════════════════════════════════════════════════════════
# Part 4 — Executor fail-closed: strict control_decision validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestExecutorFailClosed(unittest.IsolatedAsyncioTestCase):
    """
    Executor in skill_server mode strictly validates control_decision:
    - present (non-empty)
    - action in (approve, warn)
    - passed == True
    - source == "skill_server"
    """

    def setUp(self):
        self.mod, self.ctrl_mock, self.installer_cls = _load_executor_api("skill_server")

    async def test_executor_missing_control_decision_returns_error(self):
        request = _make_create_request(self.mod, control_decision=None)
        with patch.dict(os.environ, {"SKILL_CONTROL_AUTHORITY": "skill_server"}):
            result = await self.mod.create_skill(request)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "missing_authority_decision")

    async def test_executor_block_decision_returns_rejected(self):
        cd_block = {**_VALID_CD, "action": "block", "passed": False}
        request = _make_create_request(self.mod, control_decision=cd_block)
        with patch.dict(os.environ, {"SKILL_CONTROL_AUTHORITY": "skill_server"}):
            result = await self.mod.create_skill(request)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "rejected_by_authority")

    async def test_executor_empty_control_decision_returns_error(self):
        # Empty dict {} is falsy in Python → missing_authority_decision
        request = _make_create_request(self.mod, control_decision={})
        with patch.dict(os.environ, {"SKILL_CONTROL_AUTHORITY": "skill_server"}):
            result = await self.mod.create_skill(request)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "missing_authority_decision")

    async def test_executor_invalid_action_returns_rejected(self):
        cd_invalid = {**_VALID_CD, "action": "escalate"}
        request = _make_create_request(self.mod, control_decision=cd_invalid)
        with patch.dict(os.environ, {"SKILL_CONTROL_AUTHORITY": "skill_server"}):
            result = await self.mod.create_skill(request)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "rejected_by_authority")

    async def test_executor_passed_false_returns_rejected(self):
        """passed must be exactly True — False is rejected even with valid action."""
        cd_not_passed = {**_VALID_CD, "passed": False}
        request = _make_create_request(self.mod, control_decision=cd_not_passed)
        with patch.dict(os.environ, {"SKILL_CONTROL_AUTHORITY": "skill_server"}):
            result = await self.mod.create_skill(request)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "rejected_by_authority")

    async def test_executor_wrong_source_returns_rejected(self):
        """source must be exactly 'skill_server' — any other value is rejected."""
        cd_wrong_source = {**_VALID_CD, "source": "unknown_service"}
        request = _make_create_request(self.mod, control_decision=cd_wrong_source)
        with patch.dict(os.environ, {"SKILL_CONTROL_AUTHORITY": "skill_server"}):
            result = await self.mod.create_skill(request)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "rejected_by_authority")


# ═══════════════════════════════════════════════════════════════════════════════
# Part 5 — Rollback: legacy_dual uses executor local Mini-Control
# ═══════════════════════════════════════════════════════════════════════════════

class TestLegacyDualRollback(unittest.IsolatedAsyncioTestCase):
    """In legacy_dual mode, executor calls its own Mini-Control."""

    def setUp(self):
        self.mod, self.ctrl_mock, self.installer_cls = _load_executor_api("legacy_dual")

    def _set_mini_control_decision(self, action_value, passed):
        # Use the SAME ControlAction enum the loaded module has.
        CA = self.mod.ControlAction
        vr = MagicMock()
        vr.score = 0.95
        dec = MagicMock()
        dec.passed = passed
        dec.reason = f"legacy {action_value}"
        dec.action = CA(action_value)
        dec.warnings = []
        dec.validation_result = vr
        dec.to_dict = lambda: {"action": action_value, "passed": passed}
        self.ctrl_mock.process_request = AsyncMock(return_value=dec)

    async def test_executor_legacy_dual_calls_mini_control(self):
        self._set_mini_control_decision("approve", True)
        request = _make_create_request(self.mod, control_decision=None)
        with patch.dict(os.environ, {"SKILL_CONTROL_AUTHORITY": "legacy_dual"}):
            await self.mod.create_skill(request)
        self.ctrl_mock.process_request.assert_called_once()

    async def test_executor_legacy_dual_approve_installs(self):
        self._set_mini_control_decision("approve", True)
        request = _make_create_request(self.mod, control_decision=None)
        with patch.dict(os.environ, {"SKILL_CONTROL_AUTHORITY": "legacy_dual"}):
            result = await self.mod.create_skill(request)
        self.assertIn("installation", result)

    async def test_executor_legacy_dual_block_returns_decision(self):
        self._set_mini_control_decision("block", False)
        request = _make_create_request(self.mod, control_decision=None)
        with patch.dict(os.environ, {"SKILL_CONTROL_AUTHORITY": "legacy_dual"}):
            result = await self.mod.create_skill(request)
        self.assertFalse(result["passed"])
        self.assertEqual(result["action"], "block")


# ═══════════════════════════════════════════════════════════════════════════════
# Part 6 — config.py getter
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfigGetter(unittest.TestCase):
    """get_skill_control_authority() returns correct value."""

    def _load_config(self):
        """Load config.py with settings mock. Caller patches env as needed."""
        _settings_mod = MagicMock()
        _settings_mod.settings = MagicMock()
        _settings_mod.settings.get = lambda key, default="": default

        with patch.dict(sys.modules, {"utils.settings": _settings_mod}):
            spec = importlib.util.spec_from_file_location(
                "config_test", os.path.join(_REPO_ROOT, "config.py")
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        return mod

    def test_get_skill_control_authority_default_is_skill_server(self):
        cfg = self._load_config()
        saved = os.environ.pop("SKILL_CONTROL_AUTHORITY", None)
        try:
            self.assertEqual(cfg.get_skill_control_authority(), "skill_server")
        finally:
            if saved is not None:
                os.environ["SKILL_CONTROL_AUTHORITY"] = saved

    def test_get_skill_control_authority_env_override(self):
        # Call getter while env is patched (reads os.getenv at call time)
        cfg = self._load_config()
        with patch.dict(os.environ, {"SKILL_CONTROL_AUTHORITY": "legacy_dual"}):
            self.assertEqual(cfg.get_skill_control_authority(), "legacy_dual")

    def test_get_skill_control_authority_legacy_dual(self):
        cfg = self._load_config()
        with patch.dict(os.environ, {"SKILL_CONTROL_AUTHORITY": "legacy_dual"}):
            self.assertEqual(cfg.get_skill_control_authority(), "legacy_dual")


# ═══════════════════════════════════════════════════════════════════════════════
# Part 7 — autonomous flow passes control_decision to _install_skill
# ═══════════════════════════════════════════════════════════════════════════════

class TestAutonomousControlDecision(unittest.IsolatedAsyncioTestCase):
    """process_autonomous_task passes control_decision to _install_skill."""

    async def test_autonomous_install_receives_control_decision(self):
        """After validation passes, _install_skill must be called with control_decision."""
        received = {}

        async def fake_install(name, code, desc, auto_promote=True,
                               gap_patterns=None, gap_question=None,
                               default_params=None, control_decision=None):
            received["control_decision"] = control_decision
            return {"passed": True, "installation": {"success": True}}

        vr = MagicMock()
        vr.passed = True
        vr.score = 0.9
        vr.issues = []

        cim_mock = MagicMock()
        cim_mock.validate_code = MagicMock(return_value=vr)

        sys_mocks = {
            "skill_cim_light": MagicMock(
                SkillCIMLight=MagicMock,
                ValidationResult=MagicMock,
                get_skill_cim=MagicMock(return_value=cim_mock),
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
                "ss_mcl",
                os.path.join(_SKILL_SERVER, "mini_control_layer.py"),
            )
            ss_mcl = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(ss_mcl)

        ctrl = ss_mcl.SkillMiniControl(cim=cim_mock)
        ctrl._find_matching_skill = AsyncMock(return_value=None)
        ctrl._detect_gaps = MagicMock(return_value=None)
        ctrl._check_missing_packages = AsyncMock(return_value=[])
        ctrl._generate_code_with_coder = AsyncMock(return_value="def run(**k): return {}")
        ctrl._install_skill = fake_install
        ctrl._run_skill = AsyncMock(return_value={"success": True, "result": "ok"})

        task = ss_mcl.AutonomousTaskRequest(
            user_text="test task",
            intent="test intent",
            complexity=3,
            allow_auto_create=True,
            execute_after_create=True,
        )
        result = await ctrl.process_autonomous_task(task)

        self.assertIsNotNone(received.get("control_decision"),
                             "_install_skill must receive control_decision")
        cd = received["control_decision"]
        self.assertEqual(cd["source"], "skill_server")
        self.assertIn(cd["action"], ("approve", "warn"))
        self.assertTrue(cd["passed"])


if __name__ == "__main__":
    unittest.main()
