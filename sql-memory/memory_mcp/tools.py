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
    upsert_skill_metric,
    get_skill_metric,
    list_skill_metrics,
    update_skill_status,
    save_workspace_entry,
    list_workspace_entries,
    get_workspace_entry,
    update_workspace_entry,
    delete_workspace_entry,
    save_secret,
    get_secret_value,
    list_secrets,
    delete_secret,
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
    # tool_embedding_save
    # --------------------------------------------------
    @mcp.tool
    def tool_embedding_save(
        tool_name: str,
        description: str,
        capabilities: List[str]
    ) -> Dict:
        """Saves a tool definition for semantic search."""
        cap_str = ", ".join(capabilities)
        content = f"Tool: {tool_name}\nDescription: {description}\nCapabilities: {cap_str}"
        
        vs = get_vector_store()
        try:
            vs.add(
                conversation_id="global",
                content=content,
                content_type="tool_def",
                metadata={
                    "tool_name": tool_name, 
                    "capabilities": capabilities,
                    "description": description
                }
            )
            return {"result": f"Tool {tool_name} vectorized"}
        except Exception as e:
            return {"error": str(e)}

    # --------------------------------------------------
    # memory_semantic_search
    # --------------------------------------------------
    @mcp.tool
    def memory_semantic_search(
        query: str,
        conversation_id: str = None,
        limit: int = 5,
        min_similarity: float = 0.5,
        content_type: Optional[str] = None
    ) -> Dict:
        """Semantische Suche - findet ähnliche Einträge nach Bedeutung."""
        vs = get_vector_store()

        results = vs.search(
            query=query,
            conversation_id=conversation_id,
            limit=limit,
            min_similarity=min_similarity,
            content_type=content_type
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
        # Suche über ALLE source_types (nicht nur "fact" - würde z.B. "skill" Nodes verpassen)
        seed_node_ids = []
        all_known_types = ["fact", "skill", "event", "note", "observation", "task"]
        for seed in seed_results:
            seed_text = seed["content"][:80]
            found = False
            for t in all_known_types:
                candidates = gs.get_nodes_by_type(t, limit=50)
                for node in candidates:
                    if seed_text in node["content"] or node["content"][:80] in seed_text:
                        seed_node_ids.append(node["id"])
                        found = True
                        break
                if found:
                    break

        if not seed_node_ids:
            # Fallback: direkt semantische Ergebnisse zurückgeben
            return {
                "results": seed_results,
                "count": len(seed_results),
                "source": "semantic_only"
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
    # --------------------------------------------------
    # --------------------------------------------------
    # maintenance_run (AI-POWERED)
    # --------------------------------------------------
    @mcp.tool
    def maintenance_run(
        model: str = "qwen3:4b",
        validator_model = None,
        ollama_url: str = "http://ollama:11434"
    ) -> Dict:
        """
        AI-gestütztes Memory Maintenance.
        
        Args:
            model: Primary Ollama Model (z.B. 'qwen3:4b', 'deepseek-r1:8b')
            validator_model: Optional Validator für Slow Mode (z.B. 'llama3.1:8b')
            ollama_url: Ollama Endpoint URL (default: http://ollama:11434)
            
        Returns:
            Maintenance Results mit AI Decisions und optional Conflict Log
        """
        from .maintenance_ai import maintenance_run_ai
        from .config import DB_PATH
        
        # Call AI Maintenance
        return maintenance_run_ai(
            db_path=DB_PATH,
            model=model,
            validator_model=validator_model,
            ollama_url=ollama_url,

            stream_callback=None
        )
    # memory_all_recent (NEW - FOR MAINTENANCE)
    @mcp.tool
    def memory_all_recent(limit: int = 500) -> Dict:
        """
        Get all recent memory entries across ALL conversations.
        Used by maintenance to analyze all memories.
        """
        import sqlite3
        from .config import DB_PATH
        
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            
            # Get all entries, ordered by created_at DESC
            c.execute('''
                SELECT id, conversation_id, content, created_at
                FROM memory
                ORDER BY created_at DESC
                LIMIT ?
            ''', (limit,))
            
            rows = c.fetchall()
            
            entries = []
            for row in rows:
                entries.append({
                    "id": row[0],
                    "conversation_id": row[1],
                    "content": row[2],
                    "created_at": row[3]
                })
            
            return {"structuredContent": {"entries": entries, "count": len(entries), "limit": limit}}
            
        except Exception as e:
            return {"error": str(e), "entries": []}
    
    
    # memory_list_conversations (NEW - FOR MAINTENANCE)
    @mcp.tool
    def memory_list_conversations(limit: int = 100) -> Dict:
        """Lists all conversations with their entry counts."""
        import sqlite3
        from .config import DB_PATH
        
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.cursor()
            
            # Get unique conversations with entry counts
            cursor.execute("""
                SELECT 
                    conversation_id,
                    COUNT(*) as entry_count,
                    MAX(created_at) as last_updated
                FROM memory
                GROUP BY conversation_id
                ORDER BY last_updated DESC
                LIMIT ?
            """, (limit,))
            
            conversations = []
            for row in cursor.fetchall():
                conversations.append({
                    "conversation_id": row[0],
                    "entry_count": row[1],
                    "last_updated": row[2]
                })
            
            return {"structuredContent": {"conversations": conversations, "total": len(conversations)}}
        finally:
            conn.close()

    # memory_delete_bulk (NEW - FOR MAINTENANCE)
    @mcp.tool
    def memory_delete_bulk(ids: List[int]) -> Dict:
        """
        Delete multiple memory entries at once.
        Used by maintenance to clean up duplicates and unwanted entries.
        """
        import sqlite3
        from .config import DB_PATH
        
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            
            deleted_count = 0
            for entry_id in ids:
                c.execute('DELETE FROM memory WHERE id = ?', (entry_id,))
                if c.rowcount > 0:
                    deleted_count += 1
            
            conn.commit()
            
            return {"structuredContent": {"deleted": deleted_count, "total_requested": len(ids)}}
            
        except Exception as e:
            return {"error": str(e), "deleted": 0}
    
    # graph_find_duplicate_nodes (NEW - FOR MAINTENANCE)
    @mcp.tool
    def graph_find_duplicate_nodes() -> Dict:
        """
        Find duplicate nodes in the graph (same content).
        Returns groups of node IDs that are duplicates.
        """
        try:
            gs = get_graph_store()
            all_nodes = gs.get_nodes_by_type("fact", limit=1000)
            
            # Group by content
            from collections import defaultdict
            content_map = defaultdict(list)
            
            for node in all_nodes:
                content = node.get("content", "").strip().lower()
                if content:
                    content_map[content].append(node["id"])
            
            # Find duplicates (groups with more than 1 node)
            duplicates = []
            for content, node_ids in content_map.items():
                if len(node_ids) > 1:
                    duplicates.append({
                        "content_preview": content[:100],
                        "node_ids": node_ids,
                        "count": len(node_ids)
                    })
            
            return {"structuredContent": {"duplicate_groups": duplicates, "total_duplicates": sum(d["count"] - 1 for d in duplicates)}}
            
        except Exception as e:
            return {"error": str(e), "duplicate_groups": []}
    
    # graph_merge_nodes (NEW - FOR MAINTENANCE)
    @mcp.tool
    def graph_merge_nodes(node_ids: List[int]) -> Dict:
        """
        Merge multiple duplicate nodes into one.
        Keeps the first node, redirects all edges to it, deletes others.
        """
        try:
            if len(node_ids) < 2:
                return {"error": "Need at least 2 nodes to merge"}
            
            gs = get_graph_store()
            
            # Keep first node
            primary_id = node_ids[0]
            to_delete = node_ids[1:]
            
            # For each node to delete
            for node_id in to_delete:
                # Get its edges
                edges = gs.get_edges(node_id)
                
                # Redirect edges to primary node
                for edge in edges:
                    # Update edge to point to primary
                    if edge["source"] == node_id:
                        gs.add_edge(
                            src_node_id=primary_id,
                            dst_node_id=edge["target"],
                            edge_type=edge["type"],
                            weight=edge.get("weight", 1.0)
                        )
                    elif edge["target"] == node_id:
                        gs.add_edge(
                            src_node_id=edge["source"],
                            dst_node_id=primary_id,
                            edge_type=edge["type"],
                            weight=edge.get("weight", 1.0)
                        )
                
                # Delete the node
                gs.delete_node(node_id)
            
            return {"structuredContent": {"merged": len(to_delete), "primary_node": primary_id, "deleted_nodes": to_delete}}
            
        except Exception as e:
            return {"error": str(e)}
    
    # graph_delete_orphan_nodes (NEW - FOR MAINTENANCE)
    @mcp.tool
    def graph_delete_orphan_nodes() -> Dict:
        """
        Find and delete nodes with no edges (orphaned).
        """
        try:
            gs = get_graph_store()
            all_nodes = gs.get_nodes_by_type("fact", limit=1000)
            
            orphans = []
            for node in all_nodes:
                edges = gs.get_edges(node["id"])
                if not edges or len(edges) == 0:
                    orphans.append(node["id"])
                    gs.delete_node(node["id"])
            
            return {"structuredContent": {"deleted": len(orphans), "orphan_ids": orphans}}
            
        except Exception as e:
            return {"error": str(e), "deleted": 0}
    
    # graph_prune_weak_edges (NEW - FOR MAINTENANCE)
    @mcp.tool
    def graph_prune_weak_edges(threshold: float = 0.3) -> Dict:
        """
        Remove edges with weight below threshold.
        """
        try:
            gs = get_graph_store()
            
            # Get all edges (this might need optimization for large graphs)
            all_nodes = gs.get_nodes_by_type("fact", limit=1000)
            
            pruned_count = 0
            for node in all_nodes:
                edges = gs.get_edges(node["id"])
                for edge in edges:
                    if edge.get("weight", 1.0) < threshold:
                        # Delete weak edge
                        gs.delete_edge(edge["source"], edge["target"], edge["type"])
                        pruned_count += 1
            
            return {"structuredContent": {"pruned": pruned_count, "threshold": threshold}}
            
        except Exception as e:
            return {"error": str(e), "pruned": 0}

    # --------------------------------------------------
    # memory_reset (NEW - FOR FORCE CLEAR)
    # --------------------------------------------------
    @mcp.tool
    def memory_reset() -> Dict:
        """
        Wipes ALL memory, graph nodes, and edges.
        EXTREMELY DANGEROUS - IRREVERSIBLE.
        """
        import sqlite3
        from .config import DB_PATH
        
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            
            # Delete content from all tables
            c.execute("DELETE FROM memory")
            memory_count = c.rowcount
            
            c.execute("DELETE FROM graph_edges")
            edges_count = c.rowcount
            
            c.execute("DELETE FROM graph_nodes")
            nodes_count = c.rowcount
            
            # Try to clear FTS if possible
            try:
                c.execute("DELETE FROM memory_fts")
            except:
                pass
                
            conn.commit()
            conn.close()
            
            # Reset Vector Store if possible
            try:
                from vector_store import get_vector_store
                vs = get_vector_store()
                if hasattr(vs, "reset"):
                    vs.reset()
                elif hasattr(vs, "clear"):
                    vs.clear()
            except Exception as e:
                print(f"[memory_reset] Vector store reset failed: {e}")
            
            return {"structuredContent": {"success": True, "memory_entries": memory_count, "graph_nodes": nodes_count, "graph_edges": edges_count}}
            
        except Exception as e:
            return {"structuredContent": {"success": False, "error": str(e)}}

    # --------------------------------------------------
    # skill_metric_record
    # --------------------------------------------------
    @mcp.tool
    def skill_metric_record(
        skill_id: str,
        success: bool,
        exec_time_ms: float,
        error: Optional[str] = None,
        version: str = "1.0"
    ) -> Dict:
        """Records a skill execution result (success/failure, timing)."""
        row_id = upsert_skill_metric(skill_id, success, exec_time_ms, error, version)
        return {
            "structuredContent": {
                "recorded": True,
                "skill_id": skill_id,
                "row_id": row_id
            }
        }

    # --------------------------------------------------
    # skill_metric_get
    # --------------------------------------------------
    @mcp.tool
    def skill_metric_get(skill_id: str) -> Dict:
        """Returns metrics for a single skill."""
        metric = get_skill_metric(skill_id)
        if metric:
            return {"structuredContent": metric}
        return {"structuredContent": {"error": f"No metrics for {skill_id}"}}

    # --------------------------------------------------
    # skill_metrics_list
    # --------------------------------------------------
    @mcp.tool
    def skill_metrics_list(
        status: Optional[str] = None,
        limit: int = 50
    ) -> Dict:
        """Lists all skill metrics, optionally filtered by status."""
        metrics = list_skill_metrics(status, limit)
        return {
            "structuredContent": {
                "metrics": metrics,
                "count": len(metrics)
            }
        }

    # --------------------------------------------------
    # skill_metric_set_status
    # --------------------------------------------------
    @mcp.tool
    def skill_metric_set_status(skill_id: str, status: str) -> Dict:
        """Updates a skill's status (active/deprecated/beta)."""
        updated = update_skill_status(skill_id, status)
        return {
            "structuredContent": {
                "updated": updated,
                "skill_id": skill_id,
                "status": status
            }
        }

    # --------------------------------------------------
    # graph_add_node (for Daily Protocol merge)
    # --------------------------------------------------
    @mcp.tool
    def graph_add_node(
        source_type: str,
        content: str,
        conversation_id: str = "daily-protocol",
        confidence: float = 0.85,
        metadata: str = None,
    ) -> Dict:
        """Creates a graph node with embedding for semantic search. Used by Daily Protocol merge and Skill registry.
        metadata: optional JSON string with extra fields (e.g. skill_name for SkillSemanticRouter).
        """
        import json as _json
        # Embedding generieren damit memory_graph_search den Node findet
        embedding = None
        try:
            from embedding import get_embedding
            embedding = get_embedding(content)
        except Exception as e:
            print(f"[graph_add_node] Embedding failed (non-critical): {e}")

        node_id = build_node_with_edges(
            source_type=source_type,
            content=content,
            embedding=embedding,
            conversation_id=conversation_id,
            confidence=confidence,
            weight_boost=0.5
        )

        # KRITISCH: Auch in den VectorStore eintragen, damit vs.search() in
        # memory_graph_search() den Node als Seed findet. graph_nodes und
        # embeddings sind GETRENNTE Tabellen!
        try:
            vs = get_vector_store()
            # Metadata als Dict parsen wenn übergeben (für SkillSemanticRouter: skill_name)
            meta_dict = None
            if metadata:
                try:
                    meta_dict = _json.loads(metadata)
                except Exception:
                    pass
            vs.add(
                conversation_id=conversation_id,
                content=content,
                content_type=source_type,
                metadata=meta_dict,
            )
        except Exception as e:
            print(f"[graph_add_node] VectorStore add failed (non-critical): {e}")

        return {
            "structuredContent": {
                "node_id": node_id,
                "created": True
            }
        }

    # --------------------------------------------------
    # workspace_save
    # --------------------------------------------------
    @mcp.tool
    def workspace_save(
        conversation_id: str,
        content: str,
        entry_type: str = "observation",
        source_layer: str = "thinking"
    ) -> Dict:
        """Saves a workspace entry (observation, task, or note)."""
        entry_id = save_workspace_entry(conversation_id, content, entry_type, source_layer)
        return {
            "structuredContent": {
                "id": entry_id,
                "conversation_id": conversation_id,
                "entry_type": entry_type,
                "source_layer": source_layer
            }
        }

    # --------------------------------------------------
    # workspace_list
    # --------------------------------------------------
    @mcp.tool
    def workspace_list(
        conversation_id: Optional[str] = None,
        limit: int = 50,
        entry_type: Optional[str] = None
    ) -> Dict:
        """Lists workspace entries, optionally filtered by conversation and/or entry_type."""
        entries = list_workspace_entries(conversation_id, limit, entry_type)
        return {
            "structuredContent": {
                "entries": entries,
                "count": len(entries)
            }
        }

    # --------------------------------------------------
    # workspace_get
    # --------------------------------------------------
    @mcp.tool
    def workspace_get(entry_id: int) -> Dict:
        """Gets a single workspace entry by ID."""
        entry = get_workspace_entry(entry_id)
        if entry:
            return {"structuredContent": entry}
        return {"structuredContent": {"error": f"Entry {entry_id} not found"}}

    # --------------------------------------------------
    # workspace_update
    # --------------------------------------------------
    @mcp.tool
    def workspace_update(entry_id: int, content: str) -> Dict:
        """Updates the content of a workspace entry."""
        updated = update_workspace_entry(entry_id, content)
        return {
            "structuredContent": {
                "updated": updated,
                "entry_id": entry_id
            }
        }

    # --------------------------------------------------
    # workspace_delete
    # --------------------------------------------------
    @mcp.tool
    def workspace_delete(entry_id: int) -> Dict:
        """Deletes a workspace entry."""
        deleted = delete_workspace_entry(entry_id)
        return {
            "structuredContent": {
                "deleted": deleted,
                "entry_id": entry_id
            }
        }

    # --------------------------------------------------
    # memory_graph_save (NEW - Tool Registration Support)
    # --------------------------------------------------
    @mcp.tool
    def memory_graph_save(
        node_type: str,
        node_id: str,
        properties: Dict,
        searchable_text: str,
        content_type: str = "tool"
    ) -> Dict:
        """Saves a node to the graph and vector store with specific content_type.
        
        This enables Tool Selector to find tools via semantic search.
        Args:
            node_type: Type of node (e.g., 'tool')
            node_id: Unique identifier (e.g., tool name)
            properties: Metadata dict
            searchable_text: Text for semantic search
            content_type: Filter category (default: 'tool')
        """
        vs = get_vector_store()
        try:
            vs.add(
                conversation_id="global",  # Tools are global
                content=searchable_text,
                content_type=content_type,
                metadata=properties
            )
            return {
                "result": f"Saved {node_id} as {content_type}",
                "node_id": node_id,
                "content_type": content_type
            }
        except Exception as e:
            return {"error": f"Vector save failed: {e}"}

    # --------------------------------------------------
    # Secrets (encrypted API key storage)
    # --------------------------------------------------

    @mcp.tool
    def secret_save(name: str, value: str) -> dict:
        """Save or update an encrypted API secret by name."""
        try:
            save_secret(name, value)
            return {"success": True, "name": name}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool
    def secret_get(name: str) -> dict:
        """Retrieve the decrypted value of a secret. Internal use only."""
        val = get_secret_value(name)
        if val is None:
            return {"value": None, "error": f"Secret '{name}' not found"}
        return {"value": val}

    @mcp.tool
    def secret_list() -> dict:
        """List all secret names (values never returned)."""
        secrets = list_secrets()
        return {"secrets": secrets}

    @mcp.tool
    def secret_delete(name: str) -> dict:
        """Delete a secret by name."""
        deleted = delete_secret(name)
        return {"success": deleted, "name": name}
