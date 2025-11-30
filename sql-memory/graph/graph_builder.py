# sql-memory/graph/graph_builder.py
"""
Graph Builder - Erstellt automatisch Kanten beim Speichern.
"""

import logging
from typing import List, Optional
from .graph_store import get_graph_store

logger = logging.getLogger(__name__)

# Similarity Thresholds
SEMANTIC_THRESHOLD = 0.70
COOCCUR_WEIGHT = 0.2


def build_node_with_edges(
    source_type: str,
    content: str,
    source_id: int = None,
    embedding: List[float] = None,
    conversation_id: str = None,
    related_keys: List[str] = None
) -> int:
    """
    Erstellt einen Node UND automatisch passende Edges.
    
    1. Node erstellen
    2. Temporal Edge zum letzten Node der Conversation
    3. Semantic Edges zu ähnlichen Nodes
    4. Co-Occurrence Edges wenn related_keys gegeben
    """
    gs = get_graph_store()
    
    # 1. Node erstellen
    node_id = gs.add_node(
        source_type=source_type,
        content=content,
        source_id=source_id,
        embedding=embedding,
        conversation_id=conversation_id
    )
    
    logger.info(f"[GraphBuilder] Created node {node_id}")
    
    # 2. Temporal Edge (zum vorherigen Node)
    if conversation_id:
        last_node = gs.get_last_node(conversation_id)
        if last_node and last_node["id"] != node_id:
            gs.add_edge(
                src_node_id=last_node["id"],
                dst_node_id=node_id,
                edge_type="temporal",
                weight=1.0
            )
            logger.info(f"[GraphBuilder] Temporal edge: {last_node['id']} → {node_id}")
    
    # 3. Semantic Edges (wenn Embedding vorhanden)
    if embedding:
        _create_semantic_edges(node_id, embedding, conversation_id)
    
    # 4. Co-Occurrence Edges (wenn mehrere Keys zusammen auftreten)
    if related_keys and len(related_keys) > 1:
        _create_cooccur_edges(node_id, related_keys, conversation_id)
    
    return node_id


def _create_semantic_edges(
    node_id: int,
    embedding: List[float],
    conversation_id: str = None
):
    """Erstellt Semantic Edges zu ähnlichen Nodes."""
    from embedding import cosine_similarity
    import json
    
    gs = get_graph_store()
    
    # Alle Nodes mit Embeddings holen (außer der aktuelle)
    import sqlite3
    from memory_mcp.config import DB_PATH
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, embedding FROM graph_nodes
        WHERE embedding IS NOT NULL AND id != ?
        ORDER BY id DESC
        LIMIT 100
    """, (node_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    for row in rows:
        other_id, other_emb_json = row
        if not other_emb_json:
            continue
        
        try:
            other_embedding = json.loads(other_emb_json)
            similarity = cosine_similarity(embedding, other_embedding)
            
            if similarity >= SEMANTIC_THRESHOLD:
                gs.add_edge(
                    src_node_id=node_id,
                    dst_node_id=other_id,
                    edge_type="semantic",
                    weight=similarity
                )
                logger.info(f"[GraphBuilder] Semantic edge: {node_id} → {other_id} (sim={similarity:.3f})")
        except:
            continue


def _create_cooccur_edges(
    node_id: int,
    related_keys: List[str],
    conversation_id: str = None
):
    """Erstellt Co-Occurrence Edges zwischen verwandten Keys."""
    gs = get_graph_store()
    
    # Finde Nodes die zu den related_keys gehören
    import sqlite3
    from memory_mcp.config import DB_PATH
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    for key in related_keys:
        cursor.execute("""
            SELECT id FROM graph_nodes
            WHERE content LIKE ? AND id != ?
            LIMIT 5
        """, (f"%{key}%", node_id))
        
        rows = cursor.fetchall()
        for row in rows:
            other_id = row[0]
            gs.add_edge(
                src_node_id=node_id,
                dst_node_id=other_id,
                edge_type="cooccur",
                weight=COOCCUR_WEIGHT
            )
            logger.info(f"[GraphBuilder] Cooccur edge: {node_id} → {other_id}")
    
    conn.close()