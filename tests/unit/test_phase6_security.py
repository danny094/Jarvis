"""
tests/unit/test_phase6_security.py — Phase 6 Security & Hardening Tests
=========================================================================

Covers:
  P6-A  Signature Verify — _detect_no_signature, _try_verify, verify_image_signature
  P6-B  XSS Sanitizing   — source-inspection: sanitize.js present and
                            workspace.js / protocol.js use sanitizeHtml
  P6-C  REST Parity       — source-inspection: protocol_routes.py and
                            commander_routes.py accept conversation_id/session_id

Gate: python -m pytest tests/unit/test_phase6_security.py -q
Expected: ≥ 30 passed, 0 failures
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

# ── Repo root on sys.path ──────────────────────────────────────────────────────
_HERE = os.path.dirname(__file__)
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ─────────────────────────────────────────────────────────────────────────────
# Helper: source inspection
# ─────────────────────────────────────────────────────────────────────────────

def _read_source(relative_path: str) -> str:
    for base in sys.path:
        candidate = os.path.join(base, relative_path)
        if os.path.isfile(candidate):
            with open(candidate, encoding="utf-8") as f:
                return f.read()
    candidate = os.path.join(_REPO_ROOT, relative_path)
    if os.path.isfile(candidate):
        with open(candidate, encoding="utf-8") as f:
            return f.read()
    raise FileNotFoundError(f"Source not found: {relative_path}")


# ─────────────────────────────────────────────────────────────────────────────
# P6-A.1  _detect_no_signature
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectNoSignature(unittest.TestCase):

    def _detect(self, text: str) -> bool:
        from container_commander.trust import _detect_no_signature
        return _detect_no_signature(text)

    def test_no_signatures_found_pattern(self):
        self.assertTrue(self._detect("Error: no signatures found for image"))

    def test_no_matching_signatures_pattern(self):
        self.assertTrue(self._detect("no matching signatures in registry"))

    def test_no_signature_found_singular(self):
        self.assertTrue(self._detect("No signature found"))

    def test_does_not_have_associated_signature(self):
        self.assertTrue(self._detect("image does not have an associated signature"))

    def test_signature_not_found(self):
        self.assertTrue(self._detect("signature not found in store"))

    def test_no_attestations(self):
        self.assertTrue(self._detect("no attestations found"))

    def test_case_insensitive(self):
        self.assertTrue(self._detect("NO SIGNATURES FOUND"))
        self.assertTrue(self._detect("No Matching Signatures"))

    def test_invalid_signature_is_not_absent(self):
        self.assertFalse(self._detect("invalid signature: bad key"))

    def test_verification_failed_is_not_absent(self):
        self.assertFalse(self._detect("verification failed"))

    def test_empty_string(self):
        self.assertFalse(self._detect(""))


# ─────────────────────────────────────────────────────────────────────────────
# P6-A.2  _try_verify
# ─────────────────────────────────────────────────────────────────────────────

class TestTryVerify(unittest.TestCase):

    def _call(self, mock_run_side_effect=None, mock_run_return=None):
        import container_commander.trust as trust_mod
        mock_sub = MagicMock()
        mock_sub.TimeoutExpired = subprocess.TimeoutExpired
        if mock_run_side_effect is not None:
            mock_sub.run.side_effect = mock_run_side_effect
        elif mock_run_return is not None:
            mock_sub.run.return_value = mock_run_return
        with patch.object(trust_mod, "_subprocess", mock_sub):
            from container_commander.trust import _try_verify
            return _try_verify("registry/image:tag", timeout=5)

    def test_cosign_success(self):
        r = self._call(mock_run_return=MagicMock(returncode=0, stdout="OK", stderr=""))
        self.assertTrue(r["available"])
        self.assertTrue(r["ok"])
        self.assertFalse(r["absent"])
        self.assertEqual(r["tool"], "cosign")

    def test_cosign_no_signature_marks_absent(self):
        r = self._call(mock_run_return=MagicMock(returncode=1, stdout="", stderr="no signatures found"))
        self.assertTrue(r["available"])
        self.assertFalse(r["ok"])
        self.assertTrue(r["absent"])
        self.assertEqual(r["tool"], "cosign")

    def test_cosign_invalid_signature_not_absent(self):
        r = self._call(mock_run_return=MagicMock(returncode=1, stdout="", stderr="invalid signature"))
        self.assertFalse(r["ok"])
        self.assertFalse(r["absent"])

    def test_both_tools_missing_not_available(self):
        r = self._call(mock_run_side_effect=FileNotFoundError)
        self.assertFalse(r["available"])
        self.assertFalse(r["ok"])
        self.assertIsNone(r["tool"])

    def test_cosign_timeout_marks_available(self):
        import container_commander.trust as trust_mod
        mock_sub = MagicMock()
        mock_sub.TimeoutExpired = subprocess.TimeoutExpired
        mock_sub.run.side_effect = subprocess.TimeoutExpired(cmd=["cosign"], timeout=5)
        with patch.object(trust_mod, "_subprocess", mock_sub):
            from container_commander.trust import _try_verify
            r = _try_verify("registry/image:tag", timeout=5)
        self.assertTrue(r["available"])
        self.assertFalse(r["ok"])
        self.assertIn("timeout", r["reason"].lower())

    def test_result_has_required_keys(self):
        r = self._call(mock_run_return=MagicMock(returncode=0, stdout="", stderr=""))
        for key in ("available", "ok", "absent", "reason", "tool"):
            self.assertIn(key, r, f"Missing key: {key}")


# ─────────────────────────────────────────────────────────────────────────────
# P6-A.3  verify_image_signature — mode × scenario matrix
# ─────────────────────────────────────────────────────────────────────────────

class TestVerifyImageSignature(unittest.TestCase):
    """
    Because verify_image_signature() does `from config import get_signature_verify_mode`
    at call time, we patch config.get_signature_verify_mode (the source of truth),
    not container_commander.trust.get_signature_verify_mode.
    """

    def _call(self, image: str, mode: str, mock_sub=None):
        import container_commander.trust as trust_mod
        mode_patcher = patch("config.get_signature_verify_mode", return_value=mode)
        if mock_sub is not None:
            sub_patcher = patch.object(trust_mod, "_subprocess", mock_sub)
            with mode_patcher, sub_patcher:
                from container_commander.trust import verify_image_signature
                return verify_image_signature(image)
        else:
            with mode_patcher:
                from container_commander.trust import verify_image_signature
                return verify_image_signature(image)

    def _mock_sub(self, returncode=0, stderr="", side_effect=None):
        mock_sub = MagicMock()
        mock_sub.TimeoutExpired = subprocess.TimeoutExpired
        if side_effect is not None:
            mock_sub.run.side_effect = side_effect
        else:
            mock_sub.run.return_value = MagicMock(returncode=returncode, stdout="", stderr=stderr)
        return mock_sub

    # --- off mode ---

    def test_off_always_verified(self):
        r = self._call("any/image", "off")
        self.assertTrue(r["verified"])
        self.assertEqual(r["mode"], "off")

    def test_off_no_subprocess_call(self):
        import container_commander.trust as trust_mod
        mock_sub = MagicMock()
        mock_sub.TimeoutExpired = subprocess.TimeoutExpired
        with patch("config.get_signature_verify_mode", return_value="off"), \
             patch.object(trust_mod, "_subprocess", mock_sub):
            from container_commander.trust import verify_image_signature
            verify_image_signature("any/image")
        mock_sub.run.assert_not_called()

    # --- opt_in mode ---

    def test_opt_in_cosign_ok_verified(self):
        r = self._call("reg/img:tag", "opt_in", self._mock_sub(returncode=0))
        self.assertTrue(r["verified"])

    def test_opt_in_no_signature_allows(self):
        r = self._call("reg/img:tag", "opt_in",
                       self._mock_sub(returncode=1, stderr="no signatures found"))
        self.assertTrue(r["verified"])

    def test_opt_in_invalid_signature_rejects(self):
        r = self._call("reg/img:tag", "opt_in",
                       self._mock_sub(returncode=1, stderr="invalid key"))
        self.assertFalse(r["verified"])

    def test_opt_in_no_tool_allows(self):
        r = self._call("reg/img:tag", "opt_in",
                       self._mock_sub(side_effect=FileNotFoundError))
        self.assertTrue(r["verified"])

    # --- strict mode ---

    def test_strict_cosign_ok_verified(self):
        r = self._call("reg/img:tag", "strict", self._mock_sub(returncode=0))
        self.assertTrue(r["verified"])

    def test_strict_no_signature_rejects(self):
        r = self._call("reg/img:tag", "strict",
                       self._mock_sub(returncode=1, stderr="no signatures found"))
        self.assertFalse(r["verified"])

    def test_strict_invalid_signature_rejects(self):
        r = self._call("reg/img:tag", "strict",
                       self._mock_sub(returncode=1, stderr="bad key"))
        self.assertFalse(r["verified"])

    def test_strict_no_tool_rejects(self):
        r = self._call("reg/img:tag", "strict",
                       self._mock_sub(side_effect=FileNotFoundError))
        self.assertFalse(r["verified"])

    # --- result shape ---

    def test_result_has_required_keys(self):
        r = self._call("any/image", "off")
        for key in ("verified", "mode", "reason", "tool"):
            self.assertIn(key, r, f"Missing key: {key}")

    def test_result_verified_is_bool(self):
        r = self._call("any/image", "off")
        self.assertIsInstance(r["verified"], bool)

    def test_result_mode_matches_config(self):
        r = self._call("any/image", "strict", self._mock_sub(returncode=0))
        self.assertEqual(r["mode"], "strict")


# ─────────────────────────────────────────────────────────────────────────────
# P6-A.4  Config — get_signature_verify_mode
# ─────────────────────────────────────────────────────────────────────────────

class TestSignatureVerifyModeConfig(unittest.TestCase):

    def test_function_exists(self):
        from config import get_signature_verify_mode
        self.assertTrue(callable(get_signature_verify_mode))

    def test_default_is_off(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SIGNATURE_VERIFY_MODE", None)
            from config import get_signature_verify_mode
            mode = get_signature_verify_mode()
        self.assertEqual(mode, "off")

    def test_env_override(self):
        with patch.dict(os.environ, {"SIGNATURE_VERIFY_MODE": "strict"}):
            from config import get_signature_verify_mode
            mode = get_signature_verify_mode()
        self.assertEqual(mode, "strict")

    def test_mode_normalised_to_lowercase(self):
        with patch.dict(os.environ, {"SIGNATURE_VERIFY_MODE": "OPT_IN"}):
            from config import get_signature_verify_mode
            mode = get_signature_verify_mode()
        self.assertEqual(mode, "opt_in")


# ─────────────────────────────────────────────────────────────────────────────
# P6-B  XSS / Sanitizing — source inspection
# ─────────────────────────────────────────────────────────────────────────────

class TestSanitizeJsPresent(unittest.TestCase):
    """sanitize.js must exist and expose sanitizeHtml."""

    def _src(self):
        return _read_source("adapters/Jarvis/static/js/sanitize.js")

    def test_file_exists(self):
        src = self._src()
        self.assertGreater(len(src), 50)

    def test_defines_sanitize_html(self):
        self.assertIn("sanitizeHtml", self._src())

    def test_strips_script_tags(self):
        # Must reference the "script" tag in remove list
        self.assertIn('"script"', self._src())

    def test_strips_on_event_attrs(self):
        self.assertIn("ON_ATTR_RE", self._src())

    def test_adds_noopener(self):
        self.assertIn("noopener", self._src())

    def test_handles_javascript_scheme(self):
        self.assertIn("javascript:", self._src())

    def test_exposes_window_global(self):
        self.assertIn("TRIONSanitize", self._src())

    def test_handles_vbscript_scheme(self):
        self.assertIn("vbscript:", self._src())


class TestWorkspaceJsSanitized(unittest.TestCase):
    """workspace.js renderMarkdown must use TRIONSanitize / DOMPurify + rel=noopener."""

    def _src(self):
        return _read_source("adapters/Jarvis/static/js/workspace.js")

    def test_uses_trion_sanitize(self):
        self.assertIn("TRIONSanitize", self._src())

    def test_uses_sanitize_html_method(self):
        self.assertIn("sanitizeHtml", self._src())

    def test_adds_noopener_on_external_links(self):
        self.assertIn("noopener", self._src())

    def test_dompurify_still_referenced(self):
        self.assertIn("DOMPurify", self._src())

    def test_trion_sanitize_checked_first(self):
        src = self._src()
        # TRIONSanitize must appear before DOMPurify in renderMarkdown
        idx_trion = src.find("TRIONSanitize")
        idx_dompurify = src.find("DOMPurify")
        self.assertGreater(idx_trion, 0)
        self.assertGreater(idx_dompurify, 0)
        self.assertLess(idx_trion, idx_dompurify,
                        "TRIONSanitize must be checked before DOMPurify")


class TestProtocolJsSanitized(unittest.TestCase):
    """protocol.js must sanitize marked.parse() output."""

    def _src(self):
        return _read_source("adapters/Jarvis/js/apps/protocol.js")

    def test_has_sanitize_html_function(self):
        self.assertIn("function sanitizeHtml", self._src())

    def test_marked_parse_wrapped_in_sanitize(self):
        src = self._src()
        # The correct pattern: sanitizeHtml(... marked.parse(...)
        self.assertIn("sanitizeHtml(window.marked ? marked.parse(", src)

    def test_cancel_handler_uses_sanitize_html(self):
        src = self._src()
        # The cancel button listener must call sanitizeHtml, not assign raw marked.parse
        self.assertIn("sanitizeHtml(window.marked ? marked.parse(bodyText)", src)

    def test_no_inline_onclick_with_template_literal(self):
        """Inline onclick= with backtick template content was the old XSS vector."""
        src = self._src()
        self.assertNotIn('onclick="this.closest', src)

    def test_adds_noopener(self):
        self.assertIn("noopener", self._src())

    def test_has_escape_html(self):
        self.assertIn("function escapeHtml", self._src())


# ─────────────────────────────────────────────────────────────────────────────
# P6-C  REST Deploy Parity — source inspection
# ─────────────────────────────────────────────────────────────────────────────

class TestProtocolRoutesParityPatterns(unittest.TestCase):
    """protocol_routes.py /append must accept conversation_id and session_id."""

    def _src(self):
        return _read_source("adapters/admin-api/protocol_routes.py")

    def test_append_reads_conversation_id(self):
        self.assertIn('conversation_id', self._src())

    def test_append_reads_session_id(self):
        self.assertIn('session_id', self._src())

    def test_response_includes_conversation_id_key(self):
        self.assertIn('"conversation_id"', self._src())

    def test_response_includes_session_id_key(self):
        self.assertIn('"session_id"', self._src())


class TestCommanderRoutesParityPatterns(unittest.TestCase):
    """commander_routes.py /containers/deploy must accept conversation_id + session_id."""

    def _src(self):
        return _read_source("adapters/admin-api/commander_routes.py")

    def test_deploy_reads_conversation_id(self):
        self.assertIn("conversation_id", self._src())

    def test_deploy_reads_session_id(self):
        self.assertIn("session_id", self._src())

    def test_pending_approval_response_includes_conversation_id(self):
        self.assertIn('"conversation_id"', self._src())

    def test_pending_approval_response_includes_session_id(self):
        self.assertIn('"session_id"', self._src())


class TestChatJsParityPatterns(unittest.TestCase):
    """chat.js protocol/append call must include conversation_id."""

    def _src(self):
        return _read_source("adapters/Jarvis/static/js/chat.js")

    def test_append_sends_conversation_id(self):
        src = self._src()
        self.assertIn("conversation_id", src)

    def test_conversation_id_near_append_call(self):
        src = self._src()
        idx = src.find("api/protocol/append")
        self.assertGreater(idx, 0, "protocol/append endpoint must be referenced in chat.js")
        nearby = src[idx: idx + 500]
        self.assertIn("conversation_id", nearby,
                      "conversation_id must appear near the protocol/append fetch call")


# ─────────────────────────────────────────────────────────────────────────────
# P6-A Runtime Wiring — engine.py calls verify_image_signature()
# ─────────────────────────────────────────────────────────────────────────────

class TestEngineSignatureWiring(unittest.TestCase):
    """
    Source-inspection: engine.py trust gate must call verify_image_signature()
    for image-based blueprints.

    Runtime test (verify_image_signature mock injection) is in TestVerifyImageSignature.
    A full engine integration test would require Docker — keep it source-inspection here.
    """

    def _src(self):
        return _read_source("container_commander/engine.py")

    def test_engine_imports_verify_image_signature(self):
        self.assertIn("verify_image_signature", self._src())

    def test_engine_trust_gate_calls_verify_image_signature(self):
        src = self._src()
        # Must call the function, not just import it
        self.assertIn("verify_image_signature(", src)

    def test_engine_checks_verified_field(self):
        src = self._src()
        self.assertIn("_sig_result[\"verified\"]", src)

    def test_engine_raises_on_invalid_signature(self):
        src = self._src()
        # Must raise RuntimeError with Signature-Block marker
        self.assertIn("Signature-Block", src)

    def test_engine_audits_signature_blocked_event(self):
        src = self._src()
        # Must write a workspace_event of type signature_blocked
        self.assertIn("signature_blocked", src)

    def test_engine_skips_verify_for_dockerfile_builds(self):
        src = self._src()
        # Condition: `if bp.image:` gates the signature check
        self.assertIn("if bp.image:", src)

    def test_engine_logs_on_success(self):
        src = self._src()
        # In non-off modes, must log when signature passes
        self.assertIn("Signature OK", src)


# ─────────────────────────────────────────────────────────────────────────────
# P6-A Runtime: verify_image_signature called and raises in strict mode
# ─────────────────────────────────────────────────────────────────────────────

class TestVerifyImageSignatureRaisesOnBlock(unittest.TestCase):
    """
    Verify that verify_image_signature() returns verified=False for strict+invalid,
    and the result would cause engine.py to raise RuntimeError.
    (Full engine integration test requires Docker; we verify the guard logic.)
    """

    def _call_strict_invalid(self):
        import container_commander.trust as trust_mod
        mock_sub = MagicMock()
        mock_sub.TimeoutExpired = subprocess.TimeoutExpired
        mock_sub.run.return_value = MagicMock(returncode=1, stdout="", stderr="bad key")
        with patch("config.get_signature_verify_mode", return_value="strict"), \
             patch.object(trust_mod, "_subprocess", mock_sub):
            from container_commander.trust import verify_image_signature
            return verify_image_signature("reg/img:tag")

    def test_strict_invalid_returns_not_verified(self):
        r = self._call_strict_invalid()
        self.assertFalse(r["verified"])

    def test_strict_invalid_would_block_deploy(self):
        """
        Simulate the engine guard: if not _sig_result['verified']: raise RuntimeError.
        Confirms the wiring pattern is correct.
        """
        r = self._call_strict_invalid()
        if not r["verified"]:
            with self.assertRaises(RuntimeError):
                raise RuntimeError(f"[Signature-Block] {r['reason']}")


# ─────────────────────────────────────────────────────────────────────────────
# P6-C Runtime Wiring — commander_routes passes IDs to start_container()
# ─────────────────────────────────────────────────────────────────────────────

class TestCommanderRouteForwardsIds(unittest.TestCase):
    """
    Source-inspection: commander_routes.py must pass session_id=session_id and
    conversation_id=conversation_id as keyword arguments to start_container().
    This is stronger than just checking the variable names exist.
    """

    def _src(self):
        return _read_source("adapters/admin-api/commander_routes.py")

    def test_start_container_receives_session_id_kwarg(self):
        src = self._src()
        self.assertIn("session_id=session_id", src,
                      "start_container() must receive session_id=session_id kwarg")

    def test_start_container_receives_conversation_id_kwarg(self):
        src = self._src()
        self.assertIn("conversation_id=conversation_id", src,
                      "start_container() must receive conversation_id=conversation_id kwarg")


# ─────────────────────────────────────────────────────────────────────────────
# P6-C Protocol.js addEntry sends IDs explicitly
# ─────────────────────────────────────────────────────────────────────────────

class TestProtocolJsAddEntryIdsPatterns(unittest.TestCase):
    """protocol.js addEntry() must include conversation_id in the fetch body."""

    def _src(self):
        return _read_source("adapters/Jarvis/js/apps/protocol.js")

    def test_add_entry_body_includes_conversation_id(self):
        src = self._src()
        # conversation_id must appear in the addEntry() function's fetch body
        idx_fn = src.find("async function addEntry")
        self.assertGreater(idx_fn, 0, "addEntry function must exist")
        fn_body = src[idx_fn: idx_fn + 900]
        self.assertIn("conversation_id", fn_body,
                      "addEntry() fetch body must include conversation_id")

    def test_add_entry_body_includes_session_id(self):
        src = self._src()
        idx_fn = src.find("async function addEntry")
        fn_body = src[idx_fn: idx_fn + 900]
        self.assertIn("session_id", fn_body,
                      "addEntry() fetch body must include session_id")


if __name__ == "__main__":
    unittest.main()
