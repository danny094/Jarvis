"""
utils/embedding_resolver.py — Embedding Execution Target Resolver

Determines which Ollama endpoint to use and what request options to apply
based on execution policy, target availability, and fallback rules.

Used by: core/lifecycle/archive.py (and any future main-service callers).
sql-memory/embedding.py inlines the same logic (separate container).

Scope 3.1 additions:
  - RoutingDecision TypedDict with requested_policy, requested_target,
    effective_target, fallback_reason, hard_error, error_code.
  - availability parameter: {"gpu": bool, "cpu": bool} — pre-flight health.
    None = assume all available (backward-compat default).
  - hard_error=True + error_code=503 when policy constraint cannot be met.
  - Backward-compat: all old dict keys still present in RoutingDecision.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

try:
    from typing import TypedDict
except ImportError:  # Python < 3.8
    from typing_extensions import TypedDict  # type: ignore[no-redef]

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_EXECUTION_MODE = "auto"
DEFAULT_FALLBACK_POLICY = "best_effort"
DEFAULT_ENDPOINT_MODE = "single"

VALID_EXECUTION_MODES = frozenset({"auto", "prefer_gpu", "cpu_only"})
VALID_FALLBACK_POLICIES = frozenset({"best_effort", "strict"})
VALID_ENDPOINT_MODES = frozenset({"single", "dual"})

_ALL_AVAILABLE: Dict[str, bool] = {"gpu": True, "cpu": True}


# ─────────────────────────────────────────────────────────────────────────────
# Decision object
# ─────────────────────────────────────────────────────────────────────────────

class RoutingDecision(TypedDict):
    # ── Scope 3.1 canonical fields ──────────────────────────────────────────
    requested_policy: str           # "auto" | "prefer_gpu" | "cpu_only"
    requested_target: str           # "gpu" | "cpu"  (primary preference)
    effective_target: Optional[str] # "gpu" | "cpu" | None (on hard_error)
    fallback_reason: Optional[str]  # e.g. "gpu_unavailable" | "all_unavailable"
    hard_error: bool                # True → caller should return 503
    error_code: Optional[int]       # 503 on hard_error, else None
    # ── Backward-compat fields (unchanged API from before Scope 3.1) ────────
    endpoint: Optional[str]         # Ollama URL to call (None on hard_error)
    options: dict                   # e.g. {"num_gpu": 0} or {}
    fallback_endpoint: Optional[str]
    fallback_policy: str
    reason: str                     # Human-readable routing explanation
    target: str                     # Alias for effective_target (backward compat)


# ─────────────────────────────────────────────────────────────────────────────
# Main resolver
# ─────────────────────────────────────────────────────────────────────────────

def resolve_embedding_target(
    mode: str,
    endpoint_mode: str,
    base_endpoint: str,
    gpu_endpoint: str,
    cpu_endpoint: str,
    fallback_policy: str,
    availability: Optional[Dict[str, bool]] = None,
    optional_pin: Optional[str] = None,
) -> RoutingDecision:
    """
    Resolve the embedding execution target.

    Args:
        mode:             "auto" | "prefer_gpu" | "cpu_only"
        endpoint_mode:    "single" | "dual"
        base_endpoint:    Ollama base URL (OLLAMA_BASE / OLLAMA_URL)
        gpu_endpoint:     Optional dedicated GPU endpoint (empty → base)
        cpu_endpoint:     Optional dedicated CPU endpoint (empty → base)
        fallback_policy:  "best_effort" | "strict"
        availability:     Optional {"gpu": bool, "cpu": bool}.
                          None = assume all available (backward-compat).
        optional_pin:     Optional target override ("gpu" | "cpu" | None)

    Returns:
        RoutingDecision with routing details + hard_error/error_code.

    Hard error rules (hard_error=True, error_code=503):
        - cpu_only: cpu unavailable (no GPU fallback)
        - prefer_gpu / auto: all targets unavailable
    """
    # ── Normalize inputs ───────────────────────────────────────────────────
    mode = (mode or DEFAULT_EXECUTION_MODE).strip().lower()
    endpoint_mode = (endpoint_mode or DEFAULT_ENDPOINT_MODE).strip().lower()
    fallback_policy = (fallback_policy or DEFAULT_FALLBACK_POLICY).strip().lower()

    if mode not in VALID_EXECUTION_MODES:
        mode = DEFAULT_EXECUTION_MODE
    if endpoint_mode not in VALID_ENDPOINT_MODES:
        endpoint_mode = DEFAULT_ENDPOINT_MODE
    if fallback_policy not in VALID_FALLBACK_POLICIES:
        fallback_policy = DEFAULT_FALLBACK_POLICY

    avail = dict(availability) if availability is not None else dict(_ALL_AVAILABLE)
    gpu_ok = bool(avail.get("gpu", True))
    cpu_ok = bool(avail.get("cpu", True))

    eff_gpu = (gpu_endpoint or "").strip()
    eff_cpu = (cpu_endpoint or "").strip()

    # ── cpu_only ──────────────────────────────────────────────────────────
    if mode == "cpu_only":
        if not cpu_ok:
            return RoutingDecision(
                requested_policy="cpu_only",
                requested_target="cpu",
                effective_target=None,
                fallback_reason="cpu_unavailable",
                hard_error=True,
                error_code=503,
                endpoint=None,
                options={},
                fallback_endpoint=None,
                fallback_policy=fallback_policy,
                reason="cpu_only→cpu_unavailable→hard_error_503",
                target="cpu",
            )
        if endpoint_mode == "dual" and eff_cpu:
            return RoutingDecision(
                requested_policy="cpu_only",
                requested_target="cpu",
                effective_target="cpu",
                fallback_reason=None,
                hard_error=False,
                error_code=None,
                endpoint=eff_cpu,
                options={},
                fallback_endpoint=None,
                fallback_policy=fallback_policy,
                reason="cpu_only/dual→cpu_endpoint",
                target="cpu",
            )
        return RoutingDecision(
            requested_policy="cpu_only",
            requested_target="cpu",
            effective_target="cpu",
            fallback_reason=None,
            hard_error=False,
            error_code=None,
            endpoint=base_endpoint,
            options={"num_gpu": 0},
            fallback_endpoint=None,
            fallback_policy=fallback_policy,
            reason="cpu_only/single→base+num_gpu=0",
            target="cpu",
        )

    # ── prefer_gpu / auto ─────────────────────────────────────────────────
    if gpu_ok:
        if endpoint_mode == "dual" and eff_gpu:
            fb_ep: Optional[str] = (
                (eff_cpu or base_endpoint) if fallback_policy == "best_effort" else None
            )
            return RoutingDecision(
                requested_policy=mode,
                requested_target="gpu",
                effective_target="gpu",
                fallback_reason=None,
                hard_error=False,
                error_code=None,
                endpoint=eff_gpu,
                options={},
                fallback_endpoint=fb_ep,
                fallback_policy=fallback_policy,
                reason=f"{mode}/dual→gpu_endpoint",
                target="gpu",
            )
        # Single mode — base endpoint; Ollama picks GPU by default
        return RoutingDecision(
            requested_policy=mode,
            requested_target="gpu",
            effective_target="gpu",
            fallback_reason=None,
            hard_error=False,
            error_code=None,
            endpoint=base_endpoint,
            options={},
            fallback_endpoint=None,
            fallback_policy=fallback_policy,
            reason=f"{mode}/single→base_endpoint",
            target="gpu",
        )

    # GPU unavailable → CPU fallback
    if cpu_ok:
        if endpoint_mode == "dual" and eff_cpu:
            cpu_ep = eff_cpu
            cpu_opts: dict = {}
        else:
            cpu_ep = base_endpoint
            cpu_opts = {"num_gpu": 0}
        return RoutingDecision(
            requested_policy=mode,
            requested_target="gpu",
            effective_target="cpu",
            fallback_reason="gpu_unavailable",
            hard_error=False,
            error_code=None,
            endpoint=cpu_ep,
            options=cpu_opts,
            fallback_endpoint=None,
            fallback_policy=fallback_policy,
            reason=f"{mode}→gpu_unavailable→cpu_fallback",
            target="cpu",
        )

    # All unavailable → hard error
    return RoutingDecision(
        requested_policy=mode,
        requested_target="gpu",
        effective_target=None,
        fallback_reason="all_unavailable",
        hard_error=True,
        error_code=503,
        endpoint=None,
        options={},
        fallback_endpoint=None,
        fallback_policy=fallback_policy,
        reason=f"{mode}→all_unavailable→hard_error_503",
        target="gpu",
    )
