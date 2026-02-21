#!/usr/bin/env python3
"""
reconcile_graph_index.py — Phase 5 Graph Hygiene Reconcile Tool
================================================================

Standalone script to reconcile the blueprint graph index against SQLite truth.

What it does:
  1. Load all non-deleted blueprint_ids from SQLite (get_active_blueprint_ids)
  2. Query all blueprint graph nodes from the _blueprints conversation
  3. Identify stale nodes: blueprint_id not in SQLite active set, OR is_deleted=true in metadata
  4. Remove stale nodes from the graph (direct SQLite write to memory DB)
  5. Print a summary

When to run:
  - After batch deletions / imports
  - As a periodic maintenance task (e.g. weekly cron inside the admin-api container)
  - On demand via: python tools/reconcile_graph_index.py

Safety:
  - Dry-run mode by default (--apply to actually delete)
  - Never touches the SQLite blueprint store (read-only on commander.db)
  - Only deletes from graph_nodes table in memory.db

Usage:
  python tools/reconcile_graph_index.py [--apply] [--verbose]

Environment:
  JARVIS_DB_PATH    — path to commander SQLite DB (default: /app/data/commander.db)
  MEMORY_DB_PATH    — path to memory SQLite DB (default: /app/data/memory.db)
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

# ─── Add repo root to path ────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

COMMANDER_DB = os.environ.get("JARVIS_DB_PATH", "/app/data/commander.db")
MEMORY_DB    = os.environ.get("MEMORY_DB_PATH", "/app/data/memory.db")


# ─────────────────────────────────────────────────────────────────────────────
# Load active blueprint IDs from commander.db
# ─────────────────────────────────────────────────────────────────────────────

def _load_active_ids(commander_db: str) -> set:
    """Return set of blueprint_ids that are non-deleted in commander.db."""
    conn = sqlite3.connect(commander_db)
    try:
        rows = conn.execute(
            "SELECT id FROM blueprints WHERE (is_deleted IS NULL OR is_deleted = 0)"
        ).fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Load blueprint graph nodes from memory.db
# ─────────────────────────────────────────────────────────────────────────────

def _load_blueprint_graph_nodes(memory_db: str) -> list:
    """
    Return all graph_nodes rows with conversation_id='_blueprints'.
    Each row: {"node_id": int, "content": str, "metadata": dict, "blueprint_id": str}
    """
    conn = sqlite3.connect(memory_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, content, metadata FROM graph_nodes WHERE conversation_id = '_blueprints'"
        ).fetchall()
    except Exception as e:
        print(f"[Reconcile] graph_nodes query failed: {e}")
        return []
    finally:
        conn.close()

    nodes = []
    for row in rows:
        try:
            meta_raw = row["metadata"] or "{}"
            meta = json.loads(meta_raw) if isinstance(meta_raw, str) else (meta_raw or {})
        except Exception:
            meta = {}
        blueprint_id = meta.get("blueprint_id", "")
        if not blueprint_id:
            # Fallback: parse from content
            content = row["content"] or ""
            if ":" in content:
                blueprint_id = content.split(":", 1)[0].strip()
        nodes.append({
            "node_id": row["id"],
            "content": row["content"] or "",
            "metadata": meta,
            "blueprint_id": blueprint_id,
        })
    return nodes


# ─────────────────────────────────────────────────────────────────────────────
# Delete stale graph nodes
# ─────────────────────────────────────────────────────────────────────────────

def _delete_graph_nodes(memory_db: str, node_ids: list) -> int:
    """
    Hard-delete graph_nodes by id from memory.db.
    Also deletes associated embeddings rows (if table exists).
    Returns number of rows deleted from graph_nodes.
    """
    if not node_ids:
        return 0
    conn = sqlite3.connect(memory_db)
    try:
        placeholders = ",".join("?" * len(node_ids))
        conn.execute(
            f"DELETE FROM graph_nodes WHERE id IN ({placeholders})", node_ids
        )
        # Also clean up embeddings table if it exists
        try:
            conn.execute(
                f"DELETE FROM embeddings WHERE node_id IN ({placeholders})", node_ids
            )
        except Exception:
            pass  # embeddings table may not exist or have different schema
        conn.commit()
        return len(node_ids)
    except Exception as e:
        conn.rollback()
        print(f"[Reconcile] Delete failed: {e}")
        return 0
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Main reconcile logic
# ─────────────────────────────────────────────────────────────────────────────

def reconcile(
    commander_db: str = COMMANDER_DB,
    memory_db: str = MEMORY_DB,
    apply: bool = False,
    verbose: bool = False,
) -> dict:
    """
    Reconcile the blueprint graph index against SQLite truth.

    Returns dict with:
      active_in_sqlite   — count of non-deleted blueprints in SQLite
      graph_nodes_total  — total graph nodes in _blueprints
      stale_nodes        — list of {node_id, blueprint_id, reason}
      removed            — count of nodes actually deleted (0 in dry-run)
      dry_run            — True if apply=False
    """
    print(f"[Reconcile] Starting {'DRY RUN' if not apply else 'APPLY MODE'}")
    print(f"[Reconcile] commander.db: {commander_db}")
    print(f"[Reconcile] memory.db:    {memory_db}")
    print()

    # Load SQLite active set
    try:
        active_ids = _load_active_ids(commander_db)
        print(f"[Reconcile] Active blueprints in SQLite: {len(active_ids)}")
        if verbose:
            for bid in sorted(active_ids):
                print(f"  ✓ {bid}")
    except Exception as e:
        print(f"[Reconcile] ERROR: Cannot load SQLite active set: {e}")
        return {"error": str(e)}

    # Load graph nodes
    try:
        nodes = _load_blueprint_graph_nodes(memory_db)
        print(f"[Reconcile] Graph nodes in _blueprints: {len(nodes)}")
    except Exception as e:
        print(f"[Reconcile] ERROR: Cannot load graph nodes: {e}")
        return {"error": str(e)}

    # Identify stale nodes
    stale = []
    for node in nodes:
        bp_id = node["blueprint_id"]
        meta  = node["metadata"]

        if meta.get("is_deleted"):
            reason = "tombstoned (is_deleted=true in metadata)"
        elif not bp_id:
            reason = "no blueprint_id (unparseable node)"
        elif bp_id not in active_ids:
            reason = f"soft-deleted or stale ('{bp_id}' not in SQLite active set)"
        else:
            continue  # healthy node

        stale.append({
            "node_id": node["node_id"],
            "blueprint_id": bp_id or "(unknown)",
            "reason": reason,
        })

    print(f"[Reconcile] Stale graph nodes found: {len(stale)}")
    if stale:
        print()
        for s in stale:
            marker = "  [WOULD DELETE]" if not apply else "  [DELETING]"
            print(f"{marker} node_id={s['node_id']} blueprint_id={s['blueprint_id']!r}")
            print(f"    reason: {s['reason']}")

    removed = 0
    if apply and stale:
        stale_ids = [s["node_id"] for s in stale]
        removed = _delete_graph_nodes(memory_db, stale_ids)
        print(f"\n[Reconcile] Deleted {removed} stale graph nodes.")
    elif not apply and stale:
        print(f"\n[Reconcile] Dry-run: {len(stale)} nodes would be deleted. Use --apply to execute.")

    if not stale:
        print("[Reconcile] Graph index is clean — no stale nodes found.")

    result = {
        "active_in_sqlite": len(active_ids),
        "graph_nodes_total": len(nodes),
        "stale_nodes": stale,
        "removed": removed,
        "dry_run": not apply,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    return result


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Reconcile blueprint graph index against SQLite truth (Phase 5)."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete stale nodes (default: dry-run only).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print active blueprint IDs.",
    )
    parser.add_argument(
        "--commander-db",
        default=COMMANDER_DB,
        help=f"Path to commander SQLite DB (default: {COMMANDER_DB}).",
    )
    parser.add_argument(
        "--memory-db",
        default=MEMORY_DB,
        help=f"Path to memory SQLite DB (default: {MEMORY_DB}).",
    )
    args = parser.parse_args()

    result = reconcile(
        commander_db=args.commander_db,
        memory_db=args.memory_db,
        apply=args.apply,
        verbose=args.verbose,
    )
    if "error" in result:
        sys.exit(1)
