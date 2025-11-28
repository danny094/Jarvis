# sql-memory/embedding.py
"""
Embedding Client - Holt Embeddings von Ollama.
"""

import requests
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)

# Ollama URL (im Docker Network)
OLLAMA_URL = "http://ollama:11434"
EMBEDDING_MODEL = "hellord/mxbai-embed-large-v1:f16"


def get_embedding(text: str) -> Optional[List[float]]:
    """
    Holt Embedding-Vektor für einen Text von Ollama.
    
    Args:
        text: Der Text der embedded werden soll
        
    Returns:
        Liste von Floats (der Embedding-Vektor) oder None bei Fehler
    """
    if not text or not text.strip():
        return None
    
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={
                "model": EMBEDDING_MODEL,
                "prompt": text.strip()
            },
            timeout=30
        )
        response.raise_for_status()
        
        data = response.json()
        embedding = data.get("embedding")
        
        if embedding:
            logger.info(f"[Embedding] Generated vector with {len(embedding)} dimensions")
            return embedding
        else:
            logger.error("[Embedding] No embedding in response")
            return None
            
    except Exception as e:
        logger.error(f"[Embedding] Error: {e}")
        return None


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