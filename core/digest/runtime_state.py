"""
core/digest/runtime_state.py — Persistent run-state for digest pipeline (Phase 8 Operational).

State file: JSON at DIGEST_STATE_PATH (default: memory_speicher/digest_state.json).
All reads/writes are atomic (write to .tmp then os.replace).

Logging marker: [DigestRuntime]

Schema v2 (schema_version=2):
{
  "schema_version": 2,
  "daily":   { "last_run", "status", "duration_s", "input_events", "digest_written",
               "digest_key", "reason", "retry_policy" },
  "weekly":  { ... same ... },
  "archive": { ... same ... },
  "catch_up": {
    "last_run", "days_processed", "written", "status",
    "missed_runs", "recovered", "generated", "mode"
  },
  "jit": { "trigger": str|null, "rows": int|null, "ts": ISO|null }
}

Backward compat (v1 → v2 migration):
  Old flat jit_last_* fields are promoted to the jit block on first read.
  Old catch_up fields are preserved; new fields default to zero/None.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from utils.logger import log_info, log_warn

_SCHEMA_VERSION = 2

_EMPTY_CYCLE: Dict[str, Any] = {
    "last_run":       None,
    "status":         "never",
    "duration_s":     None,
    "input_events":   None,
    "digest_written": None,
    "digest_key":     None,
    "reason":         None,
    "retry_policy":   None,
}


# ── Migration ─────────────────────────────────────────────────────────────────

def _migrate_state(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Upgrade a state dict to schema v2 in-place.
    Safe to call on already-v2 dicts (no-op for fields already present).
    """
    empty = _empty_state_v2()

    # Promote flat jit_last_* → jit block (v1 → v2)
    if "jit" not in raw:
        raw["jit"] = {
            "trigger": raw.pop("jit_last_trigger", None),
            "rows":    raw.pop("jit_last_rows", None),
            "ts":      raw.pop("jit_last_ts", None),
        }
    else:
        # Remove legacy flat fields if jit block already exists
        raw.pop("jit_last_trigger", None)
        raw.pop("jit_last_rows", None)
        raw.pop("jit_last_ts", None)

    # Extend cycle dicts with new v2 fields
    for cycle in ("daily", "weekly", "archive"):
        if cycle not in raw:
            raw[cycle] = dict(_EMPTY_CYCLE)
        else:
            raw[cycle].setdefault("reason", None)
            raw[cycle].setdefault("retry_policy", None)

    # Extend catch_up with new v2 fields
    cu = raw.setdefault("catch_up", dict(empty["catch_up"]))
    cu.setdefault("missed_runs", 0)
    cu.setdefault("recovered", None)
    cu.setdefault("generated", 0)
    cu.setdefault("mode", "off")

    raw["schema_version"] = _SCHEMA_VERSION
    return raw


def _empty_state_v2() -> Dict[str, Any]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "daily":          dict(_EMPTY_CYCLE),
        "weekly":         dict(_EMPTY_CYCLE),
        "archive":        dict(_EMPTY_CYCLE),
        "catch_up": {
            "last_run":       None,
            "days_processed": 0,
            "written":        0,
            "status":         "never",
            "missed_runs":    0,
            "recovered":      None,
            "generated":      0,
            "mode":           "off",
        },
        "jit": {
            "trigger": None,
            "rows":    None,
            "ts":      None,
        },
    }


# ── Path helpers ──────────────────────────────────────────────────────────────

def _resolve(path: str) -> str:
    if os.path.isabs(path):
        return path
    base = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    return os.path.join(base, path)


def _state_path() -> str:
    try:
        from config import get_digest_state_path
        return _resolve(get_digest_state_path())
    except Exception:
        return _resolve("memory_speicher/digest_state.json")


# ── Read / write ──────────────────────────────────────────────────────────────

def _empty_state() -> Dict[str, Any]:
    return _empty_state_v2()


def _read_state() -> Dict[str, Any]:
    path = _state_path()
    if not os.path.exists(path):
        return _empty_state()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _empty_state()
        # Migrate v1 → v2 on read (idempotent for v2)
        return _migrate_state(data)
    except Exception as exc:
        log_warn(f"[DigestRuntime] Failed to read state from {path}: {exc}")
        return _empty_state()


def _write_state(state: Dict[str, Any]) -> bool:
    path = _state_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        dir_ = os.path.dirname(path)
        fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, default=str)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise
        return True
    except Exception as exc:
        log_warn(f"[DigestRuntime] Failed to write state to {path}: {exc}")
        return False


# ── Public API ────────────────────────────────────────────────────────────────

def get_state() -> Dict[str, Any]:
    """Return current runtime state (read from disk). Process-safe; read-only."""
    return _read_state()


def update_cycle(
    cycle: str,   # "daily" | "weekly" | "archive"
    *,
    status: str,
    duration_s: Optional[float] = None,
    input_events: Optional[int] = None,
    digest_written: Optional[int] = None,
    digest_key: Optional[str] = None,
    reason: Optional[str] = None,
    retry_policy: Optional[str] = None,
) -> bool:
    """Update a single cycle (daily/weekly/archive) with run results."""
    now_iso = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
    state = _read_state()
    state.setdefault(cycle, dict(_EMPTY_CYCLE))
    state[cycle].update({
        "last_run":       now_iso,
        "status":         status,
        "duration_s":     duration_s,
        "input_events":   input_events,
        "digest_written": digest_written,
        "digest_key":     digest_key,
        "reason":         reason,
        "retry_policy":   retry_policy,
    })
    ok = _write_state(state)
    log_info(
        f"[DigestRuntime] cycle={cycle} status={status} "
        f"written={digest_written} duration_s={duration_s} reason={reason}"
    )
    return ok


def update_catch_up(
    *,
    days_processed: int,
    written: int,
    status: str,
    missed_runs: int = 0,
    recovered: Optional[bool] = None,
    generated: int = 0,
    mode: str = "off",
) -> bool:
    """Update catch-up summary in state (v2: richer semantic fields)."""
    now_iso = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
    state = _read_state()
    state["catch_up"] = {
        "last_run":       now_iso,
        "days_processed": days_processed,
        "written":        written,
        "status":         status,
        "missed_runs":    missed_runs,
        "recovered":      recovered,
        "generated":      generated,
        "mode":           mode,
    }
    return _write_state(state)


def update_jit(*, trigger: Optional[str], rows: int) -> bool:
    """Update JIT CSV-load telemetry (v2: structured jit block)."""
    now_iso = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
    state = _read_state()
    state.setdefault("jit", {})
    state["jit"].update({
        "trigger": trigger,
        "rows":    rows,
        "ts":      now_iso,
    })
    # Remove legacy flat fields if somehow still present
    state.pop("jit_last_trigger", None)
    state.pop("jit_last_rows", None)
    state.pop("jit_last_ts", None)
    return _write_state(state)
