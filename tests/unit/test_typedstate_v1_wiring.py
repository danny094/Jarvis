"""
tests/unit/test_typedstate_v1_wiring.py — TypedState V1 Commit 4: Shadow/Active Wiring

Tests for:
  P4-A: _log_typedstate_diff — correct +/- NOW-bullet computation
  P4-B: format_typedstate_v1 — extends NOW with v1_extra_now, respects now_max
  P4-C: build_compact_context meta — v1_extra_now / v1_last_errors / v1_last_tool_results
  P4-D: build_small_model_context — mode=off/shadow/active branch selection
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_event(event_type: str, event_data: dict | None = None,
                event_id: str = "ev1", created_at: str = "2026-01-01T10:00:00Z") -> dict:
    return {
        "id": event_id,
        "event_type": event_type,
        "event_data": event_data or {},
        "created_at": created_at,
    }


def _import_cleanup():
    from core.context_cleanup import (
        build_compact_context,
        format_compact_context,
        format_typedstate_v1,
        _log_typedstate_diff,
        CompactContext,
    )
    return build_compact_context, format_compact_context, format_typedstate_v1, \
           _log_typedstate_diff, CompactContext


# ============================================================================
# P4-A: _log_typedstate_diff
# ============================================================================

class TestLogTypedstateDiff(unittest.TestCase):
    """_log_typedstate_diff must compute correct +/- bullet sets and log them."""

    def setUp(self):
        _, _, _, self._fn, _ = _import_cleanup()

    def test_identical_lists_log_empty_diff(self):
        """Same legacy and v1 NOW → +:[] -:[]"""
        with patch("core.context_cleanup.log_info") as mock_log:
            self._fn(["ACTIVE_CONTAINER x"], ["ACTIVE_CONTAINER x"])
        logged = " ".join(str(a) for c in mock_log.call_args_list for a in c[0])
        self.assertIn("[TypedState-DIFF]", logged)
        self.assertIn("+NOW-bullets: []", logged)
        self.assertIn("-NOW-bullets: []", logged)

    def test_v1_has_extra_bullet(self):
        """+NOW contains the bullet V1 adds; -NOW is empty."""
        with patch("core.context_cleanup.log_info") as mock_log:
            self._fn(["ACTIVE_CONTAINER x"], ["ACTIVE_CONTAINER x", "V1_TOOL: ref123"])
        logged = " ".join(str(a) for c in mock_log.call_args_list for a in c[0])
        self.assertIn("V1_TOOL: ref123", logged)
        self.assertIn("-NOW-bullets: []", logged)

    def test_legacy_has_bullet_not_in_v1(self):
        """-NOW contains bullet only in legacy; +NOW is empty."""
        with patch("core.context_cleanup.log_info") as mock_log:
            self._fn(["LEGACY_ONLY bullet"], ["OTHER bullet"])
        logged = " ".join(str(a) for c in mock_log.call_args_list for a in c[0])
        self.assertIn("LEGACY_ONLY bullet", logged)
        self.assertIn("OTHER bullet", logged)

    def test_both_sides_differ(self):
        """Asymmetric diff: each side has unique bullets."""
        with patch("core.context_cleanup.log_info") as mock_log:
            self._fn(["A", "B"], ["B", "C"])
        logged = " ".join(str(a) for c in mock_log.call_args_list for a in c[0])
        self.assertIn("[TypedState-DIFF]", logged)
        self.assertIn("C", logged)   # + side
        self.assertIn("A", logged)   # - side

    def test_empty_both(self):
        """Empty lists → +:[] -:[]"""
        with patch("core.context_cleanup.log_info") as mock_log:
            self._fn([], [])
        logged = " ".join(str(a) for c in mock_log.call_args_list for a in c[0])
        self.assertIn("+NOW-bullets: []", logged)
        self.assertIn("-NOW-bullets: []", logged)

    def test_never_raises_on_bad_input(self):
        """Non-list inputs must not raise — fail-safe."""
        try:
            self._fn(None, None)  # type: ignore
        except Exception as exc:
            self.fail(f"_log_typedstate_diff raised on bad input: {exc}")

    def test_format_marker_in_log(self):
        """Log message must start with [TypedState-DIFF] marker."""
        with patch("core.context_cleanup.log_info") as mock_log:
            self._fn([], ["V1_TOOL: xyz"])
        found = any(
            "[TypedState-DIFF]" in str(a)
            for c in mock_log.call_args_list
            for a in c[0]
        )
        self.assertTrue(found, "Expected [TypedState-DIFF] marker in log")


# ============================================================================
# P4-B: format_typedstate_v1
# ============================================================================

class TestFormatTypedstateV1(unittest.TestCase):
    """format_typedstate_v1 must extend NOW with v1_extra_now, respect now_max."""

    def setUp(self):
        _, self._legacy_fmt, self._v1_fmt, _, self._CC = _import_cleanup()

    def _ctx(self, now=None, rules=None, next_=None, meta=None):
        return self._CC(
            now=now or [],
            rules=rules or [],
            next_steps=next_ or [],
            meta=meta or {},
        )

    def test_no_extras_identical_to_legacy(self):
        """When v1_extra_now is empty, V1 output == legacy output."""
        ctx = self._ctx(
            now=["ACTIVE_CONTAINER bp/abc stability=high"],
            rules=["No freestyle"],
            next_=["Await user instruction"],
            meta={"v1_extra_now": []},
        )
        legacy = self._legacy_fmt(ctx)
        v1 = self._v1_fmt(ctx)
        self.assertEqual(legacy, v1)

    def test_extras_appended_to_now(self):
        """V1 extras appear in the NOW section of the output."""
        ctx = self._ctx(
            now=["ACTIVE_CONTAINER bp/abc stability=high"],
            rules=["No freestyle"],
            next_=["Await user instruction"],
            meta={"v1_extra_now": ["V1_TOOL: run_script"]},
        )
        v1 = self._v1_fmt(ctx)
        self.assertIn("V1_TOOL: run_script", v1)
        self.assertIn("ACTIVE_CONTAINER", v1)

    def test_extras_not_beyond_now_max(self):
        """v1_extra_now items are capped at now_max total NOW bullets."""
        from core.context_cleanup import _DEFAULT_LIMITS
        now_max = _DEFAULT_LIMITS["now_max"]
        # Fill NOW to exactly now_max with existing bullets
        now = [f"EXISTING_{i}" for i in range(now_max)]
        ctx = self._ctx(
            now=now,
            meta={"v1_extra_now": ["V1_TOOL: should_not_appear"]},
        )
        v1 = self._v1_fmt(ctx)
        self.assertNotIn("V1_TOOL: should_not_appear", v1)

    def test_extras_added_when_room(self):
        """When NOW < now_max, extras fill the remaining slots."""
        from core.context_cleanup import _DEFAULT_LIMITS
        now_max = _DEFAULT_LIMITS["now_max"]
        # NOW has 1 bullet → room for extras
        ctx = self._ctx(
            now=["EXISTING_0"],
            meta={"v1_extra_now": [f"V1_TOOL: extra_{i}" for i in range(now_max)]},
        )
        v1 = self._v1_fmt(ctx)
        now_lines = [l.strip() for l in v1.split("\n") if l.strip().startswith("- ")]
        # Should have exactly now_max NOW bullets (1 existing + (now_max-1) extras)
        # Count only before RULES or NEXT headers
        in_now = True
        now_count = 0
        for line in v1.split("\n"):
            stripped = line.strip()
            if stripped in ("RULES:", "NEXT:"):
                in_now = False
            if in_now and stripped.startswith("- "):
                now_count += 1
        self.assertEqual(now_count, now_max,
                         f"Expected {now_max} NOW bullets, got {now_count}")

    def test_rules_and_next_unchanged(self):
        """RULES and NEXT sections are identical in V1 and legacy renders."""
        ctx = self._ctx(
            now=["EXISTING"],
            rules=["Rule one", "Rule two"],
            next_=["Handle pending"],
            meta={"v1_extra_now": ["V1_TOOL: extra"]},
        )
        legacy = self._legacy_fmt(ctx)
        v1 = self._v1_fmt(ctx)
        # Extract RULES sections
        def _extract_section(text, header):
            lines = text.split("\n")
            in_sec = False
            result = []
            for l in lines:
                if l.strip() == f"{header}:":
                    in_sec = True
                    continue
                if in_sec:
                    if l.strip().endswith(":") and not l.strip().startswith("-"):
                        break
                    if l.strip().startswith("- "):
                        result.append(l.strip())
            return result
        self.assertEqual(_extract_section(legacy, "RULES"), _extract_section(v1, "RULES"))
        self.assertEqual(_extract_section(legacy, "NEXT"), _extract_section(v1, "NEXT"))

    def test_char_cap_enforced(self):
        """V1 renderer must respect char_cap."""
        ctx = self._ctx(
            now=["A" * 300],
            meta={"v1_extra_now": ["B" * 300]},
        )
        v1 = self._v1_fmt(ctx, char_cap=50)
        self.assertLessEqual(len(v1), 50)

    def test_fallback_on_internal_error(self):
        """V1 renderer must not raise; returns format_compact_context on error."""
        # Corrupt meta to trigger error inside try block
        ctx = self._ctx(now=["X"], meta={"v1_extra_now": "NOT_A_LIST"})
        try:
            result = self._v1_fmt(ctx)
        except Exception as exc:
            self.fail(f"format_typedstate_v1 raised: {exc}")
        self.assertIsInstance(result, str)

    def test_meta_missing_key_handled(self):
        """Missing v1_extra_now key in meta → V1 output same as legacy."""
        ctx = self._ctx(now=["ACTIVE"], meta={})  # no v1_extra_now key
        legacy = self._legacy_fmt(ctx)
        v1 = self._v1_fmt(ctx)
        self.assertEqual(legacy, v1)


# ============================================================================
# P4-C: build_compact_context meta — V1 fields
# ============================================================================

class TestBuildCompactContextV1Meta(unittest.TestCase):
    """build_compact_context must populate v1_extra_now / v1_last_errors / v1_last_tool_results."""

    def setUp(self):
        self._bcc, _, _, _, _ = _import_cleanup()

    def test_empty_events_v1_meta_present(self):
        """Empty event list → v1_extra_now, v1_last_errors, v1_last_tool_results in meta."""
        ctx = self._bcc(events=[], entries=None, limits=None)
        self.assertIn("v1_extra_now", ctx.meta)
        self.assertIn("v1_last_errors", ctx.meta)
        self.assertIn("v1_last_tool_results", ctx.meta)

    def test_v1_extra_now_is_list(self):
        """v1_extra_now must always be a list."""
        ctx = self._bcc(events=[], limits=None)
        self.assertIsInstance(ctx.meta["v1_extra_now"], list)

    def test_single_error_no_err_hist(self):
        """Single error → v1_extra_now has no V1_ERR_HIST (only 1 entry in last_errors → slice [:-1] is empty)."""
        events = [
            _make_event("container_exec",
                        {"container_id": "c1", "exit_code": 1, "stderr": "fail"},
                        event_id="ev1")
        ]
        ctx = self._bcc(events=events)
        err_hist = [b for b in ctx.meta["v1_extra_now"] if b.startswith("V1_ERR_HIST")]
        self.assertEqual(err_hist, [],
                         "Single error must not produce V1_ERR_HIST bullet")

    def test_multiple_errors_produce_err_hist(self):
        """Multiple exec failures → v1_extra_now has V1_ERR_HIST for earlier errors."""
        events = [
            _make_event("container_exec",
                        {"container_id": "c1", "exit_code": 1, "stderr": "error_one"},
                        event_id="ev1", created_at="2026-01-01T10:00:00Z"),
            _make_event("container_exec",
                        {"container_id": "c1", "exit_code": 1, "stderr": "error_two"},
                        event_id="ev2", created_at="2026-01-01T10:01:00Z"),
        ]
        ctx = self._bcc(events=events)
        err_hist = [b for b in ctx.meta["v1_extra_now"] if b.startswith("V1_ERR_HIST")]
        self.assertGreater(len(err_hist), 0,
                           "Multiple errors must produce at least one V1_ERR_HIST bullet")

    def test_tool_results_produce_v1_tool(self):
        """tool_result events → v1_extra_now has V1_TOOL bullets."""
        events = [
            _make_event("tool_result",
                        {"ref_id": "ref_abc123", "status": "success", "tool_name": "run_script"},
                        event_id="ev1")
        ]
        ctx = self._bcc(events=events)
        tool_bullets = [b for b in ctx.meta["v1_extra_now"] if b.startswith("V1_TOOL")]
        self.assertGreater(len(tool_bullets), 0,
                           "tool_result event must produce V1_TOOL bullet in v1_extra_now")

    def test_v1_last_errors_matches_state(self):
        """v1_last_errors list tracks all errors via last_errors state field."""
        events = [
            _make_event("container_exec",
                        {"container_id": "c1", "exit_code": 1, "stderr": "err_A"},
                        event_id="ev1", created_at="2026-01-01T10:00:00Z"),
        ]
        ctx = self._bcc(events=events)
        self.assertIsInstance(ctx.meta["v1_last_errors"], list)
        # At least one error tracked
        self.assertGreater(len(ctx.meta["v1_last_errors"]), 0)

    def test_v1_last_tool_results_matches_state(self):
        """v1_last_tool_results tracks tool_result refs."""
        events = [
            _make_event("tool_result",
                        {"ref_id": "ref_tool_1", "status": "success"},
                        event_id="ev1"),
        ]
        ctx = self._bcc(events=events)
        self.assertIn("ref_tool_1", ctx.meta["v1_last_tool_results"])

    def test_v1_extra_now_capped_at_item_char_cap(self):
        """V1 extra bullets must not exceed _ITEM_CHAR_CAP chars each."""
        from core.context_cleanup import _ITEM_CHAR_CAP
        events = [
            _make_event("tool_result",
                        {"ref_id": "X" * 300, "status": "success"},
                        event_id="ev1"),
        ]
        ctx = self._bcc(events=events)
        for bullet in ctx.meta["v1_extra_now"]:
            self.assertLessEqual(len(bullet), _ITEM_CHAR_CAP,
                                 f"V1 extra bullet too long: {len(bullet)} > {_ITEM_CHAR_CAP}")

    def test_legacy_now_bullets_unchanged(self):
        """Adding V1 meta fields must not change ctx.now (legacy NOW) content."""
        events = [
            _make_event("container_started",
                        {"container_id": "c1", "blueprint_id": "bp_x"},
                        event_id="ev1"),
        ]
        ctx = self._bcc(events=events)
        # ctx.now must NOT contain V1_TOOL or V1_ERR_HIST bullets
        for bullet in ctx.now:
            self.assertFalse(bullet.startswith("V1_"),
                             f"ctx.now must not contain V1 bullets: {bullet}")


# ============================================================================
# P4-D: build_small_model_context — mode branching
# ============================================================================

class TestBuildSmallModelContextModeBranching(unittest.TestCase):
    """build_small_model_context must branch on TYPEDSTATE_MODE=off/shadow/active."""

    def _make_mock_hub(self, events=None):
        hub = MagicMock()
        hub.call_tool.return_value = {
            "content": [{"type": "text", "text": "[]"}]
        }
        if events is not None:
            import json
            hub.call_tool.return_value = {
                "content": [{"type": "text", "text": json.dumps(events)}]
            }
        return hub

    def _run_build(self, mode: str, events=None):
        """Helper: patch all externals and call build_small_model_context.

        get_hub is imported inside build_small_model_context (not at module level)
        → patch at mcp.hub (the import source), not core.context_manager.
        """
        from core.context_manager import ContextManager
        cm = ContextManager.__new__(ContextManager)
        cm._protocol_cache = {}
        mock_hub = self._make_mock_hub(events or [])

        with patch("mcp.hub.get_hub", return_value=mock_hub), \
             patch("core.typedstate_csv_loader.maybe_load_csv_events", return_value=[]), \
             patch("config.get_typedstate_mode", return_value=mode), \
             patch("config.get_typedstate_csv_enable", return_value=False):
            result = cm.build_small_model_context(conversation_id="test-conv")
        return result

    def test_off_mode_returns_string(self):
        """mode=off → returns a string (legacy format_compact_context output)."""
        result = self._run_build("off")
        self.assertIsInstance(result, str)

    def test_shadow_mode_returns_string(self):
        """mode=shadow → returns a string (same legacy output)."""
        result = self._run_build("shadow")
        self.assertIsInstance(result, str)

    def test_active_mode_returns_string(self):
        """mode=active → returns a string (V1 render output)."""
        result = self._run_build("active")
        self.assertIsInstance(result, str)

    def test_off_is_unchanged_default(self):
        """mode=off output must equal legacy format_compact_context (parity test)."""
        result_off = self._run_build("off")
        # off and shadow must produce identical NOW/RULES/NEXT in base case (no V1 extras)
        result_shadow = self._run_build("shadow")
        # Both should produce the same output structure (no extras in empty events)
        self.assertEqual(result_off, result_shadow,
                         "off and shadow must produce identical output when v1_extra_now=[]")

    def test_shadow_logs_typedstate_diff(self):
        """mode=shadow must log [TypedState-DIFF] marker."""
        from core.context_manager import ContextManager
        cm = ContextManager.__new__(ContextManager)
        cm._protocol_cache = {}
        mock_hub = self._make_mock_hub()

        with patch("mcp.hub.get_hub", return_value=mock_hub), \
             patch("core.typedstate_csv_loader.maybe_load_csv_events", return_value=[]), \
             patch("config.get_typedstate_mode", return_value="shadow"), \
             patch("config.get_typedstate_csv_enable", return_value=False), \
             patch("core.context_cleanup.log_info") as mock_log:
            cm.build_small_model_context(conversation_id="test-conv")

        all_logged = " ".join(
            str(a) for c in mock_log.call_args_list for a in c[0]
        )
        self.assertIn("[TypedState-DIFF]", all_logged,
                      "shadow mode must log [TypedState-DIFF] marker")

    def test_off_does_not_log_typedstate_diff(self):
        """mode=off must NOT log [TypedState-DIFF] marker."""
        from core.context_manager import ContextManager
        cm = ContextManager.__new__(ContextManager)
        cm._protocol_cache = {}
        mock_hub = self._make_mock_hub()

        with patch("mcp.hub.get_hub", return_value=mock_hub), \
             patch("core.typedstate_csv_loader.maybe_load_csv_events", return_value=[]), \
             patch("config.get_typedstate_mode", return_value="off"), \
             patch("config.get_typedstate_csv_enable", return_value=False), \
             patch("core.context_cleanup.log_info") as mock_log:
            cm.build_small_model_context(conversation_id="test-conv")

        all_logged = " ".join(
            str(a) for c in mock_log.call_args_list for a in c[0]
        )
        self.assertNotIn("[TypedState-DIFF]", all_logged,
                         "off mode must NOT log [TypedState-DIFF]")

    def test_unknown_mode_falls_back_to_legacy(self):
        """Unknown mode string → falls back to legacy (same as off)."""
        result_off = self._run_build("off")
        result_unknown = self._run_build("totally_unknown_mode")
        self.assertEqual(result_off, result_unknown,
                         "Unknown mode must produce same output as off")

    def test_active_mode_with_v1_extras(self):
        """mode=active with tool_result events → no crash, returns valid string."""
        import json
        events = [
            {
                "id": "ev1",
                "event_type": "tool_result",
                "event_data": {"ref_id": "ref_xyz_999", "status": "success", "tool_name": "run"},
                "created_at": "2026-01-01T10:00:00Z",
            }
        ]
        from core.context_manager import ContextManager
        cm = ContextManager.__new__(ContextManager)
        cm._protocol_cache = {}
        mock_hub = self._make_mock_hub()
        mock_hub.call_tool.return_value = {
            "content": [{"type": "text", "text": json.dumps(events)}]
        }

        with patch("mcp.hub.get_hub", return_value=mock_hub), \
             patch("core.typedstate_csv_loader.maybe_load_csv_events", return_value=[]), \
             patch("config.get_typedstate_mode", return_value="active"), \
             patch("config.get_typedstate_csv_enable", return_value=False):
            result = cm.build_small_model_context(conversation_id="test-conv")

        # In active mode, V1_TOOL bullet should appear when now_max allows
        # (may or may not depending on now_max capacity; just check no crash)
        self.assertIsInstance(result, str)

    def test_shadow_returns_legacy_not_v1(self):
        """mode=shadow must return legacy output (identical to off), not V1."""
        result_off = self._run_build("off")
        result_shadow = self._run_build("shadow")
        self.assertEqual(result_off, result_shadow,
                         "shadow must return LEGACY output (kein Wiring im Output)")


# ============================================================================
# P4-E: Integration — format_typedstate_v1 signature and importability
# ============================================================================

class TestTypedstateV1PublicAPI(unittest.TestCase):
    """format_typedstate_v1 and _log_typedstate_diff must be importable and have correct signatures."""

    def test_format_typedstate_v1_importable(self):
        """format_typedstate_v1 must be importable from core.context_cleanup."""
        try:
            from core.context_cleanup import format_typedstate_v1
        except ImportError as exc:
            self.fail(f"format_typedstate_v1 not importable: {exc}")

    def test_log_typedstate_diff_importable(self):
        """_log_typedstate_diff must be importable from core.context_cleanup."""
        try:
            from core.context_cleanup import _log_typedstate_diff
        except ImportError as exc:
            self.fail(f"_log_typedstate_diff not importable: {exc}")

    def test_format_typedstate_v1_signature(self):
        """format_typedstate_v1(ctx, char_cap=None) must accept both positional and keyword args."""
        import inspect
        from core.context_cleanup import format_typedstate_v1
        sig = inspect.signature(format_typedstate_v1)
        params = list(sig.parameters.keys())
        self.assertIn("ctx", params, "format_typedstate_v1 must accept 'ctx'")
        self.assertIn("char_cap", params, "format_typedstate_v1 must accept 'char_cap'")

    def test_log_typedstate_diff_signature(self):
        """_log_typedstate_diff(legacy_now, v1_now) must accept two list args."""
        import inspect
        from core.context_cleanup import _log_typedstate_diff
        sig = inspect.signature(_log_typedstate_diff)
        params = list(sig.parameters.keys())
        self.assertIn("legacy_now", params)
        self.assertIn("v1_now", params)

    def test_build_compact_context_has_v1_meta_keys(self):
        """build_compact_context meta must include all 3 V1 keys."""
        from core.context_cleanup import build_compact_context
        ctx = build_compact_context(events=[], limits=None)
        for key in ("v1_extra_now", "v1_last_errors", "v1_last_tool_results"):
            self.assertIn(key, ctx.meta, f"meta must include '{key}'")

    def test_v1_meta_does_not_break_existing_meta_keys(self):
        """Existing meta keys must still be present after Commit 4 changes."""
        from core.context_cleanup import build_compact_context
        ctx = build_compact_context(events=[], limits=None)
        for key in ("cleanup_used", "fail_closed", "typedstate_version",
                    "source_event_ids_count", "events_processed"):
            self.assertIn(key, ctx.meta,
                          f"Existing meta key '{key}' must not be removed by Commit 4")


if __name__ == "__main__":
    unittest.main()
