from pathlib import Path
import re


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_terminal_has_central_api_request_helper_with_http_guard():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    assert "async function apiRequest(path, options = {}, fallbackMessage = 'Request failed')" in src
    assert "if (!response.ok) {" in src
    assert "payload.error_code" in src
    assert "HTTP ${response.status}" in src


def test_terminal_uses_only_central_fetch_call():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    fetch_calls = re.findall(r"\bfetch\(", src)
    assert len(fetch_calls) == 1, "terminal.js should use only one centralized fetch() call"
    assert "fetch(`${API}${path}`, options)" in src


def test_terminal_core_commander_flows_use_api_request():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    required = [
        "apiRequest('/blueprints', {}, 'Could not load blueprints')",
        "apiRequest('/containers/deploy', {",
        "apiRequest('/containers', {}, 'Could not load containers')",
        "apiRequest('/secrets', {}, 'Could not load secrets')",
        "apiRequest('/approvals', {}, 'Could not load approvals')",
        "apiRequest('/quota', {}, 'Could not load quota')",
        "apiRequest('/audit', {}, 'Could not load audit log')",
        "encodeURIComponent(name)",
        "encodeURIComponent(scope)",
    ]
    for marker in required:
        assert marker in src
