"""
Container Commander — Trust Verification API (Phase 2 Stub)
═══════════════════════════════════════════════════════════════

Einziger Zugangspunkt für Blueprint/Image Trust-Entscheidungen.
Aktuell: Adapter auf bestehende _OFFICIAL_BLUEPRINT_IDS + is_trusted_image().
Später: Digest/Signature-Verifikation hier austauschbar, OHNE Orchestrator-Umbau.

TrustDecision Schema (Codex Phase 2):
{
    "level":  "verified" | "unverified" | "blocked",
    "source": "official-set" | "trusted-image-pattern" | "user-created"
              | "future-digest" | "future-signature",
    "reason": str,
    "image_ref": str,
    "image_digest": str | None   # Phase 3: tatsächlicher Image-Digest
}

Verwendung:
    from container_commander.trust import evaluate_blueprint_trust
    decision = evaluate_blueprint_trust(blueprint)
    if decision["level"] == "blocked":
        raise RuntimeError(decision["reason"])
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Blueprint


# ── Official IDs (single source of truth for trust) ───────
def _official_ids():
    from .blueprint_store import _OFFICIAL_BLUEPRINT_IDS
    return _OFFICIAL_BLUEPRINT_IDS


def evaluate_blueprint_trust(blueprint: "Blueprint") -> dict:
    """
    Bestimmt das Trust-Level eines Blueprints.

    Phase 2: regelbasiert (official-set + image-pattern).
    Phase 3: Digest/Signature wird hier eingehängt, API bleibt gleich.

    Returns:
        TrustDecision dict
    """
    image_ref = blueprint.image or blueprint.dockerfile[:80] or ""

    # 1. Offiziell eingebautter Blueprint → verified
    if blueprint.id in _official_ids():
        return {
            "level": "verified",
            "source": "official-set",
            "reason": f"'{blueprint.id}' ist ein offiziell eingebauter Blueprint",
            "image_ref": image_ref,
            "image_digest": None,
        }

    # 2. Image-Prefix aus Trusted-Pattern-Liste → verified
    from .mcp_tools import is_trusted_image
    if image_ref and is_trusted_image(image_ref):
        return {
            "level": "verified",
            "source": "trusted-image-pattern",
            "reason": f"Image '{image_ref}' entspricht einem bekannten vertrauenswürdigen Prefix",
            "image_ref": image_ref,
            "image_digest": None,
        }

    # 3. User-erstellt / unbekanntes Image → unverified (kein block, nur Warnung)
    return {
        "level": "unverified",
        "source": "user-created",
        "reason": f"Blueprint '{blueprint.id}' ist nicht offiziell — Image nicht in Trusted-List",
        "image_ref": image_ref,
        "image_digest": None,
    }


def evaluate_image_trust(image_ref: str) -> dict:
    """
    Standalone Image-Trust-Check (ohne Blueprint-Kontext).
    Für zukünftige Digest-Verifikation vorbereitet.
    """
    from .mcp_tools import is_trusted_image

    if is_trusted_image(image_ref):
        return {
            "level": "verified",
            "source": "trusted-image-pattern",
            "reason": f"'{image_ref}' entspricht einem bekannten vertrauenswürdigen Prefix",
            "image_ref": image_ref,
            "image_digest": None,
        }
    return {
        "level": "unverified",
        "source": "user-created",
        "reason": f"'{image_ref}' ist nicht in der Trusted-Image-Liste",
        "image_ref": image_ref,
        "image_digest": None,
    }


# ── Phase 3 — Digest Pinning (opt-in) ─────────────────────

def resolve_image_digest(image_ref: str) -> str | None:
    """
    Resolve the actual RepoDigest of a locally available image via Docker SDK.
    Returns 'sha256:...' string or None if not resolvable.
    Does NOT pull — only checks locally cached image.
    """
    try:
        import docker as _docker
        client = _docker.from_env()
        img = client.images.get(image_ref)
        digests = img.attrs.get("RepoDigests", [])
        # RepoDigests format: ["registry/image@sha256:..."]
        for d in digests:
            if "@" in d:
                return d.split("@", 1)[1]  # Return "sha256:..."
        return None
    except Exception:
        return None


def verify_image_digest(image_ref: str, expected_digest: str) -> bool:
    """
    Phase 3: Compare resolved digest against pinned expected_digest.
    Returns True only if resolved digest matches exactly.
    Fails closed (returns False) on any error.
    """
    if not expected_digest or not image_ref:
        return False
    try:
        actual = resolve_image_digest(image_ref)
        if actual is None:
            return False
        return actual.strip() == expected_digest.strip()
    except Exception:
        return False


def check_digest_policy(blueprint) -> dict:
    """
    Central runtime policy check for digest pinning (opt-in).

    Policy:
    - image_digest set   → strict: verify, fail closed if mismatch or resolve error
    - image_digest None  → allow with warning (backwards compatible, opt-in)

    Returns:
        {
            "allowed": bool,
            "mode": "pinned_strict" | "unpinned_warn" | "no_image",
            "actual_digest": str | None,
            "reason": str,
        }
    """
    image_ref = blueprint.image or ""
    pinned = blueprint.image_digest

    if not image_ref:
        return {
            "allowed": True,
            "mode": "no_image",
            "actual_digest": None,
            "reason": "Dockerfile-basierter Blueprint — kein Image-Digest-Check",
        }

    if not pinned:
        # opt-in: no digest pinned → allow with warning
        actual = resolve_image_digest(image_ref)
        return {
            "allowed": True,
            "mode": "unpinned_warn",
            "actual_digest": actual,
            "reason": (
                f"[Trust-Warn] Blueprint '{blueprint.id}' hat keinen gepinnten Digest — "
                f"Image '{image_ref}' wird ohne Digest-Verifikation gestartet "
                f"(aktueller Digest: {actual or 'nicht auflösbar'})"
            ),
        }

    # Pinned → strict check, fail closed
    actual = resolve_image_digest(image_ref)
    if actual is None:
        return {
            "allowed": False,
            "mode": "pinned_strict",
            "actual_digest": None,
            "reason": (
                f"[Trust-Block] Image '{image_ref}' Digest nicht auflösbar — "
                f"erwartet: {pinned}. Start blockiert (fail closed)."
            ),
        }

    if actual.strip() != pinned.strip():
        return {
            "allowed": False,
            "mode": "pinned_strict",
            "actual_digest": actual,
            "reason": (
                f"[Trust-Block] Image Digest mismatch für '{image_ref}': "
                f"erwartet={pinned}, gefunden={actual}. Start blockiert."
            ),
        }

    return {
        "allowed": True,
        "mode": "pinned_strict",
        "actual_digest": actual,
        "reason": f"[Trust-OK] Image '{image_ref}' Digest verifiziert: {actual}",
    }


# ── Phase 6 — Signature Verification ──────────────────────────

import logging as _sig_logging
import subprocess as _subprocess

_sig_log = _sig_logging.getLogger(__name__ + ".signature")

# Patterns that indicate *no* signature was found (as opposed to an invalid one)
_NO_SIG_PATTERNS = (
    "no signatures found",
    "no matching signatures",
    "no signature found",
    "no attestations found",
    "does not have an associated signature",
    "signature not found",
)


def _detect_no_signature(output: str) -> bool:
    """Return True if the tool output indicates signature is absent (not invalid)."""
    low = output.lower()
    return any(p in low for p in _NO_SIG_PATTERNS)


def _try_verify(image_ref: str, timeout: int = 15) -> dict:
    """
    Try cosign then notation to verify the image signature.

    Returns a dict:
        available (bool)  — at least one tool was found
        ok        (bool)  — verification succeeded
        absent    (bool)  — no signature present (only meaningful when ok=False)
        reason    (str)   — human-readable message
        tool      (str|None)
    """
    for tool_name, cmd in [
        ("cosign",   ["cosign",   "verify", image_ref]),
        ("notation", ["notation", "verify", image_ref]),
    ]:
        try:
            proc = _subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
            if proc.returncode == 0:
                return {
                    "available": True, "ok": True, "absent": False,
                    "reason": f"{tool_name} verify: OK", "tool": tool_name,
                }
            combined = (proc.stdout + " " + proc.stderr).strip()
            return {
                "available": True, "ok": False,
                "absent": _detect_no_signature(combined),
                "reason": f"{tool_name}: {combined[:200] or 'verification failed'}",
                "tool": tool_name,
            }
        except FileNotFoundError:
            continue  # Try next tool
        except _subprocess.TimeoutExpired:
            return {
                "available": True, "ok": False, "absent": False,
                "reason": f"{tool_name} timeout after {timeout}s", "tool": tool_name,
            }
        except Exception as exc:
            return {
                "available": True, "ok": False, "absent": False,
                "reason": f"{tool_name} error: {exc}", "tool": tool_name,
            }

    return {
        "available": False, "ok": False, "absent": True,
        "reason": "No signature verification tool (cosign/notation) installed",
        "tool": None,
    }


def verify_image_signature(image_ref: str) -> dict:
    """
    Phase 6: Mode-aware image signature verification.

    Returns VerifyResult:
        {
            "verified": bool,
            "mode":     "off" | "opt_in" | "strict",
            "reason":   str,
            "tool":     str | None,   # "cosign" | "notation" | None
        }

    Mode behaviour:
        off      → always verified=True, no subprocess call
        opt_in   → check if tool available; absent sig → allow; invalid sig → reject
        strict   → signature required; absent OR invalid → reject; no tool → reject
    """
    from config import get_signature_verify_mode
    mode = get_signature_verify_mode()

    if mode == "off":
        _sig_log.debug("[Signature] mode=off image=%s → pass", image_ref)
        return {"verified": True, "mode": "off", "reason": "disabled", "tool": None}

    r = _try_verify(image_ref)

    if not r["available"]:
        # No tool installed anywhere
        if mode == "strict":
            msg = f"strict mode: {r['reason']}"
            _sig_log.warning("[Signature] BLOCK image=%s: %s", image_ref, msg)
            return {"verified": False, "mode": mode, "reason": msg, "tool": None}
        # opt_in: no tool → allow with warning
        _sig_log.info("[Signature] opt_in allow (no tool) image=%s", image_ref)
        return {
            "verified": True, "mode": mode,
            "reason": f"opt_in: {r['reason']}, allowing without verification",
            "tool": None,
        }

    if r["ok"]:
        _sig_log.info(
            "[Signature] VERIFIED image=%s tool=%s", image_ref, r["tool"]
        )
        return {"verified": True, "mode": mode, "reason": r["reason"], "tool": r["tool"]}

    # Verification failed — distinguish absent vs invalid
    if r["absent"] and mode == "opt_in":
        _sig_log.info(
            "[Signature] opt_in allow (no signature) image=%s tool=%s",
            image_ref, r["tool"]
        )
        return {
            "verified": True, "mode": mode,
            "reason": "opt_in: no signature present, allowing",
            "tool": r["tool"],
        }

    # Invalid signature, OR strict mode with absent signature → reject
    _sig_log.warning(
        "[Signature] BLOCK image=%s mode=%s tool=%s: %s",
        image_ref, mode, r["tool"], r["reason"]
    )
    return {
        "verified": False, "mode": mode, "reason": r["reason"], "tool": r["tool"],
    }
