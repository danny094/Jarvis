"""
Behavior test: malicious skill code is rejected in skill-server create flow.

Goal:
1. A malicious CREATE payload (e.g. eval/os.system) is blocked by policy.
2. The request is NOT forwarded to skill_manager.create_skill (executor path).
3. This must hold even when auto_promote=False (no draft parking for blocked code).
"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_SKILL_SERVER = os.path.join(_REPO_ROOT, "mcp-servers", "skill-server")

if not os.path.isdir(_SKILL_SERVER):
    _REPO_ROOT = "/DATA/AppData/MCP/Jarvis/Jarvis"
    _SKILL_SERVER = os.path.join(_REPO_ROOT, "mcp-servers", "skill-server")

for _path in (_REPO_ROOT, _SKILL_SERVER):
    if _path not in sys.path:
        sys.path.insert(0, _path)


def _load_server_with_real_control():
    """
    Load real skill-server/server.py while mocking only external server deps.

    Important: mini_control_layer stays real so the test exercises the real
    SkillCIMLight policy checks for malicious code.
    """
    manager_mock = MagicMock()
    manager_mock.create_skill = AsyncMock(
        return_value={"success": True, "installation": {"success": True}}
    )

    skill_manager_mod = MagicMock()
    skill_manager_mod.SkillManager = MagicMock(return_value=manager_mock)

    skill_knowledge_mod = MagicMock()
    skill_knowledge_mod.get_categories = MagicMock(return_value=[])
    skill_knowledge_mod.search = MagicMock(return_value=[])
    skill_knowledge_mod.handle_query_skill_knowledge = MagicMock(return_value={})

    mocks = {
        "skill_manager": skill_manager_mod,
        "skill_memory": MagicMock(),
        "skill_knowledge": skill_knowledge_mod,
        "uvicorn": MagicMock(),
    }

    patcher = patch.dict(sys.modules, mocks)
    patcher.start()
    try:
        # Ensure no stale mocked module from previous tests is reused.
        sys.modules.pop("mini_control_layer", None)
        sys.modules.pop("mini_control_core", None)
        sys.modules.pop("skill_cim_light", None)

        spec = importlib.util.spec_from_file_location(
            "skill_server_malicious_path",
            os.path.join(_SKILL_SERVER, "server.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception:
        patcher.stop()
        raise

    return mod, manager_mock, patcher


class TestSkillMaliciousRejectionPath(unittest.IsolatedAsyncioTestCase):
    """
    Real behavior checks for:
    create_skill -> Mini-Control/CIM validation -> local block -> no executor.
    """

    def setUp(self):
        self.mod, self.manager_mock, self.patcher = _load_server_with_real_control()

    def tearDown(self):
        self.patcher.stop()

    async def test_create_skill_blocks_eval_and_os_system_before_executor(self):
        payload = {
            "name": "dangerous_eval_shell_skill",
            "description": "Malicious test skill that must be blocked by policy.",
            "triggers": ["danger", "test"],
            "auto_promote": True,
            "code": (
                "import os\n"
                "def run(**kwargs):\n"
                "    cmd = kwargs.get('cmd', 'echo unsafe')\n"
                "    os.system(cmd)\n"
                "    expr = kwargs.get('expr', '1+1')\n"
                "    return {'result': eval(expr)}\n"
            ),
        }

        result = await self.mod.handle_create_skill(payload)

        self.assertFalse(result.get("success"), result)
        self.assertEqual(result.get("action"), "block", result)
        reason = str(result.get("error", "")).lower()
        self.assertTrue(
            ("critical security issues found" in reason)
            or ("high severity issues found" in reason),
            result,
        )
        self.manager_mock.create_skill.assert_not_called()

    async def test_blocked_code_is_not_saved_as_draft_when_auto_promote_false(self):
        payload = {
            "name": "dangerous_draft_attempt",
            "description": "Malicious draft attempt that must still be blocked.",
            "triggers": ["danger", "draft"],
            "auto_promote": False,  # Draft intent must not bypass security policy.
            "code": (
                "def run(**kwargs):\n"
                "    expression = kwargs.get('expr', '2+2')\n"
                "    return {'result': eval(expression)}\n"
            ),
        }

        result = await self.mod.handle_create_skill(payload)

        self.assertFalse(result.get("success"), result)
        self.assertEqual(result.get("action"), "block", result)
        self.manager_mock.create_skill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
