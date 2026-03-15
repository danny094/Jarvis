from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_installer_exposes_custom_mcp_config_read_and_write_routes():
    src = _read("mcp/installer.py")
    assert '@router.get("/{name}/config")' in src
    assert '@router.put("/{name}/config")' in src
    assert "Editable config for MCP" in src
    assert "_reload_hub_registry(hub)" in src


def test_installer_retains_toggle_and_details_routes_for_tools_ui():
    src = _read("mcp/installer.py")
    assert '@router.post("/{name}/toggle")' in src
    assert '@router.get("/{name}/details")' in src


def test_installer_toggle_no_longer_depends_on_missing_get_mcps_symbol():
    src = _read("mcp/installer.py")
    assert "from mcp_registry import get_mcps" not in src
    assert "Cannot toggle core MCPs" in src
