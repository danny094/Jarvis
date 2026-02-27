"""
tests/unit/test_skill_truth_store.py — C3 Skill Truth-Store
============================================================

Covers:
  Part 1 — skill_registry_store.py (pure unit, no I/O mocking needed)
    1. test_atomic_write_replaces_file_without_corruption
    2. test_load_legacy_registry_migrates_to_v2_on_write
    3. test_hash_is_stable_for_same_content
    4. test_hash_changes_on_skills_drift
    5. test_remove_skill_updates_hash
    6. test_normalize_v2_envelope
    7. test_normalize_legacy_flat_dict
    8. test_normalize_corrupt_returns_empty
    9. test_atomic_write_tmp_cleaned_on_failure
   10. test_load_missing_file_returns_empty
   11. test_load_corrupt_file_returns_empty

  Part 2 — Reader compat
   12. test_reader_compat_skill_manager_accepts_v2
   13. test_reader_compat_mini_control_accepts_v2 (skill-server)
   14. test_reader_compat_executor_mini_control_accepts_v2

  Part 3 — Installer uses store (integration-lite)
   15. test_installer_writes_v2_envelope
   16. test_installer_remove_writes_v2_envelope

  Part 4 — Config flag
   17. test_skill_graph_reconcile_default_true
   18. test_skill_graph_reconcile_false_via_env

Gate: python -m pytest tests/unit/test_skill_truth_store.py -q
Expected: ≥ 18 passed, 0 failures
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
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


# ── Load skill_registry_store directly (no complex deps) ────────────────────

_store_skip = ""
_store = None
try:
    spec = importlib.util.spec_from_file_location(
        "skill_registry_store",
        os.path.join(_TOOL_EXECUTOR, "engine", "skill_registry_store.py"),
    )
    _store = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_store)
    _HAS_STORE = True
except Exception as e:
    _HAS_STORE = False
    _store_skip = f"skill_registry_store load failed: {e}"


# ── Load skill_manager.py ────────────────────────────────────────────────────

_sm_skip = ""
_sm_mod = None
try:
    for mod_name, mock_obj in [
        ("httpx", MagicMock()),
    ]:
        sys.modules.setdefault(mod_name, mock_obj)

    spec = importlib.util.spec_from_file_location(
        "skill_manager_c3_test",
        os.path.join(_SKILL_SERVER, "skill_manager.py"),
    )
    _sm_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_sm_mod)
    _HAS_SM = True
except Exception as e:
    _HAS_SM = False
    _sm_skip = f"skill_manager load failed: {e}"


# ── Load skill-server mini_control_layer.py ──────────────────────────────────

_mcl_skip = ""
_mcl_mod = None
try:
    for mod_name, mock_obj in [
        ("cim_rag", MagicMock(cim_kb=MagicMock())),
        ("skill_cim_light", MagicMock(
            SkillCIMLight=MagicMock,
            ValidationResult=MagicMock,
            get_skill_cim=MagicMock(return_value=MagicMock()),
        )),
    ]:
        sys.modules.setdefault(mod_name, mock_obj)

    spec = importlib.util.spec_from_file_location(
        "mcl_skillserver_c3_test",
        os.path.join(_SKILL_SERVER, "mini_control_layer.py"),
    )
    _mcl_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_mcl_mod)
    _HAS_MCL = True
except Exception as e:
    _HAS_MCL = False
    _mcl_skip = f"skill-server mini_control_layer load failed: {e}"


# ── Load tool_executor mini_control_layer.py ────────────────────────────────

_mcl_exec_skip = ""
_mcl_exec_mod = None
try:
    spec = importlib.util.spec_from_file_location(
        "mcl_executor_c3_test",
        os.path.join(_TOOL_EXECUTOR, "mini_control_layer.py"),
    )
    _mcl_exec_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_mcl_exec_mod)
    _HAS_MCL_EXEC = True
except Exception as e:
    _HAS_MCL_EXEC = False
    _mcl_exec_skip = f"executor mini_control_layer load failed: {e}"


# ── Load skill_installer.py ──────────────────────────────────────────────────

_installer_skip = ""
_installer_mod = None
try:
    _obs_events = MagicMock()
    _obs_events.EventLogger = MagicMock()
    _obs_events.EventLogger.emit = MagicMock()
    sys.modules.setdefault("observability.events", _obs_events)
    sys.modules.setdefault("observability", MagicMock(events=_obs_events))

    spec = importlib.util.spec_from_file_location(
        "skill_installer_c3_test",
        os.path.join(_TOOL_EXECUTOR, "engine", "skill_installer.py"),
    )
    _installer_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_installer_mod)
    _HAS_INSTALLER = True
except Exception as e:
    _HAS_INSTALLER = False
    _installer_skip = f"skill_installer load failed: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _sample_skills():
    return {
        "hello_world": {
            "version": "1.0.0",
            "description": "A hello world skill",
            "triggers": ["hello"],
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# Part 1 — skill_registry_store unit tests
# ─────────────────────────────────────────────────────────────────────────────

@unittest.skipUnless(_HAS_STORE, _store_skip)
class TestSkillRegistryStore(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.registry_path = Path(self._tmp) / "_registry" / "installed.json"
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)

    # ── 1: atomic write ───────────────────────────────────────────────────────

    def test_atomic_write_replaces_file_without_corruption(self):
        """save_registry_atomic writes V2 envelope; file is readable JSON after write."""
        skills = _sample_skills()
        _store.save_registry_atomic(self.registry_path, skills)

        self.assertTrue(self.registry_path.exists(), "Registry file must exist after write")
        with open(self.registry_path, "r") as f:
            data = json.load(f)

        self.assertEqual(data.get("schema_version"), 2)
        self.assertIn("skill_registry_hash", data)
        self.assertIn("skills", data)
        self.assertIn("hello_world", data["skills"])

    def test_atomic_write_leaves_no_tmp_files(self):
        """After successful write, no .installed_tmp_* files remain."""
        _store.save_registry_atomic(self.registry_path, _sample_skills())
        tmp_files = list(self.registry_path.parent.glob(".installed_tmp_*"))
        self.assertEqual(tmp_files, [], f"Stale tmp files found: {tmp_files}")

    # ── 2: legacy migration ───────────────────────────────────────────────────

    def test_load_legacy_registry_migrates_to_v2_on_write(self):
        """Legacy flat dict read → save_registry_atomic → output is V2."""
        legacy = {
            "my_skill": {"version": "1.0", "description": "A skill", "triggers": []}
        }
        with open(self.registry_path, "w") as f:
            json.dump(legacy, f)

        # Load legacy → should get flat dict back
        skills = _store.load_registry(self.registry_path)
        self.assertIn("my_skill", skills, "Legacy skill must be readable")

        # Write it back → should produce V2
        _store.save_registry_atomic(self.registry_path, skills)
        with open(self.registry_path, "r") as f:
            data = json.load(f)
        self.assertEqual(data.get("schema_version"), 2, "Output must be V2 after write")

    # ── 3: hash stability ─────────────────────────────────────────────────────

    def test_hash_is_stable_for_same_content(self):
        """Same skills_map always produces the same hash."""
        skills = _sample_skills()
        h1 = _store.compute_registry_hash(skills)
        h2 = _store.compute_registry_hash(skills)
        self.assertEqual(h1, h2, "Hash must be deterministic")

    def test_hash_is_64_hex_chars(self):
        """Hash must be a valid sha256 hex digest (64 chars)."""
        h = _store.compute_registry_hash(_sample_skills())
        self.assertEqual(len(h), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in h))

    # ── 4: hash drift sensitivity ─────────────────────────────────────────────

    def test_hash_changes_on_skills_drift(self):
        """Adding or removing a skill must change the hash."""
        skills_a = _sample_skills()
        skills_b = dict(skills_a)
        skills_b["new_skill"] = {"version": "1.0", "description": "New", "triggers": []}

        h_a = _store.compute_registry_hash(skills_a)
        h_b = _store.compute_registry_hash(skills_b)
        self.assertNotEqual(h_a, h_b, "Hash must change when skills change")

    def test_hash_changes_on_field_value_change(self):
        """Changing a field value inside a skill must change the hash."""
        base = {"s": {"version": "1.0", "description": "old"}}
        changed = {"s": {"version": "1.0", "description": "new"}}
        self.assertNotEqual(
            _store.compute_registry_hash(base),
            _store.compute_registry_hash(changed),
        )

    # ── 5: remove updates hash ────────────────────────────────────────────────

    def test_remove_skill_updates_hash(self):
        """After removing a skill and re-saving, hash changes."""
        skills = {
            "skill_a": {"version": "1.0", "description": "A", "triggers": []},
            "skill_b": {"version": "1.0", "description": "B", "triggers": []},
        }
        _store.save_registry_atomic(self.registry_path, skills)
        with open(self.registry_path) as f:
            h_before = json.load(f)["skill_registry_hash"]

        del skills["skill_a"]
        _store.save_registry_atomic(self.registry_path, skills)
        with open(self.registry_path) as f:
            h_after = json.load(f)["skill_registry_hash"]

        self.assertNotEqual(h_before, h_after, "Hash must change after skill removal")

    # ── 6: normalize V2 ──────────────────────────────────────────────────────

    def test_normalize_v2_envelope(self):
        """normalize_legacy_or_v2 with V2 input returns (skills, migrated=False)."""
        v2 = {
            "schema_version": 2,
            "skill_registry_hash": "abc",
            "skills": {"x": {"version": "1.0"}},
        }
        skills, migrated = _store.normalize_legacy_or_v2(v2)
        self.assertEqual(skills, {"x": {"version": "1.0"}})
        self.assertFalse(migrated)

    # ── 7: normalize legacy ───────────────────────────────────────────────────

    def test_normalize_legacy_flat_dict(self):
        """normalize_legacy_or_v2 with legacy flat dict returns (skills, migrated=True)."""
        legacy = {"skill_a": {"version": "1.0"}, "skill_b": {"version": "2.0"}}
        skills, migrated = _store.normalize_legacy_or_v2(legacy)
        self.assertEqual(set(skills.keys()), {"skill_a", "skill_b"})
        self.assertTrue(migrated)

    # ── 8: normalize corrupt ─────────────────────────────────────────────────

    def test_normalize_corrupt_returns_empty(self):
        """normalize_legacy_or_v2 with non-dict value in top level returns ({}, False)."""
        # Top-level value is not a dict → corrupt
        corrupt = {"skill_a": "not_a_dict"}
        skills, migrated = _store.normalize_legacy_or_v2(corrupt)
        self.assertEqual(skills, {})

    def test_normalize_non_dict_input_returns_empty(self):
        """normalize_legacy_or_v2 with non-dict input returns ({}, False)."""
        skills, migrated = _store.normalize_legacy_or_v2(["list", "not", "dict"])
        self.assertEqual(skills, {})
        self.assertFalse(migrated)

    # ── 9: tmp cleanup on failure ─────────────────────────────────────────────

    def test_atomic_write_tmp_cleaned_on_failure(self):
        """On write failure, tmp file is removed and exception propagates."""
        read_only_dir = Path(self._tmp) / "ro_dir" / "_registry"
        read_only_dir.mkdir(parents=True)
        ro_path = read_only_dir / "installed.json"
        # Make directory read-only so write fails
        os.chmod(str(read_only_dir), 0o444)
        try:
            with self.assertRaises(Exception):
                _store.save_registry_atomic(ro_path, _sample_skills())
            # No tmp files should linger
            tmp_files = list(read_only_dir.glob(".installed_tmp_*"))
            self.assertEqual(tmp_files, [], f"Stale tmp files found: {tmp_files}")
        finally:
            os.chmod(str(read_only_dir), 0o755)

    # ── 10: load missing file ─────────────────────────────────────────────────

    def test_load_missing_file_returns_empty(self):
        """load_registry returns {} for non-existent path."""
        result = _store.load_registry("/nonexistent/path/installed.json")
        self.assertEqual(result, {})

    # ── 11: load corrupt file ─────────────────────────────────────────────────

    def test_load_corrupt_file_returns_empty(self):
        """load_registry returns {} for corrupt JSON."""
        corrupt_path = Path(self._tmp) / "_registry" / "corrupt.json"
        corrupt_path.parent.mkdir(parents=True, exist_ok=True)
        corrupt_path.write_text("{ this is not json }", encoding="utf-8")
        result = _store.load_registry(corrupt_path)
        self.assertEqual(result, {})


# ─────────────────────────────────────────────────────────────────────────────
# Part 2 — Reader compat
# ─────────────────────────────────────────────────────────────────────────────

@unittest.skipUnless(_HAS_SM, _sm_skip)
class TestReaderCompatSkillManager(unittest.TestCase):
    """SkillManager._load_installed() must handle V2 envelope."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._skills_dir = Path(self._tmp) / "skills"
        (self._skills_dir / "_registry").mkdir(parents=True)
        self._registry_path = self._skills_dir / "_registry" / "installed.json"

    def _make_manager(self):
        mgr = object.__new__(_sm_mod.SkillManager)
        mgr.skills_dir = self._skills_dir
        mgr.registry_url = "http://localhost"
        mgr.installed_file = self._registry_path
        return mgr

    # ── 12: V2 envelope ───────────────────────────────────────────────────────

    def test_reader_compat_skill_manager_accepts_v2(self):
        """_load_installed() must return flat skills map from V2 envelope."""
        v2_data = {
            "schema_version": 2,
            "skill_registry_hash": "abc123",
            "skills": {
                "test_skill": {"version": "1.0", "description": "A test", "triggers": []}
            },
        }
        self._registry_path.write_text(json.dumps(v2_data), encoding="utf-8")

        mgr = self._make_manager()
        result = mgr._load_installed()

        self.assertIn("test_skill", result, "V2 envelope must yield flat skills map")
        self.assertNotIn("schema_version", result, "schema_version must not leak into result")
        self.assertNotIn("skills", result, "Outer 'skills' key must not appear in result")

    def test_reader_compat_skill_manager_accepts_legacy(self):
        """_load_installed() must still work with legacy flat dict."""
        legacy = {"my_skill": {"version": "1.0", "description": "Legacy", "triggers": []}}
        self._registry_path.write_text(json.dumps(legacy), encoding="utf-8")

        mgr = self._make_manager()
        result = mgr._load_installed()
        self.assertIn("my_skill", result)


@unittest.skipUnless(_HAS_MCL, _mcl_skip)
class TestReaderCompatMiniControlSkillServer(unittest.TestCase):
    """skill-server SkillMiniControl._load_installed_skills() must handle V2."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._skills_dir = Path(self._tmp) / "skills"
        (self._skills_dir / "_registry").mkdir(parents=True)
        self._registry_path = self._skills_dir / "_registry" / "installed.json"

    def _make_instance(self):
        cls = _mcl_mod.SkillMiniControl
        instance = object.__new__(cls)
        instance.cim = MagicMock()
        instance.skills_dir = self._skills_dir
        instance.block_score_threshold = 0.3
        instance.warn_score_threshold = 0.7
        instance.auto_create_threshold = 5
        return instance

    # ── 13: V2 envelope ───────────────────────────────────────────────────────

    def test_reader_compat_mini_control_accepts_v2(self):
        """_load_installed_skills() must return flat map from V2 envelope."""
        v2_data = {
            "schema_version": 2,
            "skill_registry_hash": "deadbeef",
            "skills": {
                "calc_skill": {"version": "1.0", "triggers": ["calc"]}
            },
        }
        self._registry_path.write_text(json.dumps(v2_data), encoding="utf-8")

        instance = self._make_instance()
        result = instance._load_installed_skills()

        self.assertIn("calc_skill", result)
        self.assertNotIn("schema_version", result)

    def test_reader_compat_mini_control_accepts_legacy(self):
        """_load_installed_skills() still works with legacy flat dict."""
        legacy = {"old_skill": {"version": "0.9", "triggers": []}}
        self._registry_path.write_text(json.dumps(legacy), encoding="utf-8")

        instance = self._make_instance()
        result = instance._load_installed_skills()
        self.assertIn("old_skill", result)


@unittest.skipUnless(_HAS_MCL_EXEC, _mcl_exec_skip)
class TestReaderCompatMiniControlExecutor(unittest.TestCase):
    """tool_executor mini_control_layer._load_installed_skills() must handle V2."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._skills_dir = Path(self._tmp) / "skills"
        (self._skills_dir / "_registry").mkdir(parents=True)
        self._registry_path = self._skills_dir / "_registry" / "installed.json"

    def _make_instance(self):
        # Find the class in tool_executor mini_control_layer
        cls = None
        for attr in dir(_mcl_exec_mod):
            candidate = getattr(_mcl_exec_mod, attr)
            if (
                isinstance(candidate, type)
                and hasattr(candidate, "_load_installed_skills")
            ):
                cls = candidate
                break
        if cls is None:
            self.skipTest("No class with _load_installed_skills found in executor module")
        instance = object.__new__(cls)
        instance.skills_dir = self._skills_dir
        return instance

    # ── 14: V2 envelope ───────────────────────────────────────────────────────

    def test_reader_compat_executor_mini_control_accepts_v2(self):
        """Executor _load_installed_skills() must return flat map from V2 envelope."""
        v2_data = {
            "schema_version": 2,
            "skill_registry_hash": "cafebabe",
            "skills": {
                "exec_skill": {"version": "1.0", "triggers": ["run"]}
            },
        }
        self._registry_path.write_text(json.dumps(v2_data), encoding="utf-8")

        instance = self._make_instance()
        result = instance._load_installed_skills()

        self.assertIn("exec_skill", result)
        self.assertNotIn("schema_version", result)


# ─────────────────────────────────────────────────────────────────────────────
# Part 3 — Installer uses store (integration-lite, filesystem)
# ─────────────────────────────────────────────────────────────────────────────

@unittest.skipUnless(_HAS_INSTALLER and _HAS_STORE, _installer_skip or _store_skip)
class TestInstallerUsesStore(unittest.TestCase):
    """SkillInstaller writes V2 envelope via skill_registry_store."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    # ── 15: save_skill writes V2 ──────────────────────────────────────────────

    def test_installer_writes_v2_envelope(self):
        """save_skill → installed.json must be V2 envelope."""
        installer = _installer_mod.SkillInstaller(skills_dir=self._tmp)
        installer.save_skill(
            name="my_skill",
            code="def run(**k): return {}",
            manifest_data={"description": "A test skill", "triggers": ["test"]},
            is_draft=False,
        )
        registry_path = Path(self._tmp) / "_registry" / "installed.json"
        self.assertTrue(registry_path.exists())

        with open(registry_path) as f:
            data = json.load(f)

        self.assertEqual(data.get("schema_version"), 2, "Installer must write V2 envelope")
        self.assertIn("skill_registry_hash", data)
        self.assertIn("my_skill", data.get("skills", {}))

    # ── 16: uninstall updates hash ────────────────────────────────────────────

    def test_installer_remove_writes_v2_envelope(self):
        """uninstall_skill → installed.json still V2, skill removed, hash updated."""
        installer = _installer_mod.SkillInstaller(skills_dir=self._tmp)
        installer.save_skill(
            name="removable_skill",
            code="def run(**k): return {}",
            manifest_data={"description": "Will be removed", "triggers": []},
            is_draft=False,
        )
        registry_path = Path(self._tmp) / "_registry" / "installed.json"
        with open(registry_path) as f:
            h_before = json.load(f)["skill_registry_hash"]

        installer.uninstall_skill("removable_skill")

        with open(registry_path) as f:
            data_after = json.load(f)

        self.assertEqual(data_after.get("schema_version"), 2)
        self.assertNotIn("removable_skill", data_after.get("skills", {}))
        h_after = data_after["skill_registry_hash"]
        self.assertNotEqual(h_before, h_after, "Hash must change after removal")


# ─────────────────────────────────────────────────────────────────────────────
# Part 4 — Config flag
# ─────────────────────────────────────────────────────────────────────────────

class TestSkillGraphReconcileFlag(unittest.TestCase):
    """get_skill_graph_reconcile() returns True by default, False when overridden."""

    def _get_fn(self):
        spec = importlib.util.spec_from_file_location(
            "config_c3_test",
            os.path.join(_REPO_ROOT, "config.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.get_skill_graph_reconcile

    def test_skill_graph_reconcile_default_true(self):
        """Default value must be True."""
        fn = self._get_fn()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SKILL_GRAPH_RECONCILE", None)
            result = fn()
        self.assertTrue(result, "SKILL_GRAPH_RECONCILE must default to True")

    def test_skill_graph_reconcile_false_via_env(self):
        """SKILL_GRAPH_RECONCILE=false → returns False."""
        fn = self._get_fn()
        with patch.dict(os.environ, {"SKILL_GRAPH_RECONCILE": "false"}):
            result = fn()
        self.assertFalse(result, "SKILL_GRAPH_RECONCILE=false must return False")


if __name__ == "__main__":
    unittest.main()
