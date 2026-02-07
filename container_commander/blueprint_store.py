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

    return Blueprint(
        id=row["id"],
        name=row["name"],
        description=row["description"] or "",
        extends=row["extends"],
        dockerfile=row["dockerfile"] or "",
        image=row["image"],
        system_prompt=row["system_prompt"] or "",
        resources=ResourceLimits(**resources_data) if resources_data else ResourceLimits(),
        secrets_required=[SecretRequirement(**s) for s in secrets_data],
        mounts=[MountDef(**m) for m in mounts_data],
        network=NetworkMode(row["network"]) if row["network"] else NetworkMode.INTERNAL,
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
        "system_prompt": bp.system_prompt,
        "resources_json": bp.resources.model_dump_json() if bp.resources else "{}",
        "secrets_json": json.dumps([s.model_dump() for s in bp.secrets_required]),
        "mounts_json": json.dumps([m.model_dump() for m in bp.mounts]),
        "network": bp.network.value if bp.network else "internal",
        "tags_json": json.dumps(bp.tags),
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
            INSERT INTO blueprints (id, name, description, extends, dockerfile, image,
                system_prompt, resources_json, secrets_json, mounts_json,
                network, tags_json, icon, created_at, updated_at)
            VALUES (:id, :name, :description, :extends, :dockerfile, :image,
                :system_prompt, :resources_json, :secrets_json, :mounts_json,
                :network, :tags_json, :icon, :created_at, :updated_at)
        """, params)
        conn.commit()
        bp.created_at = params["created_at"]
        bp.updated_at = params["updated_at"]
        return bp
    finally:
        conn.close()


def get_blueprint(blueprint_id: str) -> Optional[Blueprint]:
    """Get a single blueprint by ID."""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM blueprints WHERE id = ?", (blueprint_id,)).fetchone()
        return _row_to_blueprint(row) if row else None
    finally:
        conn.close()


def list_blueprints(tag: Optional[str] = None) -> List[Blueprint]:
    """List all blueprints, optionally filtered by tag."""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT * FROM blueprints ORDER BY name").fetchall()
        blueprints = [_row_to_blueprint(r) for r in rows]
        if tag:
            blueprints = [b for b in blueprints if tag.lower() in [t.lower() for t in b.tags]]
        return blueprints
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
                dockerfile=:dockerfile, image=:image, system_prompt=:system_prompt,
                resources_json=:resources_json, secrets_json=:secrets_json,
                mounts_json=:mounts_json, network=:network, tags_json=:tags_json,
                icon=:icon, updated_at=:updated_at
            WHERE id=:id
        """, params)
        conn.commit()
        return existing
    finally:
        conn.close()


def delete_blueprint(blueprint_id: str) -> bool:
    """Delete a blueprint by ID."""
    conn = _get_conn()
    try:
        cursor = conn.execute("DELETE FROM blueprints WHERE id = ?", (blueprint_id,))
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


# Auto-init on import
init_db()
