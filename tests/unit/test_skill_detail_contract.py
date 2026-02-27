"""
tests/unit/test_skill_detail_contract.py — C1 Skill-Detail-Contract Tests
=========================================================================

Covers:
  1. list → detail for active skill: 200, channel=active
  2. Draft-only skill without channel: 200, channel=draft
  3. active + draft exist, no channel  → active returned
  4. active + draft exist, ?channel=draft → draft returned
  5. Unknown skill → 404
  6. ENABLE_SKILL_DETAIL_API=false → detail endpoint 404
  7. Existing GET /v1/skills (list) not broken
  + Unit tests for SkillManager.get_skill_detail()

Gate: python -m pytest tests/unit/test_skill_detail_contract.py -q
Expected: ≥ 15 passed, 0 failures
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Repo paths ─────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
# Fallback: when file is run from /tmp the relative walk is wrong — detect by marker
if not os.path.isdir(os.path.join(_REPO_ROOT, "mcp-servers")):
    _REPO_ROOT = "/DATA/AppData/MCP/Jarvis/Jarvis"
_SKILL_SERVER = os.path.join(_REPO_ROOT, "mcp-servers", "skill-server")

if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
if _SKILL_SERVER not in sys.path:
    sys.path.insert(0, _SKILL_SERVER)


# ── Load SkillManager class independently of server ───────────────────────────

def _load_skill_manager_class():
    spec = importlib.util.spec_from_file_location(
        "skill_manager_test_mod",
        os.path.join(_SKILL_SERVER, "skill_manager.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.SkillManager


SkillManager = _load_skill_manager_class()


# ── Filesystem helpers ─────────────────────────────────────────────────────────

def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _write_manifest(path: Path, data: dict) -> None:
    import yaml
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f)


def _make_active_skill(skills_dir: Path, name: str, **kwargs) -> None:
    """Create an active skill: registry entry + skill directory with manifest."""
    registry: dict = {}
    registry_path = skills_dir / "_registry" / "installed.json"
    if registry_path.exists():
        with open(registry_path) as f:
            registry = json.load(f)
    registry[name] = {
        "version": kwargs.get("version", "1.0.0"),
        "installed_at": "2026-02-21T10:00:00",
        "description": kwargs.get("description", f"Test skill {name}"),
        "triggers": kwargs.get("triggers", [f"test_{name}"]),
        "gap_patterns": kwargs.get("gap_patterns", []),
        "gap_question": kwargs.get("gap_question"),
        "preferred_model": kwargs.get("preferred_model"),
        "default_params": kwargs.get("default_params", {}),
    }
    _write_json(registry_path, registry)
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    _write_manifest(skill_dir / "manifest.yaml", {"name": name, **kwargs})


def _make_draft_skill(skills_dir: Path, name: str, **kwargs) -> None:
    """Create a draft skill: _drafts/name/manifest.yaml."""
    draft_dir = skills_dir / "_drafts" / name
    _write_manifest(
        draft_dir / "manifest.yaml",
        {
            "name": name,
            "version": kwargs.get("version", "draft"),
            "description": kwargs.get("description", f"Draft skill {name}"),
            "triggers": kwargs.get("triggers", [f"draft_{name}"]),
            "gap_patterns": kwargs.get("gap_patterns", []),
            "gap_question": kwargs.get("gap_question"),
            "preferred_model": kwargs.get("preferred_model"),
            "default_params": kwargs.get("default_params", {}),
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Part 1 — SkillManager.get_skill_detail() unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSkillDetailManager(unittest.TestCase):
    """Direct unit tests for SkillManager.get_skill_detail()."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._skills_dir = Path(self._tmp.name)
        (self._skills_dir / "_registry").mkdir(parents=True, exist_ok=True)
        (self._skills_dir / "_drafts").mkdir(parents=True, exist_ok=True)
        self.manager = SkillManager(
            skills_dir=str(self._skills_dir),
            registry_url="http://localhost",
        )

    def tearDown(self):
        self._tmp.cleanup()

    # ── active channel ─────────────────────────────────────────────────────

    def test_active_skill_returns_active_channel(self):
        _make_active_skill(self._skills_dir, "my_skill", description="Active skill")
        result = self.manager.get_skill_detail("my_skill")
        self.assertEqual(result["channel"], "active")
        self.assertEqual(result["name"], "my_skill")
        self.assertEqual(result["description"], "Active skill")

    def test_active_skill_has_status_installed(self):
        _make_active_skill(self._skills_dir, "my_skill")
        result = self.manager.get_skill_detail("my_skill")
        self.assertEqual(result["status"], "installed")

    # ── draft channel ──────────────────────────────────────────────────────

    def test_draft_only_no_channel_returns_draft(self):
        _make_draft_skill(self._skills_dir, "draft_skill", description="Draft only")
        result = self.manager.get_skill_detail("draft_skill")
        self.assertEqual(result["channel"], "draft")
        self.assertEqual(result["status"], "draft")
        self.assertEqual(result["description"], "Draft only")

    # ── channel preference ────────────────────────────────────────────────

    def test_active_preferred_over_draft_no_channel(self):
        _make_active_skill(self._skills_dir, "overlap", description="Active version")
        _make_draft_skill(self._skills_dir, "overlap", description="Draft version")
        result = self.manager.get_skill_detail("overlap")
        self.assertEqual(result["channel"], "active")
        self.assertEqual(result["description"], "Active version")

    def test_channel_draft_returns_draft(self):
        _make_active_skill(self._skills_dir, "overlap", description="Active version")
        _make_draft_skill(self._skills_dir, "overlap", description="Draft version")
        result = self.manager.get_skill_detail("overlap", channel="draft")
        self.assertEqual(result["channel"], "draft")
        self.assertEqual(result["description"], "Draft version")

    def test_channel_active_returns_active(self):
        _make_active_skill(self._skills_dir, "overlap", description="Active version")
        _make_draft_skill(self._skills_dir, "overlap", description="Draft version")
        result = self.manager.get_skill_detail("overlap", channel="active")
        self.assertEqual(result["channel"], "active")

    # ── not found ─────────────────────────────────────────────────────────

    def test_unknown_skill_returns_error(self):
        result = self.manager.get_skill_detail("nonexistent_xyz")
        self.assertIn("error", result)
        self.assertNotIn("channel", result)

    def test_channel_active_on_draft_only_returns_error(self):
        _make_draft_skill(self._skills_dir, "draft_only")
        result = self.manager.get_skill_detail("draft_only", channel="active")
        self.assertIn("error", result)

    def test_channel_draft_on_active_only_returns_error(self):
        _make_active_skill(self._skills_dir, "active_only")
        result = self.manager.get_skill_detail("active_only", channel="draft")
        self.assertIn("error", result)

    # ── field completeness ────────────────────────────────────────────────

    def test_result_has_all_required_fields(self):
        _make_active_skill(
            self._skills_dir, "full_skill",
            description="Full",
            triggers=["trigger1"],
            gap_patterns=["pattern1"],
            gap_question="Question?",
            preferred_model="qwen2.5-coder:3b",
            default_params={"key": "val"},
        )
        result = self.manager.get_skill_detail("full_skill")
        required = (
            "name", "channel", "version", "description", "triggers",
            "gap_patterns", "gap_question", "preferred_model",
            "default_params", "status",
        )
        for field in required:
            self.assertIn(field, result, f"Missing required field: {field}")

    def test_triggers_from_registry(self):
        _make_active_skill(
            self._skills_dir, "trig_skill", triggers=["ping", "check"]
        )
        result = self.manager.get_skill_detail("trig_skill")
        self.assertIn("ping", result["triggers"])
        self.assertIn("check", result["triggers"])


# ─────────────────────────────────────────────────────────────────────────────
# Load server module once (with mocked deps)
# ─────────────────────────────────────────────────────────────────────────────

def _load_server_module():
    """Load server.py with problematic module-level deps mocked."""

    async def _noop(*a, **kw):
        return {}

    _skill_memory_mock = MagicMock()
    _skill_memory_mock.record_execution = _noop

    for mod_name, mock_obj in [
        (
            "skill_knowledge",
            MagicMock(
                get_categories=lambda: [],
                search=lambda **kw: [],
                handle_query_skill_knowledge=lambda args: {},
            ),
        ),
        ("skill_memory", _skill_memory_mock),
        ("mini_control_layer", MagicMock()),
    ]:
        sys.modules.setdefault(mod_name, mock_obj)

    spec = importlib.util.spec_from_file_location(
        "skill_server_for_test",
        os.path.join(_SKILL_SERVER, "server.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_SKIP_REASON = ""
_server_mod = None
try:
    _server_mod = _load_server_module()
    _HAS_SERVER = True
except Exception as _e:
    _HAS_SERVER = False
    _SKIP_REASON = f"Server load failed: {_e}"


# ─────────────────────────────────────────────────────────────────────────────
# Part 2 — endpoint contract tests (without TestClient)
# ─────────────────────────────────────────────────────────────────────────────

@unittest.skipUnless(_HAS_SERVER, _SKIP_REASON)
class TestSkillDetailEndpoint(unittest.TestCase):
    """Endpoint contract tests for GET /v1/skills/{name}."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._skills_dir = Path(self._tmp.name)
        (self._skills_dir / "_registry").mkdir(parents=True, exist_ok=True)
        (self._skills_dir / "_drafts").mkdir(parents=True, exist_ok=True)

        # Swap the global skill_manager to an isolated instance
        self._orig_manager = _server_mod.skill_manager
        _server_mod.skill_manager = SkillManager(
            skills_dir=str(self._skills_dir),
            registry_url="http://localhost",
        )

    def tearDown(self):
        _server_mod.skill_manager = self._orig_manager
        self._tmp.cleanup()

    @staticmethod
    def _run(coro):
        import asyncio

        return asyncio.run(coro)

    def _get_detail(self, name: str, channel: str | None = None):
        if channel is None:
            return self._run(_server_mod.get_skill_detail(name))
        return self._run(_server_mod.get_skill_detail(name, channel=channel))

    def _get_list(self):
        return self._run(_server_mod.get_skills_direct())

    # ── Test 1: active skill → 200, channel=active ─────────────────────────

    def test_active_skill_detail_200(self):
        _make_active_skill(self._skills_dir, "test_active", description="Active skill")
        data = self._get_detail("test_active")
        self.assertEqual(data["channel"], "active")
        self.assertEqual(data["name"], "test_active")

    # ── Test 2: draft-only → 200, channel=draft ────────────────────────────

    def test_draft_only_skill_200_channel_draft(self):
        _make_draft_skill(self._skills_dir, "draft_only", description="Draft only")
        data = self._get_detail("draft_only")
        self.assertEqual(data["channel"], "draft")

    # ── Test 3: active + draft, no channel → active ────────────────────────

    def test_active_preferred_when_both_exist(self):
        _make_active_skill(self._skills_dir, "overlap", description="Active")
        _make_draft_skill(self._skills_dir, "overlap", description="Draft")
        data = self._get_detail("overlap")
        self.assertEqual(data["channel"], "active")

    # ── Test 4: active + draft, ?channel=draft → draft ────────────────────

    def test_channel_draft_query_param(self):
        _make_active_skill(self._skills_dir, "overlap", description="Active")
        _make_draft_skill(self._skills_dir, "overlap", description="Draft")
        data = self._get_detail("overlap", channel="draft")
        self.assertEqual(data["channel"], "draft")

    # ── Test 5: unknown skill → 404 ───────────────────────────────────────

    def test_unknown_skill_404(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as exc:
            self._get_detail("nonexistent_skill_xyz")
        self.assertEqual(exc.exception.status_code, 404)

    # ── Test 6: ENABLE_SKILL_DETAIL_API=false → 404 ───────────────────────

    def test_disabled_api_returns_404(self):
        from fastapi import HTTPException

        _make_active_skill(self._skills_dir, "some_skill")
        with patch.dict(os.environ, {"ENABLE_SKILL_DETAIL_API": "false"}):
            with self.assertRaises(HTTPException) as exc:
                self._get_detail("some_skill")
        self.assertEqual(exc.exception.status_code, 404)

    # ── Test 7: existing list endpoint not broken ─────────────────────────

    def test_list_endpoint_still_works(self):
        _make_active_skill(self._skills_dir, "skill_a")
        _make_draft_skill(self._skills_dir, "skill_b")
        data = self._get_list()
        self.assertIn("active", data)
        self.assertIn("drafts", data)
        self.assertIn("skill_a", data["active"])

    # ── additional contract assertions ────────────────────────────────────

    def test_response_includes_triggers(self):
        _make_active_skill(
            self._skills_dir, "triggered", triggers=["ping", "check"]
        )
        data = self._get_detail("triggered")
        self.assertIn("triggers", data)

    def test_channel_active_explicit(self):
        _make_active_skill(self._skills_dir, "explicit_active")
        data = self._get_detail("explicit_active", channel="active")
        self.assertEqual(data["channel"], "active")

    def test_enabled_api_true_returns_200(self):
        _make_active_skill(self._skills_dir, "some_skill")
        with patch.dict(os.environ, {"ENABLE_SKILL_DETAIL_API": "true"}):
            data = self._get_detail("some_skill")
        self.assertEqual(data["name"], "some_skill")


if __name__ == "__main__":
    unittest.main()
