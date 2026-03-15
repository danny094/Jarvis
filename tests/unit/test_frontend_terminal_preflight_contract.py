from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_terminal_blueprint_cards_include_quick_actions():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    assert "termCloneBp('${bp.id}')" in src
    assert "termDeployBpWithOverrides('${bp.id}')" in src
    assert "termDeployBp('${bp.id}')" in src


def test_terminal_deploy_flow_uses_preflight_modal_and_checks():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    assert 'id="bp-preflight"' in src
    assert "async function openDeployPreflight(blueprintId, options = {})" in src
    assert "apiRequest(`/blueprints/${encodeURIComponent(blueprintId)}`" in src
    assert "apiRequest('/quota', {}, 'Could not load quota')" in src
    assert "apiRequest('/secrets', {}, 'Could not load secrets')" in src
    assert "function evaluateDeployPreflight(blueprint, quota, secrets, resources)" in src
    assert "Required secret missing:" in src
    assert "Container quota exhausted" in src


def test_terminal_deploy_can_send_overrides_and_environment():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    assert "payload.override_resources = state.form.resources;" in src
    assert "payload.environment = env;" in src
    assert "payload.resume_volume = state.form.resume_volume;" in src
