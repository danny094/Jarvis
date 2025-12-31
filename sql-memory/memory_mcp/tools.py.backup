import sqlite3
import sys
sys.path.insert(0, '/app')  # Damit embedding.py gefunden wird
from graph import get_graph_store, build_node_with_edges
from vector_store import get_vector_store
from typing import Optional, List, Dict

from .config import DB_PATH
from .database import (
    insert_row,
    insert_fact,
    load_fact,
    row_to_memory_dict,
    row_to_fact_dict,
)
from .auto_layer import auto_assign_layer


def register_tools(mcp):

    # --------------------------------------------------
    # memory_save  (freier Text)
    # --------------------------------------------------
    @mcp.tool
    def memory_save(
        conversation_id: str,
        role: str,
        content: str,
        tags: Optional[str] = None,
        layer: Optional[str] = None
    ) -> Dict:
        """Speichert freien Text."""
        role_norm = role.lower()

        if not layer or layer == "auto":
            layer = auto_assign_layer(role_norm, content)

        new_id = insert_row(conversation_id, role_norm, content, tags, layer)

        # NEU: Auch als Embedding speichern für semantische Suche
        try:
            vs = get_vector_store()
            vs.add(
                conversation_id=conversation_id,
                content=content,
                content_type="memory",
                metadata={"role": role_norm, "layer": layer}
            )
        except Exception as e:
            print(f"[memory_save] Embedding failed: {e}")

        return {
            "result": f"Saved memory {new_id}",
            "structuredContent": {
                "id": new_id,
                "layer": layer,
                "content": content,
            }
        }

    # --------------------------------------------------
    # memory_fact_save (strukturierte Fakten)
    # --------------------------------------------------
    @mcp.tool
    def memory_fact_save(
        conversation_id: str,
        key: str,
        value: str,
        subject: str = "Danny",
        layer: str = "ltm"
    ) -> Dict:
        """Speichert strukturierte Fakten."""
        new_id = insert_fact(conversation_id, subject, key, value, layer)

        content = f"{subject} {key}: {value}"
        embedding = None

        # Embedding speichern
        try:
            from embedding import get_embedding
            vs = get_vector_store()
            embedding = get_embedding(content)
            vs.add(
                conversation_id=conversation_id,
                content=content,
                content_type="fact",
                metadata={"key": key, "value": value, "subject": subject}
            )
        except Exception as e:
            print(f"[memory_fact_save] Embedding failed: {e}")

        # Graph Node erstellen
        try:
            build_node_with_edges(
                source_type="fact",
                content=content,
                source_id=new_id,
                embedding=embedding,
                conversation_id=conversation_id,
                related_keys=[key]
            )
        except Exception as e:
            print (f"[memory_fact_save] Graph failed: {e}")

        return {
            "result": f"Fact saved {new_id}",
            "structuredContent": {
                "id": new_id,
                "subject": subject,
                "key": key,
                "value": value,
                "layer": layer
            }
        }
    # --------------------------------------------------
    # memory_fact_load (Fakt abrufen)
    # --------------------------------------------------
    @mcp.tool
    def memory_fact_load(conversation_id: str, key: str) -> Dict:
        value = load_fact(conversation_id, key)

        return {
            "result": value,
            "structuredContent": {
                "key": key,
                "value": value
            }
        }

    # --------------------------------------------------
    # memory_recent
    # --------------------------------------------------
    @mcp.tool
    def memory_recent(conversation_id: str, limit: int = 20) -> List[Dict]:
        conn = sqlite3.connect(DB_PATH)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT *
                FROM memory
                WHERE conversation_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (conversation_id, limit),
            )
            return [row_to_memory_dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    # --------------------------------------------------
    # memory_search (LIKE)
    # --------------------------------------------------
    @mcp.tool
    def memory_search(
        query: str,
        conversation_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict]:

        like = f"%{query}%"
        conn = sqlite3.connect(DB_PATH)
        try:
            cur = conn.cursor()

            if conversation_id:
                cur.execute(
                    """
                    SELECT *
                    FROM memory
                    WHERE conversation_id = ?
                      AND content LIKE ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (conversation_id, like, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT *
                    FROM memory
                    WHERE content LIKE ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (like, limit),
                )

            return [row_to_memory_dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    # --------------------------------------------------
    # memory_search_layered
    # --------------------------------------------------
    @mcp.tool
    def memory_search_layered(
        conversation_id: str,
        query: str,
        limit: int = 20,
    ) -> List[Dict]:

        like = f"%{query}%"
        layers = ["stm", "mtm", "ltm"]
        results: List[Dict] = []

        conn = sqlite3.connect(DB_PATH)

        try:
            cur = conn.cursor()

            for layer in layers:
                remaining = limit - len(results)
                if remaining <= 0:
                    break

                cur.execute(
                    """
                    SELECT *
                    FROM memory
                    WHERE conversation_id = ?
                      AND layer = ?
                      AND content LIKE ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (conversation_id, layer, like, remaining),
                )

                rows = [row_to_memory_dict(r) for r in cur.fetchall()]
                results.extend(rows)

            return results[:limit]
        finally:
            conn.close()

    # --------------------------------------------------
    # memory_search_fts
    # --------------------------------------------------
    @mcp.tool
    def memory_search_fts(
        query: str,
        conversation_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict]:

        conn = sqlite3.connect(DB_PATH)
        try:
            cur = conn.cursor()

            if conversation_id:
                cur.execute(
                    """
                    SELECT m.*
                    FROM memory_fts f
                    JOIN memory m ON m.id = f.rowid
                    WHERE f MATCH ?
                      AND f.conversation_id = ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (query, conversation_id, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT m.*
                    FROM memory_fts f
                    JOIN memory m ON m.id = f.rowid
                    WHERE f MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (query, limit),
                )

            return [row_to_memory_dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    # --------------------------------------------------
    # memory_delete
    # --------------------------------------------------
    @mcp.tool
    def memory_delete(id: int) -> str:

        conn = sqlite3.connect(DB_PATH)
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM memory WHERE id = ?", (id,))
            conn.commit()

            if cur.rowcount > 0:
                return f"Deleted {id}"
            return f"Not found {id}"
        finally:
            conn.close()

    # --------------------------------------------------
    # autosave hook
    # --------------------------------------------------
    @mcp.tool
    def memory_autosave_hook(conversation_id: str, message: str) -> str:
        insert_row(conversation_id, "user", message, tags="", layer="auto")
        return "OK"
    # --------------------------------------------------
    # memory_semantic_save
    # --------------------------------------------------
    @mcp.tool
    def memory_semantic_save(
        conversation_id: str,
        content: str,
        content_type: str = "fact",
        key: str = None,
        value: str = None
    ) -> Dict:
        """Speichert einen Eintrag mit Embedding für semantische Suche."""
        vs = get_vector_store()

        metadata = {}
        if key:
            metadata["key"] = key
        if value:
            metadata["value"] = value

        entry_id = vs.add(
            conversation_id=conversation_id,
            content=content,
            content_type=content_type,
            metadata=metadata
        )

        if entry_id:
            return {"success": True, "id": entry_id}
        else:
            return {"success": False, "error": "Could not save"}

    # --------------------------------------------------
    # memory_semantic_search
    # --------------------------------------------------
    @mcp.tool
    def memory_semantic_search(
        query: str,
        conversation_id: str = None,
        limit: int = 5,
        min_similarity: float = 0.5
    ) -> Dict:
        """Semantische Suche - findet ähnliche Einträge nach Bedeutung."""
        vs = get_vector_store()

        results = vs.search(
            query=query,
            conversation_id=conversation_id,
            limit=limit,
            min_similarity=min_similarity
        )

        return {
            "results": results,
            "count": len(results)
        }
    # --------------------------------------------------
    # memory_graph_search (NEU)
    # --------------------------------------------------
    @mcp.tool
    def memory_graph_search(
        query: str,
        conversation_id: str = None,
        depth: int = 2,
        limit: int = 10
    ) -> Dict:
        """Graph-basierte Suche - findet verbundene Infomrationen."""
        from vector_store import get_vector_store

        vs = get_vector_store()
        gs = get_graph_store()

        # 1. Sematic search für Seed Nodes
        seed_results = vs.search(
            query=query,
            conversation_id=conversation_id,
            limit=5,
            min_similarity=0.5
        )
        
        if not seed_results:
            return {"results": [], "count": 0}
        
        # 2. Finde Graph Nodes die zu den Seeds gehören
        seed_node_ids = []
        for seed in seed_results:
            # suche node mit passendem content
            nodes = gs.get_nodes_by_type("fact", limit=50)
            for node in nodes:
                if seed["content"] in node["content"] or node["content"] in seed["content"]:
                    seed_node_ids.append(node["id"])
                    break
                
        if not seed_node_ids:
            # Fallback nur Seantic Results
            return {
                "results": seed_results,
                "count": len(seed_results),
                "source": "sematic_only"
            }
        
        # 3 Graph Walk
        graph_results = gs.graph_walk(
            start_node_ids=seed_node_ids,
            depth=depth,
            limit=limit
        )

        # 4. Kombiniere und score
        combined = []
        for node in graph_results:
            combined.append({
                "content": node["content"],
                "type": node["source_type"],
                "depth": node.get("depth", 0),
                "node_id": node ["id"]
            })

        return {
            "results": combined,
            "count": len(combined),
            "source": "graph_walk"
        }
    
    # --------------------------------------------------
    # memory_graph_neighbors (NEU)
    # --------------------------------------------------
    @mcp.tool
    def memory_graph_neighbors(
        node_id: int,
        edge_type: str = None,
        direction: str = "outgoing"
    ) -> Dict:
        """Holt Nachbarn eines Graph-Nodes."""
        gs = get_graph_store()

        neighbors = gs.get_neighbors(
            node_id=node_id,
            edge_type=edge_type,
            direction=direction
        )

        return {
            "neighbors": neighbors,
            "count": len(neighbors)
        }
    
    # --------------------------------------------------
    # memory_graph_stats (NEU)
    # --------------------------------------------------
    @mcp.tool
    def memory_graph_stats() -> Dict:
        """Gibt Graph-Statistiken zurück."""
        import sqlite3
        from .config import DB_PATH

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM graph_nodes")
        node_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM graph_edges")
        edge_count = cursor.fetchone()[0]

        cursor.execute("""
            SELECT edge_type, COUNT(*) FROM graph_edges GROUP BY edge_type
        """)
        edge_types = {row[0]: row[1] for row in cursor.fetchall()}

        cursor.execute("""
            SELECT source_type, COUNT(*) FROM graph_nodes GROUP BY source_type    
        """)
        node_types = {row[0]: row[1] for row in cursor.fetchall()}

        conn.close()

        return {
            "nodes": node_count,
            "edges": edge_count,
            "edge_types": edge_types,
            "node_types": node_types
        }
    