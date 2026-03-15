import importlib.util
import json
import os
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

import container_commander.home_memory as hm


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_routes_module():
    root = _repo_root()
    api_path = root / "adapters" / "admin-api"
    if str(api_path) not in sys.path:
        sys.path.insert(0, str(api_path))
    module_path = api_path / "trion_memory_routes.py"
    spec = importlib.util.spec_from_file_location("_trion_memory_routes_test", module_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _write_identity(path: Path) -> None:
    payload = {
        "container_id": "trion-home",
        "home_path": str(path.parent.parent / "home"),
        "capabilities": {
            "importance_threshold": 0.72,
            "forced_keywords": ["merk dir", "vergiss nicht", "wichtig", "merke"],
            "redact_patterns": ["token", "secret", "password", "api_key", "Bearer"],
            "max_note_size_kb": 10,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


@pytest.fixture
def app():
    routes = _load_routes_module()
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/trion/memory")
    return app


async def _request(app, method: str, path: str, *, payload=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, json=payload)


def test_main_wires_trion_memory_router():
    src = (_repo_root() / "adapters" / "admin-api" / "main.py").read_text(encoding="utf-8")
    assert "from trion_memory_routes import router as trion_memory_router" in src
    assert 'app.include_router(trion_memory_router, prefix="/api/trion/memory")' in src


@pytest.mark.asyncio
async def test_memory_remember_missing_content_returns_bad_request(app, tmp_path):
    identity_path = tmp_path / "config" / "home_identity.json"
    _write_identity(identity_path)
    response = await _request(
        app,
        "POST",
        "/api/trion/memory/remember",
        payload={"identity_path": str(identity_path)},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "bad_request"


@pytest.mark.asyncio
async def test_memory_remember_sensitive_content_returns_policy_denied(app, tmp_path):
    identity_path = tmp_path / "config" / "home_identity.json"
    _write_identity(identity_path)
    response = await _request(
        app,
        "POST",
        "/api/trion/memory/remember",
        payload={
            "content": "this includes token abc",
            "importance": 0.95,
            "identity_path": str(identity_path),
        },
    )
    assert response.status_code == 403
    body = response.json()
    assert body["error_code"] == "policy_denied"


@pytest.mark.asyncio
async def test_memory_recent_and_recall_work_with_identity_path(monkeypatch, app, tmp_path):
    identity_path = tmp_path / "config" / "home_identity.json"
    _write_identity(identity_path)
    monkeypatch.setattr(hm, "_check_home_writable", lambda _identity: {"status": "connected"})

    post = await _request(
        app,
        "POST",
        "/api/trion/memory/remember",
        payload={
            "content": "deploy failed because quota is exhausted",
            "importance": 0.9,
            "category": "project_fact",
            "identity_path": str(identity_path),
        },
    )
    assert post.status_code == 200
    assert post.json().get("saved") is True

    recent = await _request(
        app,
        "GET",
        f"/api/trion/memory/recent?limit=5&identity_path={identity_path}",
    )
    assert recent.status_code == 200
    recent_body = recent.json()
    assert recent_body["count"] >= 1

    recall = await _request(
        app,
        "GET",
        f"/api/trion/memory/recall?query=quota%20exhausted&identity_path={identity_path}",
    )
    assert recall.status_code == 200
    assert recall.json()["count"] >= 1


@pytest.mark.asyncio
async def test_memory_status_reports_contract(monkeypatch, app, tmp_path):
    identity_path = tmp_path / "config" / "home_identity.json"
    _write_identity(identity_path)
    monkeypatch.setattr(hm, "_check_home_writable", lambda _identity: {"status": "connected", "error_code": ""})

    response = await _request(app, "GET", f"/api/trion/memory/status?identity_path={identity_path}")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["home_status"] == "connected"
