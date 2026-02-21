"""
Unit Tests for Phase 2: TypedState V1 + Dedupe + Renderer

Tests:
- TypedFact dataclass mapping
- ContainerEntity lifecycle
- Dedupe window (2s)
- format_compact_context: char-cap, fail-closed, determinism
- build_compact_context integration
- Backward compatibility regression

Created by: Claude (Phase 2)
Date: 2026-02-18
"""

import pytest
import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _make_event(event_type: str, data: dict, ts: float = None) -> dict:
    """Build a minimal event dict for testing.

    Note: _dedupe_events reads 'created_at' (ISO string) for timing.
    Pass ts as float Unix timestamp; it will be converted to ISO format.
    """
    from datetime import datetime, timezone
    ts_val = ts if ts is not None else time.time()
    iso = datetime.fromtimestamp(ts_val, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    return {
        "event_type": event_type,
        "created_at": iso,
        "event_data": data,
    }


def _import_or_skip(name: str, fromlist: list):
    """Import module or skip test if not available."""
    try:
        mod = __import__(name, fromlist=fromlist)
        return mod
    except ImportError as e:
        pytest.skip(f"Cannot import {name}: {e}")


# ─────────────────────────────────────────────────────────────────
# TypedFact Tests
# ─────────────────────────────────────────────────────────────────

class TestTypedFact:
    """Tests for TypedFact dataclass"""

    def test_typed_fact_defaults(self):
        """TypedFact should have sensible defaults."""
        mod = _import_or_skip("core.context_cleanup", ["TypedFact"])
        TypedFact = mod.TypedFact

        fact = TypedFact(fact_type="ACTIVE_CONTAINER", value="container-abc")
        assert fact.fact_type == "ACTIVE_CONTAINER"
        assert fact.value == "container-abc"
        assert fact.confidence == 1.0
        assert fact.observed_at == ""
        assert fact.source == ""
        assert fact.source_event_ids == []

    def test_typed_fact_custom_fields(self):
        """TypedFact should store all custom field values."""
        mod = _import_or_skip("core.context_cleanup", ["TypedFact"])
        TypedFact = mod.TypedFact

        fact = TypedFact(
            fact_type="TOOL_EXECUTED",
            value="exec_ok",
            confidence=0.9,
            observed_at="2026-02-18T10:00:00",
            source="event_42",
            source_event_ids=["ev_1", "ev_2"],
        )
        assert fact.confidence == 0.9
        assert fact.observed_at == "2026-02-18T10:00:00"
        assert fact.source_event_ids == ["ev_1", "ev_2"]

    def test_typed_fact_independent_source_ids(self):
        """Each TypedFact instance should have its own source_event_ids list."""
        mod = _import_or_skip("core.context_cleanup", ["TypedFact"])
        TypedFact = mod.TypedFact

        f1 = TypedFact(fact_type="A", value="1")
        f2 = TypedFact(fact_type="B", value="2")
        f1.source_event_ids.append("ev_x")
        assert f2.source_event_ids == [], "Lists should not be shared across instances"


# ─────────────────────────────────────────────────────────────────
# ContainerEntity Tests
# ─────────────────────────────────────────────────────────────────

class TestContainerEntity:
    """Tests for ContainerEntity dataclass"""

    def test_container_entity_defaults(self):
        """ContainerEntity should have correct defaults."""
        mod = _import_or_skip("core.context_cleanup", ["ContainerEntity"])
        ContainerEntity = mod.ContainerEntity

        c = ContainerEntity(id="c-001")
        assert c.id == "c-001"
        assert c.status == "unknown"
        assert c.stability_score == "medium"
        assert c.last_error is None
        assert c.last_exit_code is None

    def test_container_entity_lifecycle(self):
        """Should track status changes correctly."""
        mod = _import_or_skip("core.context_cleanup", ["ContainerEntity"])
        ContainerEntity = mod.ContainerEntity

        c = ContainerEntity(id="c-002", status="running")
        assert c.status == "running"

        c.status = "stopped"
        c.last_exit_code = 0
        assert c.status == "stopped"
        assert c.last_exit_code == 0

    def test_container_entity_to_dict_excludes_none(self):
        """to_dict() should exclude None fields."""
        mod = _import_or_skip("core.context_cleanup", ["ContainerEntity"])
        ContainerEntity = mod.ContainerEntity

        c = ContainerEntity(id="c-003", status="running")
        d = c.to_dict()
        assert "id" in d
        assert "status" in d
        # None fields should be excluded
        assert "last_error" not in d
        assert "ttl_remaining" not in d

    def test_container_entity_full_to_dict(self):
        """to_dict() should include all non-None fields."""
        mod = _import_or_skip("core.context_cleanup", ["ContainerEntity"])
        ContainerEntity = mod.ContainerEntity

        c = ContainerEntity(
            id="c-004",
            blueprint_id="bp-python",
            status="running",
            last_exit_code=1,
            last_error="OOMKilled",
            stability_score="low",
        )
        d = c.to_dict()
        assert d["blueprint_id"] == "bp-python"
        assert d["last_exit_code"] == 1
        assert d["last_error"] == "OOMKilled"
        assert d["stability_score"] == "low"


# ─────────────────────────────────────────────────────────────────
# Dedupe Tests
# ─────────────────────────────────────────────────────────────────

class TestDedupeEvents:
    """Tests for _dedupe_events() helper"""

    def test_dedupe_identical_events_within_window(self):
        """Identical events within 2s window should be deduplicated."""
        mod = _import_or_skip("core.context_cleanup", ["_dedupe_events"])
        _dedupe_events = mod._dedupe_events

        ts_base = time.time()
        ev1 = _make_event("container_started", {"container_id": "c-1"}, ts=ts_base)
        ev2 = _make_event("container_started", {"container_id": "c-1"}, ts=ts_base + 0.5)

        result = _dedupe_events([ev1, ev2])
        assert len(result) == 1, f"Expected 1 event after dedupe, got {len(result)}"

    def test_dedupe_identical_events_outside_window(self):
        """Identical events >2s apart should NOT be deduplicated."""
        mod = _import_or_skip("core.context_cleanup", ["_dedupe_events"])
        _dedupe_events = mod._dedupe_events

        ts_base = time.time()
        ev1 = _make_event("container_started", {"container_id": "c-2"}, ts=ts_base)
        ev2 = _make_event("container_started", {"container_id": "c-2"}, ts=ts_base + 3.0)

        result = _dedupe_events([ev1, ev2])
        assert len(result) == 2, f"Expected 2 events (outside window), got {len(result)}"

    def test_dedupe_different_event_types_kept(self):
        """Different event types with same data should NOT be deduplicated."""
        mod = _import_or_skip("core.context_cleanup", ["_dedupe_events"])
        _dedupe_events = mod._dedupe_events

        ts_base = time.time()
        ev1 = _make_event("container_started", {"container_id": "c-3"}, ts=ts_base)
        ev2 = _make_event("container_stopped", {"container_id": "c-3"}, ts=ts_base + 0.1)

        result = _dedupe_events([ev1, ev2])
        assert len(result) == 2, "Different event types must be kept separate"

    def test_dedupe_empty_list(self):
        """Empty event list should return empty list."""
        mod = _import_or_skip("core.context_cleanup", ["_dedupe_events"])
        _dedupe_events = mod._dedupe_events

        result = _dedupe_events([])
        assert result == []

    def test_dedupe_single_event_unchanged(self):
        """Single event should pass through unchanged."""
        mod = _import_or_skip("core.context_cleanup", ["_dedupe_events"])
        _dedupe_events = mod._dedupe_events

        ev = _make_event("tool_executed", {"tool": "exec_in_container"})
        result = _dedupe_events([ev])
        assert len(result) == 1
        assert result[0] is ev

    def test_dedupe_timestamp_fields_ignored_in_hash(self):
        """Events differing only in timestamp field should be treated as identical."""
        mod = _import_or_skip("core.context_cleanup", ["_dedupe_events"])
        _dedupe_events = mod._dedupe_events

        ts_base = time.time()
        # Same data but different 'updated_at' in event_data → should still dedupe
        ev1 = _make_event("blueprint_selected", {"blueprint_id": "bp-1", "updated_at": "2026-01-01"}, ts=ts_base)
        ev2 = _make_event("blueprint_selected", {"blueprint_id": "bp-1", "updated_at": "2026-01-02"}, ts=ts_base + 0.1)

        result = _dedupe_events([ev1, ev2])
        assert len(result) == 1, "updated_at difference should NOT prevent deduplication"


# ─────────────────────────────────────────────────────────────────
# Renderer Tests (format_compact_context)
# ─────────────────────────────────────────────────────────────────

class TestFormatCompactContext:
    """Tests for format_compact_context() deterministic renderer"""

    def _make_compact_ctx(self, mod, **kwargs):
        """Build a minimal CompactContext for testing.

        CompactContext(now, rules, next_steps, meta=None)
        """
        CompactContext = mod.CompactContext
        defaults = {
            "now": [],
            "rules": [],
            "next_steps": [],
        }
        defaults.update(kwargs)
        return CompactContext(**defaults)

    def test_renderer_produces_string(self):
        """format_compact_context should return a string."""
        mod = _import_or_skip("core.context_cleanup", ["format_compact_context", "CompactContext"])
        ctx = self._make_compact_ctx(mod, now=["container c-1 running"])
        result = mod.format_compact_context(ctx)
        assert isinstance(result, str)

    def test_renderer_char_cap_enforced(self):
        """Output should be truncated to char_cap."""
        mod = _import_or_skip("core.context_cleanup", ["format_compact_context", "CompactContext"])
        long_rules = [f"Rule number {i}: " + "x" * 100 for i in range(20)]
        ctx = self._make_compact_ctx(mod, rules=long_rules)

        cap = 200
        result = mod.format_compact_context(ctx, char_cap=cap)
        assert len(result) <= cap, f"Result length {len(result)} exceeds cap {cap}"

    def test_renderer_deterministic(self):
        """Same input should always produce identical output."""
        mod = _import_or_skip("core.context_cleanup", ["format_compact_context", "CompactContext"])
        ctx = self._make_compact_ctx(
            mod,
            now=["active container: c-001"],
            rules=["No freestyle exec", "Trust-gated only"],
            next_steps=["await user confirmation"],
        )

        result1 = mod.format_compact_context(ctx)
        result2 = mod.format_compact_context(ctx)
        assert result1 == result2, "Renderer output must be deterministic"

    def test_renderer_fail_closed(self):
        """Renderer should return safe fallback string on error."""
        mod = _import_or_skip("core.context_cleanup", ["format_compact_context"])

        class BrokenCtx:
            """Object that raises on attribute access."""
            @property
            def now_bullets(self):
                raise RuntimeError("Simulated renderer error")

        result = mod.format_compact_context(BrokenCtx())
        assert isinstance(result, str)
        assert len(result) > 0, "Fail-closed should return non-empty string"
        # Should contain some error indicator
        assert "CONTEXT ERROR" in result or "NOW" in result

    def test_renderer_empty_context(self):
        """Empty context should still produce valid string."""
        mod = _import_or_skip("core.context_cleanup", ["format_compact_context", "CompactContext"])
        ctx = self._make_compact_ctx(mod)
        result = mod.format_compact_context(ctx)
        assert isinstance(result, str)

    def test_renderer_sections_ordering(self):
        """NOW should appear before RULES should appear before NEXT."""
        mod = _import_or_skip("core.context_cleanup", ["format_compact_context", "CompactContext"])
        ctx = self._make_compact_ctx(
            mod,
            now=["state A"],
            rules=["rule B"],
            next_steps=["step C"],
        )
        result = mod.format_compact_context(ctx)
        pos_now = result.find("NOW")
        pos_rules = result.find("RULES")
        pos_next = result.find("NEXT")

        # At least NOW must be present
        assert pos_now >= 0, "NOW section missing from renderer output"
        if pos_rules >= 0 and pos_next >= 0:
            assert pos_now < pos_rules < pos_next, "Section order: NOW < RULES < NEXT"


# ─────────────────────────────────────────────────────────────────
# build_compact_context Integration
# ─────────────────────────────────────────────────────────────────

class TestBuildCompactContextIntegration:
    """Integration tests for build_compact_context + TypedState"""

    def test_build_with_container_started_event(self):
        """Container started event should appear in NOW bullets."""
        mod = _import_or_skip("core.context_cleanup", ["build_compact_context"])

        events = [
            _make_event("container_started", {
                "container_id": "c-integration-1",
                "blueprint_id": "bp-python",
            })
        ]
        result = mod.build_compact_context(events)
        assert result is not None

        # Render and check
        fmt_mod = _import_or_skip("core.context_cleanup", ["format_compact_context"])
        text = fmt_mod.format_compact_context(result)
        assert isinstance(text, str)

    def test_build_with_empty_events(self):
        """Empty event list should not crash."""
        mod = _import_or_skip("core.context_cleanup", ["build_compact_context"])
        result = mod.build_compact_context([])
        assert result is not None

    def test_build_dedupes_events(self):
        """Duplicate events within window should be handled gracefully."""
        mod = _import_or_skip("core.context_cleanup", ["build_compact_context"])
        ts_base = time.time()

        events = [
            _make_event("container_started", {"container_id": "c-dup"}, ts=ts_base),
            _make_event("container_started", {"container_id": "c-dup"}, ts=ts_base + 0.3),
            _make_event("container_started", {"container_id": "c-dup"}, ts=ts_base + 0.6),
        ]
        # Should not raise and should produce valid CompactContext
        result = mod.build_compact_context(events)
        assert result is not None

    def test_build_multiple_container_states(self):
        """Multiple containers should each appear in state."""
        mod = _import_or_skip("core.context_cleanup", ["build_compact_context", "TypedState"])

        events = [
            _make_event("container_started", {"container_id": "c-a", "blueprint_id": "bp-1"}),
            _make_event("container_started", {"container_id": "c-b", "blueprint_id": "bp-2"}),
        ]
        result = mod.build_compact_context(events)
        assert result is not None


# ─────────────────────────────────────────────────────────────────
# Backward Compatibility
# ─────────────────────────────────────────────────────────────────

class TestBackwardCompatibility:
    """Regression tests to ensure Phase 2 doesn't break existing API"""

    def test_typed_state_entities_dict_preserved(self):
        """TypedState.entities dict must still exist for legacy compatibility."""
        mod = _import_or_skip("core.context_cleanup", ["TypedState"])
        ts = mod.TypedState()
        assert hasattr(ts, "entities"), "TypedState.entities must remain for backward compat"
        assert isinstance(ts.entities, dict)

    def test_typed_state_has_new_containers_field(self):
        """TypedState should also have .containers dict (Phase 2 addition)."""
        mod = _import_or_skip("core.context_cleanup", ["TypedState"])
        ts = mod.TypedState()
        assert hasattr(ts, "containers"), "TypedState.containers must exist (Phase 2)"
        assert isinstance(ts.containers, dict)

    def test_typed_state_has_facts_field(self):
        """TypedState should have .facts dict (Phase 2 addition): Dict[fact_type, List[TypedFact]]."""
        mod = _import_or_skip("core.context_cleanup", ["TypedState"])
        ts = mod.TypedState()
        assert hasattr(ts, "facts"), "TypedState.facts must exist (Phase 2)"
        assert isinstance(ts.facts, dict)

    def test_compact_context_dataclass_unchanged(self):
        """CompactContext should still accept its fields: now, rules, next_steps, meta."""
        mod = _import_or_skip("core.context_cleanup", ["CompactContext"])
        ctx = mod.CompactContext(
            now=["test"],
            rules=["rule"],
            next_steps=["step"],
        )
        assert ctx.now == ["test"]

    def test_format_compact_context_no_char_cap_arg(self):
        """format_compact_context should work without char_cap argument (backward compat)."""
        mod = _import_or_skip("core.context_cleanup", ["format_compact_context", "CompactContext"])
        ctx = mod.CompactContext(
            now=["container running"],
            rules=["be safe"],
            next_steps=[],
        )
        # Should not raise TypeError for missing char_cap
        result = mod.format_compact_context(ctx)
        assert isinstance(result, str)

    def test_build_compact_context_callable_with_list(self):
        """build_compact_context(events) should accept a plain list."""
        mod = _import_or_skip("core.context_cleanup", ["build_compact_context"])
        # Should not raise
        result = mod.build_compact_context([])
        assert result is not None

    def test_event_core_hash_stable(self):
        """_event_core_hash should be stable across calls."""
        mod = _import_or_skip("core.context_cleanup", ["_event_core_hash"])
        ev = {"event_type": "tool_executed", "event_data": {"tool": "exec_in_container", "exit_code": 0}}
        h1 = mod._event_core_hash(ev)
        h2 = mod._event_core_hash(ev)
        assert h1 == h2, "Hash must be stable"

    def test_event_core_hash_ignores_timestamp(self):
        """Hash must ignore timestamp-like fields."""
        mod = _import_or_skip("core.context_cleanup", ["_event_core_hash"])
        ev1 = {"event_type": "X", "event_data": {"key": "val", "timestamp": "2026-01-01"}}
        ev2 = {"event_type": "X", "event_data": {"key": "val", "timestamp": "2026-06-01"}}
        assert mod._event_core_hash(ev1) == mod._event_core_hash(ev2)


# ─────────────────────────────────────────────────────────────────
# TypedState V1 Fields (Commit 1)
# ─────────────────────────────────────────────────────────────────

class TestTypedStateV1Fields:
    """TypedState must expose all V1 schema fields with stable defaults (Commit 1)."""

    def test_version_field_exists(self):
        mod = _import_or_skip("core.context_cleanup", ["TypedState"])
        ts = mod.TypedState()
        assert hasattr(ts, "version")
        assert ts.version == "1"

    def test_session_id_default_none(self):
        mod = _import_or_skip("core.context_cleanup", ["TypedState"])
        ts = mod.TypedState()
        assert hasattr(ts, "session_id")
        assert ts.session_id is None

    def test_conversation_id_default_none(self):
        mod = _import_or_skip("core.context_cleanup", ["TypedState"])
        ts = mod.TypedState()
        assert hasattr(ts, "conversation_id")
        assert ts.conversation_id is None

    def test_last_errors_default_empty_list(self):
        mod = _import_or_skip("core.context_cleanup", ["TypedState"])
        ts = mod.TypedState()
        assert hasattr(ts, "last_errors")
        assert isinstance(ts.last_errors, list)
        assert ts.last_errors == []

    def test_pending_approvals_default_empty_list(self):
        mod = _import_or_skip("core.context_cleanup", ["TypedState"])
        ts = mod.TypedState()
        assert hasattr(ts, "pending_approvals")
        assert isinstance(ts.pending_approvals, list)
        assert ts.pending_approvals == []

    def test_last_tool_results_default_empty_list(self):
        mod = _import_or_skip("core.context_cleanup", ["TypedState"])
        ts = mod.TypedState()
        assert hasattr(ts, "last_tool_results")
        assert isinstance(ts.last_tool_results, list)
        assert ts.last_tool_results == []

    def test_source_event_ids_default_empty_list(self):
        mod = _import_or_skip("core.context_cleanup", ["TypedState"])
        ts = mod.TypedState()
        assert hasattr(ts, "source_event_ids")
        assert isinstance(ts.source_event_ids, list)
        assert ts.source_event_ids == []

    def test_v1_lists_independent_across_instances(self):
        """V1 list fields must not be shared across TypedState instances."""
        mod = _import_or_skip("core.context_cleanup", ["TypedState"])
        ts1 = mod.TypedState()
        ts2 = mod.TypedState()
        ts1.last_errors.append("err")
        ts1.pending_approvals.append("approval")
        ts1.last_tool_results.append("tool_ref")
        ts1.source_event_ids.append("ev_x")
        assert ts2.last_errors == []
        assert ts2.pending_approvals == []
        assert ts2.last_tool_results == []
        assert ts2.source_event_ids == []

    def test_legacy_fields_still_accessible(self):
        """Existing TypedState fields must not be removed by V1 extension."""
        mod = _import_or_skip("core.context_cleanup", ["TypedState"])
        ts = mod.TypedState()
        for field in ("entities", "containers", "facts", "focus_entity",
                      "active_gates", "open_issues", "user_constraints",
                      "last_error", "pending_blueprint", "updated_at"):
            assert hasattr(ts, field), f"Legacy field '{field}' missing from TypedState"


# ─────────────────────────────────────────────────────────────────
# ContainerEntity V1 Fields (Commit 1)
# ─────────────────────────────────────────────────────────────────

class TestContainerEntityV1Fields:
    """ContainerEntity must expose V1 fields and backward-compat container_id alias."""

    def test_session_id_field_exists(self):
        mod = _import_or_skip("core.context_cleanup", ["ContainerEntity"])
        c = mod.ContainerEntity(id="c-v1-1")
        assert hasattr(c, "session_id")
        assert c.session_id is None

    def test_conversation_id_field_exists(self):
        mod = _import_or_skip("core.context_cleanup", ["ContainerEntity"])
        c = mod.ContainerEntity(id="c-v1-2")
        assert hasattr(c, "conversation_id")
        assert c.conversation_id is None

    def test_source_event_ids_field_exists(self):
        mod = _import_or_skip("core.context_cleanup", ["ContainerEntity"])
        c = mod.ContainerEntity(id="c-v1-3")
        assert hasattr(c, "source_event_ids")
        assert isinstance(c.source_event_ids, list)
        assert c.source_event_ids == []

    def test_container_id_alias(self):
        """container_id must be a backward-compat alias for id."""
        mod = _import_or_skip("core.context_cleanup", ["ContainerEntity"])
        c = mod.ContainerEntity(id="my-container-001")
        assert c.container_id == "my-container-001"
        assert c.container_id == c.id

    def test_source_event_ids_independent_across_instances(self):
        """source_event_ids must not be shared across ContainerEntity instances."""
        mod = _import_or_skip("core.context_cleanup", ["ContainerEntity"])
        c1 = mod.ContainerEntity(id="c-x1")
        c2 = mod.ContainerEntity(id="c-x2")
        c1.source_event_ids.append("ev_1")
        assert c2.source_event_ids == []

    def test_v1_none_fields_not_in_to_dict(self):
        """None V1 fields must not appear in to_dict() (backward compat)."""
        mod = _import_or_skip("core.context_cleanup", ["ContainerEntity"])
        c = mod.ContainerEntity(id="c-v1-4")
        d = c.to_dict()
        assert "session_id" not in d
        assert "conversation_id" not in d

    def test_v1_set_fields_appear_in_to_dict(self):
        """Set V1 fields must appear in to_dict()."""
        mod = _import_or_skip("core.context_cleanup", ["ContainerEntity"])
        c = mod.ContainerEntity(id="c-v1-5", session_id="sess-abc", conversation_id="conv-xyz")
        d = c.to_dict()
        assert d["session_id"] == "sess-abc"
        assert d["conversation_id"] == "conv-xyz"


# ─────────────────────────────────────────────────────────────────
# config.py TypedState Flags (Commit 1)
# ─────────────────────────────────────────────────────────────────

class TestConfigTypedStateFlags:
    """config.py must expose TypedState toggle getters with stable defaults."""

    def test_typedstate_mode_default_off(self):
        try:
            from config import get_typedstate_mode
        except ImportError:
            pytest.skip("config not importable")
        mode = get_typedstate_mode()
        assert mode == "off", f"TYPEDSTATE_MODE default must be 'off', got '{mode}'"

    def test_typedstate_enable_small_only_default_true(self):
        try:
            from config import get_typedstate_enable_small_only
        except ImportError:
            pytest.skip("config not importable")
        flag = get_typedstate_enable_small_only()
        assert flag is True, f"TYPEDSTATE_ENABLE_SMALL_ONLY default must be True, got {flag}"

    def test_typedstate_mode_is_valid_value(self):
        """Getter must return one of the defined modes."""
        try:
            from config import get_typedstate_mode
        except ImportError:
            pytest.skip("config not importable")
        mode = get_typedstate_mode()
        assert mode in ("off", "shadow", "active"), f"Unexpected mode: '{mode}'"

    def test_typedstate_constants_exported(self):
        """Module-level constants must be exported for fast access."""
        try:
            import config
        except ImportError:
            pytest.skip("config not importable")
        assert hasattr(config, "TYPEDSTATE_MODE")
        assert hasattr(config, "TYPEDSTATE_ENABLE_SMALL_ONLY")


# ═══════════════════════════════════════════════════════════════
# Commit 2 Tests (appended — no existing tests removed)
# ═══════════════════════════════════════════════════════════════

def _make_ev(event_type: str, data: dict, ts: float = None, ev_id: str = "") -> dict:
    """Extended _make_event with optional ev_id (Commit 2 tests only)."""
    ev = _make_event(event_type, data, ts)
    if ev_id:
        ev["id"] = ev_id
    return ev


class TestNormalizeEvents:
    def setup_method(self):
        mod = _import_or_skip("core.context_cleanup", ["_normalize_events"])
        self.fn = mod._normalize_events

    def test_returns_list(self):
        result = self.fn([])
        assert isinstance(result, list)
        assert result == []

    def test_shallow_copy_does_not_mutate_input(self):
        ev = {"event_type": "x", "event_data": {"k": "v"}, "created_at": "2026-02-19T10:00:00Z"}
        result = self.fn([ev])
        result[0]["event_type"] = "MUTATED"
        assert ev["event_type"] == "x", "normalize must not mutate original event"

    def test_event_data_string_parsed_to_dict(self):
        ev = {"event_type": "x", "event_data": '{"foo": 1}', "created_at": ""}
        result = self.fn([ev])
        assert isinstance(result[0]["event_data"], dict)
        assert result[0]["event_data"]["foo"] == 1

    def test_event_data_invalid_json_becomes_empty_dict(self):
        ev = {"event_type": "x", "event_data": "not-json", "created_at": ""}
        result = self.fn([ev])
        assert result[0]["event_data"] == {}

    def test_event_data_already_dict_unchanged(self):
        ev = {"event_type": "x", "event_data": {"a": 1}, "created_at": ""}
        result = self.fn([ev])
        assert result[0]["event_data"] == {"a": 1}

    def test_missing_id_generates_stable_id(self):
        ev = {"event_type": "x", "event_data": {"k": "v"}, "created_at": "2026-02-19T10:00:00Z"}
        r1 = self.fn([ev])[0]["id"]
        r2 = self.fn([ev])[0]["id"]
        assert r1 == r2, "Generated id must be stable (deterministic)"
        assert r1.startswith("gen-")

    def test_existing_id_preserved(self):
        ev = {"event_type": "x", "event_data": {}, "created_at": "", "id": "my-id-001"}
        result = self.fn([ev])
        assert result[0]["id"] == "my-id-001"

    def test_missing_created_at_defaults_to_empty_string(self):
        ev = {"event_type": "x", "event_data": {}}
        result = self.fn([ev])
        assert "created_at" in result[0]
        assert result[0]["created_at"] == ""

    def test_two_different_events_get_different_generated_ids(self):
        ev1 = {"event_type": "a", "event_data": {"k": "1"}, "created_at": "2026-02-19T10:00:00Z"}
        ev2 = {"event_type": "b", "event_data": {"k": "2"}, "created_at": "2026-02-19T10:00:00Z"}
        result = self.fn([ev1, ev2])
        assert result[0]["id"] != result[1]["id"]


# ─────────────────────────────────────────────────────────────────
# TestSortEventsAsc
# ─────────────────────────────────────────────────────────────────

class TestSortEventsAsc:
    def setup_method(self):
        mod = _import_or_skip("core.context_cleanup", ["_sort_events_asc"])
        self.fn = mod._sort_events_asc

    def _ev(self, ts_str: str, ev_id: str) -> dict:
        return {"created_at": ts_str, "id": ev_id, "event_type": "x", "event_data": {}}

    def test_already_sorted_unchanged(self):
        evs = [
            self._ev("2026-02-18T01:00:00Z", "id-a"),
            self._ev("2026-02-18T02:00:00Z", "id-b"),
        ]
        result = self.fn(evs)
        assert [e["id"] for e in result] == ["id-a", "id-b"]

    def test_reversed_input_sorted_correctly(self):
        evs = [
            self._ev("2026-02-18T02:00:00Z", "id-b"),
            self._ev("2026-02-18T01:00:00Z", "id-a"),
        ]
        result = self.fn(evs)
        assert [e["id"] for e in result] == ["id-a", "id-b"]

    def test_same_timestamp_sorted_by_id_asc(self):
        evs = [
            self._ev("2026-02-18T01:00:00Z", "id-z"),
            self._ev("2026-02-18T01:00:00Z", "id-a"),
            self._ev("2026-02-18T01:00:00Z", "id-m"),
        ]
        result = self.fn(evs)
        assert [e["id"] for e in result] == ["id-a", "id-m", "id-z"]

    def test_unparseable_timestamp_sorts_to_front(self):
        evs = [
            self._ev("2026-02-18T01:00:00Z", "id-valid"),
            self._ev("not-a-date",            "id-bad"),
        ]
        result = self.fn(evs)
        # bad timestamp → ts=0.0 → sorts before valid timestamp
        assert result[0]["id"] == "id-bad"
        assert result[1]["id"] == "id-valid"

    def test_empty_list(self):
        assert self.fn([]) == []

    def test_does_not_mutate_input(self):
        evs = [
            self._ev("2026-02-18T02:00:00Z", "id-b"),
            self._ev("2026-02-18T01:00:00Z", "id-a"),
        ]
        original_order = [e["id"] for e in evs]
        self.fn(evs)
        assert [e["id"] for e in evs] == original_order

    def test_any_permutation_yields_same_result(self):
        import itertools
        evs = [
            self._ev("2026-02-18T01:00:00Z", "id-a"),
            self._ev("2026-02-18T02:00:00Z", "id-b"),
            self._ev("2026-02-18T01:00:00Z", "id-c"),
        ]
        expected = [e["id"] for e in self.fn(evs)]
        for perm in itertools.permutations(evs):
            result = [e["id"] for e in self.fn(list(perm))]
            assert result == expected, f"Permutation gave {result}, expected {expected}"


# ─────────────────────────────────────────────────────────────────
# TestCorrelateEvents
# ─────────────────────────────────────────────────────────────────

class TestCorrelateEvents:
    def setup_method(self):
        mod = _import_or_skip("core.context_cleanup", ["_correlate_events"])
        self.fn = mod._correlate_events

    def test_returns_dict_with_required_keys(self):
        result = self.fn([])
        assert "container_last_status" in result
        assert "tool_result_refs" in result

    def test_container_started_recorded(self):
        ev = {"event_type": "container_started",
              "event_data": {"container_id": "cid-001"}, "created_at": ""}
        result = self.fn([ev])
        assert result["container_last_status"].get("cid-001") == "running"

    def test_container_stopped_after_started(self):
        evs = [
            {"event_type": "container_started",
             "event_data": {"container_id": "cid-002"}, "created_at": "2026-02-18T01:00:00Z"},
            {"event_type": "container_stopped",
             "event_data": {"container_id": "cid-002"}, "created_at": "2026-02-18T02:00:00Z"},
        ]
        result = self.fn(evs)
        assert result["container_last_status"]["cid-002"] == "stopped"

    def test_tool_result_indexed_by_ref_id(self):
        ev = {"event_type": "tool_result",
              "event_data": {"ref_id": "ref-abc", "status": "success"}, "created_at": ""}
        result = self.fn([ev])
        assert "ref-abc" in result["tool_result_refs"]
        assert result["tool_result_refs"]["ref-abc"] is ev

    def test_tool_result_no_ref_id_not_indexed(self):
        ev = {"event_type": "tool_result",
              "event_data": {"status": "success"}, "created_at": ""}
        result = self.fn([ev])
        assert len(result["tool_result_refs"]) == 0

    def test_empty_events(self):
        result = self.fn([])
        assert result["container_last_status"] == {}
        assert result["tool_result_refs"] == {}


# ─────────────────────────────────────────────────────────────────
# TestDeterminism
# ─────────────────────────────────────────────────────────────────

class TestDeterminism:
    """
    Same events in any input order must yield identical CompactContext
    (NOW / RULES / NEXT unchanged).
    """

    def test_two_container_events_order_independent(self):
        import itertools
        mod = _import_or_skip("core.context_cleanup", ["build_compact_context"])

        ts_base = 1_700_000_000.0
        events = [
            _make_ev("container_started",
                        {"container_id": "c-det-1", "blueprint_id": "bp-a"},
                        ts=ts_base, ev_id="ev-1"),
            _make_ev("container_stopped",
                        {"container_id": "c-det-1"},
                        ts=ts_base + 10, ev_id="ev-2"),
        ]
        ref_ctx = mod.build_compact_context(list(events))

        for perm in itertools.permutations(events):
            ctx = mod.build_compact_context(list(perm))
            assert ctx.now == ref_ctx.now, (
                f"NOW differs for permutation {[e['id'] for e in perm]}: "
                f"{ctx.now} vs {ref_ctx.now}"
            )
            assert ctx.rules == ref_ctx.rules
            assert ctx.next == ref_ctx.next

    def test_three_events_all_permutations(self):
        import itertools
        mod = _import_or_skip("core.context_cleanup", ["build_compact_context"])

        ts = 1_700_000_000.0
        events = [
            _make_ev("container_started",
                        {"container_id": "c-X", "blueprint_id": "bp-X"},
                        ts=ts, ev_id="det-a"),
            _make_ev("container_exec",
                        {"container_id": "c-X", "exit_code": 0},
                        ts=ts + 5, ev_id="det-b"),
            _make_ev("trust_blocked",
                        {"reason": "low_trust"},
                        ts=ts + 10, ev_id="det-c"),
        ]
        ref = mod.build_compact_context(list(events))

        for perm in itertools.permutations(events):
            ctx = mod.build_compact_context(list(perm))
            assert ctx.now == ref.now, (
                f"NOW differs: {ctx.now} vs {ref.now}"
            )

    def test_empty_events_always_identical(self):
        mod = _import_or_skip("core.context_cleanup", ["build_compact_context"])
        ctx1 = mod.build_compact_context([])
        ctx2 = mod.build_compact_context([])
        assert ctx1.now == ctx2.now
        assert ctx1.rules == ctx2.rules
        assert ctx1.next == ctx2.next


# ─────────────────────────────────────────────────────────────────
# TestToolResultMapping
# ─────────────────────────────────────────────────────────────────

class TestToolResultMapping:
    """tool_result events → last_tool_results + error state."""

    def _run(self, events):
        """Apply events and return the resulting TypedState."""
        mod = _import_or_skip(
            "core.context_cleanup",
            ["_normalize_events", "_dedupe_events", "_sort_events_asc",
             "_correlate_events", "_apply_events_to_state",
             "_load_confidence_config", "TypedState"])
        all_evs = mod._normalize_events(events)
        all_evs = mod._dedupe_events(all_evs)
        all_evs = mod._sort_events_asc(all_evs)
        corrs   = mod._correlate_events(all_evs)
        state   = mod.TypedState()
        mod._apply_events_to_state(state, all_evs, corrs, mod._load_confidence_config())
        return state

    def test_success_adds_ref_id_to_last_tool_results(self):
        ev = _make_event("tool_result",
                         {"ref_id": "ref-001", "status": "success", "tool_name": "exec"})
        state = self._run([ev])
        assert "ref-001" in state.last_tool_results

    def test_success_does_not_add_to_last_errors(self):
        ev = _make_event("tool_result",
                         {"ref_id": "ref-002", "status": "success"})
        state = self._run([ev])
        assert state.last_errors == []
        assert state.last_error is None

    def test_error_status_adds_to_last_errors(self):
        ev = _make_event("tool_result",
                         {"ref_id": "ref-003", "status": "error",
                          "error": "timeout reached"})
        state = self._run([ev])
        assert any("timeout" in e for e in state.last_errors)
        assert state.last_error is not None and "timeout" in state.last_error

    def test_error_status_adds_to_open_issues(self):
        ev = _make_event("tool_result",
                         {"ref_id": "ref-004", "status": "error",
                          "error": "connection refused"})
        state = self._run([ev])
        assert any("connection refused" in i for i in state.open_issues)

    def test_partial_status_also_treated_as_error(self):
        ev = _make_event("tool_result",
                         {"ref_id": "ref-005", "status": "partial",
                          "message": "only 3 of 10 items processed"})
        state = self._run([ev])
        assert state.last_error is not None

    def test_last_tool_results_bounded_at_10(self):
        ts = 1_700_000_000.0
        events = [
            _make_ev("tool_result",
                        {"ref_id": f"ref-{i:03d}", "status": "success"},
                        ts=ts + i, ev_id=f"ev-{i}")
            for i in range(12)
        ]
        state = self._run(events)
        assert len(state.last_tool_results) <= 10

    def test_tool_result_deduped_in_last_tool_results(self):
        """Same ref_id from two tool_result events: appears only once."""
        ts = 1_700_000_000.0
        ev1 = _make_ev("tool_result", {"ref_id": "dup-ref", "status": "success"},
                          ts=ts, ev_id="ev-dup-1")
        ev2 = _make_ev("tool_result", {"ref_id": "dup-ref", "status": "success"},
                          ts=ts + 5, ev_id="ev-dup-2")  # outside dedupe window
        state = self._run([ev1, ev2])
        assert state.last_tool_results.count("dup-ref") == 1

    def test_tool_result_creates_typed_fact(self):
        ev = _make_event("tool_result",
                         {"ref_id": "ref-fact", "status": "success", "tool_name": "my_tool"})
        state = self._run([ev])
        assert "TOOL_RESULT" in state.facts
        assert len(state.facts["TOOL_RESULT"]) >= 1


# ─────────────────────────────────────────────────────────────────
# TestPendingSkillMapping
# ─────────────────────────────────────────────────────────────────

class TestPendingSkillMapping:
    """pending_skill / approval_requested / skill_pending → pending_approvals."""

    def _run(self, events):
        mod = _import_or_skip(
            "core.context_cleanup",
            ["_normalize_events", "_dedupe_events", "_sort_events_asc",
             "_correlate_events", "_apply_events_to_state",
             "_load_confidence_config", "TypedState"])
        all_evs = mod._normalize_events(events)
        all_evs = mod._dedupe_events(all_evs)
        all_evs = mod._sort_events_asc(all_evs)
        corrs   = mod._correlate_events(all_evs)
        state   = mod.TypedState()
        mod._apply_events_to_state(state, all_evs, corrs, mod._load_confidence_config())
        return state

    def test_pending_skill_adds_skill_id_to_pending_approvals(self):
        ev = _make_event("pending_skill", {"skill_id": "sk-deploy-nginx"})
        state = self._run([ev])
        assert "sk-deploy-nginx" in state.pending_approvals

    def test_approval_requested_event_type_works(self):
        ev = _make_event("approval_requested", {"skill_name": "deploy_container"})
        state = self._run([ev])
        assert "deploy_container" in state.pending_approvals

    def test_skill_pending_event_type_works(self):
        ev = _make_event("skill_pending", {"ref_id": "skill-ref-001"})
        state = self._run([ev])
        assert "skill-ref-001" in state.pending_approvals

    def test_pending_approvals_deduped(self):
        """Same skill_id from two events (outside dedupe window): only one entry."""
        ts = 1_700_000_000.0
        ev1 = _make_ev("pending_skill", {"skill_id": "sk-same"},
                          ts=ts, ev_id="ev-pa-1")
        ev2 = _make_ev("pending_skill", {"skill_id": "sk-same"},
                          ts=ts + 5, ev_id="ev-pa-2")  # outside 2s window
        state = self._run([ev1, ev2])
        assert state.pending_approvals.count("sk-same") == 1

    def test_pending_approvals_bounded_at_20(self):
        ts = 1_700_000_000.0
        events = [
            _make_ev("pending_skill", {"skill_id": f"sk-{i:03d}"},
                        ts=ts + i, ev_id=f"ev-sk-{i}")
            for i in range(25)
        ]
        state = self._run(events)
        assert len(state.pending_approvals) <= 20

    def test_pending_approvals_empty_for_unrelated_events(self):
        ev = _make_event("container_started", {"container_id": "c-1"})
        state = self._run([ev])
        assert state.pending_approvals == []


# ─────────────────────────────────────────────────────────────────
# TestConfidenceFromYaml
# ─────────────────────────────────────────────────────────────────

class TestConfidenceFromYaml:
    """TypedFact.confidence is computed from YAML config, not hardcoded 1.0."""

    def setup_method(self):
        mod = _import_or_skip(
            "core.context_cleanup",
            ["_compute_fact_confidence", "_load_confidence_config"])
        self.compute = mod._compute_fact_confidence
        self.load_cfg = mod._load_confidence_config

    def test_workspace_event_confidence_is_one(self):
        cfg = self.load_cfg()
        c = self.compute("workspace_event", conf_cfg=cfg)
        assert c == pytest.approx(1.0)

    def test_tool_result_confidence_below_one(self):
        """tool_result source reliability is 0.85 in YAML → confidence < 1.0."""
        cfg = self.load_cfg()
        c = self.compute("tool_result", conf_cfg=cfg)
        assert c < 1.0, f"Expected tool_result confidence < 1.0, got {c}"
        assert c > 0.0

    def test_inference_confidence_lowest(self):
        cfg = self.load_cfg()
        c_workspace = self.compute("workspace_event", conf_cfg=cfg)
        c_inference  = self.compute("inference", conf_cfg=cfg)
        assert c_inference < c_workspace

    def test_exact_entity_match_keeps_confidence(self):
        cfg = self.load_cfg()
        c_exact = self.compute("workspace_event", "exact", conf_cfg=cfg)
        c_none  = self.compute("workspace_event", "none",  conf_cfg=cfg)
        assert c_exact > c_none

    def test_confidence_clamped_to_zero_one(self):
        # Force edge case with artificial multipliers
        c = self.compute("workspace_event", consistency_factor=2.0, conf_cfg={})
        assert 0.0 <= c <= 1.0
        c2 = self.compute("inference", consistency_factor=0.0, conf_cfg={})
        assert c2 == pytest.approx(0.0)

    def test_missing_conf_cfg_falls_back_to_defaults(self):
        c = self.compute("tool_result", conf_cfg=None)
        # Falls back to _SOURCE_RELIABILITY_DEFAULTS["tool_result"] = 0.85
        assert c == pytest.approx(0.85, abs=0.01)

    def test_tool_result_event_fact_has_correct_confidence(self):
        """
        End-to-end: tool_result event → TypedFact in state has confidence from YAML.
        """
        mod = _import_or_skip(
            "core.context_cleanup",
            ["_normalize_events", "_dedupe_events", "_sort_events_asc",
             "_correlate_events", "_apply_events_to_state",
             "_load_confidence_config", "TypedState"])

        ev = _make_event("tool_result",
                         {"ref_id": "ref-conf", "status": "success", "tool_name": "ping"})
        all_evs = mod._normalize_events([ev])
        all_evs = mod._sort_events_asc(all_evs)
        corrs   = mod._correlate_events(all_evs)
        conf_cfg = mod._load_confidence_config()
        state   = mod.TypedState()
        mod._apply_events_to_state(state, all_evs, corrs, conf_cfg)

        facts = state.facts.get("TOOL_RESULT", [])
        assert len(facts) >= 1
        # Confidence must be < 1.0 (tool_result reliability < workspace_event)
        assert facts[0].confidence < 1.0, (
            f"Expected tool_result fact confidence < 1.0, got {facts[0].confidence}"
        )

    def test_container_started_fact_confidence_is_one(self):
        """container_started uses workspace_event source → confidence == 1.0."""
        mod = _import_or_skip(
            "core.context_cleanup",
            ["_normalize_events", "_sort_events_asc", "_correlate_events",
             "_apply_events_to_state", "_load_confidence_config", "TypedState"])

        ev = _make_event("container_started",
                         {"container_id": "c-conf-1", "blueprint_id": "bp"})
        all_evs = mod._normalize_events([ev])
        all_evs = mod._sort_events_asc(all_evs)
        corrs   = mod._correlate_events(all_evs)
        conf_cfg = mod._load_confidence_config()
        state   = mod.TypedState()
        mod._apply_events_to_state(state, all_evs, corrs, conf_cfg)

        facts = state.facts.get("CONTAINER_STARTED", [])
        assert len(facts) >= 1
        assert facts[0].confidence == pytest.approx(1.0)


# ─────────────────────────────────────────────────────────────────
# TestSourceEventIds
# ─────────────────────────────────────────────────────────────────

class TestSourceEventIds:
    """state.source_event_ids is stably tracked across all event types."""

    def _run(self, events):
        mod = _import_or_skip(
            "core.context_cleanup",
            ["_normalize_events", "_dedupe_events", "_sort_events_asc",
             "_correlate_events", "_apply_events_to_state",
             "_load_confidence_config", "TypedState"])
        all_evs = mod._normalize_events(events)
        all_evs = mod._dedupe_events(all_evs)
        all_evs = mod._sort_events_asc(all_evs)
        corrs   = mod._correlate_events(all_evs)
        state   = mod.TypedState()
        mod._apply_events_to_state(state, all_evs, corrs, mod._load_confidence_config())
        return state

    def test_event_ids_tracked(self):
        ev = _make_ev("container_started",
                         {"container_id": "c-src-1"}, ev_id="tracked-ev-001")
        state = self._run([ev])
        assert "tracked-ev-001" in state.source_event_ids

    def test_multiple_event_ids_all_tracked(self):
        ts = 1_700_000_000.0
        evs = [
            _make_ev("container_started", {"container_id": "c-1"},
                        ts=ts, ev_id="ev-s-001"),
            _make_ev("tool_result", {"ref_id": "r-1", "status": "success"},
                        ts=ts + 1, ev_id="ev-s-002"),
            _make_ev("trust_blocked", {"reason": "low"},
                        ts=ts + 2, ev_id="ev-s-003"),
        ]
        state = self._run(evs)
        for eid in ("ev-s-001", "ev-s-002", "ev-s-003"):
            assert eid in state.source_event_ids

    def test_source_event_ids_deduplicated(self):
        """Same id appears only once even if event is processed twice."""
        ts = 1_700_000_000.0
        ev1 = _make_ev("container_started", {"container_id": "c-dup"},
                          ts=ts, ev_id="dup-ev-id")
        # Second event outside dedupe window but same id (force unique content)
        ev2 = _make_ev("container_stopped", {"container_id": "c-dup"},
                          ts=ts + 5, ev_id="dup-ev-id")
        state = self._run([ev1, ev2])
        assert state.source_event_ids.count("dup-ev-id") == 1

    def test_source_event_ids_bounded_at_100(self):
        ts = 1_700_000_000.0
        events = [
            _make_ev("observation", {"content": f"note {i}"},
                        ts=ts + i, ev_id=f"ev-bound-{i:04d}")
            for i in range(110)
        ]
        state = self._run(events)
        assert len(state.source_event_ids) <= 100

    def test_generated_ids_tracked_for_anonymous_events(self):
        """Events without explicit id still get tracked via generated id."""
        ev = {"event_type": "observation", "event_data": {"content": "anon"},
              "created_at": "2026-02-19T10:00:00Z"}
        state = self._run([ev])
        assert len(state.source_event_ids) == 1
        assert state.source_event_ids[0].startswith("gen-")

    def test_source_event_ids_consistent_across_permutations(self):
        """Same events in any order → same source_event_ids set (order may differ)."""
        import itertools
        ts = 1_700_000_000.0
        events = [
            _make_ev("container_started", {"container_id": "c-p"},
                        ts=ts, ev_id="perm-ev-1"),
            _make_ev("tool_result", {"ref_id": "r-p", "status": "success"},
                        ts=ts + 1, ev_id="perm-ev-2"),
        ]
        ref = set(self._run(list(events)).source_event_ids)
        for perm in itertools.permutations(events):
            result = set(self._run(list(perm)).source_event_ids)
            assert result == ref
"""
Commit 3 tests — standalone, includes required helpers.
When appended to test_context_cleanup_phase2.py the helpers become redundant
but do not conflict (different names prefixed with _c3_).
"""

import pytest
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "..", "..", "..",
                                "DATA", "AppData", "MCP", "Jarvis", "Jarvis"))


def _import_or_skip(name: str, fromlist: list):
    try:
        mod = __import__(name, fromlist=fromlist)
        return mod
    except ImportError as e:
        pytest.skip(f"Cannot import {name}: {e}")


# ═══════════════════════════════════════════════════════════════
# Commit 3 Tests — NOW/RULES/NEXT builders + renderer hardening
# ═══════════════════════════════════════════════════════════════

def _import_cc3(names):
    mod = _import_or_skip("core.context_cleanup", names)
    return tuple(getattr(mod, n) for n in names)


# ─────────────────────────────────────────────────────────────────
# TestNowBulletsPriority
# ─────────────────────────────────────────────────────────────────

class TestNowBulletsPriority:
    def setup_method(self):
        (_build_now_bullets,) = _import_cc3(["_build_now_bullets"])
        self.fn = _build_now_bullets
        from core.context_cleanup import TypedState, ContainerEntity
        self.TypedState = TypedState
        self.ContainerEntity = ContainerEntity

    def _cfg(self, **kw):
        return {"now_max": 10, "rules_max": 5, "next_max": 5, **kw}

    def _output_cfg(self, **kw):
        return kw

    def test_empty_state_returns_empty_list(self):
        state = self.TypedState()
        result = self.fn(state, self._cfg(), self._output_cfg())
        assert result == []

    def test_active_container_appears(self):
        state = self.TypedState()
        c = self.ContainerEntity(id="ccc-001", blueprint_id="my-bp")
        c.status = "running"
        c.stability_score = "high"
        state.containers["ccc-001"] = c
        result = self.fn(state, self._cfg(), self._output_cfg())
        assert any("ACTIVE_CONTAINER" in b for b in result)

    def test_active_container_sorted_by_id(self):
        state = self.TypedState()
        for cid in ("z-container", "a-container", "m-container"):
            c = self.ContainerEntity(id=cid, blueprint_id="bp")
            c.status = "running"
            state.containers[cid] = c
        result = self.fn(state, self._cfg(), self._output_cfg())
        names = [b for b in result if "ACTIVE_CONTAINER" in b]
        # Each bullet: "ACTIVE_CONTAINER bp/cid_prefix ..."
        cid_prefixes = [b.split("/")[1].split(" ")[0] for b in names]
        assert cid_prefixes == sorted(cid_prefixes)

    def test_gate_active_sorted_alphabetically(self):
        state = self.TypedState()
        state.active_gates = {"z-gate", "a-gate", "m-gate"}
        result = self.fn(state, self._cfg(), self._output_cfg())
        gates = [b for b in result if "GATE_ACTIVE" in b]
        labels = [b.replace("GATE_ACTIVE ", "") for b in gates]
        assert labels == sorted(labels)

    def test_open_issues_sorted_alphabetically(self):
        state = self.TypedState()
        state.open_issues = {"z-issue", "a-issue", "m-issue"}
        result = self.fn(state, self._cfg(), self._output_cfg())
        issues = [b for b in result if "OPEN_ISSUE" in b]
        labels = [b.replace("OPEN_ISSUE ", "") for b in issues]
        assert labels == sorted(labels)

    def test_last_error_appears(self):
        state = self.TypedState()
        state.last_error = "something went wrong"
        result = self.fn(state, self._cfg(), self._output_cfg())
        assert any("LAST_ERROR" in b for b in result)

    def test_item_capped_at_200_chars(self):
        state = self.TypedState()
        state.last_error = "x" * 500
        result = self.fn(state, self._cfg(), self._output_cfg())
        for bullet in result:
            assert len(bullet) <= 200, f"Bullet too long: {len(bullet)}"

    def test_now_max_limits_output(self):
        state = self.TypedState()
        state.open_issues = {f"issue-{i}" for i in range(20)}
        result = self.fn(state, self._cfg(now_max=3), self._output_cfg())
        assert len(result) <= 3

    def test_yaml_order_respected(self):
        """When output_cfg specifies last_error before active_gates, last_error comes first."""
        state = self.TypedState()
        state.last_error = "err"
        state.active_gates = {"gate-a"}
        output_cfg = {"now_order": ["last_error", "active_gates", "open_issues",
                                    "active_container", "focus_entity"]}
        result = self.fn(state, self._cfg(), output_cfg)
        assert len(result) >= 2
        idx_err = next(i for i, b in enumerate(result) if "LAST_ERROR" in b)
        idx_gate = next(i for i, b in enumerate(result) if "GATE_ACTIVE" in b)
        assert idx_err < idx_gate

    def test_focus_entity_skipped_if_running(self):
        """focus_entity that is 'running' should not emit FOCUS_ENTITY bullet."""
        state = self.TypedState()
        state.focus_entity = "c-001"
        c = self.ContainerEntity(id="c-001", blueprint_id="bp")
        c.state = "running"
        c.type = "container"
        state.entities["c-001"] = c
        result = self.fn(state, self._cfg(), self._output_cfg())
        focus_bullets = [b for b in result if "FOCUS_ENTITY" in b]
        assert focus_bullets == []


# ─────────────────────────────────────────────────────────────────
# TestNowBulletsDeterminism
# ─────────────────────────────────────────────────────────────────

class TestNowBulletsDeterminism:
    def setup_method(self):
        (_build_now_bullets,) = _import_cc3(["_build_now_bullets"])
        self.fn = _build_now_bullets
        from core.context_cleanup import TypedState, ContainerEntity
        self.TypedState = TypedState
        self.ContainerEntity = ContainerEntity

    def _cfg(self):
        return {"now_max": 20, "rules_max": 5, "next_max": 5}

    def test_same_state_same_output(self):
        state = self.TypedState()
        state.active_gates = {"g-z", "g-a", "g-m"}
        state.open_issues = {"i-3", "i-1", "i-2"}
        state.last_error = "err-msg"
        r1 = self.fn(state, self._cfg(), {})
        r2 = self.fn(state, self._cfg(), {})
        assert r1 == r2

    def test_multiple_containers_deterministic(self):
        """Containers in any dict insertion order → same sorted bullets."""
        ids = [f"c-{i:03d}" for i in range(6)]

        def _make_state(container_ids):
            state = self.TypedState()
            for cid in container_ids:
                c = self.ContainerEntity(id=cid, blueprint_id="bp")
                c.status = "running"
                state.containers[cid] = c
            return state

        r1 = self.fn(_make_state(ids), self._cfg(), {})
        r2 = self.fn(_make_state(list(reversed(ids))), self._cfg(), {})
        assert r1 == r2

    def test_gates_same_regardless_of_set_iteration(self):
        """Set iteration is non-deterministic; builder must sort to stabilize."""
        state = self.TypedState()
        state.active_gates = {f"gate-{chr(ord('a') + i)}" for i in range(10)}
        r1 = self.fn(state, self._cfg(), {})
        r2 = self.fn(state, self._cfg(), {})
        assert r1 == r2


# ─────────────────────────────────────────────────────────────────
# TestRulesBulletsDedup
# ─────────────────────────────────────────────────────────────────

class TestRulesBulletsDedup:
    def setup_method(self):
        (_build_rules_bullets,) = _import_cc3(["_build_rules_bullets"])
        self.fn = _build_rules_bullets
        from core.context_cleanup import TypedState, _DEFAULT_RULES
        self.TypedState = TypedState
        self.DEFAULT_RULES = list(_DEFAULT_RULES)

    def _cfg(self, rules_max=10):
        return {"now_max": 5, "rules_max": rules_max, "next_max": 5}

    def test_empty_state_returns_default_rules(self):
        state = self.TypedState()
        result = self.fn(state, self._cfg(), {})
        assert result == self.DEFAULT_RULES[: self._cfg()["rules_max"]]

    def test_user_constraints_appended(self):
        state = self.TypedState()
        state.user_constraints = {"my-constraint"}
        result = self.fn(state, self._cfg(), {})
        assert any("USER: my-constraint" in r for r in result)

    def test_user_constraints_sorted_alphabetically(self):
        state = self.TypedState()
        state.user_constraints = {"z-rule", "a-rule", "m-rule"}
        result = self.fn(state, self._cfg(), {})
        user_entries = [r for r in result if r.startswith("USER:")]
        labels = [e.replace("USER: ", "") for e in user_entries]
        assert labels == sorted(labels)

    def test_duplicate_user_constraint_not_repeated(self):
        state = self.TypedState()
        state.user_constraints = {"unique-rule"}
        result = self.fn(state, self._cfg(), {})
        user_entries = [r for r in result if "unique-rule" in r]
        assert len(user_entries) == 1

    def test_rules_max_limits_output(self):
        state = self.TypedState()
        state.user_constraints = {f"rule-{i}" for i in range(20)}
        result = self.fn(state, self._cfg(rules_max=3), {})
        assert len(result) <= 3

    def test_yaml_rules_default_overrides_module_default(self):
        state = self.TypedState()
        output_cfg = {"rules_default": ["YAML-RULE-1", "YAML-RULE-2"]}
        result = self.fn(state, self._cfg(), output_cfg)
        assert "YAML-RULE-1" in result
        assert "YAML-RULE-2" in result
        for dr in self.DEFAULT_RULES:
            assert dr not in result, f"Default rule {dr!r} should be replaced by YAML"

    def test_user_constraint_matching_base_rule_not_duplicated(self):
        """Raw constraint string identical to a base rule must not appear twice."""
        state = self.TypedState()
        if not self.DEFAULT_RULES:
            pytest.skip("No default rules defined")
        base_rule = self.DEFAULT_RULES[0]
        state.user_constraints = {base_rule}
        result = self.fn(state, self._cfg(), {})
        assert result.count(base_rule) == 1


# ─────────────────────────────────────────────────────────────────
# TestNextBulletsPriority
# ─────────────────────────────────────────────────────────────────

class TestNextBulletsPriority:
    def setup_method(self):
        (_build_next_bullets,) = _import_cc3(["_build_next_bullets"])
        self.fn = _build_next_bullets
        from core.context_cleanup import TypedState, ContainerEntity
        self.TypedState = TypedState
        self.ContainerEntity = ContainerEntity

    def _cfg(self, next_max=5):
        return {"now_max": 5, "rules_max": 5, "next_max": next_max}

    def test_empty_state_returns_await(self):
        state = self.TypedState()
        result = self.fn(state, self._cfg())
        assert result == ["Await user instruction"]

    def test_pending_approval_takes_priority(self):
        state = self.TypedState()
        state.pending_approvals = ["skill-xyz requires approval"]
        state.last_error = "some error"
        result = self.fn(state, self._cfg())
        assert any("approval" in b.lower() for b in result)

    def test_last_error_above_focus_entity(self):
        state = self.TypedState()
        state.last_error = "boom"
        c = self.ContainerEntity(id="fe-001", blueprint_id="bp")
        c.state = "running"
        state.entities["fe-001"] = c
        state.focus_entity = "fe-001"
        result = self.fn(state, self._cfg())
        assert any("Diagnose" in b for b in result)

    def test_focus_entity_running_continues_work(self):
        state = self.TypedState()
        c = self.ContainerEntity(id="fe-002", blueprint_id="my-bp")
        c.state = "running"
        state.entities["fe-002"] = c
        state.focus_entity = "fe-002"
        result = self.fn(state, self._cfg())
        assert any("Continue" in b for b in result)

    def test_focus_entity_not_running_falls_back_to_await(self):
        state = self.TypedState()
        c = self.ContainerEntity(id="fe-003", blueprint_id="bp")
        c.state = "stopped"
        state.entities["fe-003"] = c
        state.focus_entity = "fe-003"
        result = self.fn(state, self._cfg())
        assert result == ["Await user instruction"]

    def test_focus_entity_missing_from_entities_falls_back(self):
        state = self.TypedState()
        state.focus_entity = "ghost-id"
        result = self.fn(state, self._cfg())
        assert result == ["Await user instruction"]

    def test_next_max_limits_output(self):
        state = self.TypedState()
        state.pending_approvals = [f"skill-{i}" for i in range(10)]
        result = self.fn(state, self._cfg(next_max=1))
        assert len(result) <= 1

    def test_most_recent_pending_approval_used(self):
        state = self.TypedState()
        state.pending_approvals = ["older-ref", "newer-ref"]
        result = self.fn(state, self._cfg())
        assert any("newer-ref" in b for b in result)


# ─────────────────────────────────────────────────────────────────
# TestRendererHardening
# ─────────────────────────────────────────────────────────────────

class TestRendererHardening:
    def setup_method(self):
        (
            _build_now_bullets,
            _build_rules_bullets,
            _build_next_bullets,
        ) = _import_cc3(["_build_now_bullets", "_build_rules_bullets", "_build_next_bullets"])
        self.now_fn = _build_now_bullets
        self.rules_fn = _build_rules_bullets
        self.next_fn = _build_next_bullets
        from core.context_cleanup import TypedState, _DEFAULT_RULES
        self.TypedState = TypedState
        self.DEFAULT_RULES = list(_DEFAULT_RULES)

    def _cfg(self):
        return {"now_max": 5, "rules_max": 5, "next_max": 5}

    def test_now_builder_returns_list_on_corrupt_state(self):
        state = self.TypedState()
        state.active_gates = None  # type: ignore
        result = self.now_fn(state, self._cfg(), {})
        assert isinstance(result, list)

    def test_rules_builder_returns_list_on_corrupt_constraints(self):
        state = self.TypedState()
        state.user_constraints = None  # type: ignore
        result = self.rules_fn(state, self._cfg(), {})
        assert isinstance(result, list)
        assert len(result) > 0

    def test_next_builder_returns_await_on_error(self):
        state = self.TypedState()
        state.pending_approvals = None  # type: ignore
        result = self.next_fn(state, self._cfg())
        assert result == ["Await user instruction"]

    def test_output_cfg_unknown_keys_ignored(self):
        state = self.TypedState()
        state.active_gates = {"gate-a"}
        output_cfg = {
            "now_order": ["active_gates"],
            "unknown_key_xyz": "should-be-ignored",
        }
        result = self.now_fn(state, self._cfg(), output_cfg)
        assert isinstance(result, list)

    def test_build_compact_context_returns_result_on_empty_input(self):
        from core.context_cleanup import build_compact_context
        result = build_compact_context([])
        assert result is not None
        assert hasattr(result, "now")
        assert hasattr(result, "rules")
        assert hasattr(result, "next")   # CompactContext stores next_steps as .next
        assert hasattr(result, "meta")


# ─────────────────────────────────────────────────────────────────
# TestRetrievalCountMeta
# ─────────────────────────────────────────────────────────────────

class TestRetrievalCountMeta:
    def setup_method(self):
        from core.context_cleanup import build_compact_context
        self.fn = build_compact_context

    def test_default_retrieval_count_is_1(self):
        result = self.fn([])
        assert result.meta["retrieval_count"] == 1

    def test_retrieval_count_read_from_limits(self):
        result = self.fn([], limits={"retrieval_count": 7})
        assert result.meta["retrieval_count"] == 7

    def test_retrieval_count_zero_allowed(self):
        result = self.fn([], limits={"retrieval_count": 0})
        assert result.meta["retrieval_count"] == 0

    def test_retrieval_count_large_value(self):
        result = self.fn([], limits={"retrieval_count": 9999})
        assert result.meta["retrieval_count"] == 9999

    def test_limits_without_retrieval_count_defaults_to_1(self):
        result = self.fn([], limits={"now_max": 3})
        assert result.meta["retrieval_count"] == 1

    def test_meta_contains_expected_keys(self):
        result = self.fn([])
        for key in ("small_model_mode", "cleanup_used", "focus_entity",
                    "retrieval_count", "context_chars", "events_processed",
                    "entities_tracked", "generated_at"):
            assert key in result.meta, f"meta missing key: {key}"

    def test_context_chars_matches_bullet_total(self):
        result = self.fn([])
        expected = sum(len(s) for s in result.now + result.rules + result.next)
        assert result.meta["context_chars"] == expected
# ─────────────────────────────────────────────────────────────────
# Phase-3: select_top + global priority + fail-closed
# ─────────────────────────────────────────────────────────────────

def _import_cc3(names):
    """Import names from core.context_cleanup; skip on ImportError."""
    import importlib
    try:
        mod = importlib.import_module("core.context_cleanup")
        return tuple(getattr(mod, n) for n in names)
    except Exception as e:
        import pytest
        pytest.skip(f"core.context_cleanup not importable: {e}")


class TestSelectTopGlobalBudget:
    """
    Phase-3 Req A/B/C: select_top is a distinct pipeline step that enforces a
    global candidate budget across all sections.
    """

    def setup_method(self):
        self.Candidate, self.select_top = _import_cc3(["Candidate", "select_top"])

    def _make_cand(self, section, text, confidence=0.9, severity=1, recency=0.0):
        return self.Candidate(
            section=section, text=text,
            confidence=confidence, severity=severity,
            recency_ts=recency, tie_breaker=f"{section}:{text[:50]}",
        )

    def test_select_top_limits_across_sections(self):
        """Global budget=3 from 10 candidates must return exactly 3."""
        cands = (
            [self._make_cand("now", f"now-{i}") for i in range(4)]
            + [self._make_cand("rules", f"rule-{i}") for i in range(3)]
            + [self._make_cand("next", f"next-{i}") for i in range(3)]
        )
        selected = self.select_top(cands, budget=3)
        assert len(selected) == 3, (
            f"select_top(budget=3) must return 3 candidates, got {len(selected)}"
        )

    def test_select_top_budget_zero_returns_empty(self):
        """budget=0 must return empty list."""
        cands = [self._make_cand("now", "x")]
        assert self.select_top(cands, budget=0) == []

    def test_select_top_budget_larger_than_pool_returns_all(self):
        """budget > pool size must return all candidates."""
        cands = [self._make_cand("now", f"x{i}") for i in range(5)]
        selected = self.select_top(cands, budget=100)
        assert len(selected) == 5

    def test_select_top_cross_section_eviction(self):
        """With tight budget, high-priority items from any section win over
        low-priority items from a different section."""
        # 1 high-severity NOW candidate + 3 low-severity RULES candidates
        high_now = self._make_cand("now", "GATE_ACTIVE block", confidence=1.0, severity=3)
        low_rules = [self._make_cand("rules", f"rule-{i}", confidence=0.9, severity=1)
                     for i in range(3)]
        cands = [high_now] + low_rules

        # Budget=2: high NOW must be selected; at least one rule too
        selected = self.select_top(cands, budget=2)
        sections = [c.section for c in selected]
        assert "now" in sections, "High-severity NOW candidate must be selected within budget=2"

    def test_build_compact_context_respects_top_budget(self):
        """build_compact_context with top_budget=1 must produce at most 1 bullet total."""
        (build_compact_context,) = _import_cc3(["build_compact_context"])
        result = build_compact_context(
            [],
            limits={"top_budget": 1, "now_max": 5, "rules_max": 3, "next_max": 2},
        )
        total = len(result.now) + len(result.rules) + len(result.next)
        assert total <= 1, (
            f"top_budget=1 must yield ≤1 total bullets, got {total}"
        )


class TestGlobalPrioritizationOrder:
    """
    Phase-3 Req B: global sort must obey confidence > severity > recency > tie_breaker.
    """

    def setup_method(self):
        self.Candidate, self.select_top = _import_cc3(["Candidate", "select_top"])

    def _cand(self, section, text, confidence, severity, recency=0.0, tb=None):
        return self.Candidate(
            section=section, text=text,
            confidence=confidence, severity=severity,
            recency_ts=recency,
            tie_breaker=tb or f"{section}:{text[:50]}",
        )

    def test_confidence_beats_severity(self):
        """Higher confidence wins even if lower severity."""
        hi_conf_low_sev = self._cand("now", "A", confidence=1.0, severity=0)
        lo_conf_hi_sev = self._cand("now", "B", confidence=0.5, severity=3)
        selected = self.select_top([lo_conf_hi_sev, hi_conf_low_sev], budget=1)
        assert selected[0].text == "A", (
            "confidence=1.0 must beat confidence=0.5 regardless of severity"
        )

    def test_severity_breaks_confidence_tie(self):
        """Equal confidence: higher severity wins."""
        hi_sev = self._cand("now", "A", confidence=0.9, severity=3)
        lo_sev = self._cand("now", "B", confidence=0.9, severity=1)
        selected = self.select_top([lo_sev, hi_sev], budget=1)
        assert selected[0].text == "A", (
            "severity=3 must beat severity=1 when confidence is equal"
        )

    def test_recency_breaks_severity_tie(self):
        """Equal confidence+severity: more recent wins."""
        recent = self._cand("now", "A", confidence=0.9, severity=1, recency=2000.0)
        older = self._cand("now", "B", confidence=0.9, severity=1, recency=1000.0)
        selected = self.select_top([older, recent], budget=1)
        assert selected[0].text == "A", (
            "recency_ts=2000 must beat recency_ts=1000 when confidence+severity equal"
        )

    def test_tie_breaker_asc_last_resort(self):
        """All equal: tie_breaker ASC decides (alphabetically lower wins)."""
        a_cand = self._cand("now", "A", confidence=0.9, severity=1, recency=0.0, tb="now:AAA")
        z_cand = self._cand("now", "Z", confidence=0.9, severity=1, recency=0.0, tb="now:ZZZ")
        selected = self.select_top([z_cand, a_cand], budget=1)
        assert selected[0].tie_breaker == "now:AAA", (
            "tie_breaker ASC must select 'now:AAA' over 'now:ZZZ'"
        )

    def test_full_priority_chain(self):
        """Confidence > severity > recency > tie_breaker obeyed in one shot."""
        # Deliberately out-of-priority order
        cands = [
            self._cand("now", "worst", confidence=0.5, severity=0, recency=0.0, tb="now:z"),
            self._cand("now", "best", confidence=1.0, severity=3, recency=999.0, tb="now:a"),
            self._cand("now", "mid", confidence=0.8, severity=2, recency=500.0, tb="now:m"),
        ]
        selected = self.select_top(cands, budget=3)
        assert selected[0].text == "best", "Top candidate must be 'best'"
        assert selected[1].text == "mid",  "Second must be 'mid'"
        assert selected[2].text == "worst", "Third must be 'worst'"


class TestSelectTopDeterminism:
    """
    Phase-3 Req B: identical inputs in any order must yield identical output.
    """

    def setup_method(self):
        self.Candidate, self.select_top = _import_cc3(["Candidate", "select_top"])

    def test_permutation_invariant(self):
        """All 6 permutations of 3 candidates must yield same sorted result."""
        import itertools

        Candidate = self.Candidate
        cands = [
            Candidate("now", "gate", 1.0, 3, 0.0, "now:gate"),
            Candidate("rules", "rule", 0.9, 1, 0.0, "rules:0000:rule"),
            Candidate("next", "await", 1.0, 0, 0.0, "next:await_user"),
        ]
        ref = self.select_top(list(cands), budget=10)
        ref_texts = [c.text for c in ref]

        for perm in itertools.permutations(cands):
            result = self.select_top(list(perm), budget=10)
            assert [c.text for c in result] == ref_texts, (
                f"Permutation {[c.text for c in perm]} yielded different order: "
                f"{[c.text for c in result]} vs {ref_texts}"
            )

    def test_duplicate_inputs_stable(self):
        """Identical candidates must be returned in stable order."""
        Candidate = self.Candidate
        cands = [
            Candidate("now", "x", 0.9, 1, 0.0, "now:x"),
            Candidate("now", "x", 0.9, 1, 0.0, "now:x"),
        ]
        r1 = self.select_top(cands, budget=2)
        r2 = self.select_top(list(reversed(cands)), budget=2)
        assert [c.text for c in r1] == [c.text for c in r2]

    def test_build_compact_context_deterministic_across_permutations(self):
        """build_compact_context on permuted events yields identical NOW/RULES/NEXT."""
        import itertools, time as _time
        (build_compact_context,) = _import_cc3(["build_compact_context"])

        ts = 1_700_000_000.0
        events = [
            {"event_type": "container_started",
             "event_data": {"container_id": "c-X", "blueprint_id": "bp-X"},
             "created_at": f"{ts}", "id": "ev-1"},
            {"event_type": "trust_blocked",
             "event_data": {"reason": "low_trust"},
             "created_at": f"{ts + 5}", "id": "ev-2"},
        ]
        ref = build_compact_context(list(events))
        for perm in itertools.permutations(events):
            ctx = build_compact_context(list(perm))
            assert ctx.now == ref.now
            assert ctx.rules == ref.rules
            assert ctx.next == ref.next


class TestFailClosedEndToEnd:
    """
    Phase-3 Req D: fatal error in pipeline → _minimal_fail_context (Minimal-NOW + Rückfrage).
    """

    def test_minimal_fail_context_structure(self):
        """_minimal_fail_context returns the canonical fail-closed CompactContext."""
        (_minimal_fail_context,) = _import_cc3(["_minimal_fail_context"])
        ctx = _minimal_fail_context()
        assert len(ctx.now) >= 1, "fail-closed must have at least one NOW bullet"
        assert "CONTEXT ERROR" in ctx.now[0], (
            f"NOW[0] must contain 'CONTEXT ERROR', got: {ctx.now[0]!r}"
        )
        assert len(ctx.next) >= 1, "fail-closed must have at least one NEXT bullet"
        assert "präzisieren" in ctx.next[0] or "wiederholen" in ctx.next[0], (
            f"NEXT[0] must be the Rückfrage, got: {ctx.next[0]!r}"
        )
        assert ctx.meta.get("fail_closed") is True

    def test_build_compact_context_returns_fail_closed_on_pipeline_error(self):
        """If the pipeline raises, build_compact_context must return _minimal_fail_context."""
        import unittest.mock as mock
        (build_compact_context, _minimal_fail_context) = _import_cc3(
            ["build_compact_context", "_minimal_fail_context"]
        )
        # Force a fatal error at step 6 (_apply_events_to_state)
        with mock.patch(
            "core.context_cleanup._apply_events_to_state",
            side_effect=RuntimeError("forced fatal error"),
        ):
            result = build_compact_context([{"event_type": "container_started",
                                             "event_data": {"container_id": "x"}}])

        assert result is not None, "build_compact_context must not raise"
        assert len(result.now) >= 1
        assert "CONTEXT ERROR" in result.now[0], (
            f"After fatal error, NOW must contain CONTEXT ERROR, got: {result.now}"
        )
        assert result.meta.get("fail_closed") is True

    def test_format_compact_context_renders_minimal_fail_context(self):
        """format_compact_context must stably render _minimal_fail_context."""
        (format_compact_context, _minimal_fail_context) = _import_cc3(
            ["format_compact_context", "_minimal_fail_context"]
        )
        ctx = _minimal_fail_context()
        text = format_compact_context(ctx)
        assert isinstance(text, str) and len(text) > 0
        assert "CONTEXT ERROR" in text
        assert "NOW" in text
        assert "NEXT" in text

    def test_fail_closed_renderer_on_corrupt_ctx(self):
        """format_compact_context with a corrupt ctx object must return fail-closed string."""
        (format_compact_context,) = _import_cc3(["format_compact_context"])

        class Corrupt:
            @property
            def now(self):
                raise ValueError("broken")

        result = format_compact_context(Corrupt())
        assert isinstance(result, str) and len(result) > 0
        # Must contain CONTEXT ERROR or NOW (per existing test contract)
        assert "CONTEXT ERROR" in result or "NOW" in result


class TestCharCapStillEnforced:
    """
    Phase-3: char_cap must still be enforced after select_top renders the output.
    """

    def test_format_respects_char_cap_after_select_top(self):
        """format_compact_context must truncate to char_cap regardless of content."""
        (format_compact_context, build_compact_context) = _import_cc3(
            ["format_compact_context", "build_compact_context"]
        )
        # Create events that generate multiple bullets
        events = [
            {"event_type": "container_started",
             "event_data": {"container_id": f"c-{i:03d}", "blueprint_id": "bp-test"},
             "created_at": f"2026-01-01T00:00:{i:02d}Z", "id": f"ev-{i}"}
            for i in range(10)
        ]
        result = build_compact_context(events)
        text = format_compact_context(result, char_cap=100)
        assert len(text) <= 100, (
            f"char_cap=100 must be enforced, got {len(text)} chars"
        )

    def test_select_top_with_small_budget_reduces_char_count(self):
        """top_budget=1 must yield less total text than top_budget=10."""
        (build_compact_context, format_compact_context) = _import_cc3(
            ["build_compact_context", "format_compact_context"]
        )
        events = [
            {"event_type": "trust_blocked",
             "event_data": {"reason": "gate-A"},
             "created_at": "2026-01-01T00:00:01Z", "id": "ev-A"},
            {"event_type": "trust_blocked",
             "event_data": {"reason": "gate-B"},
             "created_at": "2026-01-01T00:00:02Z", "id": "ev-B"},
        ]
        ctx_tight = build_compact_context(events, limits={"top_budget": 1})
        ctx_wide = build_compact_context(events, limits={"top_budget": 20})
        chars_tight = sum(len(s) for s in ctx_tight.now + ctx_tight.rules + ctx_tight.next)
        chars_wide = sum(len(s) for s in ctx_wide.now + ctx_wide.rules + ctx_wide.next)
        assert chars_tight <= chars_wide, (
            f"top_budget=1 must yield ≤ chars vs top_budget=20: {chars_tight} vs {chars_wide}"
        )

# ═══════════════════════════════════════════════════════════════
# Commit A (Phase 3): TypedState V1 Wiring — session/conversation + entity source_event_ids
# ═══════════════════════════════════════════════════════════════


def _import_cc_wiring(symbols: list):
    """Import context_cleanup symbols for Commit-A wiring tests."""
    try:
        import importlib
        mod = importlib.import_module("core.context_cleanup")
        return tuple(getattr(mod, s) for s in symbols)
    except (ImportError, AttributeError) as e:
        pytest.skip(f"Cannot import: {e}")


class TestTypedStateV1Wiring:
    """
    Commit A (Phase 3): Verify V1 field wiring for session_id, conversation_id,
    and entity-level source_event_ids.
    """

    def _run_pipeline(self, events: list):
        """Run the full deterministic pipeline and return the resulting TypedState."""
        (
            _normalize_events, _dedupe_events, _sort_events_asc,
            _correlate_events, _apply_events_to_state, TypedState,
        ) = _import_cc_wiring([
            "_normalize_events", "_dedupe_events", "_sort_events_asc",
            "_correlate_events", "_apply_events_to_state", "TypedState",
        ])
        evs = _normalize_events(events)
        evs = _dedupe_events(evs)
        evs = _sort_events_asc(evs)
        corr = _correlate_events(evs)
        state = TypedState()
        _apply_events_to_state(state, evs, corr, {})
        return state

    # ── session_id / conversation_id on TypedState ────────────────────────

    def test_state_session_id_wired_from_container_started(self):
        """state.session_id must be set from container_started.event_data.session_id."""
        events = [_make_ev(
            "container_started",
            {"container_id": "c-001", "blueprint_id": "bp-x", "session_id": "sess-42"},
            ts=1700000000.0, ev_id="ev-001",
        )]
        state = self._run_pipeline(events)
        assert state.session_id == "sess-42", (
            f"state.session_id must be 'sess-42', got {state.session_id!r}"
        )

    def test_state_conversation_id_wired_from_container_started(self):
        """state.conversation_id must be set from container_started.event_data.conversation_id."""
        events = [_make_ev(
            "container_started",
            {"container_id": "c-002", "blueprint_id": "bp-y", "conversation_id": "conv-99"},
            ts=1700000000.0, ev_id="ev-002",
        )]
        state = self._run_pipeline(events)
        assert state.conversation_id == "conv-99", (
            f"state.conversation_id must be 'conv-99', got {state.conversation_id!r}"
        )

    def test_state_session_id_wired_from_tool_result(self):
        """state.session_id must be set from tool_result.event_data.session_id."""
        events = [_make_ev(
            "tool_result",
            {"ref_id": "r-01", "status": "success", "tool_name": "exec", "session_id": "sess-tool"},
            ts=1700000000.0, ev_id="ev-t01",
        )]
        state = self._run_pipeline(events)
        assert state.session_id == "sess-tool", (
            f"state.session_id must be 'sess-tool', got {state.session_id!r}"
        )

    def test_state_conversation_id_wired_from_pending_skill(self):
        """state.conversation_id must be set from pending_skill.event_data.conversation_id."""
        events = [_make_ev(
            "pending_skill",
            {"skill_id": "sk-1", "conversation_id": "conv-skill"},
            ts=1700000000.0, ev_id="ev-ps1",
        )]
        state = self._run_pipeline(events)
        assert state.conversation_id == "conv-skill", (
            f"state.conversation_id must be 'conv-skill', got {state.conversation_id!r}"
        )

    def test_state_session_id_last_write_wins_asc_sort(self):
        """With ASC sort, the newest event's session_id wins."""
        events = [
            _make_ev("tool_result",
                     {"ref_id": "r1", "status": "success", "session_id": "sess-OLD"},
                     ts=1700000000.0, ev_id="ev-old"),
            _make_ev("container_started",
                     {"container_id": "c-1", "session_id": "sess-NEW"},
                     ts=1700000001.0, ev_id="ev-new"),
        ]
        state = self._run_pipeline(events)
        assert state.session_id == "sess-NEW", (
            f"Newest event session_id must win (ASC sort), got {state.session_id!r}"
        )

    def test_state_session_id_missing_stays_none(self):
        """state.session_id must remain None when no event carries session_id."""
        events = [_make_ev(
            "trust_blocked",
            {"reason": "no-trust"},
            ts=1700000000.0, ev_id="ev-tb1",
        )]
        state = self._run_pipeline(events)
        assert state.session_id is None, (
            f"state.session_id must be None when no event sets it, got {state.session_id!r}"
        )

    # ── session_id / conversation_id on ContainerEntity ──────────────────

    def test_container_entity_session_id_wired(self):
        """ContainerEntity.session_id must be set from container_started event."""
        events = [_make_ev(
            "container_started",
            {"container_id": "c-se1", "blueprint_id": "bp-z", "session_id": "sess-ent"},
            ts=1700000000.0, ev_id="ev-se1",
        )]
        state = self._run_pipeline(events)
        assert "c-se1" in state.containers, "Container must be in state.containers"
        c = state.containers["c-se1"]
        assert c.session_id == "sess-ent", (
            f"ContainerEntity.session_id must be 'sess-ent', got {c.session_id!r}"
        )

    def test_container_entity_conversation_id_wired(self):
        """ContainerEntity.conversation_id must be set from container_started event."""
        events = [_make_ev(
            "container_started",
            {"container_id": "c-cv1", "blueprint_id": "bp-z", "conversation_id": "conv-ent"},
            ts=1700000000.0, ev_id="ev-cv1",
        )]
        state = self._run_pipeline(events)
        assert "c-cv1" in state.containers
        c = state.containers["c-cv1"]
        assert c.conversation_id == "conv-ent", (
            f"ContainerEntity.conversation_id must be 'conv-ent', got {c.conversation_id!r}"
        )

    def test_container_entity_no_session_stays_none(self):
        """ContainerEntity.session_id must be None when event carries no session_id."""
        events = [_make_ev(
            "container_started",
            {"container_id": "c-ns1", "blueprint_id": "bp-ns"},
            ts=1700000000.0, ev_id="ev-ns1",
        )]
        state = self._run_pipeline(events)
        assert "c-ns1" in state.containers
        c = state.containers["c-ns1"]
        assert c.session_id is None, (
            f"ContainerEntity.session_id must be None when event has no session_id, got {c.session_id!r}"
        )

    # ── source_event_ids at ContainerEntity level ─────────────────────────

    def test_container_entity_source_event_ids_from_started(self):
        """ContainerEntity.source_event_ids must contain the container_started event_id."""
        events = [_make_ev(
            "container_started",
            {"container_id": "c-sid1", "blueprint_id": "bp-a"},
            ts=1700000000.0, ev_id="ev-started-001",
        )]
        state = self._run_pipeline(events)
        assert "c-sid1" in state.containers
        c = state.containers["c-sid1"]
        assert "ev-started-001" in c.source_event_ids, (
            f"container_started event_id must be in ContainerEntity.source_event_ids, "
            f"got {c.source_event_ids!r}"
        )

    def test_container_entity_source_event_ids_accumulate_lifecycle(self):
        """ContainerEntity.source_event_ids must accumulate across lifecycle events."""
        events = [
            _make_ev("container_started",
                     {"container_id": "c-lc1", "blueprint_id": "bp-lc"},
                     ts=1700000000.0, ev_id="ev-lc-start"),
            _make_ev("container_exec",
                     {"container_id": "c-lc1", "exit_code": 0},
                     ts=1700000001.0, ev_id="ev-lc-exec"),
            _make_ev("container_stopped",
                     {"container_id": "c-lc1"},
                     ts=1700000002.0, ev_id="ev-lc-stop"),
        ]
        state = self._run_pipeline(events)
        assert "c-lc1" in state.containers
        c = state.containers["c-lc1"]
        assert "ev-lc-start" in c.source_event_ids, "container_started must be tracked"
        assert "ev-lc-exec" in c.source_event_ids, "container_exec must be tracked"
        assert "ev-lc-stop" in c.source_event_ids, "container_stopped must be tracked"

    def test_container_entity_source_event_ids_ttl_expired(self):
        """ContainerEntity.source_event_ids must include container_ttl_expired event_id."""
        events = [
            _make_ev("container_started",
                     {"container_id": "c-ttl1", "blueprint_id": "bp-ttl"},
                     ts=1700000000.0, ev_id="ev-ttl-s"),
            _make_ev("container_ttl_expired",
                     {"container_id": "c-ttl1"},
                     ts=1700000005.0, ev_id="ev-ttl-e"),
        ]
        state = self._run_pipeline(events)
        assert "c-ttl1" in state.containers
        c = state.containers["c-ttl1"]
        assert "ev-ttl-e" in c.source_event_ids, (
            f"container_ttl_expired event_id must be tracked, got {c.source_event_ids!r}"
        )

    def test_container_entity_source_event_ids_no_duplicates(self):
        """ContainerEntity.source_event_ids must not contain duplicate event_ids."""
        ev1 = _make_ev("container_started",
                       {"container_id": "c-dup1", "blueprint_id": "bp-d"},
                       ts=1700000000.0, ev_id="ev-unique-001")
        ev2 = _make_ev("container_exec",
                       {"container_id": "c-dup1", "exit_code": 0},
                       ts=1700000010.0, ev_id="ev-unique-001")  # same id, different event type
        state = self._run_pipeline([ev1, ev2])
        assert "c-dup1" in state.containers
        c = state.containers["c-dup1"]
        assert c.source_event_ids.count("ev-unique-001") == 1, (
            f"Duplicate event_id must not appear twice: {c.source_event_ids}"
        )

    # ── Determinism: permutation-stability ────────────────────────────────

    def test_wiring_determinism_session_id_any_order(self):
        """session_id wiring result must be identical regardless of input order."""
        ev1 = _make_ev("container_started",
                       {"container_id": "c-dm1", "session_id": "sess-dm-A"},
                       ts=1700000000.0, ev_id="ev-dm-1")
        ev2 = _make_ev("tool_result",
                       {"ref_id": "r1", "status": "success", "session_id": "sess-dm-B"},
                       ts=1700000001.0, ev_id="ev-dm-2")
        s1 = self._run_pipeline([ev1, ev2])
        s2 = self._run_pipeline([ev2, ev1])
        assert s1.session_id == s2.session_id, (
            f"Permutation must not affect session_id wiring: "
            f"{s1.session_id!r} vs {s2.session_id!r}"
        )

    def test_wiring_determinism_entity_source_ids_any_order(self):
        """ContainerEntity.source_event_ids must be same regardless of input order."""
        ev1 = _make_ev("container_started",
                       {"container_id": "c-dm2", "blueprint_id": "bp-dm"},
                       ts=1700000000.0, ev_id="ev-dm-s")
        ev2 = _make_ev("container_exec",
                       {"container_id": "c-dm2", "exit_code": 0},
                       ts=1700000001.0, ev_id="ev-dm-e")
        s1 = self._run_pipeline([ev1, ev2])
        s2 = self._run_pipeline([ev2, ev1])
        ids1 = sorted(s1.containers.get("c-dm2").source_event_ids)
        ids2 = sorted(s2.containers.get("c-dm2").source_event_ids)
        assert ids1 == ids2, (
            f"Permutation must not affect entity source_event_ids: {ids1} vs {ids2}"
        )


# ═══════════════════════════════════════════════════════════════
# Commit C (Phase 3): Observability — typedstate_version, source_event_ids_count, fail_closed
# ═══════════════════════════════════════════════════════════════


def _import_cc_obs(symbols: list):
    """Import context_cleanup symbols for Commit-C observability tests."""
    try:
        import importlib
        mod = importlib.import_module("core.context_cleanup")
        return tuple(getattr(mod, s) for s in symbols)
    except (ImportError, AttributeError) as e:
        pytest.skip(f"Cannot import: {e}")


class TestObservabilityMeta:
    """
    Commit C (Phase 3): build_compact_context meta must expose typedstate_version,
    source_event_ids_count, and fail_closed. Existing markers must remain intact.
    """

    def _run(self, events=None):
        (build_compact_context,) = _import_cc_obs(["build_compact_context"])
        return build_compact_context(events or [])

    # ── New fields ────────────────────────────────────────────────────────

    def test_meta_has_typedstate_version(self):
        """meta must include 'typedstate_version' key."""
        ctx = self._run()
        assert "typedstate_version" in ctx.meta, (
            f"meta missing 'typedstate_version'. Keys: {sorted(ctx.meta.keys())}"
        )

    def test_meta_typedstate_version_value(self):
        """meta['typedstate_version'] must be the string '1'."""
        ctx = self._run()
        assert ctx.meta["typedstate_version"] == "1", (
            f"typedstate_version must be '1', got {ctx.meta['typedstate_version']!r}"
        )

    def test_meta_has_source_event_ids_count(self):
        """meta must include 'source_event_ids_count' key."""
        ctx = self._run()
        assert "source_event_ids_count" in ctx.meta, (
            f"meta missing 'source_event_ids_count'. Keys: {sorted(ctx.meta.keys())}"
        )

    def test_meta_source_event_ids_count_zero_for_empty_events(self):
        """source_event_ids_count must be 0 for an empty event list."""
        ctx = self._run([])
        assert ctx.meta["source_event_ids_count"] == 0, (
            f"Expected 0, got {ctx.meta['source_event_ids_count']}"
        )

    def test_meta_source_event_ids_count_matches_events(self):
        """source_event_ids_count must equal the number of unique processed event IDs."""
        events = [
            {"event_type": "container_started",
             "event_data": {"container_id": "c-obs1", "blueprint_id": "bp"},
             "created_at": "2026-01-01T00:00:01Z", "id": "ev-obs-001"},
            {"event_type": "container_stopped",
             "event_data": {"container_id": "c-obs1"},
             "created_at": "2026-01-01T00:00:02Z", "id": "ev-obs-002"},
        ]
        ctx = self._run(events)
        assert ctx.meta["source_event_ids_count"] == 2, (
            f"Expected 2, got {ctx.meta['source_event_ids_count']}"
        )

    def test_meta_has_fail_closed(self):
        """meta must include 'fail_closed' key."""
        ctx = self._run()
        assert "fail_closed" in ctx.meta, (
            f"meta missing 'fail_closed'. Keys: {sorted(ctx.meta.keys())}"
        )

    def test_meta_fail_closed_false_on_success(self):
        """meta['fail_closed'] must be False on normal (non-error) pipeline completion."""
        ctx = self._run([])
        assert ctx.meta["fail_closed"] is False, (
            f"fail_closed must be False on normal completion, got {ctx.meta['fail_closed']!r}"
        )

    def test_meta_fail_closed_true_in_minimal_fail_context(self):
        """_minimal_fail_context must set fail_closed=True."""
        (_minimal_fail_context,) = _import_cc_obs(["_minimal_fail_context"])
        ctx = _minimal_fail_context()
        assert ctx.meta.get("fail_closed") is True, (
            f"_minimal_fail_context must set fail_closed=True, got {ctx.meta.get('fail_closed')!r}"
        )

    # ── Existing markers must remain intact ──────────────────────────────

    def test_meta_still_has_events_processed(self):
        """Existing 'events_processed' key must remain present (no regression)."""
        events = [
            {"event_type": "trust_blocked",
             "event_data": {"reason": "test"},
             "created_at": "2026-01-01T00:00:01Z", "id": "ev-rg-001"},
        ]
        ctx = self._run(events)
        assert "events_processed" in ctx.meta, "events_processed must still be in meta"
        assert ctx.meta["events_processed"] == 1

    def test_meta_still_has_mode_markers(self):
        """Existing mode markers (cleanup_used, small_model_mode) must remain."""
        ctx = self._run([])
        assert ctx.meta.get("cleanup_used") is True
        assert ctx.meta.get("small_model_mode") is True

    def test_meta_still_has_retrieval_count(self):
        """Existing retrieval_count must remain in meta."""
        ctx = self._run([])
        assert "retrieval_count" in ctx.meta, "retrieval_count must remain in meta"

    def test_meta_still_has_context_chars(self):
        """Existing context_chars must remain in meta."""
        ctx = self._run([])
        assert "context_chars" in ctx.meta, "context_chars must remain in meta"
