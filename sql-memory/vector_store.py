# sql-memory/vector_store.py
"""
Vector Store - Speichert und sucht Embeddings in SQLite.
"""

import sqlite3
import json
import logging
from typing import List, Dict, Any, Optional
from embedding import get_embedding, cosine_similarity
from memory_mcp.config import DB_PATH

logger = logging.getLogger(__name__)


class VectorStore:
    """SQLite-basierter Vector Store."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_table()
    
    def _init_table(self):
        """Erstellt die Embedding-Tabelle falls nicht vorhanden."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                content TEXT NOT NULL,
                content_type TEXT DEFAULT 'fact',
                metadata TEXT,
                embedding BLOB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_embeddings_conv 
            ON embeddings(conversation_id)
        """)
        
        conn.commit()
        conn.close()
        logger.info("[VectorStore] Table initialized")
    
    def add(
        self, 
        conversation_id: str, 
        content: str, 
        content_type: str = "fact",
        metadata: Dict[str, Any] = None
    ) -> Optional[int]:
        """
        Fügt einen Eintrag mit Embedding hinzu.
        """
        embedding = get_embedding(content)
        if not embedding:
            logger.error("[VectorStore] Could not generate embedding")
            return None
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO embeddings 
                (conversation_id, content, content_type, metadata, embedding)
                VALUES (?, ?, ?, ?, ?)
            """, (
                conversation_id,
                content,
                content_type,
                json.dumps(metadata) if metadata else None,
                json.dumps(embedding)
            ))
            
            conn.commit()
            entry_id = cursor.lastrowid
            logger.info(f"[VectorStore] Added entry {entry_id}")
            return entry_id
            
        except Exception as e:
            logger.error(f"[VectorStore] Error adding: {e}")
            return None
        finally:
            conn.close()
    
    def search(
        self, 
        query: str, 
        conversation_id: str = None,
        limit: int = 5,
        min_similarity: float = 0.5
    ) -> List[Dict[str, Any]]:
        """
        Semantische Suche nach ähnlichen Einträgen.
        """
        query_embedding = get_embedding(query)
        if not query_embedding:
            return []
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if conversation_id:
            cursor.execute("""
                SELECT id, content, content_type, metadata, embedding
                FROM embeddings WHERE conversation_id = ?
            """, (conversation_id,))
        else:
            cursor.execute("""
                SELECT id, content, content_type, metadata, embedding
                FROM embeddings
            """)
        
        rows = cursor.fetchall()
        conn.close()
        
        results = []
        for row in rows:
            entry_id, content, content_type, metadata_json, embedding_json = row
            
            if not embedding_json:
                continue
            
            try:
                stored_embedding = json.loads(embedding_json)
                similarity = cosine_similarity(query_embedding, stored_embedding)
                
                if similarity >= min_similarity:
                    results.append({
                        "id": entry_id,
                        "content": content,
                        "type": content_type,
                        "metadata": json.loads(metadata_json) if metadata_json else {},
                        "similarity": round(similarity, 4)
                    })
            except:
                continue
        
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:limit]


# Singleton
_vector_store: Optional[VectorStore] = None

def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore(DB_PATH)
    return _vector_store