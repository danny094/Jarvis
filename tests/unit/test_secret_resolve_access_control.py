import pytest
import sys
import os
from unittest.mock import AsyncMock
import httpx
from fastapi import FastAPI

# Add admin-api directory to path
api_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../adapters/admin-api"))
if api_path not in sys.path:
    sys.path.append(api_path)

import secrets_routes


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(secrets_routes.router, prefix="/api/secrets")
    return app

@pytest.fixture(autouse=True)
def setup_teardown():
    # Clear rate limits before each test
    secrets_routes._rate_limits.clear()
    if hasattr(secrets_routes, "_audit_events"):
        secrets_routes._audit_events.clear()
    yield

async def _get(app, path: str, headers=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path, headers=headers or {})


@pytest.mark.asyncio
async def test_resolve_requires_auth(monkeypatch, app):
    monkeypatch.setattr(secrets_routes, "get_internal_token", lambda: "test_token")
    
    # No auth header
    response = await _get(app, "/api/secrets/resolve/MY_SECRET")
    assert response.status_code == 401
    
    # Invalid auth header
    response = await _get(
        app,
        "/api/secrets/resolve/MY_SECRET",
        headers={"Authorization": "Bearer wrong_token"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_resolve_rate_limit(monkeypatch, app):
    monkeypatch.setattr(secrets_routes, "get_internal_token", lambda: "test_token")
    monkeypatch.setattr(secrets_routes, "get_rate_limit", lambda: 2)
    
    # Mock the internal MCP call
    monkeypatch.setattr(
        secrets_routes,
        "_mcp_call",
        AsyncMock(return_value={"value": "secret123"}),
    )
    
    # Call 1 - ok
    res1 = await _get(
        app,
        "/api/secrets/resolve/MY_SECRET",
        headers={"Authorization": "Bearer test_token"},
    )
    assert res1.status_code == 200
    
    # Call 2 - ok
    res2 = await _get(
        app,
        "/api/secrets/resolve/MY_SECRET",
        headers={"Authorization": "Bearer test_token"},
    )
    assert res2.status_code == 200
    
    # Call 3 - rate limited
    res3 = await _get(
        app,
        "/api/secrets/resolve/MY_SECRET",
        headers={"Authorization": "Bearer test_token"},
    )
    assert res3.status_code == 429


@pytest.mark.asyncio
async def test_resolve_not_found(monkeypatch, app):
    monkeypatch.setattr(secrets_routes, "get_internal_token", lambda: "test_token")
    monkeypatch.setattr(secrets_routes, "get_rate_limit", lambda: 100)
    
    # Missing secret
    monkeypatch.setattr(
        secrets_routes,
        "_mcp_call",
        AsyncMock(return_value={}),
    )
    
    res = await _get(
        app,
        "/api/secrets/resolve/MISSING_SECRET",
        headers={"Authorization": "Bearer test_token"},
    )
    assert res.status_code == 404
    # Ensure error message is generic, no leaks
    assert "Secret not found" in res.json()["detail"]
