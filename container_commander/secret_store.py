"""
Container Commander — Encrypted Secret Vault (Fernet)
═══════════════════════════════════════════════════════
Stores secrets encrypted at rest in SQLite.
The KI NEVER sees plaintext values — only SecretRef objects.

Encryption: Fernet (symmetric, AES-128-CBC + HMAC-SHA256)
Master Key: From TRION_VAULT_KEY env var or auto-generated

Flow:
1. User stores secret via Terminal UI → encrypted in DB
2. KI calls request_container(blueprint_id)
3. Engine checks blueprint.secrets_required
4. Engine decrypts & injects as --env vars into container
5. KI executes code that reads os.environ — never sees the key
"""

import os
import json
import sqlite3
import base64
import hashlib
from datetime import datetime
from typing import Optional, List
from cryptography.fernet import Fernet

from .models import SecretEntry, SecretRef, SecretScope


# ── Encryption Setup ──────────────────────────────────────

def _get_master_key() -> bytes:
    """
    Get or generate the master encryption key.
    Priority: TRION_VAULT_KEY env → auto-generated key file.
    """
    env_key = os.environ.get("TRION_VAULT_KEY")
    if env_key:
        # Derive a proper Fernet key from the env var
        key_bytes = hashlib.sha256(env_key.encode()).digest()
        return base64.urlsafe_b64encode(key_bytes)

    # Auto-generate and persist
    key_file = os.path.join(os.path.dirname(DB_PATH), ".vault_key")
    if os.path.exists(key_file):
        with open(key_file, "rb") as f:
            return f.read().strip()
    
    key = Fernet.generate_key()
    os.makedirs(os.path.dirname(key_file), exist_ok=True)
    with open(key_file, "wb") as f:
        f.write(key)
    os.chmod(key_file, 0o600)  # Owner-only read
    return key


def _get_fernet() -> Fernet:
    return Fernet(_get_master_key())


# ── Database ──────────────────────────────────────────────

DB_PATH = os.environ.get("COMMANDER_DB_PATH", "/app/data/commander.db")


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_secrets_db():
    """Create the secrets table."""
    conn = _get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS secrets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                encrypted_value BLOB NOT NULL,
                scope TEXT DEFAULT 'global',
                blueprint_id TEXT,
                created_at TEXT,
                expires_at TEXT,
                UNIQUE(name, scope, blueprint_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS secret_access_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                secret_name TEXT,
                action TEXT,
                container_id TEXT,
                blueprint_id TEXT,
                accessed_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    finally:
        conn.close()


# ── Store / Retrieve ──────────────────────────────────────

def store_secret(name: str, value: str, scope: SecretScope = SecretScope.GLOBAL,
                 blueprint_id: Optional[str] = None, expires_at: Optional[str] = None) -> SecretEntry:
    """Encrypt and store a secret. Returns entry WITHOUT the value."""
    fernet = _get_fernet()
    encrypted = fernet.encrypt(value.encode("utf-8"))
    now = datetime.utcnow().isoformat()

    conn = _get_conn()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO secrets (name, encrypted_value, scope, blueprint_id, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (name, encrypted, scope.value, blueprint_id, now, expires_at))
        conn.commit()

        return SecretEntry(
            name=name, scope=scope, blueprint_id=blueprint_id,
            created_at=now, expires_at=expires_at
        )
    finally:
        conn.close()


def get_secret_value(name: str, scope: SecretScope = SecretScope.GLOBAL,
                     blueprint_id: Optional[str] = None) -> Optional[str]:
    """
    Decrypt and return a secret value.
    INTERNAL USE ONLY — for injecting into containers.
    The KI should NEVER call this directly.
    """
    conn = _get_conn()
    try:
        if scope == SecretScope.BLUEPRINT and blueprint_id:
            row = conn.execute(
                "SELECT * FROM secrets WHERE name = ? AND scope = ? AND blueprint_id = ?",
                (name, scope.value, blueprint_id)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM secrets WHERE name = ? AND scope = 'global'", (name,)
            ).fetchone()

        if not row:
            return None

        # Check expiry
        if row["expires_at"]:
            if datetime.fromisoformat(row["expires_at"]) < datetime.utcnow():
                # Expired — delete and return None
                conn.execute("DELETE FROM secrets WHERE id = ?", (row["id"],))
                conn.commit()
                return None

        fernet = _get_fernet()
        return fernet.decrypt(row["encrypted_value"]).decode("utf-8")
    finally:
        conn.close()


def list_secrets(scope: Optional[SecretScope] = None,
                 blueprint_id: Optional[str] = None) -> List[SecretRef]:
    """List all secrets as references (no values exposed)."""
    conn = _get_conn()
    try:
        query = "SELECT name, scope, blueprint_id FROM secrets"
        params = []

        conditions = []
        if scope:
            conditions.append("scope = ?")
            params.append(scope.value)
        if blueprint_id:
            conditions.append("blueprint_id = ?")
            params.append(blueprint_id)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY name"
        rows = conn.execute(query, params).fetchall()

        return [
            SecretRef(name=r["name"], scope=r["scope"], blueprint_id=r["blueprint_id"])
            for r in rows
        ]
    finally:
        conn.close()


def delete_secret(name: str, scope: SecretScope = SecretScope.GLOBAL,
                  blueprint_id: Optional[str] = None) -> bool:
    """Delete a secret from the vault."""
    conn = _get_conn()
    try:
        if scope == SecretScope.BLUEPRINT and blueprint_id:
            cursor = conn.execute(
                "DELETE FROM secrets WHERE name = ? AND scope = ? AND blueprint_id = ?",
                (name, scope.value, blueprint_id)
            )
        else:
            cursor = conn.execute(
                "DELETE FROM secrets WHERE name = ? AND scope = 'global'", (name,)
            )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# ── Injection Helper ──────────────────────────────────────

def get_secrets_for_blueprint(blueprint_id: str, required_secrets: List[dict]) -> dict:
    """
    Resolve all secrets needed by a blueprint.
    Returns: {ENV_VAR_NAME: decrypted_value}
    Used by Container Engine when starting containers.
    """
    env_vars = {}
    for req in required_secrets:
        name = req.get("name", "")
        optional = req.get("optional", False)

        # Try blueprint-scoped first, then global
        value = get_secret_value(name, SecretScope.BLUEPRINT, blueprint_id)
        if value is None:
            value = get_secret_value(name, SecretScope.GLOBAL)

        if value:
            env_vars[name] = value
        elif not optional:
            raise ValueError(f"Required secret '{name}' not found for blueprint '{blueprint_id}'")

    return env_vars


def log_secret_access(secret_name: str, action: str,
                      container_id: str = "", blueprint_id: str = ""):
    """Audit log for secret access."""
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO secret_access_log (secret_name, action, container_id, blueprint_id) VALUES (?, ?, ?, ?)",
            (secret_name, action, container_id, blueprint_id)
        )
        conn.commit()
    finally:
        conn.close()


def get_access_log(limit: int = 50) -> List[dict]:
    """Get secret access audit log."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM secret_access_log ORDER BY accessed_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# Auto-init
init_secrets_db()
