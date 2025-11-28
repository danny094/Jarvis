import sqlite3
import sys
sys.path.insert(0, '/app')  # Damit embedding.py gefunden wird
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

        # NEU: Auch als Embedding speichern für semantische Suche
        try:
            vs = get_vector_store()
            content = f"{subject} {key}: {value}"
            vs.add(
                conversation_id=conversation_id,
                content=content,
                content_type="fact",
                metadata={"key": key, "value": value, "subject": subject}
            )
        except Exception as e:
            print(f"[memory_fact_save] Embedding failed: {e}")

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
    # memory_semantic_save (NEU)
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
    # memory_semantic_search (NEU)
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