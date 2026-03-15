from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_port_manager_module_contract_present():
    src = _read("container_commander/port_manager.py")
    assert "def list_used_ports" in src
    assert "def check_port" in src
    assert "def find_free_port" in src
    assert "def validate_port_bindings" in src
    assert "def list_blueprint_ports" in src


def test_engine_uses_port_conflict_precheck_and_port_labels():
    src = _read("container_commander/engine.py")
    assert "validate_port_bindings" in src
    assert "port_conflict_precheck_failed" in src
    assert "\"trion.port_bindings\": json.dumps(port_bindings) if port_bindings else \"\"" in src
    assert "COMMANDER_AUTO_PORT_MIN" in src
    assert "COMMANDER_AUTO_PORT_MAX" in src


def test_sysinfo_exposes_port_inspector_tools():
    src = _read("sysinfo/mcp_tools.py")
    assert "\"name\": \"list_used_ports\"" in src
    assert "\"name\": \"find_free_port\"" in src
    assert "\"name\": \"check_port\"" in src
    assert "\"name\": \"list_blueprint_ports\"" in src
    assert "elif tool_name == \"list_used_ports\":" in src
    assert "elif tool_name == \"check_port\":" in src
    assert "elif tool_name == \"find_free_port\":" in src
    assert "elif tool_name == \"list_blueprint_ports\":" in src


def test_validate_port_bindings_reports_conflicts(monkeypatch):
    import container_commander.port_manager as pm

    def _fake_check(port: int, protocol: str = "tcp"):
        if int(port) == 47984:
            return False, "Address already in use"
        return True, "free"

    monkeypatch.setattr(pm, "check_port", _fake_check)
    conflicts = pm.validate_port_bindings(
        {
            "47984/tcp": "47984",
            "47989/tcp": "47989",
        }
    )
    assert len(conflicts) == 1
    assert conflicts[0]["host_port"] == 47984
    assert conflicts[0]["protocol"] == "tcp"
