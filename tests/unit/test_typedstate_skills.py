"""
tests/unit/test_typedstate_skills.py — C5 TypedState Skills-Entity

Tests for core/typedstate_skills.py:
  - normalize()             (27 tests)
  - dedupe()                (6 tests)
  - top_k()                 (8 tests)
  - budget()                (6 tests)
  - render_entity()         (10 tests)
  - build_skills_context()  (10 tests — mode wiring)
  - pipeline integration    (3 tests)

Total: 70 tests
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest

_PROJECT_ROOT = "/DATA/AppData/MCP/Jarvis/Jarvis"
_MODULE_PATH = os.path.join(_PROJECT_ROOT, "core", "typedstate_skills.py")
_MODULE_NAME = "_typedstate_skills_standalone"   # avoids core/__init__.py trigger


# ---------------------------------------------------------------------------
# Load the module standalone (bypasses core package __init__ chain)
# ---------------------------------------------------------------------------

def _load():
    # Save originals so we can restore them after loading
    _orig_utils = sys.modules.get("utils")
    _orig_logger = sys.modules.get("utils.logger")

    # Stub utils.logger — the only external dep of typedstate_skills.py
    _utils = types.ModuleType("utils")
    _logger = types.ModuleType("utils.logger")
    _logger.log_info = lambda msg: None   # type: ignore
    _logger.log_warn = lambda msg: None   # type: ignore
    sys.modules["utils"] = _utils
    sys.modules["utils.logger"] = _logger

    try:
        spec = importlib.util.spec_from_file_location(_MODULE_NAME, _MODULE_PATH)
        mod = importlib.util.module_from_spec(spec)
        # Register BEFORE exec so @dataclass can resolve cls.__module__
        sys.modules[_MODULE_NAME] = mod
        spec.loader.exec_module(mod)
    finally:
        # Restore sys.modules to pre-stub state so other test modules are unaffected
        if _orig_utils is None:
            sys.modules.pop("utils", None)
        else:
            sys.modules["utils"] = _orig_utils
        if _orig_logger is None:
            sys.modules.pop("utils.logger", None)
        else:
            sys.modules["utils.logger"] = _orig_logger

    return mod


_mod = _load()

SkillEntity = _mod.SkillEntity
normalize = _mod.normalize
dedupe = _mod.dedupe
top_k = _mod.top_k
budget = _mod.budget
render_entity = _mod.render_entity
build_skills_context = _mod.build_skills_context


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ACTIVE_SKILL = {
    "name": "weather_skill",
    "channel": "active",
    "description": "Fetches weather data from OpenMeteo",
    "triggers": ["weather", "temperature"],
    "validation_score": 1.0,
    "gap_question": None,
    "required_packages": [],
    "default_params": {},
    "status": "installed",
    "signature_status": "unsigned",
}

DRAFT_SKILL = {
    "name": "draft_skill",
    "channel": "draft",
    "description": "A draft skill",
    "triggers": ["draft"],
    "validation_score": 0.7,
    "gap_question": None,
    "required_packages": [],
    "default_params": {},
    "status": "draft",
    "signature_status": "unsigned",
}

SECRET_SKILL = {
    "name": "api_integration",
    "channel": "active",
    "description": "Integrates with external API",
    "triggers": ["api"],
    "validation_score": 0.9,
    "gap_question": "What is your API token?",
    "required_packages": ["httpx"],
    "default_params": {},
    "status": "installed",
    "signature_status": "verified",
}

BROKEN_SKILL = {
    "name": "broken_skill",
    "channel": "active",
    "description": "Something broken",
    "triggers": [],
    "validation_score": 0.3,
    "gap_question": None,
    "required_packages": [],
    "default_params": {},
    "status": "broken",
    "signature_status": "unsigned",
}


# ===========================================================================
# Part 1 — normalize()
# ===========================================================================

class TestNormalize(unittest.TestCase):

    def test_name_extracted(self):
        e = normalize({"name": "foo_skill"})
        self.assertEqual(e.name, "foo_skill")

    def test_name_fallback_on_missing(self):
        e = normalize({})
        self.assertEqual(e.name, "unknown")

    def test_name_stripped(self):
        e = normalize({"name": "  bar  "})
        self.assertEqual(e.name, "bar")

    def test_channel_active(self):
        e = normalize({"name": "x", "channel": "active"})
        self.assertEqual(e.channel, "active")

    def test_channel_draft(self):
        e = normalize({"name": "x", "channel": "draft"})
        self.assertEqual(e.channel, "draft")

    def test_channel_invalid_defaults_to_active(self):
        e = normalize({"name": "x", "channel": "unknown_channel"})
        self.assertEqual(e.channel, "active")

    def test_capabilities_from_triggers(self):
        e = normalize({"name": "x", "triggers": ["weather", "temperature"]})
        self.assertIn("weather", e.capabilities)
        self.assertIn("temperature", e.capabilities)

    def test_capabilities_sorted(self):
        e = normalize({"name": "x", "triggers": ["zebra", "apple", "mango"]})
        self.assertEqual(list(e.capabilities), sorted(e.capabilities))

    def test_capabilities_max_5(self):
        e = normalize({
            "name": "x",
            "triggers": ["a", "b", "c", "d", "e", "f", "g"],
        })
        self.assertLessEqual(len(e.capabilities), 5)

    def test_capabilities_tuple_type(self):
        e = normalize(ACTIVE_SKILL)
        self.assertIsInstance(e.capabilities, tuple)

    def test_capabilities_deduplicated(self):
        e = normalize({"name": "x", "triggers": ["foo", "foo", "bar"]})
        self.assertEqual(len(e.capabilities), len(set(e.capabilities)))

    def test_requires_secrets_gap_question(self):
        e = normalize(SECRET_SKILL)
        self.assertTrue(e.requires_secrets)

    def test_requires_secrets_keyword_in_description(self):
        e = normalize({
            "name": "x",
            "description": "Needs an api_key to connect",
        })
        self.assertTrue(e.requires_secrets)

    def test_requires_secrets_false_when_no_keywords(self):
        e = normalize(ACTIVE_SKILL)
        self.assertFalse(e.requires_secrets)

    def test_trust_level_trusted(self):
        e = normalize({"name": "x", "validation_score": 1.0})
        self.assertEqual(e.trust_level, "trusted")

    def test_trust_level_trusted_at_boundary(self):
        e = normalize({"name": "x", "validation_score": 0.9})
        self.assertEqual(e.trust_level, "trusted")

    def test_trust_level_unverified(self):
        e = normalize({"name": "x", "validation_score": 0.7})
        self.assertEqual(e.trust_level, "unverified")

    def test_trust_level_untrusted(self):
        e = normalize({"name": "x", "validation_score": 0.3})
        self.assertEqual(e.trust_level, "untrusted")

    def test_trust_level_untrusted_at_boundary(self):
        e = normalize({"name": "x", "validation_score": 0.0})
        self.assertEqual(e.trust_level, "untrusted")

    def test_trust_level_missing_score_is_unverified(self):
        e = normalize({"name": "x"})
        self.assertEqual(e.trust_level, "unverified")

    def test_signature_status_verified(self):
        e = normalize({"name": "x", "signature_status": "verified"})
        self.assertEqual(e.signature_status, "verified")

    def test_signature_status_invalid_is_valid(self):
        e = normalize({"name": "x", "signature_status": "invalid"})
        self.assertEqual(e.signature_status, "invalid")

    def test_signature_status_garbage_defaults_to_unsigned(self):
        e = normalize({"name": "x", "signature_status": "garbage"})
        self.assertEqual(e.signature_status, "unsigned")

    def test_state_active_from_status_installed(self):
        e = normalize({"name": "x", "status": "installed"})
        self.assertEqual(e.state, "active")

    def test_state_broken(self):
        e = normalize(BROKEN_SKILL)
        self.assertEqual(e.state, "broken")

    def test_state_draft_from_channel(self):
        e = normalize({"name": "x", "channel": "draft"})
        self.assertEqual(e.state, "draft")

    def test_state_unknown_when_no_hints(self):
        e = normalize({"name": "x"})
        self.assertEqual(e.state, "unknown")

    def test_required_packages_sorted_tuple(self):
        e = normalize({"name": "x", "required_packages": ["httpx", "aiohttp"]})
        self.assertEqual(e.required_packages, ("aiohttp", "httpx"))

    def test_required_packages_from_default_params_fallback(self):
        e = normalize({
            "name": "x",
            "required_packages": [],
            "default_params": {"httpx": "0.24", "numpy": "1.26"},
        })
        self.assertEqual(e.required_packages, ("httpx", "numpy"))

    def test_missing_packages_empty_by_default(self):
        e = normalize(ACTIVE_SKILL)
        self.assertEqual(e.missing_packages, ())

    def test_entity_is_frozen(self):
        e = normalize(ACTIVE_SKILL)
        with self.assertRaises(Exception):
            e.name = "changed"  # type: ignore

    def test_all_9_fields_present(self):
        e = normalize(ACTIVE_SKILL)
        for field in (
            "name", "channel", "capabilities", "requires_secrets",
            "required_packages", "missing_packages",
            "trust_level", "signature_status", "state",
        ):
            self.assertTrue(hasattr(e, field), f"Missing field: {field}")

    def test_returns_skill_entity_instance(self):
        e = normalize(ACTIVE_SKILL)
        self.assertIsInstance(e, SkillEntity)


# ===========================================================================
# Part 2 — dedupe()
# ===========================================================================

class TestDedupe(unittest.TestCase):

    def _make(self, name, channel, score=1.0):
        return normalize({
            "name": name, "channel": channel,
            "validation_score": score,
            "status": "installed" if channel == "active" else "draft",
        })

    def test_single_entity_passes_through(self):
        entities = [self._make("foo", "active")]
        result = dedupe(entities)
        self.assertEqual(len(result), 1)

    def test_active_wins_over_draft_when_draft_first(self):
        draft = self._make("foo", "draft")
        active = self._make("foo", "active")
        result = dedupe([draft, active])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].channel, "active")

    def test_active_wins_over_draft_when_active_first(self):
        active = self._make("foo", "active")
        draft = self._make("foo", "draft")
        result = dedupe([active, draft])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].channel, "active")

    def test_different_names_all_kept(self):
        entities = [self._make("a", "active"), self._make("b", "draft")]
        result = dedupe(entities)
        self.assertEqual(len(result), 2)

    def test_output_sorted_by_name(self):
        entities = [
            self._make("z", "active"),
            self._make("a", "active"),
            self._make("m", "draft"),
        ]
        result = dedupe(entities)
        names = [e.name for e in result]
        self.assertEqual(names, sorted(names))

    def test_empty_input(self):
        self.assertEqual(dedupe([]), [])


# ===========================================================================
# Part 3 — top_k()
# ===========================================================================

class TestTopK(unittest.TestCase):

    def _make(self, name, state="active", trust="trusted"):
        return SkillEntity(
            name=name,
            channel="active" if state == "active" else "draft",
            capabilities=(),
            requires_secrets=False,
            required_packages=(),
            missing_packages=(),
            trust_level=trust,
            signature_status="unsigned",
            state=state,
        )

    def test_k_zero_returns_empty(self):
        entities = [self._make("a"), self._make("b")]
        self.assertEqual(top_k(entities, 0), [])

    def test_k_negative_returns_empty(self):
        self.assertEqual(top_k([self._make("a")], -1), [])

    def test_k_larger_than_list_returns_all(self):
        entities = [self._make("a"), self._make("b")]
        result = top_k(entities, 100)
        self.assertEqual(len(result), 2)

    def test_active_before_draft(self):
        draft = self._make("draft_skill", state="draft")
        active = self._make("active_skill", state="active")
        result = top_k([draft, active], 2)
        self.assertEqual(result[0].state, "active")

    def test_trusted_before_untrusted(self):
        untrusted = self._make("b", trust="untrusted")
        trusted = self._make("a", trust="trusted")
        result = top_k([untrusted, trusted], 2)
        self.assertEqual(result[0].trust_level, "trusted")

    def test_name_alphabetical_tiebreaker(self):
        a = self._make("zebra", state="active", trust="trusted")
        b = self._make("apple", state="active", trust="trusted")
        result = top_k([a, b], 2)
        self.assertEqual(result[0].name, "apple")

    def test_deterministic_same_input_same_output(self):
        entities = [self._make(n) for n in ["c", "b", "a"]]
        r1 = top_k(entities, 3)
        r2 = top_k(entities, 3)
        self.assertEqual([e.name for e in r1], [e.name for e in r2])

    def test_empty_input(self):
        self.assertEqual(top_k([], 5), [])


# ===========================================================================
# Part 4 — budget()
# ===========================================================================

class TestBudget(unittest.TestCase):

    def _make_entity(self, name):
        return SkillEntity(
            name=name,
            channel="active",
            capabilities=("cap",),
            requires_secrets=False,
            required_packages=(),
            missing_packages=(),
            trust_level="trusted",
            signature_status="unsigned",
            state="active",
        )

    def test_cap_zero_returns_all(self):
        entities = [self._make_entity("a"), self._make_entity("b")]
        result = budget(entities, 0)
        self.assertEqual(len(result), 2)

    def test_cap_negative_returns_all(self):
        result = budget([self._make_entity("a")], -1)
        self.assertEqual(len(result), 1)

    def test_cap_large_returns_all(self):
        entities = [self._make_entity("a"), self._make_entity("b")]
        result = budget(entities, 999999)
        self.assertEqual(len(result), 2)

    def test_cap_very_small_cuts_list(self):
        # render_entity produces ~50+ chars; cap=1 → nothing fits
        entities = [self._make_entity("a"), self._make_entity("b")]
        result = budget(entities, 1)
        self.assertEqual(len(result), 0)

    def test_total_render_within_cap(self):
        entities = [self._make_entity("alpha"), self._make_entity("beta")]
        cap = 10000
        result = budget(entities, cap)
        total = sum(len(render_entity(e)) + 1 for e in result)
        self.assertLessEqual(total, cap)

    def test_empty_input(self):
        self.assertEqual(budget([], 100), [])


# ===========================================================================
# Part 5 — render_entity()
# ===========================================================================

class TestRenderEntity(unittest.TestCase):

    def _make(self, **kwargs):
        defaults = dict(
            name="test_skill",
            channel="active",
            capabilities=("weather", "temperature"),
            requires_secrets=False,
            required_packages=(),
            missing_packages=(),
            trust_level="trusted",
            signature_status="unsigned",
            state="active",
        )
        defaults.update(kwargs)
        return SkillEntity(**defaults)

    def test_starts_with_skill_prefix(self):
        self.assertTrue(render_entity(self._make()).startswith("SKILL:"))

    def test_contains_name(self):
        self.assertIn("foo_skill", render_entity(self._make(name="foo_skill")))

    def test_contains_channel_in_brackets_active(self):
        self.assertIn("[active]", render_entity(self._make(channel="active")))

    def test_contains_channel_in_brackets_draft(self):
        self.assertIn("[draft]", render_entity(self._make(channel="draft")))

    def test_secrets_yes(self):
        self.assertIn("secrets=yes", render_entity(self._make(requires_secrets=True)))

    def test_secrets_no(self):
        self.assertIn("secrets=no", render_entity(self._make(requires_secrets=False)))

    def test_contains_trust_level(self):
        self.assertIn("trust=unverified", render_entity(self._make(trust_level="unverified")))

    def test_pkgs_shown_when_present(self):
        self.assertIn("pkgs=httpx", render_entity(self._make(required_packages=("httpx",))))

    def test_missing_shown_when_present(self):
        line = render_entity(self._make(
            required_packages=("httpx",),
            missing_packages=("httpx",),
        ))
        self.assertIn("MISSING=httpx", line)

    def test_no_pkgs_field_when_empty(self):
        self.assertNotIn("pkgs=", render_entity(self._make(required_packages=())))

    def test_capabilities_dash_when_empty(self):
        self.assertIn("cap=-", render_entity(self._make(capabilities=())))

    def test_returns_str(self):
        self.assertIsInstance(render_entity(self._make()), str)


# ===========================================================================
# Part 6 — build_skills_context() mode wiring
# ===========================================================================

class TestBuildSkillsContext(unittest.TestCase):

    _SKILLS = [ACTIVE_SKILL, DRAFT_SKILL, SECRET_SKILL]

    def test_off_mode_returns_empty(self):
        self.assertEqual(build_skills_context(self._SKILLS, mode="off"), "")

    def test_off_mode_empty_input_still_empty(self):
        self.assertEqual(build_skills_context([], mode="off"), "")

    def test_shadow_mode_returns_empty(self):
        self.assertEqual(build_skills_context(self._SKILLS, mode="shadow"), "")

    def test_shadow_mode_empty_input_returns_empty(self):
        self.assertEqual(build_skills_context([], mode="shadow"), "")

    def test_active_mode_returns_string(self):
        result = build_skills_context(self._SKILLS, mode="active")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_active_mode_has_skills_header(self):
        result = build_skills_context(self._SKILLS, mode="active")
        self.assertIn("SKILLS:", result)

    def test_active_mode_contains_skill_name(self):
        result = build_skills_context(self._SKILLS, mode="active")
        self.assertIn("weather_skill", result)

    def test_active_mode_empty_input_returns_empty(self):
        self.assertEqual(build_skills_context([], mode="active"), "")

    def test_active_mode_top_k_limits(self):
        skills = [
            {"name": f"skill_{i:02d}", "channel": "active", "validation_score": 1.0,
             "status": "installed"}
            for i in range(20)
        ]
        result = build_skills_context(skills, mode="active", top_k_count=3)
        self.assertEqual(result.count("SKILL:"), 3)

    def test_active_mode_char_cap_respected(self):
        skills = [
            {"name": f"skill_{i:02d}", "channel": "active", "validation_score": 1.0,
             "status": "installed", "triggers": ["cap"]}
            for i in range(20)
        ]
        result = build_skills_context(skills, mode="active", top_k_count=20, char_cap=200)
        # Result may include header + a few lines; should be well under 500
        self.assertLessEqual(len(result), 500)

    def test_pipeline_error_returns_empty(self):
        # Pass None as installed_skills → normalize loop fails gracefully
        result = build_skills_context(None, mode="active")  # type: ignore
        self.assertEqual(result, "")


# ===========================================================================
# Part 7 — Pipeline integration
# ===========================================================================

class TestPipelineIntegration(unittest.TestCase):

    def test_dedupes_active_draft_same_name(self):
        """Same skill in both channels → only active in output."""
        skills = [
            {"name": "my_skill", "channel": "active", "validation_score": 1.0,
             "status": "installed", "triggers": ["x"]},
            {"name": "my_skill", "channel": "draft", "validation_score": 0.5,
             "status": "draft", "triggers": ["x"]},
        ]
        result = build_skills_context(skills, mode="active")
        self.assertEqual(result.count("my_skill"), 1)
        self.assertIn("[active]", result)

    def test_deterministic_output_repeated_calls(self):
        """Identical input → identical output across multiple calls."""
        skills = [ACTIVE_SKILL, DRAFT_SKILL, SECRET_SKILL, BROKEN_SKILL]
        r1 = build_skills_context(skills, mode="active")
        r2 = build_skills_context(skills, mode="active")
        self.assertEqual(r1, r2)

    def test_broken_skill_sorted_after_active(self):
        """Active skills appear before broken skills in output."""
        skills = [BROKEN_SKILL, ACTIVE_SKILL]
        result = build_skills_context(skills, mode="active")
        active_pos = result.find("weather_skill")
        broken_pos = result.find("broken_skill")
        self.assertGreater(broken_pos, active_pos)


if __name__ == "__main__":
    unittest.main(verbosity=2)
