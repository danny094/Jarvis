"""
SkillKnowledgeBase — Pull-basierte Inspirationsdatenbank für Skill-Erstellung

TRION bekommt nur einen winzigen Hinweis dass diese DB existiert.
Er fragt sie aktiv ab wenn er Inspiration oder Paket-Infos braucht.

REST Endpoints:
  GET  /v1/skill-knowledge/categories
  GET  /v1/skill-knowledge/search?query=...&category=...&limit=5

MCP Tool:
  query_skill_knowledge(query, category, limit)
"""

import os
import json
import sqlite3
from typing import Optional, List, Dict, Any
from pathlib import Path


DB_PATH = os.getenv("SKILL_KNOWLEDGE_DB", "/app/data/skill_knowledge.db")


# ─── DB Init ──────────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Erstellt die Tabelle falls sie nicht existiert."""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS skill_knowledge (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                category    TEXT NOT NULL,
                subcategory TEXT,
                name        TEXT NOT NULL UNIQUE,
                description TEXT,
                packages    TEXT DEFAULT '[]',
                code_snippet TEXT DEFAULT '',
                triggers    TEXT DEFAULT '[]',
                complexity  TEXT DEFAULT 'simple'
            )
        """)
        conn.commit()


# ─── Queries ──────────────────────────────────────────────────────────────────

def get_categories() -> List[str]:
    """Gibt alle vorhandenen Kategorien zurück."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT category FROM skill_knowledge ORDER BY category"
        ).fetchall()
    return [r["category"] for r in rows]


def search(
    query: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Volltextsuche auf name + description + triggers.
    Optionaler category-Filter.
    Gibt immer packages zurück (wichtig für Allowlist-Check).
    """
    with _get_conn() as conn:
        params: list = []
        conditions: list = []

        if category:
            conditions.append("category = ?")
            params.append(category)

        if query:
            q = f"%{query.lower()}%"
            conditions.append(
                "(lower(name) LIKE ? OR lower(description) LIKE ? OR lower(triggers) LIKE ?)"
            )
            params += [q, q, q]

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = f"""
            SELECT id, category, subcategory, name, description,
                   packages, code_snippet, triggers, complexity
            FROM skill_knowledge
            {where}
            ORDER BY complexity ASC, name ASC
            LIMIT ?
        """
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()

    results = []
    for r in rows:
        results.append({
            "name": r["name"],
            "category": r["category"],
            "subcategory": r["subcategory"],
            "description": r["description"],
            "packages": json.loads(r["packages"] or "[]"),
            "triggers": json.loads(r["triggers"] or "[]"),
            "complexity": r["complexity"],
            "code_snippet": r["code_snippet"] or "",
        })
    return results


def add_entry(
    category: str,
    name: str,
    description: str,
    packages: list,
    triggers: list,
    subcategory: str = "",
    code_snippet: str = "",
    complexity: str = "simple",
) -> bool:
    """Fügt einen Eintrag hinzu (UPSERT). Gibt True bei Erfolg zurück."""
    try:
        with _get_conn() as conn:
            conn.execute(
                """
                INSERT INTO skill_knowledge
                    (category, subcategory, name, description, packages,
                     code_snippet, triggers, complexity)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    category    = excluded.category,
                    subcategory = excluded.subcategory,
                    description = excluded.description,
                    packages    = excluded.packages,
                    code_snippet = excluded.code_snippet,
                    triggers    = excluded.triggers,
                    complexity  = excluded.complexity
                """,
                (
                    category, subcategory, name, description,
                    json.dumps(packages, ensure_ascii=False),
                    code_snippet,
                    json.dumps(triggers, ensure_ascii=False),
                    complexity,
                ),
            )
            conn.commit()
        return True
    except Exception as e:
        print(f"[SkillKnowledge] add_entry error: {e}")
        return False


def count() -> int:
    with _get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM skill_knowledge").fetchone()[0]


# ─── MCP Tool Handler ─────────────────────────────────────────────────────────

def handle_query_skill_knowledge(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    MCP Tool: query_skill_knowledge
    Gibt Inspiration + Paket-Infos für Skill-Erstellung zurück.
    """
    query = args.get("query")
    category = args.get("category")
    limit = min(int(args.get("limit", 5)), 10)

    results = search(query=query, category=category, limit=limit)

    if not results:
        return {
            "found": 0,
            "entries": [],
            "hint": "Keine passenden Templates gefunden. Skill von Grund auf erstellen.",
        }

    return {
        "found": len(results),
        "entries": results,
        "hint": (
            "Nutze code_snippet als Ausgangsbasis. "
            "Prüfe 'packages' — leere Liste = nur Python Built-ins."
        ),
    }


# ─── Init on import ───────────────────────────────────────────────────────────

init_db()
