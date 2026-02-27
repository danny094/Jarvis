"""
Skill-server config fallback guards.

Ensures create_skill package-mode resolution has no hard runtime dependency on
top-level /app/config.py inside isolated skill-server containers.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch


_ROOT = "/DATA/AppData/MCP/Jarvis/Jarvis"
_SKILL_SERVER = os.path.join(_ROOT, "mcp-servers", "skill-server")


def _load_server_module():
    """Load skill-server/server.py with minimal mocked dependencies."""
    ctrl_mock = MagicMock()
    ctrl_mock._check_missing_packages = AsyncMock(return_value=[])
    ctrl_mock.process_request = AsyncMock(
        return_value=MagicMock(
            passed=True,
            reason="ok",
            action=MagicMock(value="approve"),
            warnings=[],
            validation_result=MagicMock(score=1.0),
        )
    )

    mcl_mod = MagicMock()
    mcl_mod.get_mini_control = MagicMock(return_value=ctrl_mock)
    mcl_mod.SkillRequest = MagicMock(return_value=MagicMock())
    mcl_mod.AutonomousTaskRequest = MagicMock(return_value=MagicMock())

    manager = MagicMock()
    manager.create_skill = AsyncMock(return_value={"installation": {"success": True}})
    skill_manager_mod = MagicMock()
    skill_manager_mod.SkillManager = MagicMock(return_value=manager)

    skill_knowledge_mod = MagicMock()
    skill_knowledge_mod.get_categories = MagicMock(return_value=[])
    skill_knowledge_mod.search = MagicMock(return_value=[])
    skill_knowledge_mod.handle_query_skill_knowledge = MagicMock(return_value={})

    mocks = {
        "mini_control_layer": mcl_mod,
        "skill_manager": skill_manager_mod,
        "skill_memory": MagicMock(),
        "skill_knowledge": skill_knowledge_mod,
        "uvicorn": MagicMock(),
    }

    with patch.dict(sys.modules, mocks):
        spec = importlib.util.spec_from_file_location(
            "skill_server_config_fallback_test",
            os.path.join(_SKILL_SERVER, "server.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def test_server_source_has_no_hard_config_import_for_package_mode():
    with open(os.path.join(_SKILL_SERVER, "server.py"), "r", encoding="utf-8") as f:
        src = f.read()
    assert "def _get_skill_package_install_mode" in src
    assert "from config import get_skill_package_install_mode" not in src


def test_package_mode_defaults_to_allowlist_auto_without_config_module():
    mod = _load_server_module()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SKILL_PACKAGE_INSTALL_MODE", None)
        assert mod._get_skill_package_install_mode() == "allowlist_auto"


def test_package_mode_respects_valid_env_and_normalizes_invalid():
    mod = _load_server_module()
    with patch.dict(os.environ, {"SKILL_PACKAGE_INSTALL_MODE": "manual_only"}, clear=False):
        assert mod._get_skill_package_install_mode() == "manual_only"
    with patch.dict(os.environ, {"SKILL_PACKAGE_INSTALL_MODE": "weird_mode"}, clear=False):
        assert mod._get_skill_package_install_mode() == "allowlist_auto"


def test_trace_id_normalization_strips_unsafe_chars():
    mod = _load_server_module()
    trace = mod._normalize_trace_id(" intent:abc/123 ?! ")
    assert trace
    assert "/" not in trace
    assert " " not in trace


def test_sanitize_thinking_plan_keeps_compact_schema():
    mod = _load_server_module()
    out = mod._sanitize_thinking_plan(
        {
            "intent": "make skill",
            "reasoning": "x",
            "sequential_complexity": "8",
            "needs_memory": 1,
            "suggested_tools": [{"name": "autonomous_skill_task"}, {"tool": "run_skill"}, {"foo": "bar"}],
            "_sequential_result": {"debug": "drop"},
        }
    )
    assert isinstance(out, dict)
    assert out["intent"] == "make skill"
    assert out["sequential_complexity"] == 8
    assert out["needs_memory"] is True
    assert out["suggested_tools"] == ["autonomous_skill_task", "run_skill"]
    assert "_sequential_result" not in out
