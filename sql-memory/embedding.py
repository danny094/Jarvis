# sql-memory/embedding.py
"""
Embedding Client - Holt Embeddings von Ollama.

Model resolution precedence (per call, with short TTL cache):
  1. Settings API  (/api/settings/models/effective)  — when SETTINGS_API_URL is set
  2. EMBEDDING_MODEL env var
  3. Hardcoded default

Execution mode (GPU vs CPU) is resolved per-call via the inline
_inline_resolve_target() function, which mirrors utils/embedding_resolver.py
(inlined because sql-memory runs in a separate container).
"""

import os
import hashlib
import time
import threading
import requests
from typing import List, Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)
_ROUTING_LOG_LEVEL = str(
    os.getenv("EMBEDDING_ROUTING_LOG_LEVEL", "warning")
).strip().lower()

# ─────────────────────────────────────────────────────────────────────────────
# Service URLs
# ─────────────────────────────────────────────────────────────────────────────
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
SETTINGS_API_URL = os.getenv("SETTINGS_API_URL", "").strip()  # e.g. http://jarvis-admin-api:8200/api/settings
if not SETTINGS_API_URL:
    _admin_api = os.getenv("ADMIN_API_URL", os.getenv("JARVIS_ADMIN_API_URL", "http://jarvis-admin-api:8200")).rstrip("/")
    SETTINGS_API_URL = f"{_admin_api}/api/settings"

_EMBED_DEFAULT = os.getenv("EMBEDDING_MODEL", "hellord/mxbai-embed-large-v1:f16")
_CACHE_TTL = int(os.getenv("SETTINGS_CACHE_TTL", "60"))
_RUNTIME_CACHE_TTL = int(
    os.getenv("SETTINGS_RUNTIME_CACHE_TTL", os.getenv("SETTINGS_CACHE_TTL", "5"))
)
_RUNTIME_REFRESH_INTERVAL_S = max(
    2,
    int(os.getenv("SETTINGS_RUNTIME_REFRESH_INTERVAL_S", "15")),
)
_RUNTIME_FETCH_TIMEOUT_S = max(
    0.2,
    float(os.getenv("SETTINGS_RUNTIME_FETCH_TIMEOUT_S", "1.5")),
)
_ROUTE_FETCH_TIMEOUT_S = max(
    0.2,
    float(os.getenv("SETTINGS_ROUTE_FETCH_TIMEOUT_S", "1.0")),
)
_REFRESH_WARN_THROTTLE_S = 60.0

# ─────────────────────────────────────────────────────────────────────────────
# Runtime model resolver (Settings API → env → default)
# ─────────────────────────────────────────────────────────────────────────────
_cache: dict = {"value": None, "ts": 0.0}

# ─────────────────────────────────────────────────────────────────────────────
# Embedding runtime config (execution mode / endpoint routing)
# ─────────────────────────────────────────────────────────────────────────────
_RT_DEFAULTS = {
    "EMBEDDING_EXECUTION_MODE": "auto",
    "EMBEDDING_FALLBACK_POLICY": "best_effort",
    "EMBEDDING_GPU_ENDPOINT": "",
    "EMBEDDING_CPU_ENDPOINT": "",
    "EMBEDDING_ENDPOINT_MODE": "single",
}
_rt_cache: dict = {"config": None, "ts": 0.0}
_route_cache: dict = {"value": None, "ts": 0.0}
_refresh_state = {"started": False, "lock": threading.Lock()}
_warn_state = {"runtime": 0.0, "route": 0.0}


def _default_runtime_config() -> dict:
    cfg = {k: os.getenv(k, v) for k, v in _RT_DEFAULTS.items()}
    cfg["embedding_runtime_policy"] = os.getenv(
        "EMBEDDING_RUNTIME_POLICY",
        os.getenv("EMBEDDING_EXECUTION_MODE", "auto"),
    )
    if not cfg.get("embedding_runtime_policy"):
        cfg["embedding_runtime_policy"] = str(
            cfg.get("EMBEDDING_EXECUTION_MODE", "auto")
        ).strip().lower() or "auto"
    return cfg


def _warn_throttled(kind: str, msg: str) -> None:
    now = time.time()
    last = float(_warn_state.get(kind, 0.0))
    if (now - last) < _REFRESH_WARN_THROTTLE_S:
        return
    _warn_state[kind] = now
    logger.warning(msg)


def _refresh_runtime_config_once() -> None:
    cfg = _default_runtime_config()
    if SETTINGS_API_URL:
        try:
            resp = requests.get(
                f"{SETTINGS_API_URL}/embeddings/runtime",
                timeout=_RUNTIME_FETCH_TIMEOUT_S,
            )
            resp.raise_for_status()
            data = resp.json()
            effective = data.get("effective", {})
            for key in _RT_DEFAULTS:
                val = effective.get(key, {}).get("value", "")
                if val:
                    cfg[key] = val
            active_policy = str(data.get("runtime", {}).get("active_policy", "")).strip().lower()
            effective_policy = str(
                effective.get("embedding_runtime_policy", {}).get("value", "")
            ).strip().lower()
            if active_policy:
                cfg["embedding_runtime_policy"] = active_policy
            elif effective_policy:
                cfg["embedding_runtime_policy"] = effective_policy
        except Exception as e:
            _warn_throttled("runtime", f"[Embedding] runtime settings refresh failed: {e}")

    _rt_cache["config"] = cfg
    _rt_cache["ts"] = time.time()


def _refresh_route_once() -> None:
    base = _runtime_api_base()
    if not base:
        _route_cache["value"] = None
        _route_cache["ts"] = time.time()
        return
    try:
        resp = requests.get(f"{base}/api/runtime/compute/routing", timeout=_ROUTE_FETCH_TIMEOUT_S)
        resp.raise_for_status()
        data = resp.json()
        emb = (data.get("effective", {}) or {}).get("embedding", {}) or {}
        requested = str(emb.get("requested_target") or "auto").strip()
        effective = emb.get("effective_target")
        endpoint = emb.get("effective_endpoint")
        fallback_reason = emb.get("fallback_reason")
        hard_error = bool(requested != "auto" and not endpoint)
        _route_cache["value"] = {
            "requested_target": requested,
            "effective_target": effective,
            "endpoint": endpoint,
            "fallback_reason": fallback_reason,
            "hard_error": hard_error,
        }
        _route_cache["ts"] = time.time()
    except Exception as e:
        _warn_throttled("route", f"[Embedding] runtime route refresh failed: {e}")


def _runtime_refresh_loop() -> None:
    while True:
        try:
            _refresh_runtime_config_once()
            _refresh_route_once()
        except Exception:
            # fail-open: request path always has defaults/cached values
            pass
        time.sleep(_RUNTIME_REFRESH_INTERVAL_S)


def _ensure_runtime_refresh_worker() -> None:
    if _refresh_state["started"]:
        return
    with _refresh_state["lock"]:
        if _refresh_state["started"]:
            return
        thread = threading.Thread(
            target=_runtime_refresh_loop,
            daemon=True,
            name="embedding-runtime-refresh",
        )
        thread.start()
        _refresh_state["started"] = True


def _canonical_policy(runtime_cfg: Optional[dict] = None) -> str:
    cfg = runtime_cfg or _resolve_runtime_config()
    return str(
        cfg.get("embedding_runtime_policy") or cfg.get("EMBEDDING_EXECUTION_MODE") or "auto"
    ).strip().lower()


def compute_embedding_version_id(model: str, runtime_policy: str) -> str:
    """
    Deterministische Versions-ID fuer Embeddings.
    Hash-Basis: model + runtime policy.
    """
    model_norm = (model or "").strip()
    policy_norm = (runtime_policy or "auto").strip().lower()
    seed = f"{model_norm}|{policy_norm}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"embv1_{digest}"


def get_active_embedding_version() -> str:
    """Aktive embedding_version auf Basis der effektiven Runtime-Konfiguration."""
    model = _resolve_embedding_model()
    policy = _canonical_policy()
    return compute_embedding_version_id(model, policy)


def _resolve_embedding_model() -> str:
    """
    Resolve embedding model at runtime.

    Precedence:
      1. Settings API /models/effective (with _CACHE_TTL-second cache)
      2. EMBEDDING_MODEL env var (via _EMBED_DEFAULT)
      3. Hardcoded default

    Falls back silently on any API error so embeddings are never blocked.
    """
    now = time.time()
    if _cache["value"] is not None and (now - _cache["ts"]) < _CACHE_TTL:
        return _cache["value"]

    if SETTINGS_API_URL:
        try:
            resp = requests.get(
                f"{SETTINGS_API_URL}/models/effective",
                timeout=2,
            )
            resp.raise_for_status()
            data = resp.json()
            effective_val = data.get("effective", {}).get("EMBEDDING_MODEL", {}).get("value", "")
            if effective_val:
                _cache["value"] = effective_val
                _cache["ts"] = now
                return effective_val
        except Exception:
            pass  # fall through to env/default

    _cache["value"] = _EMBED_DEFAULT
    _cache["ts"] = now
    return _EMBED_DEFAULT


def _resolve_runtime_config() -> dict:
    """
    Resolve embedding runtime settings (execution mode, endpoint routing).

    Precedence per key:
      1. Settings API /embeddings/runtime (when SETTINGS_API_URL is set, TTL-cached)
      2. Environment variable
      3. Hardcoded default

    Returns a dict with keys:
      - embedding_runtime_policy (canonical)
      - EMBEDDING_EXECUTION_MODE (legacy/compat)
      - EMBEDDING_FALLBACK_POLICY, EMBEDDING_GPU_ENDPOINT,
        EMBEDDING_CPU_ENDPOINT, EMBEDDING_ENDPOINT_MODE.
    """
    _ensure_runtime_refresh_worker()
    cfg = _rt_cache.get("config")
    if isinstance(cfg, dict):
        return cfg
    # Fail-open default until first background refresh succeeds.
    cfg = _default_runtime_config()
    _rt_cache["config"] = cfg
    _rt_cache["ts"] = time.time()
    return cfg


def _runtime_api_base() -> str:
    """
    SETTINGS_API_URL is usually ".../api/settings".
    Convert to API base for runtime routes (".../api/runtime/...").
    """
    if not SETTINGS_API_URL:
        return ""
    marker = "/api/settings"
    idx = SETTINGS_API_URL.find(marker)
    if idx >= 0:
        return SETTINGS_API_URL[:idx]
    return SETTINGS_API_URL.rstrip("/")


def _resolve_embedding_role_route() -> Optional[Dict[str, Any]]:
    """
    Resolve per-layer compute route for embedding role from admin-api runtime endpoint.
    Used for explicit pinning only; auto mode still follows embedding runtime policy.
    """
    _ensure_runtime_refresh_worker()
    route = _route_cache.get("value")
    if isinstance(route, dict):
        return route
    return None


def _inline_resolve_target(
    mode: str,
    endpoint_mode: str,
    base_endpoint: str,
    gpu_endpoint: str,
    cpu_endpoint: str,
    fallback_policy: str,
    availability: Optional[dict] = None,
) -> dict:
    """
    Inline mirror of utils/embedding_resolver.resolve_embedding_target().
    Inlined here because sql-memory runs in a separate container without
    access to the main-service utils/ package.

    Scope 3.1: adds availability param + RoutingDecision-compatible fields:
      requested_policy, requested_target, effective_target,
      fallback_reason, hard_error, error_code.
    Backward-compat: old keys (target, endpoint, options, ...) still present.
    """
    _valid_modes = {"auto", "prefer_gpu", "cpu_only"}
    _valid_policies = {"best_effort", "strict"}
    _valid_ep_modes = {"single", "dual"}

    mode = (mode or "auto").strip().lower()
    endpoint_mode = (endpoint_mode or "single").strip().lower()
    fallback_policy = (fallback_policy or "best_effort").strip().lower()

    if mode not in _valid_modes:
        mode = "auto"
    if endpoint_mode not in _valid_ep_modes:
        endpoint_mode = "single"
    if fallback_policy not in _valid_policies:
        fallback_policy = "best_effort"

    avail = dict(availability) if availability is not None else {"gpu": True, "cpu": True}
    gpu_ok = bool(avail.get("gpu", True))
    cpu_ok = bool(avail.get("cpu", True))

    eff_gpu = (gpu_endpoint or "").strip()
    eff_cpu = (cpu_endpoint or "").strip()

    # ── cpu_only ──────────────────────────────────────────────────────────
    if mode == "cpu_only":
        if not cpu_ok:
            return {
                "requested_policy": "cpu_only", "requested_target": "cpu",
                "effective_target": None, "fallback_reason": "cpu_unavailable",
                "hard_error": True, "error_code": 503,
                "endpoint": None, "options": {}, "fallback_endpoint": None,
                "fallback_policy": fallback_policy,
                "reason": "cpu_only→cpu_unavailable→hard_error_503",
                "target": "cpu",
            }
        if endpoint_mode == "dual" and eff_cpu:
            return {
                "requested_policy": "cpu_only", "requested_target": "cpu",
                "effective_target": "cpu", "fallback_reason": None,
                "hard_error": False, "error_code": None,
                "endpoint": eff_cpu, "options": {}, "fallback_endpoint": None,
                "fallback_policy": fallback_policy,
                "reason": "cpu_only/dual→cpu_endpoint",
                "target": "cpu",
            }
        return {
            "requested_policy": "cpu_only", "requested_target": "cpu",
            "effective_target": "cpu", "fallback_reason": None,
            "hard_error": False, "error_code": None,
            "endpoint": base_endpoint, "options": {"num_gpu": 0},
            "fallback_endpoint": None, "fallback_policy": fallback_policy,
            "reason": "cpu_only/single→base+num_gpu=0",
            "target": "cpu",
        }

    # ── prefer_gpu / auto ─────────────────────────────────────────────────
    if gpu_ok:
        if endpoint_mode == "dual" and eff_gpu:
            fb_ep = (eff_cpu or base_endpoint) if fallback_policy == "best_effort" else None
            return {
                "requested_policy": mode, "requested_target": "gpu",
                "effective_target": "gpu", "fallback_reason": None,
                "hard_error": False, "error_code": None,
                "endpoint": eff_gpu, "options": {}, "fallback_endpoint": fb_ep,
                "fallback_policy": fallback_policy,
                "reason": f"{mode}/dual→gpu_endpoint",
                "target": "gpu",
            }
        return {
            "requested_policy": mode, "requested_target": "gpu",
            "effective_target": "gpu", "fallback_reason": None,
            "hard_error": False, "error_code": None,
            "endpoint": base_endpoint, "options": {}, "fallback_endpoint": None,
            "fallback_policy": fallback_policy,
            "reason": f"{mode}/single→base_endpoint",
            "target": "gpu",
        }

    # GPU unavailable → CPU fallback
    if cpu_ok:
        if endpoint_mode == "dual" and eff_cpu:
            cpu_ep, cpu_opts = eff_cpu, {}
        else:
            cpu_ep, cpu_opts = base_endpoint, {"num_gpu": 0}
        return {
            "requested_policy": mode, "requested_target": "gpu",
            "effective_target": "cpu", "fallback_reason": "gpu_unavailable",
            "hard_error": False, "error_code": None,
            "endpoint": cpu_ep, "options": cpu_opts, "fallback_endpoint": None,
            "fallback_policy": fallback_policy,
            "reason": f"{mode}→gpu_unavailable→cpu_fallback",
            "target": "cpu",
        }

    # All unavailable → hard error
    return {
        "requested_policy": mode, "requested_target": "gpu",
        "effective_target": None, "fallback_reason": "all_unavailable",
        "hard_error": True, "error_code": 503,
        "endpoint": None, "options": {}, "fallback_endpoint": None,
        "fallback_policy": fallback_policy,
        "reason": f"{mode}→all_unavailable→hard_error_503",
        "target": "gpu",
    }


def _request_embedding(url: str, model: str, text: str, options: dict) -> Optional[List[float]]:
    """Single Ollama /api/embeddings call; returns None on any failure."""
    try:
        payload: dict = {"model": model, "prompt": text.strip()}
        if options:
            payload["options"] = options
        response = requests.post(f"{url}/api/embeddings", json=payload, timeout=30)
        response.raise_for_status()
        return response.json().get("embedding") or None
    except Exception as e:
        logger.error(f"[Embedding] Error @ {url}: {e}")
        return None


def _log_routing_decision(message: str, hard_error: bool = False) -> None:
    """
    Emit routing decision with a visibility-safe default level.
    Default WARNING level ensures docker logs contain routing evidence
    even when INFO logs are suppressed by process defaults.
    """
    if hard_error:
        logger.error(message)
        return
    if _ROUTING_LOG_LEVEL == "info":
        logger.info(message)
        return
    if _ROUTING_LOG_LEVEL == "error":
        logger.error(message)
        return
    logger.warning(message)


def get_embedding(text: str) -> Optional[List[float]]:
    """
    Holt Embedding-Vektor für einen Text von Ollama.

    Routes to GPU or CPU endpoint based on embedding_runtime_policy
    (read via EMBEDDING_EXECUTION_MODE env var / Settings API).
    Emits structured log per Scope 3.1 observability spec.
    Falls back to fallback_endpoint on failure when policy=best_effort.

    Args:
        text: Der Text der embedded werden soll

    Returns:
        Liste von Floats (der Embedding-Vektor) oder None bei Fehler
    """
    if not text or not text.strip():
        return None

    model = _resolve_embedding_model()
    rt = _resolve_runtime_config()
    role_route = _resolve_embedding_role_route()

    requested_pin = (role_route or {}).get("requested_target", "auto") if role_route else "auto"
    if role_route and requested_pin != "auto":
        if role_route.get("hard_error"):
            logger.error(
                f"[Embedding] role=sql_memory_embedding policy={(rt.get('embedding_runtime_policy') or rt['EMBEDDING_EXECUTION_MODE'])} "
                f"requested_target={requested_pin} effective_target=none fallback=true "
                f"reason={role_route.get('fallback_reason') or 'requested_unavailable'}"
            )
            return None

        eff_target = role_route.get("effective_target") or requested_pin
        endpoint = role_route.get("endpoint") or OLLAMA_URL
        options = {}
        if eff_target == "cpu" and endpoint == OLLAMA_URL:
            options = {"num_gpu": 0}
        target = {
            "requested_policy": rt.get("embedding_runtime_policy") or rt["EMBEDDING_EXECUTION_MODE"],
            "requested_target": requested_pin,
            "effective_target": eff_target,
            "fallback_reason": role_route.get("fallback_reason"),
            "hard_error": False,
            "error_code": None,
            "endpoint": endpoint,
            "options": options,
            "fallback_endpoint": None,
            "fallback_policy": rt["EMBEDDING_FALLBACK_POLICY"],
            "reason": f"layer_routing_pin:{requested_pin}",
            "target": eff_target,
        }
    else:
        target = _inline_resolve_target(
            mode=rt.get("embedding_runtime_policy") or rt["EMBEDDING_EXECUTION_MODE"],
            endpoint_mode=rt["EMBEDDING_ENDPOINT_MODE"],
            base_endpoint=OLLAMA_URL,
            gpu_endpoint=rt["EMBEDDING_GPU_ENDPOINT"],
            cpu_endpoint=rt["EMBEDDING_CPU_ENDPOINT"],
            fallback_policy=rt["EMBEDDING_FALLBACK_POLICY"],
            # availability: not checked pre-flight in sql-memory (single-mode, optimistic)
        )

    # Structured log per Scope 3.1
    _fallback = target["fallback_reason"] is not None
    _log_msg = (
        f"[Embedding] role=sql_memory_embedding "
        f"policy={target['requested_policy']} "
        f"requested_target={target['requested_target']} "
        f"effective_target={target['effective_target'] or 'none'} "
        f"fallback={_fallback} "
        f"reason={target['reason']}"
    )
    if target["hard_error"]:
        _log_routing_decision(_log_msg, hard_error=True)
        return None
    _log_routing_decision(_log_msg, hard_error=False)

    embedding = _request_embedding(target["endpoint"], model, text, target["options"])

    if embedding is None and target.get("fallback_endpoint"):
        logger.info(
            f"[Embedding] role=sql_memory_embedding policy={target['requested_policy']} "
            f"primary_failed=true retrying_fallback={target['fallback_endpoint']}"
        )
        embedding = _request_embedding(
            target["fallback_endpoint"], model, text, target["options"]
        )

    if embedding:
        logger.info(
            f"[Embedding] Generated vector with {len(embedding)} dimensions "
            f"target={target['effective_target']}"
        )
        return embedding
    logger.error("[Embedding] No embedding in response")
    return None


def get_embedding_with_metadata(text: str) -> Optional[dict]:
    """
    Generate embedding plus version metadata for Scope 3.2.

    Returns:
      {
        "embedding": List[float],
        "embedding_model": str,
        "embedding_dim": int,
        "embedding_version": str,
        "runtime_policy": str
      }
    """
    embedding = get_embedding(text)
    if not embedding:
        return None

    model = _resolve_embedding_model()
    policy = _canonical_policy()
    version_id = compute_embedding_version_id(model, policy)

    return {
        "embedding": embedding,
        "embedding_model": model,
        "embedding_dim": len(embedding),
        "embedding_version": version_id,
        "runtime_policy": policy,
    }


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """
    Berechnet Cosine Similarity zwischen zwei Vektoren.

    Returns:
        Wert zwischen -1 und 1 (1 = identisch, 0 = orthogonal)
    """
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = sum(a * a for a in vec1) ** 0.5
    norm2 = sum(b * b for b in vec2) ** 0.5

    if norm1 == 0 or norm2 == 0:
        return 0.0

    return dot_product / (norm1 * norm2)


# Prime runtime config once at import time so request-path deadlocks/timeouts
# do not drop initial policy resolution back to env defaults.
try:
    _resolve_runtime_config()
except Exception:
    pass
