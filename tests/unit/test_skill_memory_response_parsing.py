from __future__ import annotations

import importlib.util
import os


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_SKILL_MEMORY_PATH = os.path.join(
    _REPO_ROOT, "mcp-servers", "skill-server", "skill_memory.py"
)


def _load_skill_memory_module():
    spec = importlib.util.spec_from_file_location(
        "skill_memory_response_test_mod",
        _SKILL_MEMORY_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_parse_sse_response_accepts_sse_payload():
    mod = _load_skill_memory_module()
    payload = (
        'event: message\n'
        'data: {"jsonrpc":"2.0","id":1,"result":{"structuredContent":{"ok":true}}}\n\n'
    )
    parsed = mod._parse_sse_response(payload)
    assert isinstance(parsed, dict)
    assert parsed["result"]["structuredContent"]["ok"] is True


def test_parse_sse_response_accepts_plain_json_payload():
    mod = _load_skill_memory_module()
    payload = '{"jsonrpc":"2.0","id":2,"result":{"structuredContent":{"ok":true}}}'
    parsed = mod._parse_sse_response(payload)
    assert isinstance(parsed, dict)
    assert parsed["id"] == 2


def test_parse_sse_response_invalid_returns_none():
    mod = _load_skill_memory_module()
    assert mod._parse_sse_response("not-json") is None
