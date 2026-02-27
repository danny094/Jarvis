"""
core/typedstate_skills.py — TypedState Skills Entity (C5)

Deterministic pipeline: raw skill dicts → SkillEntity → context string.

    installed_skills (List[Dict])
        └─ normalize()     → List[SkillEntity]
        └─ dedupe()        → List[SkillEntity]  (prefer active over draft)
        └─ top_k()         → List[SkillEntity]  (deterministic sort, bounded)
        └─ budget()        → List[SkillEntity]  (char-cap cut)
        └─ render_entity() → str per entity

Entry point: build_skills_context(installed_skills, mode, top_k_count, char_cap)

TYPEDSTATE_SKILLS_MODE:
  off    — return "" (pipeline not run)
  shadow — run pipeline, log diff, return "" (observe-only)
  active — return rendered pipeline output

Rollback: TYPEDSTATE_SKILLS_MODE=off (default)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import log_info, log_warn


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_CAPABILITIES = 5
_CHANNEL_VALUES = frozenset({"active", "draft"})
_SIG_STATUSES = frozenset({"verified", "unsigned", "invalid"})

_SECRET_KEYWORDS = frozenset({
    "secret", "api_key", "apikey", "token", "password", "credential",
    "auth", "bearer", "private_key", "access_key",
})


# ---------------------------------------------------------------------------
# SkillEntity — canonical, frozen, exactly 9 fields
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SkillEntity:
    """Canonical, immutable representation of a skill for TypedState context."""
    name: str
    channel: str               # "active" | "draft"
    capabilities: Tuple[str, ...]  # from triggers/description, sorted, max 5
    requires_secrets: bool     # gap_question set or secret keywords present
    required_packages: Tuple[str, ...]  # from manifest
    missing_packages: Tuple[str, ...]   # subset not installed (default: ())
    trust_level: str           # "trusted" | "untrusted" | "unverified"
    signature_status: str      # "verified" | "unsigned" | "invalid"
    state: str                 # "active" | "draft" | "broken" | "unknown"


# ---------------------------------------------------------------------------
# normalize helpers
# ---------------------------------------------------------------------------

def _derive_capabilities(raw: Dict[str, Any]) -> Tuple[str, ...]:
    """
    Extract capabilities from triggers + description.
    Result: sorted, unique, max _MAX_CAPABILITIES items.
    """
    candidates: List[str] = []

    # 1. Explicit triggers
    for t in raw.get("triggers", []) or []:
        t = str(t).strip()
        if t:
            candidates.append(t.lower())

    # 2. Description words (min 3 chars, alpha/digit/underscore only)
    desc = str(raw.get("description", "") or "")
    for word in re.split(r"[\s,;.]+", desc):
        word = re.sub(r"[^a-zA-Z0-9_äöüÄÖÜß]", "", word).strip()
        if len(word) >= 3:
            candidates.append(word.lower())

    # dedupe preserving insertion order, then sort and cap
    seen: set = set()
    unique: List[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)

    return tuple(sorted(unique)[:_MAX_CAPABILITIES])


def _derive_requires_secrets(raw: Dict[str, Any]) -> bool:
    """True if gap_question is set OR secret keywords appear in name/description."""
    if raw.get("gap_question"):
        return True
    combined = " ".join([
        str(raw.get("description", "") or ""),
        str(raw.get("name", "") or ""),
        str(raw.get("gap_question", "") or ""),
    ]).lower()
    return any(kw in combined for kw in _SECRET_KEYWORDS)


def _derive_trust_level(raw: Dict[str, Any]) -> str:
    """Derive trust from validation_score: >=0.9→trusted, <0.5→untrusted, else→unverified."""
    score = raw.get("validation_score")
    try:
        score = float(score)
    except (TypeError, ValueError):
        return "unverified"
    if score >= 0.9:
        return "trusted"
    if score < 0.5:
        return "untrusted"
    return "unverified"


def _derive_state(raw: Dict[str, Any]) -> str:
    """Map raw status/channel to canonical state enum."""
    status = str(raw.get("status", "") or "").lower()
    channel = str(raw.get("channel", "") or "").lower()
    if status == "broken":
        return "broken"
    if status in ("installed", "active") or channel == "active":
        return "active"
    if status == "draft" or channel == "draft":
        return "draft"
    return "unknown"


# ---------------------------------------------------------------------------
# normalize — raw dict → SkillEntity
# ---------------------------------------------------------------------------

def normalize(raw: Dict[str, Any]) -> SkillEntity:
    """
    Convert a raw skill dict to a SkillEntity.
    Deterministic: no I/O, no side effects, no randomness.
    """
    name = str(raw.get("name", "unknown") or "unknown").strip()

    raw_channel = str(raw.get("channel", "active") or "active").lower()
    channel = raw_channel if raw_channel in _CHANNEL_VALUES else "active"

    capabilities = _derive_capabilities(raw)
    requires_secrets = _derive_requires_secrets(raw)

    # required_packages: from explicit field or default_params keys
    req_pkgs_raw = raw.get("required_packages") or []
    if not req_pkgs_raw:
        dp = raw.get("default_params")
        req_pkgs_raw = list(dp.keys()) if isinstance(dp, dict) else []
    required_packages = tuple(sorted(str(p) for p in req_pkgs_raw if p))

    missing_packages: Tuple[str, ...] = tuple()  # runtime check not done here

    trust_level = _derive_trust_level(raw)

    raw_sig = str(raw.get("signature_status", "unsigned") or "unsigned").lower()
    signature_status = raw_sig if raw_sig in _SIG_STATUSES else "unsigned"

    state = _derive_state(raw)

    return SkillEntity(
        name=name,
        channel=channel,
        capabilities=capabilities,
        requires_secrets=requires_secrets,
        required_packages=required_packages,
        missing_packages=missing_packages,
        trust_level=trust_level,
        signature_status=signature_status,
        state=state,
    )


# ---------------------------------------------------------------------------
# dedupe — prefer active over draft for same name
# ---------------------------------------------------------------------------

def dedupe(entities: List[SkillEntity]) -> List[SkillEntity]:
    """
    Deduplicate by name. Active channel wins over draft.
    Output is sorted by name for deterministic ordering.
    """
    by_name: Dict[str, SkillEntity] = {}
    for e in entities:
        existing = by_name.get(e.name)
        if existing is None:
            by_name[e.name] = e
        elif existing.channel == "draft" and e.channel == "active":
            by_name[e.name] = e
        # else: keep existing (active stays, or first-seen if same channel)
    return sorted(by_name.values(), key=lambda e: e.name)


# ---------------------------------------------------------------------------
# top_k — deterministic sort, bounded
# ---------------------------------------------------------------------------

_STATE_ORDER = {"active": 0, "draft": 1, "broken": 2, "unknown": 3}
_TRUST_ORDER = {"trusted": 0, "unverified": 1, "untrusted": 2}


def top_k(entities: List[SkillEntity], k: int) -> List[SkillEntity]:
    """
    Return top-k entities using a fully deterministic sort:
      1. state:      active < draft < broken < unknown
      2. trust_level: trusted < unverified < untrusted
      3. name:        alphabetical (tie-breaker)
    k <= 0 returns empty list.
    """
    if k <= 0:
        return []
    sorted_entities = sorted(
        entities,
        key=lambda e: (
            _STATE_ORDER.get(e.state, 3),
            _TRUST_ORDER.get(e.trust_level, 1),
            e.name,
        ),
    )
    return sorted_entities[:k]


# ---------------------------------------------------------------------------
# budget — char-cap cut
# ---------------------------------------------------------------------------

def budget(entities: List[SkillEntity], char_cap: int) -> List[SkillEntity]:
    """
    Cut entity list to fit within char_cap rendered characters.
    char_cap <= 0 → return all entities unchanged.
    """
    if char_cap <= 0:
        return list(entities)
    result: List[SkillEntity] = []
    total = 0
    for e in entities:
        rendered = render_entity(e)
        cost = len(rendered) + 1  # +1 for newline separator
        if total + cost > char_cap:
            break
        result.append(e)
        total += cost
    return result


# ---------------------------------------------------------------------------
# render_entity — single SkillEntity → compact context line
# ---------------------------------------------------------------------------

def render_entity(entity: SkillEntity) -> str:
    """
    Render one SkillEntity as a compact context line.
    Format: SKILL: {name} [{channel}] cap={...} secrets={yes|no} trust={level}
    """
    caps = ",".join(entity.capabilities) if entity.capabilities else "-"
    secrets = "yes" if entity.requires_secrets else "no"
    line = (
        f"SKILL: {entity.name} [{entity.channel}]"
        f" cap={caps} secrets={secrets} trust={entity.trust_level}"
    )
    if entity.required_packages:
        line += f" pkgs={','.join(entity.required_packages)}"
    if entity.missing_packages:
        line += f" MISSING={','.join(entity.missing_packages)}"
    return line


# ---------------------------------------------------------------------------
# build_skills_context — full pipeline entry point
# ---------------------------------------------------------------------------

def build_skills_context(
    installed_skills: List[Dict[str, Any]],
    mode: str,
    *,
    top_k_count: int = 10,
    char_cap: int = 2000,
) -> str:
    """
    Full pipeline: normalize → dedupe → top_k → budget → render.

    mode:
      "off"    — return "" immediately (pipeline not run)
      "shadow" — run pipeline, log result count, return "" (observe-only)
      "active" — run pipeline, return rendered context string

    installed_skills: list of raw skill dicts from skill_manager / installed.json.
    """
    if mode == "off":
        return ""

    try:
        entities = [normalize(s) for s in installed_skills]
        entities = dedupe(entities)
        entities = top_k(entities, top_k_count)
        entities = budget(entities, char_cap)
    except Exception as exc:
        log_warn(f"[TypedStateSkills] pipeline error: {exc}")
        return ""

    if mode == "shadow":
        log_info(
            f"[TypedStateSkills] shadow mode:"
            f" {len(entities)} entities after pipeline"
            f" (top_k={top_k_count}, char_cap={char_cap})"
        )
        return ""

    # mode == "active"
    if not entities:
        return ""

    lines = ["SKILLS:"]
    for e in entities:
        lines.append(f"  - {render_entity(e)}")
    return "\n".join(lines)
