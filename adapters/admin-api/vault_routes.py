"""
vault_routes.py — TRION Vault Backend
Encrypted password manager with AES-256-GCM (via Fernet).
Master password never stored — used only to derive the encryption key.
"""
import os, json, sqlite3, secrets, hashlib, time
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter()

VAULT_DB_PATH = Path(os.getenv("VAULT_DB_PATH", "/app/data/vault.db"))
VAULT_SALT_PATH = Path(os.getenv("VAULT_DB_PATH", "/app/data/vault.db")).with_suffix(".salt")
SESSION_TTL = 300  # 5 minutes

# In-memory session store: token -> {key_b64, expires}
_sessions: dict = {}

# ── Crypto helpers ─────────────────────────────────────────────────────────────

def _derive_key(password: str, salt: bytes) -> bytes:
    """PBKDF2-HMAC-SHA256, 200k iterations → 32-byte key for Fernet."""
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)

def _get_or_create_salt() -> bytes:
    if VAULT_SALT_PATH.exists():
        return VAULT_SALT_PATH.read_bytes()
    salt = secrets.token_bytes(32)
    VAULT_SALT_PATH.write_bytes(salt)
    return salt

def _fernet(key32: bytes):
    from cryptography.fernet import Fernet
    import base64
    return Fernet(base64.urlsafe_b64encode(key32))

def _encrypt(key32: bytes, plaintext: str) -> str:
    return _fernet(key32).encrypt(plaintext.encode()).decode()

def _decrypt(key32: bytes, token: str) -> str:
    return _fernet(key32).decrypt(token.encode()).decode()

# ── DB helpers ─────────────────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    VAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(VAULT_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vault_entries (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            username    TEXT DEFAULT '',
            password_enc TEXT DEFAULT '',
            url         TEXT DEFAULT '',
            category    TEXT DEFAULT 'internet',
            icon        TEXT DEFAULT '🔑',
            tags        TEXT DEFAULT '[]',
            notes       TEXT DEFAULT '',
            favorite    INTEGER DEFAULT 0,
            expires     TEXT DEFAULT '',
            totp_secret TEXT DEFAULT '',
            created_at  REAL,
            updated_at  REAL
        )
    """)
    conn.commit()
    return conn

# ── Session helpers ────────────────────────────────────────────────────────────

def _new_session(key32: bytes) -> str:
    import base64
    token = secrets.token_urlsafe(32)
    _sessions[token] = {
        "key": key32,
        "expires": time.time() + SESSION_TTL,
    }
    return token

def _get_session_key(token: str) -> bytes:
    _purge_expired()
    sess = _sessions.get(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    if time.time() > sess["expires"]:
        _sessions.pop(token, None)
        raise HTTPException(status_code=401, detail="Session expired")
    sess["expires"] = time.time() + SESSION_TTL  # sliding window
    return sess["key"]

def _purge_expired():
    now = time.time()
    expired = [t for t, s in _sessions.items() if now > s["expires"]]
    for t in expired:
        _sessions.pop(t, None)

def _get_token(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing X-Vault-Token")
    return authorization

# ── Pydantic models ────────────────────────────────────────────────────────────

class UnlockRequest(BaseModel):
    master_password: str

class EntryCreate(BaseModel):
    title: str
    username: str = ""
    password: str = ""
    url: str = ""
    category: str = "internet"
    icon: str = "🔑"
    tags: list = []
    notes: str = ""
    favorite: bool = False
    expires: str = ""
    totp_secret: str = ""

class EntryUpdate(EntryCreate):
    pass

# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/unlock")
async def unlock(body: UnlockRequest):
    """Validate master password and return a session token."""
    try:
        salt = _get_or_create_salt()
        key32 = _derive_key(body.master_password, salt)
        db = _get_db()
        # Verify by attempting to decrypt the first entry (if any)
        row = db.execute("SELECT password_enc FROM vault_entries LIMIT 1").fetchone()
        if row and row["password_enc"]:
            try:
                _decrypt(key32, row["password_enc"])
            except Exception:
                raise HTTPException(status_code=401, detail="Wrong master password")
        token = _new_session(key32)
        return {"session_token": token, "ttl": SESSION_TTL}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/lock")
async def lock(x_vault_token: Optional[str] = Header(default=None)):
    if x_vault_token and x_vault_token in _sessions:
        _sessions.pop(x_vault_token)
    return {"locked": True}

@router.get("/entries")
async def list_entries(x_vault_token: Optional[str] = Header(default=None)):
    """Return all entries (passwords never included)."""
    key32 = _get_session_key(_get_token(x_vault_token))
    db = _get_db()
    rows = db.execute(
        "SELECT id,title,username,url,category,icon,tags,notes,favorite,expires,totp_secret,created_at,updated_at "
        "FROM vault_entries ORDER BY title COLLATE NOCASE"
    ).fetchall()
    entries = []
    for r in rows:
        entries.append({
            "id": r["id"],
            "title": r["title"],
            "username": r["username"],
            "url": r["url"],
            "category": r["category"],
            "icon": r["icon"],
            "tags": json.loads(r["tags"] or "[]"),
            "notes": r["notes"],
            "favorite": bool(r["favorite"]),
            "expires": r["expires"],
            "totp_secret": r["totp_secret"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        })
    return {"entries": entries, "count": len(entries)}

@router.get("/entries/{entry_id}/password")
async def get_password(entry_id: str, x_vault_token: Optional[str] = Header(default=None)):
    """Return decrypted password for a single entry."""
    key32 = _get_session_key(_get_token(x_vault_token))
    db = _get_db()
    row = db.execute("SELECT password_enc FROM vault_entries WHERE id=?", (entry_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Entry not found")
    try:
        plain = _decrypt(key32, row["password_enc"]) if row["password_enc"] else ""
    except Exception:
        raise HTTPException(status_code=500, detail="Decryption failed")
    return JSONResponse({"password": plain}, headers={"Cache-Control": "no-store"})

@router.post("/entries")
async def create_entry(body: EntryCreate, x_vault_token: Optional[str] = Header(default=None)):
    key32 = _get_session_key(_get_token(x_vault_token))
    entry_id = secrets.token_urlsafe(12)
    now = time.time()
    pw_enc = _encrypt(key32, body.password) if body.password else ""
    db = _get_db()
    db.execute("""
        INSERT INTO vault_entries
        (id,title,username,password_enc,url,category,icon,tags,notes,favorite,expires,totp_secret,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (entry_id, body.title, body.username, pw_enc, body.url, body.category,
          body.icon, json.dumps(body.tags), body.notes, int(body.favorite),
          body.expires, body.totp_secret, now, now))
    db.commit()
    return {"id": entry_id, "created": True}

@router.put("/entries/{entry_id}")
async def update_entry(entry_id: str, body: EntryUpdate, x_vault_token: Optional[str] = Header(default=None)):
    key32 = _get_session_key(_get_token(x_vault_token))
    now = time.time()
    pw_enc = _encrypt(key32, body.password) if body.password else ""
    db = _get_db()
    db.execute("""
        UPDATE vault_entries SET
        title=?,username=?,password_enc=?,url=?,category=?,icon=?,
        tags=?,notes=?,favorite=?,expires=?,totp_secret=?,updated_at=?
        WHERE id=?
    """, (body.title, body.username, pw_enc, body.url, body.category, body.icon,
          json.dumps(body.tags), body.notes, int(body.favorite),
          body.expires, body.totp_secret, now, entry_id))
    db.commit()
    return {"id": entry_id, "updated": True}

@router.delete("/entries/{entry_id}")
async def delete_entry(entry_id: str, x_vault_token: Optional[str] = Header(default=None)):
    _get_session_key(_get_token(x_vault_token))
    db = _get_db()
    db.execute("DELETE FROM vault_entries WHERE id=?", (entry_id,))
    db.commit()
    return {"id": entry_id, "deleted": True}

@router.get("/status")
async def vault_status():
    """Check if vault DB exists, whether master password is set, and entry count."""
    db_exists = VAULT_DB_PATH.exists()
    salt_exists = VAULT_SALT_PATH.exists()
    count = 0
    has_master = False
    if db_exists:
        try:
            db = _get_db()
            count = db.execute("SELECT COUNT(*) FROM vault_entries").fetchone()[0]
            # Master is considered set if salt file exists and setup_marker entry exists
            marker = db.execute(
                "SELECT id FROM vault_entries WHERE id='__setup_marker__'"
            ).fetchone()
            has_master = salt_exists and marker is not None
        except Exception:
            pass
    return {
        "initialized": db_exists and has_master,
        "has_master": has_master,
        "entry_count": max(0, count - 1) if has_master else count,  # exclude marker
    }

@router.post("/setup")
async def setup_vault(body: UnlockRequest):
    """First-time setup: set master password and create setup marker."""
    if VAULT_SALT_PATH.exists():
        # Check if already set up
        try:
            db = _get_db()
            marker = db.execute("SELECT id FROM vault_entries WHERE id='__setup_marker__'").fetchone()
            if marker:
                raise HTTPException(status_code=409, detail="Vault already initialized")
        except HTTPException:
            raise
        except Exception:
            pass
    # Create salt + derive key
    salt = secrets.token_bytes(32)
    VAULT_SALT_PATH.parent.mkdir(parents=True, exist_ok=True)
    VAULT_SALT_PATH.write_bytes(salt)
    key32 = _derive_key(body.master_password, salt)
    # Store encrypted marker so unlock can verify the key later
    marker_enc = _encrypt(key32, "__trion_vault_ok__")
    db = _get_db()
    now = time.time()
    db.execute("""
        INSERT OR REPLACE INTO vault_entries
        (id,title,username,password_enc,url,category,icon,tags,notes,favorite,expires,totp_secret,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, ("__setup_marker__", "__setup_marker__", "", marker_enc, "", "system",
          "🔐", "[]", "", 0, "", "", now, now))
    db.commit()
    token = _new_session(key32)
    return {"session_token": token, "ttl": SESSION_TTL, "setup": True}
