"""
Shared embedding helper for lightweight runtime checks.
"""

from __future__ import annotations

import math
from typing import List, Optional

import httpx

from config import OLLAMA_BASE, get_embedding_model
from utils.logger import log_debug
from utils.role_endpoint_resolver import resolve_role_endpoint


async def embed_text(
    text: str,
    *,
    timeout_s: float = 2.8,
) -> Optional[List[float]]:
    payload = {
        "model": get_embedding_model(),
        "prompt": str(text or ""),
    }
    route = resolve_role_endpoint("embedding", default_endpoint=OLLAMA_BASE)
    if route.get("hard_error"):
        return None
    endpoint = route.get("endpoint") or OLLAMA_BASE
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(f"{endpoint}/api/embeddings", json=payload)
            resp.raise_for_status()
            data = resp.json()
        vec = data.get("embedding")
        if isinstance(vec, list) and vec:
            return [float(v) for v in vec]
    except Exception as exc:
        log_debug(f"[EmbeddingClient] unavailable: {type(exc).__name__}: {exc}")
    return None


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))

