from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest


def _load_tool_executor_mini_control_core():
    root = Path(__file__).resolve().parents[2]
    tool_executor_dir = root / "tool_executor"
    module_path = tool_executor_dir / "mini_control_core.py"

    if str(tool_executor_dir) not in sys.path:
        sys.path.insert(0, str(tool_executor_dir))

    spec = importlib.util.spec_from_file_location(
        "tool_executor_mini_control_core_install_fallback_test",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


@pytest.mark.asyncio
async def test_install_skill_falls_back_to_local_executor(monkeypatch):
    mod = _load_tool_executor_mini_control_core()
    control = mod.SkillMiniControl(cim=MagicMock(), skills_dir="/tmp")

    attempted_urls = []

    class _FakeResponse:
        status_code = 200
        text = '{"passed": true}'

        def json(self):
            return {"passed": True, "installation": {"success": True}}

    class _FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json):
            attempted_urls.append(url)
            if "tool-executor" in url:
                raise httpx.ConnectError("name or service not known")
            return _FakeResponse()

    monkeypatch.setenv("EXECUTOR_URL", "http://tool-executor:8000")
    monkeypatch.setattr(mod.httpx, "AsyncClient", _FakeAsyncClient)

    result = await control._install_skill(
        "fallback_test_skill",
        "def run(**kwargs):\n    return 42\n",
        "fallback install test",
        control_decision={
            "action": "approve",
            "passed": True,
            "source": "skill_server",
            "validation_score": 1.0,
        },
    )

    assert result.get("passed") is True
    assert any("tool-executor:8000" in u for u in attempted_urls)
    assert any("localhost:8000" in u for u in attempted_urls)


@pytest.mark.asyncio
async def test_install_skill_reports_non_json_executor_response(monkeypatch):
    mod = _load_tool_executor_mini_control_core()
    control = mod.SkillMiniControl(cim=MagicMock(), skills_dir="/tmp")

    class _FakeResponse:
        status_code = 502
        text = "<html>bad gateway</html>"

        def json(self):
            raise ValueError("Expecting value: line 1 column 1 (char 0)")

    class _FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json):
            return _FakeResponse()

    monkeypatch.setenv("EXECUTOR_URL", "http://tool-executor:8000")
    monkeypatch.setattr(mod.httpx, "AsyncClient", _FakeAsyncClient)

    result = await control._install_skill(
        "non_json_test_skill",
        "def run(**kwargs):\n    return 42\n",
        "non json install test",
    )

    assert result.get("success") is False
    assert "failed across all executor endpoints" in str(result.get("error", "")).lower()
    assert "non-json response" in str(result.get("detail", "")).lower()
    assert any("localhost:8000" in u for u in result.get("attempts", []))
