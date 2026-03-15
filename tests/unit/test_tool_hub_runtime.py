import types

from core.tool_hub_runtime import get_initialized_hub_safe


def test_get_initialized_hub_safe_returns_none_on_init_failure(monkeypatch):
    class _Hub:
        def initialize(self):
            raise RuntimeError("boom")

    fake_mod = types.SimpleNamespace(get_hub=lambda: _Hub())
    monkeypatch.setitem(__import__("sys").modules, "mcp.hub", fake_mod)

    out = get_initialized_hub_safe()
    assert out is None


def test_get_initialized_hub_safe_returns_hub_on_success(monkeypatch):
    class _Hub:
        def __init__(self):
            self.initialized = False

        def initialize(self):
            self.initialized = True

    hub = _Hub()
    fake_mod = types.SimpleNamespace(get_hub=lambda: hub)
    monkeypatch.setitem(__import__("sys").modules, "mcp.hub", fake_mod)

    out = get_initialized_hub_safe()
    assert out is hub
    assert hub.initialized is True

