"""
tool_executor/engine/skill_registry_store.py — Skill Registry Truth Store
==========================================================================
Single responsibility: atomic reads and writes of installed.json.

V2 envelope shape:
    {
        "schema_version": 2,
        "skill_registry_hash": "<sha256-64>",
        "skills": { "<skill_name>": { ... } }
    }

Legacy shape (flat dict): { "<skill_name>": { ... } }
→ transparently migrated to V2 on next write.

[SkillTruth] markers emitted to stdout for observability.
No path/secret leaks in markers.

Rollback:
    SKILL_REGISTRY_SCHEMA_VERSION=1  →  writes legacy flat dict (no envelope)
    SKILL_GRAPH_RECONCILE=false      →  skip reconcile gating (see config)
    SKILL_KEY_MODE=legacy            →  disable key-based dedupe/normalization
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = 2


# ─────────────────────────────────────────────────────────────────────────────
# Hash
# ─────────────────────────────────────────────────────────────────────────────

def compute_registry_hash(skills_map: Dict[str, Any], schema_version: int = SCHEMA_VERSION) -> str:
    """
    Stable, deterministic sha256 over the canonical serialization of skills.

    Canonical payload:
        json.dumps({"schema_version": schema_version, "skills": skills_map},
                   sort_keys=True, separators=(",", ":"))

    Deliberately excludes skill_registry_hash itself (no circular dependency).
    Drift-sensitive: any change in keys or values changes the hash.
    """
    canonical = json.dumps(
        {"schema_version": schema_version, "skills": skills_map},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Normalizer
# ─────────────────────────────────────────────────────────────────────────────

def normalize_legacy_or_v2(raw: Any) -> Tuple[Dict[str, Any], bool]:
    """
    Accept both legacy flat dict and V2 envelope.

    Returns:
        (skills_map, migrated_legacy)
        - skills_map: flat { skill_name: {...} } — backward compat for all callers
        - migrated_legacy: True if input was a legacy flat dict
    """
    if not isinstance(raw, dict):
        return {}, False

    if raw.get("schema_version") == SCHEMA_VERSION and "skills" in raw:
        # V2 envelope — already normalized
        skills = raw.get("skills", {})
        if not isinstance(skills, dict):
            skills = {}
        return skills, False

    # Legacy: top-level keys are skill names.
    # Guard: any non-dict value → treat as empty (corrupt or unknown structure).
    if all(isinstance(v, dict) for v in raw.values()):
        return dict(raw), True

    return {}, False


# ─────────────────────────────────────────────────────────────────────────────
# Skill-Key helpers (C4)
# ─────────────────────────────────────────────────────────────────────────────

def make_skill_key(name: str, channel: str = "active", mode: str = "name") -> str:
    """
    Compute the stable identity key for a skill record.

    mode='name' (default): key = normalized name (lowercase, underscores).
    mode='legacy':         key = name as-is (no normalization enforced).

    channel is carried for future multi-channel keying but not used in
    either current mode — skill_key is always name-scoped.
    """
    if mode == "legacy":
        return name
    return name.lower().replace("-", "_").replace(" ", "_")


def dedupe_latest_by_skill_key(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Given a list of skill record dicts, keep exactly one per unique skill_key —
    the most recent one.

    'Most recent' ordering:
        1. updated_at  (ISO-8601 string — lexicographic sort works correctly)
        2. revision    (int — higher wins)
        3. name        (lexicographic ascending — deterministic tie-break)

    Records with no skill_key (or empty skill_key) are dropped.
    """
    best: Dict[str, Dict[str, Any]] = {}
    for rec in records:
        key = rec.get("skill_key") or ""
        if not key:
            continue
        if key not in best:
            best[key] = rec
        else:
            existing = best[key]
            rec_ua = str(rec.get("updated_at") or "")
            ex_ua = str(existing.get("updated_at") or "")
            rec_rev = int(rec.get("revision") or 1)
            ex_rev = int(existing.get("revision") or 1)
            rec_name = str(rec.get("name") or "")
            ex_name = str(existing.get("name") or "")
            # Primary: higher updated_at wins (ISO-8601 lex sort)
            # Secondary: higher revision wins
            # Tie-break: lexicographically smaller name wins (ascending, deterministic)
            if (rec_ua, rec_rev) > (ex_ua, ex_rev):
                best[key] = rec
            elif (rec_ua, rec_rev) == (ex_ua, ex_rev) and rec_name < ex_name:
                best[key] = rec
    return list(best.values())


def _normalize_for_write(
    skills_map: Dict[str, Any], mode: str = "name"
) -> Dict[str, Any]:
    """
    Ensure every skill record has canonical C4 fields before writing to disk.

    Fields added/defaulted (only when absent, no overwrite):
        skill_key  — computed deterministically from name + mode
        name       — from the dict key if missing in record
        channel    — default "active"
        revision   — default 1

    updated_at is intentionally NOT defaulted here; callers (installer) set it
    explicitly so the hash stays stable for unchanged records.

    If mode='name': apply dedupe_latest_by_skill_key (keeps newest per key).
    If mode='legacy': no dedupe — return map with fields added, order preserved.
    """
    annotated: List[Tuple[str, Dict[str, Any]]] = []
    for name, record in skills_map.items():
        rec = dict(record)
        rec.setdefault("name", name)
        rec.setdefault("channel", "active")
        rec.setdefault("revision", 1)
        # Preserve existing skill_key if already set (e.g., by installer);
        # only compute from name when absent.
        if not rec.get("skill_key"):
            rec["skill_key"] = make_skill_key(
                rec.get("name", name), rec.get("channel", "active"), mode
            )
        annotated.append((name, rec))

    if mode == "name":
        deduped = dedupe_latest_by_skill_key([r for _, r in annotated])
        result: Dict[str, Any] = {}
        for rec in deduped:
            key_name = str(rec.get("name") or "")
            if key_name:
                result[key_name] = rec
        return result
    else:
        return {name: rec for name, rec in annotated}


# ─────────────────────────────────────────────────────────────────────────────
# Load (fail-safe read, no exception propagated)
# ─────────────────────────────────────────────────────────────────────────────

def load_registry(path: "str | Path") -> Dict[str, Any]:
    """
    Load installed.json and return the normalized skills flat-map.
    Returns {} on missing file or parse error.
    Emits [SkillTruth] read marker (no path leak, only file name).
    """
    p = Path(path)
    if not p.exists():
        return {}

    try:
        with open(p, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as exc:
        print(f"[SkillTruth] read_error file={p.name} err={exc}")
        return {}

    skills, migrated = normalize_legacy_or_v2(raw)
    schema = raw.get("schema_version", "legacy") if isinstance(raw, dict) else "legacy"
    raw_hash = raw.get("skill_registry_hash", "–") if isinstance(raw, dict) else "–"
    hash_prefix = raw_hash[:12] if isinstance(raw_hash, str) and raw_hash != "–" else "–"

    print(
        f"[SkillTruth] read schema={schema} hash={hash_prefix}"
        f" skills_count={len(skills)} migrated_legacy={migrated}"
    )
    return skills


# ─────────────────────────────────────────────────────────────────────────────
# Save (atomic write, POSIX rename guarantee)
# ─────────────────────────────────────────────────────────────────────────────

def save_registry_atomic(
    path: "str | Path",
    skills_map: Dict[str, Any],
    mode: Optional[str] = None,
) -> None:
    """
    Write skills_map as a V2 envelope to path atomically.

    mode: 'name' (default) or 'legacy' — controls field normalization and dedupe.
          Falls back to SKILL_KEY_MODE env var when not passed explicitly.

    Strategy:
        1. Normalize fields + optional dedupe (controlled by mode)
        2. Compute hash over normalized skills_map
        3. Build V2 envelope
        4. Write to tmp file (same directory → same filesystem → atomic rename)
        5. fsync
        6. os.replace(tmp, target)  ← atomic on POSIX, never partial write on target

    Raises on failure — caller treats as hard error.
    Emits [SkillTruth] write_atomic=ok/fail marker.
    """
    if mode is None:
        mode = os.getenv("SKILL_KEY_MODE", "name").lower()

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    # Normalize fields and apply dedupe (mode-controlled)
    skills_map = _normalize_for_write(skills_map, mode=mode)

    h = compute_registry_hash(skills_map)
    envelope: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "skill_registry_hash": h,
        "skills": skills_map,
    }
    payload = json.dumps(envelope, indent=2, sort_keys=False, ensure_ascii=True)

    tmp_path: Optional[Path] = None
    try:
        fd, tmp_str = tempfile.mkstemp(
            dir=p.parent, prefix=".installed_tmp_", suffix=".json"
        )
        tmp_path = Path(tmp_str)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(p))
        tmp_path = None  # Renamed — no cleanup needed

        print(
            f"[SkillTruth] write_atomic=ok schema=v{SCHEMA_VERSION}"
            f" hash={h[:12]} skills_count={len(skills_map)}"
        )
    except Exception as exc:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        print(f"[SkillTruth] write_atomic=fail err={exc}")
        raise
