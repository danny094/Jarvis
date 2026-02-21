"""
Container Commander — Blueprint Store (SQLite CRUD)
═══════════════════════════════════════════════════════
Manages blueprint persistence in SQLite with:
- CRUD operations (create, read, update, delete)
- YAML import/export
- Blueprint inheritance resolution (extends field)
- Tag-based search
"""

import os
import json
import sqlite3
import yaml
from datetime import datetime
from typing import Optional, List, Dict
from .models import Blueprint, ResourceLimits, SecretRequirement, MountDef, NetworkMode


# ── Database Path ─────────────────────────────────────────

DB_PATH = os.environ.get("COMMANDER_DB_PATH", "/app/data/commander.db")


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create blueprint tables if they don't exist."""
    conn = _get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS blueprints (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                extends TEXT,
                dockerfile TEXT DEFAULT '',
                image TEXT,
                system_prompt TEXT DEFAULT '',
                resources_json TEXT DEFAULT '{}',
                secrets_json TEXT DEFAULT '[]',
                mounts_json TEXT DEFAULT '[]',
                network TEXT DEFAULT 'internal',
                tags_json TEXT DEFAULT '[]',
                icon TEXT DEFAULT '📦',
                created_at TEXT,
                updated_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS container_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                container_id TEXT,
                blueprint_id TEXT,
                action TEXT,
                details TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Auto-migration: add exec_policy_json column if not present (added in Phase 2)
        try:
            conn.execute("ALTER TABLE blueprints ADD COLUMN exec_policy_json TEXT DEFAULT '[]'")
            conn.commit()
        except Exception:
            pass  # Column already exists
        # Auto-migration: add is_deleted column if not present (added in Phase 3)
        try:
            conn.execute("ALTER TABLE blueprints ADD COLUMN is_deleted INTEGER DEFAULT 0")
            conn.commit()
        except Exception:
            pass  # Column already exists
        # Auto-migration: add image_digest column if not present (added in Phase 3 - trust hardening)
        try:
            conn.execute("ALTER TABLE blueprints ADD COLUMN image_digest TEXT DEFAULT NULL")
            conn.commit()
        except Exception:
            pass  # Column already exists
        conn.commit()
    finally:
        conn.close()


# ── Row ↔ Model Conversion ────────────────────────────────

def _row_to_blueprint(row: sqlite3.Row) -> Blueprint:
    """Convert a DB row to a Blueprint model."""
    resources_data = json.loads(row["resources_json"] or "{}")
    secrets_data = json.loads(row["secrets_json"] or "[]")
    mounts_data = json.loads(row["mounts_json"] or "[]")
    tags = json.loads(row["tags_json"] or "[]")
    # exec_policy_json added in Phase 2 — graceful fallback for older rows
    try:
        allowed_exec = json.loads(row["exec_policy_json"] or "[]")
    except Exception:
        allowed_exec = []

    # image_digest added in Phase 3 — graceful fallback
    try:
        image_digest = row["image_digest"] or None
    except Exception:
        image_digest = None

    return Blueprint(
        id=row["id"],
        name=row["name"],
        description=row["description"] or "",
        extends=row["extends"],
        dockerfile=row["dockerfile"] or "",
        image=row["image"],
        image_digest=image_digest,
        system_prompt=row["system_prompt"] or "",
        resources=ResourceLimits(**resources_data) if resources_data else ResourceLimits(),
        secrets_required=[SecretRequirement(**s) for s in secrets_data],
        mounts=[MountDef(**m) for m in mounts_data],
        network=NetworkMode(row["network"]) if row["network"] else NetworkMode.INTERNAL,
        allowed_exec=allowed_exec,
        tags=tags,
        icon=row["icon"] or "📦",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _blueprint_to_params(bp: Blueprint) -> dict:
    """Convert a Blueprint model to DB insert params."""
    return {
        "id": bp.id,
        "name": bp.name,
        "description": bp.description,
        "extends": bp.extends,
        "dockerfile": bp.dockerfile,
        "image": bp.image,
        "image_digest": bp.image_digest,
        "system_prompt": bp.system_prompt,
        "resources_json": bp.resources.model_dump_json() if bp.resources else "{}",
        "secrets_json": json.dumps([s.model_dump() for s in bp.secrets_required]),
        "mounts_json": json.dumps([m.model_dump() for m in bp.mounts]),
        "network": bp.network.value if bp.network else "internal",
        "tags_json": json.dumps(bp.tags),
        "exec_policy_json": json.dumps(bp.allowed_exec),
        "icon": bp.icon,
        "created_at": bp.created_at or datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }


# ── CRUD Operations ───────────────────────────────────────

def create_blueprint(bp: Blueprint) -> Blueprint:
    """Insert a new blueprint into the database."""
    conn = _get_conn()
    try:
        params = _blueprint_to_params(bp)
        conn.execute("""
            INSERT INTO blueprints (id, name, description, extends, dockerfile, image, image_digest,
                system_prompt, resources_json, secrets_json, mounts_json,
                network, tags_json, exec_policy_json, icon, created_at, updated_at)
            VALUES (:id, :name, :description, :extends, :dockerfile, :image, :image_digest,
                :system_prompt, :resources_json, :secrets_json, :mounts_json,
                :network, :tags_json, :exec_policy_json, :icon, :created_at, :updated_at)
        """, params)
        conn.commit()
        bp.created_at = params["created_at"]
        bp.updated_at = params["updated_at"]
        return bp
    finally:
        conn.close()


def get_blueprint(blueprint_id: str) -> Optional[Blueprint]:
    """Get a single blueprint by ID (excluding soft-deleted)."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM blueprints WHERE id = ? AND (is_deleted IS NULL OR is_deleted = 0)",
            (blueprint_id,)
        ).fetchone()
        return _row_to_blueprint(row) if row else None
    finally:
        conn.close()


def list_blueprints(tag: Optional[str] = None) -> List[Blueprint]:
    """List all active (non-deleted) blueprints, optionally filtered by tag."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM blueprints WHERE (is_deleted IS NULL OR is_deleted = 0) ORDER BY name"
        ).fetchall()
        blueprints = [_row_to_blueprint(r) for r in rows]
        if tag:
            blueprints = [b for b in blueprints if tag.lower() in [t.lower() for t in b.tags]]
        return blueprints
    finally:
        conn.close()


def get_active_blueprint_ids() -> set:
    """Return the set of active (non-deleted) blueprint IDs for cross-checking."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT id FROM blueprints WHERE (is_deleted IS NULL OR is_deleted = 0)"
        ).fetchall()
        return {row["id"] for row in rows}
    except Exception:
        return set()
    finally:
        conn.close()


def update_blueprint(blueprint_id: str, updates: dict) -> Optional[Blueprint]:
    """Update specific fields of a blueprint."""
    existing = get_blueprint(blueprint_id)
    if not existing:
        return None

    # Merge updates into existing blueprint
    for key, value in updates.items():
        if hasattr(existing, key) and value is not None:
            if key == "resources" and isinstance(value, dict):
                setattr(existing, key, ResourceLimits(**value))
            elif key == "secrets_required" and isinstance(value, list):
                setattr(existing, key, [SecretRequirement(**s) if isinstance(s, dict) else s for s in value])
            elif key == "mounts" and isinstance(value, list):
                setattr(existing, key, [MountDef(**m) if isinstance(m, dict) else m for m in value])
            elif key == "network":
                setattr(existing, key, NetworkMode(value) if isinstance(value, str) else value)
            else:
                setattr(existing, key, value)

    conn = _get_conn()
    try:
        params = _blueprint_to_params(existing)
        conn.execute("""
            UPDATE blueprints SET
                name=:name, description=:description, extends=:extends,
                dockerfile=:dockerfile, image=:image, image_digest=:image_digest,
                system_prompt=:system_prompt,
                resources_json=:resources_json, secrets_json=:secrets_json,
                mounts_json=:mounts_json, network=:network, tags_json=:tags_json,
                exec_policy_json=:exec_policy_json,
                icon=:icon, updated_at=:updated_at
            WHERE id=:id
        """, params)
        conn.commit()
        return existing
    finally:
        conn.close()


def delete_blueprint(blueprint_id: str) -> bool:
    """Soft-delete a blueprint by ID (sets is_deleted=1, keeps row for audit trail).
    The Graph node for this blueprint will remain (no graph_delete_node tool available),
    but Router and ContextManager cross-check against this SQLite flag — stale graph
    nodes are filtered before routing or context injection.
    """
    conn = _get_conn()
    try:
        cursor = conn.execute(
            "UPDATE blueprints SET is_deleted=1, updated_at=? WHERE id=? AND (is_deleted IS NULL OR is_deleted=0)",
            (datetime.utcnow().isoformat(), blueprint_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# ── Blueprint Inheritance ──────────────────────────────────

def resolve_blueprint(blueprint_id: str) -> Optional[Blueprint]:
    """
    Resolve a blueprint with inheritance (extends field).
    Child overrides parent. Merges: tags, secrets, mounts.
    """
    bp = get_blueprint(blueprint_id)
    if not bp:
        return None
    if not bp.extends:
        return bp

    parent = resolve_blueprint(bp.extends)  # Recursive
    if not parent:
        return bp

    # Merge: child overrides parent, lists are combined
    merged = parent.model_copy()
    merged.id = bp.id
    merged.name = bp.name
    merged.icon = bp.icon

    if bp.description:
        merged.description = bp.description
    if bp.dockerfile:
        merged.dockerfile = bp.dockerfile
    if bp.image:
        merged.image = bp.image
    if bp.system_prompt:
        merged.system_prompt = bp.system_prompt
    if bp.network != NetworkMode.INTERNAL:
        merged.network = bp.network

    # Merge resources (child overrides non-default values)
    if bp.resources:
        merged.resources = bp.resources

    # Combine lists (deduplicate tags, append secrets/mounts)
    merged.tags = list(set(parent.tags + bp.tags))
    
    existing_secret_names = {s.name for s in parent.secrets_required}
    for s in bp.secrets_required:
        if s.name not in existing_secret_names:
            merged.secrets_required.append(s)

    existing_mounts = {m.container for m in parent.mounts}
    for m in bp.mounts:
        if m.container not in existing_mounts:
            merged.mounts.append(m)

    merged.created_at = bp.created_at
    merged.updated_at = bp.updated_at
    return merged


# ── YAML Import/Export ─────────────────────────────────────

def import_from_yaml(yaml_content: str) -> Blueprint:
    """Parse a YAML string into a Blueprint and save it."""
    data = yaml.safe_load(yaml_content)
    
    # Handle nested resource/secrets/mounts
    resources = ResourceLimits(**(data.pop("resources", {})))
    secrets = [SecretRequirement(**s) for s in data.pop("secrets_required", [])]
    mounts = [MountDef(**m) for m in data.pop("mounts", [])]
    network = NetworkMode(data.pop("network", "internal"))
    
    bp = Blueprint(
        resources=resources,
        secrets_required=secrets,
        mounts=mounts,
        network=network,
        **{k: v for k, v in data.items() if k in Blueprint.model_fields}
    )
    
    return create_blueprint(bp)


def export_to_yaml(blueprint_id: str) -> Optional[str]:
    """Export a blueprint as YAML string."""
    bp = resolve_blueprint(blueprint_id)
    if not bp:
        return None
    
    data = bp.model_dump(exclude_none=True)
    # Convert enums to strings
    data["network"] = bp.network.value
    data["resources"] = bp.resources.model_dump()
    data["secrets_required"] = [s.model_dump() for s in bp.secrets_required]
    data["mounts"] = [m.model_dump() for m in bp.mounts]
    
    return yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)


# ── Audit Log ──────────────────────────────────────────────

def log_action(container_id: str, blueprint_id: str, action: str, details: str = ""):
    """Log a container action for audit trail."""
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO container_log (container_id, blueprint_id, action, details) VALUES (?, ?, ?, ?)",
            (container_id, blueprint_id, action, details)
        )
        conn.commit()
    finally:
        conn.close()


def get_audit_log(blueprint_id: Optional[str] = None, limit: int = 50) -> List[dict]:
    """Get audit log entries."""
    conn = _get_conn()
    try:
        if blueprint_id:
            rows = conn.execute(
                "SELECT * FROM container_log WHERE blueprint_id = ? ORDER BY created_at DESC LIMIT ?",
                (blueprint_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM container_log ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def seed_default_blueprints():
    """Seed default blueprints if DB is empty."""
    from .models import Blueprint, ResourceLimits, NetworkMode
    
    existing = list_blueprints()
    if existing:
        return  # Already seeded
    
    defaults = [
        Blueprint(id="python-sandbox", name="Python Sandbox",
                  description="Isolierte Python-Umgebung mit pip. Fuer Berechnungen, Datenanalyse, Scripts.",
                  image="python:3.12-slim", icon="\U0001f40d",
                  resources=ResourceLimits(cpu_limit="1.0", memory_limit="512m", timeout_seconds=600),
                  tags=["python", "sandbox", "code", "compute"],
                  allowed_exec=["python", "python3", "pip", "pip3", "sh", "bash"]),
        Blueprint(id="node-sandbox", name="Node.js Sandbox",
                  description="Isolierte Node.js-Umgebung mit npm. Fuer JavaScript, TypeScript, Web-Tools.",
                  image="node:20-slim", icon="\U0001f7e2",
                  resources=ResourceLimits(cpu_limit="1.0", memory_limit="512m", timeout_seconds=600),
                  tags=["node", "javascript", "sandbox", "web"],
                  allowed_exec=["node", "npm", "npx", "yarn", "sh", "bash"]),
        Blueprint(id="db-sandbox", name="Database Sandbox",
                  description="SQLite/PostgreSQL-Umgebung fuer Datenbankoperationen und SQL-Queries.",
                  image="python:3.12-slim", icon="\U0001f5c4",
                  resources=ResourceLimits(cpu_limit="0.5", memory_limit="256m", timeout_seconds=300),
                  tags=["database", "sql", "sqlite", "data"],
                  allowed_exec=["python", "python3", "pip", "pip3", "sqlite3", "sh", "bash"]),
        Blueprint(id="shell-sandbox", name="Shell Sandbox",
                  description="Alpine-basierte Shell-Umgebung fuer Systemtools, curl, jq, etc.",
                  image="alpine:latest", icon="\U0001f41a",
                  resources=ResourceLimits(cpu_limit="0.5", memory_limit="256m", timeout_seconds=300),
                  tags=["shell", "linux", "tools", "system"],
                  allowed_exec=["sh", "ash", "bash", "ls", "cat", "grep", "echo",
                                "curl", "wget", "jq", "awk", "sed", "find", "ps",
                                "df", "du", "env", "printenv", "uname", "hostname"]),
    ]
    
    for bp in defaults:
        try:
            create_blueprint(bp)
        except Exception:
            pass
    
    import logging
    logging.getLogger(__name__).info(f"[BlueprintStore] Seeded {len(defaults)} default blueprints")


_DEFAULT_EXEC_POLICIES = {
    "python-sandbox": ["python", "python3", "pip", "pip3", "sh", "bash"],
    "node-sandbox":   ["node", "npm", "npx", "yarn", "sh", "bash"],
    "db-sandbox":     ["python", "python3", "pip", "pip3", "sqlite3", "sh", "bash"],
    "shell-sandbox":  ["sh", "ash", "bash", "ls", "cat", "grep", "echo",
                       "curl", "wget", "jq", "awk", "sed", "find", "ps",
                       "df", "du", "env", "printenv", "uname", "hostname"],
}


def backfill_exec_policies():
    """
    Backfill allowed_exec for official blueprints that predate Phase 2.
    Only updates rows where exec_policy_json is empty/null.
    Safe to call on every startup.
    """
    import logging as _log
    conn = _get_conn()
    try:
        updated = 0
        for bp_id, policy in _DEFAULT_EXEC_POLICIES.items():
            row = conn.execute(
                "SELECT exec_policy_json FROM blueprints WHERE id = ?", (bp_id,)
            ).fetchone()
            if row is None:
                continue
            current = json.loads(row["exec_policy_json"] or "[]")
            if not current:
                conn.execute(
                    "UPDATE blueprints SET exec_policy_json = ? WHERE id = ?",
                    (json.dumps(policy), bp_id)
                )
                updated += 1
        conn.commit()
        if updated:
            _log.getLogger(__name__).info(f"[BlueprintStore] Backfilled exec policies for {updated} blueprints")
    finally:
        conn.close()


# Official built-in blueprints that are always trusted.
# User-created blueprints (via API or MCP) are "unverified" by default.
_OFFICIAL_BLUEPRINT_IDS = frozenset({"python-sandbox", "node-sandbox", "db-sandbox", "shell-sandbox"})


def _sync_single_blueprint_to_graph(bp, trust_level: str = "", force_update: bool = False) -> bool:
    """
    Sync a single blueprint to the graph (for create/update hooks).
    trust_level: override string; if empty, derived via trust.py (single source of truth).
    force_update: if True, always write a new node (for update flows — overwrites stale graph data).
                  if False (default), skip if blueprint_id already exists in graph (create flow).
    Returns True on success.
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)
    try:
        from mcp.client import call_tool
        if not force_update:
            # Dedup: skip if already in graph (create flow)
            # call_tool() wraps hub results as {"result": original} — handle all variants
            existing_raw = call_tool("memory_graph_search", {"conversation_id": "_blueprints", "query": bp.id, "limit": 5}) or {}
            existing = existing_raw.get("result", existing_raw) if isinstance(existing_raw, dict) else {}
            # structuredContent may live on existing_raw OR on the unwrapped existing dict
            sc = (
                existing_raw.get("structuredContent", {}) if isinstance(existing_raw, dict) else {}
            ) or (
                existing.get("structuredContent", {}) if isinstance(existing, dict) else {}
            )
            nodes = (
                existing.get("nodes")
                or existing.get("results")
                or sc.get("nodes")
                or sc.get("results")
                or []
            )
            for node in nodes:
                try:
                    meta_raw = node.get("metadata") or "{}"
                    # metadata can be a JSON string OR already a dict (depends on MCP response variant)
                    meta = meta_raw if isinstance(meta_raw, dict) else json.loads(meta_raw)
                except Exception:
                    continue
                if meta.get("blueprint_id") == bp.id:
                    _log.info(f"[BlueprintSync] Single sync: {bp.id} already in graph — skipping")
                    return True

        # Derive trust via trust.py if not provided by caller
        if not trust_level:
            try:
                from .trust import evaluate_blueprint_trust
                trust_level = evaluate_blueprint_trust(bp)["level"]
            except Exception:
                trust_level = "unverified"

        caps = bp.tags or []
        resources = bp.resources
        content = (
            f"{bp.id}: {bp.description or bp.name} "
            f"(Capabilities: {', '.join(caps)})"
        )
        result = call_tool("graph_add_node", {
            "conversation_id": "_blueprints",
            "source_type": "blueprint",
            "content": content,
            "confidence": 0.9,
            "metadata": json.dumps({
                "blueprint_id": bp.id,
                "name": bp.name,
                "trust_level": trust_level,
                "capabilities": caps,
                "network": bp.network.value if bp.network else "internal",
                "image": bp.image or "",
                "memory": resources.memory_limit if resources else "",
                "cpu": resources.cpu_limit if resources else "",
                "updated_at": bp.updated_at or "",  # Phase 5: enables revision-based dedupe
            }),
        })
        if result and result.get("error"):
            _log.warning(f"[BlueprintSync] Single sync error for {bp.id}: {result}")
            return False
        _log.info(f"[BlueprintSync] Single sync: {bp.id} (trust={trust_level})")
        return True
    except Exception as e:
        _log.warning(f"[BlueprintSync] Single sync failed for {bp.id}: {e}")
        return False


def remove_blueprint_from_graph(blueprint_id: str) -> int:
    """
    Mark stale graph nodes for a deleted blueprint as tombstoned.

    Phase 5 — Delete consistency:
    The primary tombstone mechanism is the SQLite cross-check in core/graph_hygiene.py
    (fail-closed): once a blueprint is deleted from SQLite, it disappears from all
    Router/Context results immediately.

    This function additionally marks matching graph nodes with is_deleted=true in their
    metadata so that the reconcile script (tools/reconcile_graph_index.py) can later
    clean them up from the graph store.

    Returns: number of graph nodes marked (0 if none found or on error).
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)
    try:
        from mcp.client import call_tool
        # Find existing nodes for this blueprint_id
        existing_raw = call_tool(
            "memory_graph_search",
            {"conversation_id": "_blueprints", "query": blueprint_id, "limit": 10},
        ) or {}
        existing = existing_raw.get("result", existing_raw) if isinstance(existing_raw, dict) else {}
        sc = (
            existing_raw.get("structuredContent", {}) if isinstance(existing_raw, dict) else {}
        ) or (
            existing.get("structuredContent", {}) if isinstance(existing, dict) else {}
        )
        nodes = (
            existing.get("nodes") or existing.get("results")
            or sc.get("nodes") or sc.get("results") or []
        )

        marked = 0
        for node in nodes:
            try:
                meta_raw = node.get("metadata") or "{}"
                meta = meta_raw if isinstance(meta_raw, dict) else json.loads(meta_raw)
            except Exception:
                continue
            if meta.get("blueprint_id") != blueprint_id:
                continue
            # Add tombstone marker via a new graph node (overwrites via force_update pattern)
            meta["is_deleted"] = True
            meta["deleted_at"] = datetime.utcnow().isoformat()
            # Re-upsert the node with tombstone metadata so reconcile can identify it
            call_tool("graph_add_node", {
                "conversation_id": "_blueprints",
                "source_type": "blueprint",
                "content": node.get("content", blueprint_id),
                "confidence": 0.0,  # Low confidence signals tombstoned node
                "metadata": json.dumps(meta),
            })
            marked += 1
            _log.info(f"[BlueprintSync] Tombstoned graph node for '{blueprint_id}' (node_id={node.get('id', '?')})")

        if marked == 0:
            _log.info(f"[BlueprintSync] No graph nodes found for '{blueprint_id}' — nothing to tombstone")
        return marked
    except Exception as e:
        _log.warning(f"[BlueprintSync] remove_blueprint_from_graph failed for '{blueprint_id}': {e}")
        return 0


def sync_blueprints_to_graph() -> int:
    """
    Sync all blueprints from SQLite to the memory graph (conv_id="_blueprints").

    Uses mcp.client.call_tool() — reuses MCPHub protocol (SSE-aware).
    Idempotent: fetches existing graph nodes first, skips already-synced blueprints.
    Per-blueprint try/except: one failure doesn't abort the whole sync.

    Returns: number of newly synced blueprints.
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)

    # Import here to avoid circular imports at module load time
    try:
        from mcp.client import call_tool
    except ImportError as e:
        _log.error(f"[BlueprintSync] Cannot import mcp.client: {e}")
        return 0

    blueprints = list_blueprints()
    if not blueprints:
        return 0

    # 1. Load existing blueprint_ids from graph to avoid duplicates
    existing_ids: set = set()
    try:
        resp = call_tool("memory_graph_search", {
            "query": "blueprint",
            "conversation_id": "_blueprints",
            "depth": 0,
            "limit": 100,
        })
        result = resp.get("result", resp) if resp else {}
        if isinstance(result, dict):
            results = result.get("results", [])
        else:
            results = []
        for node in results:
            try:
                meta_raw = node.get("metadata") or "{}"
                meta = json.loads(meta_raw) if isinstance(meta_raw, str) else meta_raw
                bp_id = meta.get("blueprint_id")
                if bp_id:
                    existing_ids.add(bp_id)
            except Exception:
                pass
        _log.info(f"[BlueprintSync] {len(existing_ids)} blueprints already in graph")
    except Exception as e:
        _log.warning(f"[BlueprintSync] Could not fetch existing graph nodes: {e} — syncing all")

    # 2. Sync missing blueprints
    count = 0
    for bp in blueprints:
        try:
            if bp.id in existing_ids:
                _log.info(f"[BlueprintSync] Skipping {bp.id} — already in graph")
                continue

            caps = bp.tags or []
            resources = bp.resources
            content = (
                f"{bp.id}: {bp.description or bp.name} "
                f"(Capabilities: {', '.join(caps)})"
            )
            from .trust import evaluate_blueprint_trust
            _trust = evaluate_blueprint_trust(bp)["level"]
            result = call_tool("graph_add_node", {
                "conversation_id": "_blueprints",
                "source_type": "blueprint",
                "content": content,
                "confidence": 0.9,
                "metadata": json.dumps({
                    "blueprint_id": bp.id,
                    "name": bp.name,
                    "trust_level": _trust,  # Official built-ins = verified, user-created = unverified
                    "capabilities": caps,
                    "network": bp.network.value if bp.network else "internal",
                    "image": bp.image or "",
                    "memory": resources.memory_limit if resources else "",
                    "cpu": resources.cpu_limit if resources else "",
                    "updated_at": bp.updated_at or "",  # Phase 5: enables revision-based dedupe
                }),
            })
            # Check for error in response before counting as success
            if result and (result.get("error") or result.get("structuredContent", {}).get("error")):
                _log.warning(f"[BlueprintSync] graph_add_node returned error for {bp.id}: {result}")
                continue
            count += 1
            _log.info(f"[BlueprintSync] Synced blueprint: {bp.id}")
        except Exception as e:
            _log.warning(f"[BlueprintSync] Failed to sync {bp.id}: {e}")
            continue  # One failure doesn't abort the rest

    _log.info(f"[BlueprintSync] Done: {count} new blueprints synced to graph")
    return count


# Auto-init on import
init_db()
seed_default_blueprints()
