import os

# ═══════════════════════════════════════════════════════════════
# CORS
# ═══════════════════════════════════════════════════════════════
ALLOW_ORIGINS = [
    "http://localhost:8400",
    "http://localhost:8100",
]

# ═══════════════════════════════════════════════════════════════
from utils.settings import settings

# ═══════════════════════════════════════════════════════════════
# SERVICES
# ═══════════════════════════════════════════════════════════════
OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://host.docker.internal:11434")
MCP_BASE = os.getenv("MCP_BASE", "http://mcp-sql-memory:8081")
VALIDATOR_URL = os.getenv("VALIDATOR_URL", "http://validator-service:8000")

# ═══════════════════════════════════════════════════════════════
# MODEL KONFIGURATION (Dynamic)
# ═══════════════════════════════════════════════════════════════

def get_thinking_model():
    return settings.get("THINKING_MODEL", os.getenv("THINKING_MODEL", "deepseek-r1:8b"))

def get_control_model():
    return settings.get("CONTROL_MODEL", os.getenv("CONTROL_MODEL", "ministral-3:8b"))

def get_output_model():
    return settings.get("OUTPUT_MODEL", os.getenv("OUTPUT_MODEL", "ministral-3:3b"))

# Backward compatibility (Module level vars will be static on import, so use functions where possible)
# OR use a class/property trick. For now, we expose functions but keep vars for legacy.
THINKING_MODEL = get_thinking_model()
CONTROL_MODEL = get_control_model()
OUTPUT_MODEL = get_output_model()

# Embedding Model für Semantic Search
# Embedding Model für Semantic Search
EMBEDDING_MODEL = settings.get("EMBEDDING_MODEL", os.getenv("EMBEDDING_MODEL", "hellord/mxbai-embed-large-v1:f16"))

# ═══════════════════════════════════════════════════════════════
# TOOL SELECTOR (Layer 0)
# ═══════════════════════════════════════════════════════════════
def get_tool_selector_model():
    return settings.get("TOOL_SELECTOR_MODEL", os.getenv("TOOL_SELECTOR_MODEL", "qwen2.5:1.5b-instruct"))

TOOL_SELECTOR_MODEL = get_tool_selector_model()
ENABLE_TOOL_SELECTOR = settings.get("ENABLE_TOOL_SELECTOR", os.getenv("ENABLE_TOOL_SELECTOR", "true").lower() == "true")

# ═══════════════════════════════════════════════════════════════
# LAYER TOGGLES & OPTIMIERUNG
# ═══════════════════════════════════════════════════════════════

# ControlLayer komplett deaktivieren
ENABLE_CONTROL_LAYER = settings.get("ENABLE_CONTROL_LAYER", os.getenv("ENABLE_CONTROL_LAYER", "true").lower() == "true")

# ControlLayer bei low-risk überspringen (Speed-Optimierung!)
SKIP_CONTROL_ON_LOW_RISK = settings.get("SKIP_CONTROL_ON_LOW_RISK", os.getenv("SKIP_CONTROL_ON_LOW_RISK", "false").lower() == "true")

# ═══════════════════════════════════════════════════════════════
# VALIDATOR SERVICE
# ═══════════════════════════════════════════════════════════════
ENABLE_VALIDATION = settings.get("ENABLE_VALIDATION", os.getenv("ENABLE_VALIDATION", "true").lower() == "true")
VALIDATION_THRESHOLD = float(settings.get("VALIDATION_THRESHOLD", os.getenv("VALIDATION_THRESHOLD", "0.70")))
VALIDATION_HARD_FAIL = settings.get("VALIDATION_HARD_FAIL", os.getenv("VALIDATION_HARD_FAIL", "true").lower() == "true")

# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*")
ENABLE_CORS = os.getenv("ENABLE_CORS", "true").lower() == "true"

# ═══════════════════════════════════════════════════════════════
# CHUNKING CONFIGURATION
# ═══════════════════════════════════════════════════════════════

# Ab wann wird ein Text gechunked (Token-Schätzung)
CHUNKING_THRESHOLD = int(os.getenv("CHUNKING_THRESHOLD", "6000"))

# Maximale Tokens pro Chunk
CHUNK_MAX_TOKENS = int(os.getenv("CHUNK_MAX_TOKENS", "4000"))

# Overlap zwischen Chunks für Kontexterhalt
CHUNK_OVERLAP_TOKENS = int(os.getenv("CHUNK_OVERLAP_TOKENS", "200"))

# Workspace-Pfad für Session-Daten
WORKSPACE_BASE = os.getenv("WORKSPACE_BASE", "/tmp/trion/jarvis/workspace")

# Chunking aktivieren/deaktivieren
ENABLE_CHUNKING = os.getenv("ENABLE_CHUNKING", "true").lower() == "true"

# ═══════════════════════════════════════════════════════════════
# SMALL-MODEL MODE (Compact NOW/RULES/NEXT context)
# ═══════════════════════════════════════════════════════════════

# Master toggle: activates compact context injection for small/constrained models
def get_small_model_mode() -> bool:
    return settings.get("SMALL_MODEL_MODE", os.getenv("SMALL_MODEL_MODE", "false")).lower() == "true"

SMALL_MODEL_MODE = get_small_model_mode()

# Hard limits for compact context sections (overridable at runtime)
def get_small_model_now_max() -> int:
    return int(settings.get("SMALL_MODEL_NOW_MAX", os.getenv("SMALL_MODEL_NOW_MAX", "5")))

def get_small_model_rules_max() -> int:
    return int(settings.get("SMALL_MODEL_RULES_MAX", os.getenv("SMALL_MODEL_RULES_MAX", "3")))

def get_small_model_next_max() -> int:
    return int(settings.get("SMALL_MODEL_NEXT_MAX", os.getenv("SMALL_MODEL_NEXT_MAX", "2")))

SMALL_MODEL_NOW_MAX = get_small_model_now_max()
SMALL_MODEL_RULES_MAX = get_small_model_rules_max()
SMALL_MODEL_NEXT_MAX = get_small_model_next_max()

# JIT Retrieval budget: how many workspace_event_list fetches per turn
def get_jit_retrieval_max() -> int:
    return int(settings.get("JIT_RETRIEVAL_MAX", os.getenv("JIT_RETRIEVAL_MAX", "1")))

def get_jit_retrieval_max_on_failure() -> int:
    return int(settings.get("JIT_RETRIEVAL_MAX_ON_FAILURE", os.getenv("JIT_RETRIEVAL_MAX_ON_FAILURE", "2")))

JIT_RETRIEVAL_MAX = get_jit_retrieval_max()
JIT_RETRIEVAL_MAX_ON_FAILURE = get_jit_retrieval_max_on_failure()

# Context trace dry-run: when True, both new and legacy paths are built,
# diff is logged, but legacy result is returned. Default: False.
def get_context_trace_dryrun() -> bool:
    return settings.get("CONTEXT_TRACE_DRYRUN", os.getenv("CONTEXT_TRACE_DRYRUN", "false")).lower() == "true"

CONTEXT_TRACE_DRYRUN = get_context_trace_dryrun()

# ═══════════════════════════════════════════════════════════════
# SMALL-MODEL DETERMINISM (Hard Cap + Policy Knobs)
# ═══════════════════════════════════════════════════════════════

# Hard char cap for effective context in small mode.
# Allowed band: 1800–2200. Values outside are clamped.
def get_small_model_char_cap() -> int:
    val = int(settings.get("SMALL_MODEL_CHAR_CAP", os.getenv("SMALL_MODEL_CHAR_CAP", "2000")))
    return max(1800, min(2200, val))

SMALL_MODEL_CHAR_CAP = get_small_model_char_cap()

# Skill prefetch policy in small mode: "off" (default) | "thin"
# "off"  → no skill context injected before ThinkingLayer (unless explicit skill-intent signal)
# "thin" → injected only on explicit skill-intent signal; capped at SKILL_PREFETCH_THIN_CAP chars
def get_small_model_skill_prefetch_policy() -> str:
    return settings.get(
        "SMALL_MODEL_SKILL_PREFETCH_POLICY",
        os.getenv("SMALL_MODEL_SKILL_PREFETCH_POLICY", "off")
    ).lower()

SMALL_MODEL_SKILL_PREFETCH_POLICY = get_small_model_skill_prefetch_policy()

# Char budget for thin skill prefetch (top-1 skill equivalent)
def get_small_model_skill_prefetch_thin_cap() -> int:
    return int(settings.get(
        "SMALL_MODEL_SKILL_PREFETCH_THIN_CAP",
        os.getenv("SMALL_MODEL_SKILL_PREFETCH_THIN_CAP", "400")
    ))

SMALL_MODEL_SKILL_PREFETCH_THIN_CAP = get_small_model_skill_prefetch_thin_cap()

# Detection rules policy in small mode: "off" | "thin" (default) | "full"
# "off"  → no detection rules injected (maximum strictness)
# "thin" → safety-critical rules only (memory + container), hard line+char cap
# "full" → all core + custom MCP rules (current behaviour)
def get_small_model_detection_rules_policy() -> str:
    return settings.get(
        "SMALL_MODEL_DETECTION_RULES_POLICY",
        os.getenv("SMALL_MODEL_DETECTION_RULES_POLICY", "thin")
    ).lower()

SMALL_MODEL_DETECTION_RULES_POLICY = get_small_model_detection_rules_policy()

# Hard limits for thin detection rules injection
def get_small_model_detection_rules_thin_lines() -> int:
    return int(settings.get(
        "SMALL_MODEL_DETECTION_RULES_THIN_LINES",
        os.getenv("SMALL_MODEL_DETECTION_RULES_THIN_LINES", "12")
    ))

def get_small_model_detection_rules_thin_chars() -> int:
    return int(settings.get(
        "SMALL_MODEL_DETECTION_RULES_THIN_CHARS",
        os.getenv("SMALL_MODEL_DETECTION_RULES_THIN_CHARS", "600")
    ))

# ═══════════════════════════════════════════════════════════════
# PHASE 2.5: Final cap + Tool-Delta-Summary (small mode only)
# ═══════════════════════════════════════════════════════════════

# Hard cap for total context string (retrieved_memory / full_context) after ALL appends.
# 0 = disabled (default). Enable by setting e.g. SMALL_MODEL_FINAL_CAP=4096.
def get_small_model_final_cap() -> int:
    return int(settings.get(
        "SMALL_MODEL_FINAL_CAP",
        os.getenv("SMALL_MODEL_FINAL_CAP", "0")
    ))

# Cap for tool_context string BEFORE appending to context (tool-delta-summary).
# 0 = disabled (default). Enable by setting e.g. SMALL_MODEL_TOOL_CTX_CAP=2000.
# When triggered: raw output is truncated with a "[...truncated: N chars]" marker.
def get_small_model_tool_ctx_cap() -> int:
    return int(settings.get(
        "SMALL_MODEL_TOOL_CTX_CAP",
        os.getenv("SMALL_MODEL_TOOL_CTX_CAP", "0")
    ))

# ═══════════════════════════════════════════════════════════════
# TYPEDSTATE V1 (Commit 1: schema flag — no active wiring yet)
# ═══════════════════════════════════════════════════════════════

# Controls TypedState V1 schema activation mode:
# "off"    → V1 fields exist in schema but flow is not wired (default, safe)
# "shadow" → V1 fields populated in background; result not used for rendering
# "active" → V1 fields used for rendering decisions (future, Commit 2+)
def get_typedstate_mode() -> str:
    return settings.get(
        "TYPEDSTATE_MODE",
        os.getenv("TYPEDSTATE_MODE", "off")
    ).lower()

TYPEDSTATE_MODE = get_typedstate_mode()

# When True: TypedState V1 shadow/active wiring applies only in small-model mode.
# When False: applies in all modes (not recommended until stable).
def get_typedstate_enable_small_only() -> bool:
    return settings.get(
        "TYPEDSTATE_ENABLE_SMALL_ONLY",
        os.getenv("TYPEDSTATE_ENABLE_SMALL_ONLY", "true")
    ).lower() == "true"

TYPEDSTATE_ENABLE_SMALL_ONLY = get_typedstate_enable_small_only()

# ═══════════════════════════════════════════════════════════════
# TYPEDSTATE V1 — CSV Event Source (Commit 3)
# ═══════════════════════════════════════════════════════════════

# Path to the CSV file used as a supplementary fact/event source.
# Relative paths are resolved from the project root.
def get_typedstate_csv_path() -> str:
    return settings.get(
        "TYPEDSTATE_CSV_PATH",
        os.getenv("TYPEDSTATE_CSV_PATH", "memory_speicher/memory_150_rows.csv")
    )

# Master toggle for CSV event source integration.
# Default: false — CSV is NOT loaded unless explicitly enabled.
def get_typedstate_csv_enable() -> bool:
    return settings.get(
        "TYPEDSTATE_CSV_ENABLE",
        os.getenv("TYPEDSTATE_CSV_ENABLE", "false")
    ).lower() == "true"

# ═══════════════════════════════════════════════════════════════
# PHASE 6 — Signature Verify (container image)
# ═══════════════════════════════════════════════════════════════

# SIGNATURE_VERIFY_MODE controls image signature verification:
# "off"     → no verification (default, backwards-compatible)
# "opt_in"  → verify if signature present; reject on invalid, allow if absent
# "strict"  → signature required; reject if absent or invalid
def get_signature_verify_mode() -> str:
    return settings.get(
        "SIGNATURE_VERIFY_MODE",
        os.getenv("SIGNATURE_VERIFY_MODE", "off")
    ).lower()

SIGNATURE_VERIFY_MODE = get_signature_verify_mode()

# ═══════════════════════════════════════════════════════════════
# PHASE 8 — DIGEST PIPELINE
# All toggles default OFF → zero behaviour change on existing deployments.
# Rollback: DIGEST_ENABLE=false (master switch disables all digest features).
# ═══════════════════════════════════════════════════════════════

def get_digest_enable() -> bool:
    """Master toggle for all digest pipeline features (default: false)."""
    return settings.get(
        "DIGEST_ENABLE", os.getenv("DIGEST_ENABLE", "false")
    ).lower() == "true"

def get_digest_daily_enable() -> bool:
    """Enable daily 04:00 Europe/Berlin compression job (requires DIGEST_ENABLE=true)."""
    return get_digest_enable() and settings.get(
        "DIGEST_DAILY_ENABLE", os.getenv("DIGEST_DAILY_ENABLE", "false")
    ).lower() == "true"

def get_digest_weekly_enable() -> bool:
    """Enable rolling 7-day weekly digest built from daily_digests (requires DIGEST_ENABLE=true)."""
    return get_digest_enable() and settings.get(
        "DIGEST_WEEKLY_ENABLE", os.getenv("DIGEST_WEEKLY_ENABLE", "false")
    ).lower() == "true"

def get_digest_archive_enable() -> bool:
    """Enable archive_digest to Graph after 14 days (requires DIGEST_ENABLE=true)."""
    return get_digest_enable() and settings.get(
        "DIGEST_ARCHIVE_ENABLE", os.getenv("DIGEST_ARCHIVE_ENABLE", "false")
    ).lower() == "true"

def get_digest_tz() -> str:
    """IANA timezone name used for digest scheduling. Default: Europe/Berlin."""
    return settings.get("DIGEST_TZ", os.getenv("DIGEST_TZ", "Europe/Berlin"))

def get_digest_store_path() -> str:
    """Path to digest store CSV (daily/weekly/archive digest records).
    Relative paths resolved from project root."""
    return settings.get(
        "DIGEST_STORE_PATH",
        os.getenv("DIGEST_STORE_PATH", "memory_speicher/digest_store.csv")
    )

def get_typedstate_csv_jit_only() -> bool:
    """When True: CSV events only loaded on explicit JIT triggers (time_reference/remember/fact_recall).
    Default: false (load on every build_small_model_context call, existing behaviour)."""
    return settings.get(
        "TYPEDSTATE_CSV_JIT_ONLY",
        os.getenv("TYPEDSTATE_CSV_JIT_ONLY", "false")
    ).lower() == "true"

def get_digest_filters_enable() -> bool:
    """Enable time-window and conversation-scope filtering in CSV loading. Default: false."""
    return settings.get(
        "DIGEST_FILTERS_ENABLE",
        os.getenv("DIGEST_FILTERS_ENABLE", "false")
    ).lower() == "true"

def get_digest_dedupe_include_conv() -> bool:
    """When True: dedupe key includes conversation_id (cross-conversation safe). Default: true."""
    return settings.get(
        "DIGEST_DEDUPE_INCLUDE_CONV",
        os.getenv("DIGEST_DEDUPE_INCLUDE_CONV", "true")
    ).lower() == "true"

# ── Phase 8 Operational flags ──────────────────────────────────────────────

def get_digest_state_path() -> str:
    """Path to digest runtime state JSON. Default: memory_speicher/digest_state.json"""
    return settings.get(
        "DIGEST_STATE_PATH",
        os.getenv("DIGEST_STATE_PATH", "memory_speicher/digest_state.json")
    )

def get_digest_lock_path() -> str:
    """Path to digest file lock. Default: memory_speicher/digest.lock"""
    return settings.get(
        "DIGEST_LOCK_PATH",
        os.getenv("DIGEST_LOCK_PATH", "memory_speicher/digest.lock")
    )

def get_digest_lock_timeout_s() -> int:
    """Stale lock takeover threshold in seconds. Default: 300."""
    try:
        return int(settings.get(
            "DIGEST_LOCK_TIMEOUT_S",
            os.getenv("DIGEST_LOCK_TIMEOUT_S", "300")
        ))
    except Exception:
        return 300

def get_digest_run_mode() -> str:
    """Digest scheduling mode: 'off' | 'sidecar' | 'inline'. Default: off."""
    return settings.get(
        "DIGEST_RUN_MODE",
        os.getenv("DIGEST_RUN_MODE", "off")
    ).lower()

def get_digest_catchup_max_days() -> int:
    """Max days to catch up on restart. 0 = skip catch-up entirely. Default: 7."""
    try:
        return int(settings.get(
            "DIGEST_CATCHUP_MAX_DAYS",
            os.getenv("DIGEST_CATCHUP_MAX_DAYS", "7")
        ))
    except Exception:
        return 7

def get_digest_min_events_daily() -> int:
    """Min raw events required to produce a daily digest. 0 = no minimum. Default: 0."""
    try:
        return int(settings.get(
            "DIGEST_MIN_EVENTS_DAILY",
            os.getenv("DIGEST_MIN_EVENTS_DAILY", "0")
        ))
    except Exception:
        return 0

def get_digest_min_daily_per_week() -> int:
    """Min daily digests required to produce a weekly digest. 0 = no minimum. Default: 0."""
    try:
        return int(settings.get(
            "DIGEST_MIN_DAILY_PER_WEEK",
            os.getenv("DIGEST_MIN_DAILY_PER_WEEK", "0")
        ))
    except Exception:
        return 0

def get_digest_ui_enable() -> bool:
    """Show digest status panel in frontend. Default: false (feature flag)."""
    return settings.get(
        "DIGEST_UI_ENABLE",
        os.getenv("DIGEST_UI_ENABLE", "false")
    ).lower() == "true"

def get_jit_window_time_reference_h() -> int:
    """Hours window for time_reference JIT trigger (yesterday+today). Default: 48."""
    try:
        return int(settings.get(
            "JIT_WINDOW_TIME_REFERENCE_H",
            os.getenv("JIT_WINDOW_TIME_REFERENCE_H", "48")
        ))
    except Exception:
        return 48

def get_jit_window_fact_recall_h() -> int:
    """Hours window for fact_recall JIT trigger (7d). Default: 168."""
    try:
        return int(settings.get(
            "JIT_WINDOW_FACT_RECALL_H",
            os.getenv("JIT_WINDOW_FACT_RECALL_H", "168")
        ))
    except Exception:
        return 168

def get_jit_window_remember_h() -> int:
    """Hours window for remember JIT trigger (14d). Default: 336."""
    try:
        return int(settings.get(
            "JIT_WINDOW_REMEMBER_H",
            os.getenv("JIT_WINDOW_REMEMBER_H", "336")
        ))
    except Exception:
        return 336

# ── Phase 8 Operational Hardening ──────────────────────────────────────────

def get_digest_runtime_api_v2() -> bool:
    """Serve flat API v2 response shape from /api/runtime/digest-state. Default: true.
    Set DIGEST_RUNTIME_API_V2=false to fall back to legacy {state, flags, lock} shape."""
    return settings.get(
        "DIGEST_RUNTIME_API_V2",
        os.getenv("DIGEST_RUNTIME_API_V2", "true")
    ).lower() == "true"

def get_digest_jit_warn_on_disabled() -> bool:
    """Emit startup warning when JIT_ONLY=false with active digest pipeline. Default: true."""
    return settings.get(
        "DIGEST_JIT_WARN_ON_DISABLED",
        os.getenv("DIGEST_JIT_WARN_ON_DISABLED", "true")
    ).lower() == "true"

def get_digest_key_version() -> str:
    """Digest key version: 'v1' (default, backward-compat) or 'v2' (explicit window bounds).
    First run with v2 re-creates existing digests (idempotent). Default: v1."""
    return settings.get(
        "DIGEST_KEY_VERSION",
        os.getenv("DIGEST_KEY_VERSION", "v1")
    ).lower()
