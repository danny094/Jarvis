"""
Secrets Management Routes
Stores encrypted API keys. Values never leave the server in plaintext.
"""
import os
import json
import httpx
from fastapi import APIRouter, HTTPException, Request, Header
from pydantic import BaseModel
import time
from collections import defaultdict, deque
from fastapi.responses import JSONResponse

router = APIRouter()

MEMORY_URL = os.getenv("MEMORY_URL", "http://mcp-sql-memory:8081")

# C8 Secret Policy: Static internal token and rate-limiting
def get_internal_token() -> str:
    try:
        from config import get_secret_resolve_token
        token = get_secret_resolve_token()
    except Exception:
        token = os.getenv("INTERNAL_SECRET_RESOLVE_TOKEN", "")
    return str(token or "")

def get_rate_limit() -> int:
    try:
        from config import get_secret_rate_limit
        val = int(get_secret_rate_limit())
    except Exception:
        try:
            val = int(os.getenv("SECRET_RATE_LIMIT", "100"))
        except Exception:
            val = 100
    return max(1, min(10_000, val))

# Rate limiting state: {"<client>|<token-prefix>": deque([timestamps])}
_rate_limits = defaultdict(deque)
_audit_events = deque(maxlen=500)

def _rate_limit_key(request: Request, token: str) -> str:
    client_ip = request.client.host if request.client else "unknown"
    return f"{client_ip}|{token[:16]}"

def check_rate_limit(request: Request, token: str) -> bool:
    """Returns True if request is allowed, False if limited."""
    now = time.monotonic()
    limit = get_rate_limit()

    key = _rate_limit_key(request, token)
    bucket = _rate_limits[key]
    while bucket and (now - bucket[0] >= 60):
        bucket.popleft()

    if len(bucket) >= limit:
        return False

    bucket.append(now)
    return True

def _audit_log(
    action: str,
    name: str,
    success: bool,
    reason: str = "",
    request: Request | None = None,
) -> None:
    """Safe audit logging without leaking secret values."""
    status = "SUCCESS" if success else "DENIED"
    safe_name = str(name).upper().strip()[:128]
    safe_reason = str(reason)[:120]
    client_ip = request.client.host if request and request.client else "unknown"
    _audit_events.append({
        "action": action,
        "target": safe_name,
        "status": status,
        "reason": safe_reason,
        "client": client_ip,
        "ts": int(time.time()),
    })



class SecretCreate(BaseModel):
    name: str
    value: str

class SecretUpdate(BaseModel):
    value: str


async def _mcp_call(tool: str, args: dict):
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": args}
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{MEMORY_URL}/mcp",
            json=payload,
            headers={"Accept": "application/json, text/event-stream"}
        )
    for line in resp.text.splitlines():
        if line.startswith("data:"):
            data = json.loads(line[5:].strip())
            content = data.get("result", {}).get("content", [{}])
            text = content[0].get("text", "{}") if content else "{}"
            return json.loads(text)
    return {}


@router.get("")
async def list_secrets():
    """List all secret names — values are never returned."""
    result = await _mcp_call("secret_list", {})
    return result


@router.post("")
async def create_secret(body: SecretCreate):
    """Store a new encrypted secret."""
    result = await _mcp_call("secret_save", {
        "name": body.name.upper().strip(),
        "value": body.value
    })
    return result


@router.put("/{name}")
async def update_secret(name: str, body: SecretUpdate):
    """Update an existing secret."""
    result = await _mcp_call("secret_save", {
        "name": name.upper().strip(),
        "value": body.value
    })
    return result


@router.delete("/{name}")
async def delete_secret(name: str):
    """Delete a secret."""
    result = await _mcp_call("secret_delete", {"name": name.upper().strip()})
    return result


@router.get("/resolve/{name}")
async def resolve_secret(name: str, request: Request, authorization: str | None = Header(default=None)):
    """
    Internal: resolve a secret value for skill sandbox use.
    Only reachable within Docker network — not exposed via nginx.
    """
    # 1. Token Auth
    internal_token = get_internal_token()
    if not internal_token:
        _audit_log("resolve", name, False, "unconfigured_token", request=request)
        raise HTTPException(status_code=500, detail="Secret resolution unconfigured")

    if not authorization or not authorization.startswith("Bearer "):
        _audit_log("resolve", name, False, "invalid_authorization", request=request)
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    token = authorization.split(" ")[1]
    if token != internal_token:
        _audit_log("resolve", name, False, "invalid_token", request=request)
        raise HTTPException(status_code=403, detail="Forbidden")

    # 2. Rate Limiting
    if not check_rate_limit(request, token):
        _audit_log("resolve", name, False, "rate_limited", request=request)
        raise HTTPException(status_code=429, detail="Too Many Requests")

    name_clean = name.upper().strip()

    try:
        result = await _mcp_call("secret_get", {"name": name_clean})
        if not result or not result.get("value"):
            _audit_log("resolve", name_clean, False, "not_found", request=request)
            raise HTTPException(status_code=404, detail="Secret not found")
            
        _audit_log("resolve", name_clean, True, request=request)
        return JSONResponse(
            {"value": result["value"]},
            headers={"Cache-Control": "no-store"},
        )
    except HTTPException:
        raise
    except Exception:
        _audit_log("resolve", name_clean, False, "internal_error", request=request)
        # Fail safe and avoid leaking any internal value in traceback
        raise HTTPException(status_code=500, detail="Internal server error")
