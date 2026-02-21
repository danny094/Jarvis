"""
tests/harness/golden.py — Commit D
=====================================
Golden snapshot management for AI response regression tests.

Snapshots are stored as JSON files in tests/golden/.
Volatile fields are stripped by normalize_response() before comparison.

Update mode:
    AI_UPDATE_GOLDEN=1  — silently overwrite golden files with current output
    --update-golden flag can be passed via conftest fixture injection

Usage:
    from tests.harness.golden import assert_golden, update_golden, load_golden

    result = runner.run(inp)
    assert_golden(result, key="p0_basic_hello_sync")
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from tests.harness.runner import normalize_response
from tests.harness.types import HarnessResult

# ─────────────────────────────────────────────────────────────────────────────
# Golden directory
# ─────────────────────────────────────────────────────────────────────────────

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent   # tests/harness/ → tests/ → repo root
_DEFAULT_GOLDEN_DIR = _REPO_ROOT / "tests" / "golden"
# Allow override via env var (useful when tests/ is ACL-protected)
GOLDEN_DIR = Path(os.environ.get("AI_GOLDEN_DIR", str(_DEFAULT_GOLDEN_DIR)))


def _golden_path(key: str) -> Path:
    """Return the full path for a golden file (key = basename without .json)."""
    return GOLDEN_DIR / f"{key}.json"


# ─────────────────────────────────────────────────────────────────────────────
# Load / Save
# ─────────────────────────────────────────────────────────────────────────────

def load_golden(key: str) -> Optional[Dict[str, Any]]:
    """Load a golden snapshot. Returns None if the file does not exist."""
    path = _golden_path(key)
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def save_golden(key: str, data: Dict[str, Any]) -> None:
    """Save / overwrite a golden snapshot file."""
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    path = _golden_path(key)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _build_snapshot(result: HarnessResult) -> Dict[str, Any]:
    """Build the dict that will be stored in the golden file."""
    return {
        "mode": result.mode,
        "provider": result.provider,
        "normalized": result.normalized or normalize_response(result.response_text),
        "markers_keys": sorted(result.markers.keys()),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Assert / Update
# ─────────────────────────────────────────────────────────────────────────────

def is_update_mode() -> bool:
    """Return True if golden files should be updated rather than compared."""
    return os.environ.get("AI_UPDATE_GOLDEN", "").lower() in ("1", "true", "yes")


def assert_golden(result: HarnessResult, key: str) -> None:
    """
    Compare a HarnessResult against the golden snapshot for `key`.

    - If AI_UPDATE_GOLDEN=1: writes the current result as the new golden (no assertion).
    - If the golden file does not exist: creates it and passes (first-run bootstrap).
    - Otherwise: asserts normalized response matches the stored snapshot.

    Raises AssertionError on mismatch.
    """
    snapshot = _build_snapshot(result)

    if is_update_mode():
        save_golden(key, snapshot)
        return

    existing = load_golden(key)
    if existing is None:
        # First run: bootstrap the golden file
        save_golden(key, snapshot)
        return

    # Compare normalized response (the main stability signal)
    expected_norm = existing.get("normalized", "")
    actual_norm = snapshot["normalized"]

    if actual_norm != expected_norm:
        raise AssertionError(
            f"Golden mismatch for {key!r}:\n"
            f"  Expected (golden): {expected_norm[:300]!r}\n"
            f"  Got (current):     {actual_norm[:300]!r}\n"
            f"\nTo update the golden file: AI_UPDATE_GOLDEN=1 pytest ..."
        )

    # Optionally check marker key presence (not values — too volatile for golden)
    expected_keys = set(existing.get("markers_keys", []))
    actual_keys = set(snapshot.get("markers_keys", []))
    if expected_keys and not expected_keys.issubset(actual_keys):
        missing = expected_keys - actual_keys
        raise AssertionError(
            f"Golden markers mismatch for {key!r}: "
            f"missing marker keys {missing}. "
            f"Got: {sorted(actual_keys)}"
        )
