"""
Shared helpers for control decision normalization and workspace summaries.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional
import re


DEFAULT_HARD_BLOCK_REASON_CODES = {
    "malicious_intent",
    "pii",
    "critical_cim",
    "hardware_self_protection",
}


def normalize_block_reason_code(value: Any) -> str:
    code = str(value or "").strip().lower()
    if not code:
        return ""
    code = re.sub(r"[^a-z0-9_]+", "_", code)
    code = re.sub(r"_+", "_", code).strip("_")
    return code


def is_allowed_hard_block_reason_code(
    code: str,
    *,
    allowed_codes: Optional[Iterable[str]] = None,
) -> bool:
    normalized = normalize_block_reason_code(code)
    scope = {
        normalize_block_reason_code(item)
        for item in (allowed_codes or DEFAULT_HARD_BLOCK_REASON_CODES)
        if normalize_block_reason_code(item)
    }
    return normalized in scope


def make_hard_block_verification(
    *,
    reason_code: str,
    warnings: Any = None,
    final_instruction: str = "Request blocked",
    reason: str = "",
) -> Dict[str, Any]:
    warning_list: List[str]
    if isinstance(warnings, list):
        warning_list = [str(item) for item in warnings if str(item).strip()]
    elif warnings:
        warning_list = [str(warnings)]
    else:
        warning_list = []
    normalized_code = normalize_block_reason_code(reason_code) or "critical_cim"
    return {
        "approved": False,
        "hard_block": True,
        "decision_class": "hard_block",
        "block_reason_code": normalized_code,
        "reason": reason or normalized_code,
        "corrections": {},
        "warnings": warning_list,
        "final_instruction": final_instruction,
    }


def is_control_hard_block_decision(
    verification: Dict[str, Any],
    *,
    allowed_reason_codes: Optional[Iterable[str]] = None,
) -> bool:
    if not isinstance(verification, dict):
        return False
    if verification.get("approved") is not False:
        return False

    if bool(verification.get("hard_block")):
        return True

    decision_class = str(verification.get("decision_class") or "").strip().lower()
    if decision_class == "hard_block":
        return True

    reason_code = str(verification.get("block_reason_code") or "").strip().lower()
    if is_allowed_hard_block_reason_code(
        reason_code,
        allowed_codes=allowed_reason_codes,
    ):
        return True

    reason_text = " ".join(
        str(part or "")
        for part in (
            verification.get("reason"),
            verification.get("final_instruction"),
            " ".join(str(w) for w in (verification.get("warnings") or [])),
        )
    ).lower()
    hard_markers = (
        "dangerous keyword detected",
        "sensitive content detected",
        "email address detected",
        "phone number detected",
        "pii",
        "malicious",
        "policy guard",
    )
    return any(marker in reason_text for marker in hard_markers)


def soften_control_deny(
    verification: Dict[str, Any],
    *,
    warning_message: str = (
        "Soft control deny downgraded to warning "
        "(single hard-block authority = Control hard_block only)."
    ),
    fallback_reason: str = "soft_control_warning_auto_corrected",
) -> Dict[str, Any]:
    if not isinstance(verification, dict):
        return verification
    if verification.get("approved") is not False:
        return verification

    warnings = verification.get("warnings")
    if not isinstance(warnings, list):
        warnings = [str(warnings)] if warnings else []
    warnings.append(warning_message)
    verification["warnings"] = warnings
    verification["approved"] = True
    verification["hard_block"] = False
    verification["decision_class"] = "warn"
    verification["block_reason_code"] = ""
    verification["reason"] = str(verification.get("reason") or fallback_reason)
    return verification


def build_control_workspace_summary(
    verification: Dict[str, Any],
    *,
    skipped: bool,
    skip_reason: str = "",
) -> str:
    ver = verification if isinstance(verification, dict) else {}
    approved = ver.get("approved", True)
    warnings = ver.get("warnings", []) if isinstance(ver.get("warnings", []), list) else []
    corrections = ver.get("corrections", {}) if isinstance(ver.get("corrections", {}), dict) else {}
    reason = str(ver.get("reason", "") or "").strip()
    correction_keys = sorted([str(k) for k in corrections.keys()])[:6]
    parts = [
        f"approved={bool(approved)}",
        f"skipped={bool(skipped)}",
    ]
    if skip_reason:
        parts.append(f"skip_reason={skip_reason}")
    if reason:
        parts.append(f"reason={reason[:120]}")
    if warnings:
        parts.append(f"warnings={len(warnings)}")
    if correction_keys:
        parts.append(f"corrections={','.join(correction_keys)}")
    return " | ".join(parts)


def build_done_workspace_summary(
    done_reason: str,
    *,
    response_mode: str = "",
    model: str = "",
    memory_used: Optional[bool] = None,
) -> str:
    parts = [f"done_reason={str(done_reason or 'stop').strip()}"]
    if response_mode:
        parts.append(f"response_mode={response_mode}")
    if model:
        parts.append(f"model={model}")
    if memory_used is not None:
        parts.append(f"memory_used={bool(memory_used)}")
    return " | ".join(parts)
