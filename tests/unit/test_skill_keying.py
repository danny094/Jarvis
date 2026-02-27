"""
tests/unit/test_skill_keying.py — C4 Skill-Keying stabil
=========================================================

Covers:
  Part 1 — make_skill_key + dedupe_latest_by_skill_key
    1.  test_skill_key_default_is_normalized_name
    2.  test_skill_key_legacy_mode_no_normalization
    3.  test_skill_key_hyphen_to_underscore
    4.  test_skill_dedupe_by_skill_key
    5.  test_skill_dedupe_keeps_latest_by_updated_at
    6.  test_skill_dedupe_keeps_latest_by_revision
    7.  test_skill_dedupe_tie_break_by_name
    8.  test_skill_dedupe_empty_list
    9.  test_skill_dedupe_drops_records_without_key

  Part 2 — save_registry_atomic normalization
    10. test_save_normalizes_skill_key_field
    11. test_save_normalizes_channel_default_active
    12. test_save_normalizes_revision_default_one
    13. test_save_legacy_mode_no_dedupe_drop
    14. test_normalize_for_write_mode_name_dedupes

  Part 3 — SkillInstaller: revision + updated_at on update
    15. test_skill_update_increments_revision
    16. test_skill_updated_at_changes_on_update
    17. test_skill_installed_at_preserved_on_update
    18. test_skill_key_set_on_install

  Part 4 — get_skill_detail includes C4 fields
    19. test_get_skill_detail_includes_revision_updated_at
    20. test_get_skill_detail_includes_skill_key
    21. test_get_skill_detail_draft_has_revision_1

  Part 5 — Config flag
    22. test_legacy_key_mode_keeps_backward_behavior
    23. test_skill_key_mode_default_is_name

Gate: python -m pytest tests/unit/test_skill_keying.py -q
Expected: ≥ 23 passed, 0 failures
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Repo paths ──────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_TOOL_EXECUTOR = os.path.join(_REPO_ROOT, "tool_executor")
_SKILL_SERVER = os.path.join(_REPO_ROOT, "mcp-servers", "skill-server")

if not os.path.isdir(os.path.join(_REPO_ROOT, "tool_executor")):
    _REPO_ROOT = "/DATA/AppData/MCP/Jarvis/Jarvis"
    _TOOL_EXECUTOR = os.path.join(_REPO_ROOT, "tool_executor")
    _SKILL_SERVER = os.path.join(_REPO_ROOT, "mcp-servers", "skill-server")

for p in [_REPO_ROOT, _TOOL_EXECUTOR, _SKILL_SERVER]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ── Load skill_registry_store ────────────────────────────────────────────────

_store_skip = ""
_store = None
try:
    spec = importlib.util.spec_from_file_location(
        "skill_registry_store_c4",
        os.path.join(_TOOL_EXECUTOR, "engine", "skill_registry_store.py"),
    )
    _store = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_store)
    _HAS_STORE = True
except Exception as e:
    _HAS_STORE = False
    _store_skip = f"skill_registry_store load failed: {e}"


# ── Load skill_installer ─────────────────────────────────────────────────────

_installer_skip = ""
_installer_mod = None
try:
    _obs_events = MagicMock()
    _obs_events.EventLogger = MagicMock()
    _obs_events.EventLogger.emit = MagicMock()
    sys.modules.setdefault("observability.events", _obs_events)
    sys.modules.setdefault("observability", MagicMock(events=_obs_events))

    spec = importlib.util.spec_from_file_location(
        "skill_installer_c4",
        os.path.join(_TOOL_EXECUTOR, "engine", "skill_installer.py"),
    )
    _installer_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_installer_mod)
    _HAS_INSTALLER = True
except Exception as e:
    _HAS_INSTALLER = False
    _installer_skip = f"skill_installer load failed: {e}"


# ── Load skill_manager ───────────────────────────────────────────────────────

_sm_skip = ""
_sm_mod = None
try:
    sys.modules.setdefault("httpx", MagicMock())
    spec = importlib.util.spec_from_file_location(
        "skill_manager_c4",
        os.path.join(_SKILL_SERVER, "skill_manager.py"),
    )
    _sm_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_sm_mod)
    _HAS_SM = True
except Exception as e:
    _HAS_SM = False
    _sm_skip = f"skill_manager load failed: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _iso(offset_seconds: int = 0) -> str:
    return (datetime.now() + timedelta(seconds=offset_seconds)).isoformat()


def _make_record(name: str, skill_key: str = None, revision: int = 1,
                 updated_at: str = None) -> dict:
    return {
        "name": name,
        "skill_key": skill_key or name,
        "channel": "active",
        "revision": revision,
        "updated_at": updated_at or _iso(),
        "version": "1.0.0",
        "description": "Test",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Part 1 — make_skill_key + dedupe_latest_by_skill_key
# ─────────────────────────────────────────────────────────────────────────────

@unittest.skipUnless(_HAS_STORE, _store_skip)
class TestMakeSkillKey(unittest.TestCase):

    # ── 1: default mode=name ─────────────────────────────────────────────────

    def test_skill_key_default_is_normalized_name(self):
        """mode='name': skill_key = lowercase with underscores."""
        key = _store.make_skill_key("My_Skill")
        self.assertEqual(key, "my_skill")

    # ── 2: legacy mode ────────────────────────────────────────────────────────

    def test_skill_key_legacy_mode_no_normalization(self):
        """mode='legacy': skill_key = name as-is."""
        key = _store.make_skill_key("MySkill", mode="legacy")
        self.assertEqual(key, "MySkill")

    # ── 3: hyphen + space normalization ──────────────────────────────────────

    def test_skill_key_hyphen_to_underscore(self):
        """Hyphens and spaces become underscores in mode='name'."""
        key = _store.make_skill_key("hello-world skill", mode="name")
        self.assertEqual(key, "hello_world_skill")


@unittest.skipUnless(_HAS_STORE, _store_skip)
class TestDedupeBySkillKey(unittest.TestCase):

    # ── 4: basic dedupe ───────────────────────────────────────────────────────

    def test_skill_dedupe_by_skill_key(self):
        """Two records with same skill_key → only the newest survives."""
        old = _make_record("skill_a", skill_key="skill_a", revision=1,
                           updated_at="2026-01-01T10:00:00")
        new = _make_record("skill_a", skill_key="skill_a", revision=2,
                           updated_at="2026-01-02T10:00:00")
        result = _store.dedupe_latest_by_skill_key([old, new])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["revision"], 2)

    # ── 5: latest by updated_at ───────────────────────────────────────────────

    def test_skill_dedupe_keeps_latest_by_updated_at(self):
        """Higher updated_at wins regardless of insertion order."""
        r1 = _make_record("x", skill_key="x", revision=1,
                          updated_at="2026-02-01T00:00:00")
        r2 = _make_record("x", skill_key="x", revision=1,
                          updated_at="2026-02-15T00:00:00")
        result = _store.dedupe_latest_by_skill_key([r2, r1])  # r2 first
        self.assertEqual(result[0]["updated_at"], "2026-02-15T00:00:00")

    # ── 6: latest by revision ─────────────────────────────────────────────────

    def test_skill_dedupe_keeps_latest_by_revision(self):
        """Same updated_at → higher revision wins."""
        ts = "2026-02-01T10:00:00"
        r1 = _make_record("s", skill_key="s", revision=3, updated_at=ts)
        r2 = _make_record("s", skill_key="s", revision=5, updated_at=ts)
        result = _store.dedupe_latest_by_skill_key([r1, r2])
        self.assertEqual(result[0]["revision"], 5)

    # ── 7: tie-break by name ──────────────────────────────────────────────────

    def test_skill_dedupe_tie_break_by_name(self):
        """Same skill_key, updated_at, revision → lexicographic ascending name wins."""
        ts = "2026-02-01T00:00:00"
        ra = _make_record("alpha", skill_key="sk", revision=1, updated_at=ts)
        rb = _make_record("beta", skill_key="sk", revision=1, updated_at=ts)
        # 'alpha' < 'beta' → alpha wins (ascending sort)
        result = _store.dedupe_latest_by_skill_key([rb, ra])
        self.assertEqual(result[0]["name"], "alpha")

    # ── 8: empty list ─────────────────────────────────────────────────────────

    def test_skill_dedupe_empty_list(self):
        """Empty input → empty output."""
        self.assertEqual(_store.dedupe_latest_by_skill_key([]), [])

    # ── 9: drop records without skill_key ────────────────────────────────────

    def test_skill_dedupe_drops_records_without_key(self):
        """Records with empty/missing skill_key are silently dropped."""
        bad = {"name": "x", "revision": 1}  # no skill_key
        good = _make_record("y", skill_key="y")
        result = _store.dedupe_latest_by_skill_key([bad, good])
        names = [r["name"] for r in result]
        self.assertIn("y", names)
        self.assertNotIn("x", names)


# ─────────────────────────────────────────────────────────────────────────────
# Part 2 — save_registry_atomic normalization
# ─────────────────────────────────────────────────────────────────────────────

@unittest.skipUnless(_HAS_STORE, _store_skip)
class TestSaveNormalization(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.path = Path(self._tmp) / "_registry" / "installed.json"
        self.path.parent.mkdir(parents=True)

    # ── 10: skill_key is added ────────────────────────────────────────────────

    def test_save_normalizes_skill_key_field(self):
        """save_registry_atomic adds skill_key to records that lack it."""
        skills = {"hello_world": {"version": "1.0", "description": "x"}}
        _store.save_registry_atomic(self.path, skills, mode="name")
        with open(self.path) as f:
            data = json.load(f)
        record = data["skills"]["hello_world"]
        self.assertIn("skill_key", record)
        self.assertEqual(record["skill_key"], "hello_world")

    # ── 11: channel defaults to active ───────────────────────────────────────

    def test_save_normalizes_channel_default_active(self):
        """Records without channel get channel='active'."""
        skills = {"my_skill": {"version": "1.0", "description": "x"}}
        _store.save_registry_atomic(self.path, skills, mode="name")
        with open(self.path) as f:
            data = json.load(f)
        self.assertEqual(data["skills"]["my_skill"]["channel"], "active")

    # ── 12: revision defaults to 1 ───────────────────────────────────────────

    def test_save_normalizes_revision_default_one(self):
        """Records without revision get revision=1."""
        skills = {"my_skill": {"version": "1.0", "description": "x"}}
        _store.save_registry_atomic(self.path, skills, mode="name")
        with open(self.path) as f:
            data = json.load(f)
        self.assertEqual(data["skills"]["my_skill"]["revision"], 1)

    # ── 13: legacy mode — no dedupe drop ─────────────────────────────────────

    def test_save_legacy_mode_no_dedupe_drop(self):
        """mode=legacy: multiple skills with same normalized key are all kept."""
        # In legacy mode, keys aren't deduplicated — both survive
        skills = {
            "Skill_A": {"version": "1.0", "description": "x", "skill_key": "sk"},
            "Skill_B": {"version": "1.0", "description": "y", "skill_key": "sk"},
        }
        _store.save_registry_atomic(self.path, skills, mode="legacy")
        with open(self.path) as f:
            data = json.load(f)
        self.assertEqual(len(data["skills"]), 2, "Legacy mode must not drop records")

    # ── 14: mode=name dedupes ─────────────────────────────────────────────────

    def test_normalize_for_write_mode_name_dedupes(self):
        """_normalize_for_write with mode='name' drops duplicate skill_keys."""
        ts_old = "2026-01-01T10:00:00"
        ts_new = "2026-01-02T10:00:00"
        skills = {
            "skill_a": {"skill_key": "sk", "updated_at": ts_old, "revision": 1,
                        "version": "1.0", "description": "old", "name": "skill_a"},
            "skill_b": {"skill_key": "sk", "updated_at": ts_new, "revision": 2,
                        "version": "1.0", "description": "new", "name": "skill_b"},
        }
        result = _store._normalize_for_write(skills, mode="name")
        # Only one record should remain (the one with ts_new/rev 2)
        self.assertEqual(len(result), 1)
        surviving = list(result.values())[0]
        self.assertEqual(surviving["updated_at"], ts_new)


# ─────────────────────────────────────────────────────────────────────────────
# Part 3 — SkillInstaller: revision + updated_at + skill_key
# ─────────────────────────────────────────────────────────────────────────────

@unittest.skipUnless(_HAS_INSTALLER and _HAS_STORE, _installer_skip or _store_skip)
class TestInstallerC4Fields(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def _install(self, name: str, description: str = "A test skill") -> dict:
        """Install skill and return registry record for that skill."""
        installer = _installer_mod.SkillInstaller(skills_dir=self._tmp)
        installer.save_skill(
            name=name,
            code="def run(**k): return {}",
            manifest_data={"description": description, "triggers": []},
            is_draft=False,
        )
        # Installer sanitizes: lowercase + hyphen→underscore
        safe_name = name.lower().replace(" ", "_").replace("-", "_")
        registry_path = Path(self._tmp) / "_registry" / "installed.json"
        with open(registry_path) as f:
            data = json.load(f)
        return data["skills"][safe_name]

    # ── 15: revision increments ───────────────────────────────────────────────

    def test_skill_update_increments_revision(self):
        """Installing same skill twice → revision goes 1 → 2."""
        installer = _installer_mod.SkillInstaller(skills_dir=self._tmp)
        kwargs = dict(
            name="my_skill",
            code="def run(**k): return {}",
            manifest_data={"description": "Initial install", "triggers": []},
            is_draft=False,
        )
        installer.save_skill(**kwargs)
        registry_path = Path(self._tmp) / "_registry" / "installed.json"
        with open(registry_path) as f:
            r1 = json.load(f)["skills"]["my_skill"]["revision"]

        installer.save_skill(**{**kwargs, "manifest_data": {"description": "Updated skill", "triggers": []}})
        with open(registry_path) as f:
            r2 = json.load(f)["skills"]["my_skill"]["revision"]

        self.assertEqual(r1, 1, "First install must be revision 1")
        self.assertEqual(r2, 2, "Second install must be revision 2")

    # ── 16: updated_at changes ────────────────────────────────────────────────

    def test_skill_updated_at_changes_on_update(self):
        """Second install gets a different (newer or equal) updated_at."""
        installer = _installer_mod.SkillInstaller(skills_dir=self._tmp)
        registry_path = Path(self._tmp) / "_registry" / "installed.json"
        kwargs = dict(
            name="ts_skill",
            code="def run(**k): return {}",
            manifest_data={"description": "First version", "triggers": []},
            is_draft=False,
        )
        installer.save_skill(**kwargs)
        with open(registry_path) as f:
            ua1 = json.load(f)["skills"]["ts_skill"]["updated_at"]

        # Brief sleep to ensure timestamps differ
        time.sleep(0.01)
        installer.save_skill(**{**kwargs, "manifest_data": {"description": "Updated version", "triggers": []}})
        with open(registry_path) as f:
            ua2 = json.load(f)["skills"]["ts_skill"]["updated_at"]

        self.assertIsNotNone(ua1)
        self.assertIsNotNone(ua2)
        self.assertGreaterEqual(ua2, ua1, "updated_at must not go backward")

    # ── 17: installed_at preserved ───────────────────────────────────────────

    def test_skill_installed_at_preserved_on_update(self):
        """installed_at must NOT change on subsequent installs."""
        installer = _installer_mod.SkillInstaller(skills_dir=self._tmp)
        registry_path = Path(self._tmp) / "_registry" / "installed.json"
        kwargs = dict(
            name="stable_skill",
            code="def run(**k): return {}",
            manifest_data={"description": "First version", "triggers": []},
            is_draft=False,
        )
        installer.save_skill(**kwargs)
        with open(registry_path) as f:
            ia1 = json.load(f)["skills"]["stable_skill"]["installed_at"]

        time.sleep(0.01)
        installer.save_skill(**{**kwargs, "manifest_data": {"description": "Updated version", "triggers": []}})
        with open(registry_path) as f:
            ia2 = json.load(f)["skills"]["stable_skill"]["installed_at"]

        self.assertEqual(ia1, ia2, "installed_at must be preserved on update")

    # ── 18: skill_key is set ──────────────────────────────────────────────────

    def test_skill_key_set_on_install(self):
        """After install, registry record contains skill_key."""
        record = self._install("My-Skill")
        self.assertIn("skill_key", record)
        # mode=name by default → normalized
        self.assertEqual(record["skill_key"], "my_skill")


# ─────────────────────────────────────────────────────────────────────────────
# Part 4 — get_skill_detail includes C4 fields
# ─────────────────────────────────────────────────────────────────────────────

@unittest.skipUnless(_HAS_SM and _HAS_INSTALLER, _sm_skip or _installer_skip)
class TestGetSkillDetailC4Fields(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._skills_dir = Path(self._tmp) / "skills"
        (self._skills_dir / "_registry").mkdir(parents=True)
        self._registry_path = self._skills_dir / "_registry" / "installed.json"

    def _write_v2_registry(self, skills: dict):
        from hashlib import sha256
        canonical = json.dumps(
            {"schema_version": 2, "skills": skills},
            sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        h = sha256(canonical.encode()).hexdigest()
        envelope = {"schema_version": 2, "skill_registry_hash": h, "skills": skills}
        self._registry_path.write_text(json.dumps(envelope), encoding="utf-8")

    def _make_skill_dir(self, name: str):
        skill_dir = self._skills_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        return skill_dir

    def _make_manager(self):
        mgr = object.__new__(_sm_mod.SkillManager)
        mgr.skills_dir = self._skills_dir
        mgr.registry_url = "http://localhost"
        mgr.installed_file = self._registry_path
        return mgr

    # ── 19: revision + updated_at present ────────────────────────────────────

    def test_get_skill_detail_includes_revision_updated_at(self):
        """get_skill_detail must return revision and updated_at for active skills."""
        now = datetime.now().isoformat()
        skills = {
            "test_skill": {
                "skill_key": "test_skill",
                "name": "test_skill",
                "channel": "active",
                "version": "1.0.0",
                "revision": 3,
                "updated_at": now,
                "description": "A test skill",
                "triggers": [],
            }
        }
        self._write_v2_registry(skills)
        self._make_skill_dir("test_skill")

        mgr = self._make_manager()
        detail = mgr.get_skill_detail("test_skill")

        self.assertEqual(detail.get("revision"), 3)
        self.assertEqual(detail.get("updated_at"), now)

    # ── 20: skill_key present ─────────────────────────────────────────────────

    def test_get_skill_detail_includes_skill_key(self):
        """get_skill_detail must return skill_key for active skills."""
        skills = {
            "calc": {
                "skill_key": "calc",
                "version": "1.0.0",
                "revision": 1,
                "updated_at": _iso(),
                "description": "Calculator",
                "triggers": [],
            }
        }
        self._write_v2_registry(skills)
        self._make_skill_dir("calc")

        mgr = self._make_manager()
        detail = mgr.get_skill_detail("calc")
        self.assertIn("skill_key", detail)
        self.assertEqual(detail["skill_key"], "calc")

    # ── 21: draft has revision=1 ──────────────────────────────────────────────

    def test_get_skill_detail_draft_has_revision_1(self):
        """Draft skills always have revision=1 in get_skill_detail."""
        draft_dir = self._skills_dir / "_drafts" / "draft_skill"
        draft_dir.mkdir(parents=True)
        import yaml
        manifest = {
            "name": "draft_skill",
            "version": "draft",
            "description": "A draft skill",
            "triggers": [],
            "created_at": datetime.now().isoformat(),
        }
        with open(draft_dir / "manifest.yaml", "w") as f:
            yaml.dump(manifest, f)

        mgr = self._make_manager()
        detail = mgr.get_skill_detail("draft_skill", channel="draft")

        self.assertEqual(detail.get("revision"), 1, "Draft revision must be 1")
        self.assertEqual(detail.get("channel"), "draft")


# ─────────────────────────────────────────────────────────────────────────────
# Part 5 — Config flag
# ─────────────────────────────────────────────────────────────────────────────

class TestSkillKeyModeConfig(unittest.TestCase):

    def _get_fn(self):
        spec = importlib.util.spec_from_file_location(
            "config_c4_test",
            os.path.join(_REPO_ROOT, "config.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.get_skill_key_mode

    # ── 22: legacy mode via env ───────────────────────────────────────────────

    def test_legacy_key_mode_keeps_backward_behavior(self):
        """SKILL_KEY_MODE=legacy → returns 'legacy'."""
        fn = self._get_fn()
        with patch.dict(os.environ, {"SKILL_KEY_MODE": "legacy"}):
            result = fn()
        self.assertEqual(result, "legacy")

    # ── 23: default is name ───────────────────────────────────────────────────

    def test_skill_key_mode_default_is_name(self):
        """Default SKILL_KEY_MODE must be 'name'."""
        fn = self._get_fn()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SKILL_KEY_MODE", None)
            result = fn()
        self.assertEqual(result, "name")


if __name__ == "__main__":
    unittest.main()
