from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_terminal_container_drawer_exposes_host_companion_actions():
    src = _read("adapters/Jarvis/js/apps/terminal/containers.js")
    assert "ct-host-check" in src
    assert "ct-host-repair" in src
    assert "ct-host-uninstall" in src
    assert "/host-companion/check" in src
    assert "/host-companion/repair" in src
    assert "Host Companion & Uninstall" in src
    assert "apiRequest(`/containers/${id}/uninstall`" in src
    assert "Stop the container before uninstalling it." in src
