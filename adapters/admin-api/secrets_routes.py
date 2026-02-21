"""
Secrets Management Routes
Stores encrypted API keys. Values never leave the server in plaintext.
"""
import os
import json
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

MEMORY_URL = os.getenv("MEMORY_URL", "http://mcp-sql-memory:8081")


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
async def resolve_secret(name: str):
    """
    Internal: resolve a secret value for skill sandbox use.
    Only reachable within Docker network — not exposed via nginx.
    """
    result = await _mcp_call("secret_get", {"name": name.upper().strip()})
    if not result.get("value"):
        raise HTTPException(status_code=404, detail=f"Secret '{name}' not found")
    return {"value": result["value"]}
