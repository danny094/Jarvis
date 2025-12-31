# sql-memory/graph/graph_store.py

# Global singleton instance
_graph_store = None

"""
Graph Store - Speichert Nodes und Edges in SQLite.
"""

import sqlite3
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class GraphStore:
    """SQLite-basierter Graph Store."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_tables()
    
    def _init_tables(self):
        """Erstellt die Graph-Tabellen falls nicht vorhanden."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Nodes Tabelle
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS graph_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL,
                source_id INTEGER,
                content TEXT NOT NULL,
                embedding BLOB,
                conversation_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Edges Tabelle
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS graph_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                src_node_id INTEGER NOT NULL,
                dst_node_id INTEGER NOT NULL,
                edge_type TEXT NOT NULL,
                weight REAL DEFAULT 1.0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (src_node_id) REFERENCES graph_nodes(id),
                FOREIGN KEY (dst_node_id) REFERENCES graph_nodes(id)
            )
        """)
        
        # Indices
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_nodes_source 
            ON graph_nodes(source_type, source_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_nodes_conv 
            ON graph_nodes(conversation_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_edges_src 
            ON graph_edges(src_node_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_edges_dst 
            ON graph_edges(dst_node_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_edges_type 
            ON graph_edges(edge_type)
        """)
        
        conn.commit()
        conn.close()
        logger.info("[GraphStore] Tables initialized")
    
    # ══════════════════════════════════════════════════════════
    # NODE OPERATIONS
    # ══════════════════════════════════════════════════════════
    
    def add_node(
        self,
        source_type: str,
        content: str,
        source_id: int = None,
        embedding: List[float] = None,
        conversation_id: str = None
    ) -> int:
        """Fügt einen Node hinzu."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO graph_nodes 
            (source_type, source_id, content, embedding, conversation_id)
            VALUES (?, ?, ?, ?, ?)
        """, (
            source_type,
            source_id,
            content,
            json.dumps(embedding) if embedding else None,
            conversation_id
        ))
        
        conn.commit()
        node_id = cursor.lastrowid
        conn.close()
        
        logger.info(f"[GraphStore] Added node {node_id}: {source_type}")
        return node_id
    
    def get_node(self, node_id: int) -> Optional[Dict]:
        """Holt einen Node by ID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, source_type, source_id, content, embedding, conversation_id, created_at
            FROM graph_nodes WHERE id = ?
        """, (node_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "id": row[0],
                "source_type": row[1],
                "source_id": row[2],
                "content": row[3],
                "embedding": json.loads(row[4]) if row[4] else None,
                "conversation_id": row[5],
                "created_at": row[6]
            }
        return None
    
    def get_last_node(self, conversation_id: str) -> Optional[Dict]:
        """Holt den letzten Node einer Conversation."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, source_type, source_id, content, embedding, conversation_id, created_at
            FROM graph_nodes 
            WHERE conversation_id = ?
            ORDER BY id DESC
            LIMIT 1
        """, (conversation_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "id": row[0],
                "source_type": row[1],
                "source_id": row[2],
                "content": row[3],
                "embedding": json.loads(row[4]) if row[4] else None,
                "conversation_id": row[5],
                "created_at": row[6]
            }
        return None
    
    def get_nodes_by_type(self, source_type: str, limit: int = 100) -> List[Dict]:
        """Holt alle Nodes eines Typs."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, source_type, source_id, content, embedding, conversation_id, created_at
            FROM graph_nodes 
            WHERE source_type = ?
            ORDER BY id DESC
            LIMIT ?
        """, (source_type, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [{
            "id": row[0],
            "source_type": row[1],
            "source_id": row[2],
            "content": row[3],
            "embedding": json.loads(row[4]) if row[4] else None,
            "conversation_id": row[5],
            "created_at": row[6]
        } for row in rows]
    
    # ══════════════════════════════════════════════════════════
    # EDGE OPERATIONS
    # ══════════════════════════════════════════════════════════
    
    def add_edge(
        self,
        src_node_id: int,
        dst_node_id: int,
        edge_type: str,
        weight: float = 1.0
    ) -> int:
        """Fügt eine Edge hinzu."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check ob Edge schon existiert
        cursor.execute("""
            SELECT id, weight FROM graph_edges
            WHERE src_node_id = ? AND dst_node_id = ? AND edge_type = ?
        """, (src_node_id, dst_node_id, edge_type))
        
        existing = cursor.fetchone()
        
        if existing:
            # Update weight (akkumulieren)
            new_weight = min(existing[1] + weight, 1.0)
            cursor.execute("""
                UPDATE graph_edges SET weight = ? WHERE id = ?
            """, (new_weight, existing[0]))
            conn.commit()
            conn.close()
            logger.info(f"[GraphStore] Updated edge {existing[0]}: weight={new_weight}")
            return existing[0]
        
        # Neue Edge
        cursor.execute("""
            INSERT INTO graph_edges (src_node_id, dst_node_id, edge_type, weight)
            VALUES (?, ?, ?, ?)
        """, (src_node_id, dst_node_id, edge_type, weight))
        
        conn.commit()
        edge_id = cursor.lastrowid
        conn.close()
        
        logger.info(f"[GraphStore] Added edge {edge_id}: {src_node_id}--[{edge_type}]-->{dst_node_id}")
        return edge_id
    
    def get_neighbors(
        self,
        node_id: int,
        edge_type: str = None,
        direction: str = "outgoing"
    ) -> List[Dict]:
        """Holt Nachbarn eines Nodes."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if direction == "outgoing":
            if edge_type:
                cursor.execute("""
                    SELECT e.id, e.dst_node_id, e.edge_type, e.weight, n.content, n.source_type
                    FROM graph_edges e
                    JOIN graph_nodes n ON e.dst_node_id = n.id
                    WHERE e.src_node_id = ? AND e.edge_type = ?
                    ORDER BY e.weight DESC
                """, (node_id, edge_type))
            else:
                cursor.execute("""
                    SELECT e.id, e.dst_node_id, e.edge_type, e.weight, n.content, n.source_type
                    FROM graph_edges e
                    JOIN graph_nodes n ON e.dst_node_id = n.id
                    WHERE e.src_node_id = ?
                    ORDER BY e.weight DESC
                """, (node_id,))
        else:  # incoming
            if edge_type:
                cursor.execute("""
                    SELECT e.id, e.src_node_id, e.edge_type, e.weight, n.content, n.source_type
                    FROM graph_edges e
                    JOIN graph_nodes n ON e.src_node_id = n.id
                    WHERE e.dst_node_id = ? AND e.edge_type = ?
                    ORDER BY e.weight DESC
                """, (node_id, edge_type))
            else:
                cursor.execute("""
                    SELECT e.id, e.src_node_id, e.edge_type, e.weight, n.content, n.source_type
                    FROM graph_edges e
                    JOIN graph_nodes n ON e.src_node_id = n.id
                    WHERE e.dst_node_id = ?
                    ORDER BY e.weight DESC
                """, (node_id,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [{
            "edge_id": row[0],
            "node_id": row[1],
            "edge_type": row[2],
            "weight": row[3],
            "content": row[4],
            "source_type": row[5]
        } for row in rows]
    
    # ══════════════════════════════════════════════════════════
    # GRAPH WALK
    # ══════════════════════════════════════════════════════════
    
    def graph_walk(
        self,
        start_node_ids: List[int],
        depth: int = 2,
        limit: int = 10
    ) -> List[Dict]:
        """
        Graph-Walk von Start-Nodes aus.
        Sammelt Nodes bis zur gegebenen Tiefe.
        """
        visited = set()
        results = []
        
        current_level = start_node_ids
        
        for d in range(depth):
            next_level = []
            
            for node_id in current_level:
                if node_id in visited:
                    continue
                visited.add(node_id)
                
                node = self.get_node(node_id)
                if node:
                    node["depth"] = d
                    results.append(node)
                
                # Nachbarn holen
                neighbors = self.get_neighbors(node_id)
                for neighbor in neighbors:
                    if neighbor["node_id"] not in visited:
                        next_level.append(neighbor["node_id"])
            
            current_level = next_level
            
            if len(results) >= limit:
                break
        
        return results[:limit]



    def get_edges(self, node_id: int):
        """Get all edges connected to a node."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT src_node_id as source, dst_node_id as target, edge_type as type, weight, created_at
                FROM graph_edges
                WHERE src_node_id = ? OR dst_node_id = ?
            ''', (node_id, node_id))
            
            edges = []
            for row in cursor.fetchall():
                edges.append({
                    "source": row[0],
                    "target": row[1],
                    "type": row[2],
                    "weight": row[3],
                    "created_at": row[4]
                })
            return edges
        finally:
            conn.close()
    
    def delete_node(self, node_id: int):
        """Delete a node and all its edges."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''DELETE FROM graph_edges WHERE src_node_id = ? OR dst_node_id = ?''', (node_id, node_id))
            cursor.execute('''DELETE FROM graph_nodes WHERE id = ?''', (node_id,))
            conn.commit()
        except Exception as e:
            print(f"Error deleting node: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    def delete_edge(self, source: int, target: int, edge_type: str):
        """Delete a specific edge."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''DELETE FROM graph_edges WHERE src_node_id = ? AND dst_node_id = ? AND edge_type = ?''', (source, target, edge_type))
            conn.commit()
        except Exception as e:
            print(f"Error deleting edge: {e}")
            conn.rollback()
        finally:
            conn.close()


def get_graph_store(db_path: str = None) -> GraphStore:
    global _graph_store
    if _graph_store is None:
        from memory_mcp.config import DB_PATH
        _graph_store = GraphStore(db_path or DB_PATH)
    return _graph_store