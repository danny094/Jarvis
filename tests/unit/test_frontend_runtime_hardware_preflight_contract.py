from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_preflight_loads_blueprint_hardware_preview_and_renders_opt_in_section():
    src = _read("adapters/Jarvis/js/apps/terminal/preflight.js")
    assert "deps.apiRequest(`/blueprints/${encodeURIComponent(blueprintId)}/hardware`, {}, 'Could not load hardware preview')" in src
    assert "loadRuntimeHardwareResources(deps.getApiBase)" in src
    assert '<div class="bp-preflight-section">' in src
    assert '<h4>Hardware Opt-in</h4>' in src
    assert 'id="pf-hw-list"' in src
    assert 'id="pf-hw-empty"' in src
    assert "renderHardwareOptInRows(state);" in src
    assert "hardwareData," in src
    assert "runtimeHardwareResources," in src
    assert "function buildHardwareOptInItems(state)" in src
    assert "function renderHardwareOptInSummary(state)" in src


def test_preflight_passes_selected_block_apply_handoffs_into_deploy_payload():
    src = _read("adapters/Jarvis/js/apps/terminal/preflight.js")
    assert "function defaultHardwareOptInSelection(state)" in src
    assert ".filter(item => String(item.requestedBy || '').trim() === 'simple-wizard')" in src
    assert "deployPreflightState.form.block_apply_handoff_resource_ids = defaultHardwareOptInSelection(deployPreflightState);" in src
    assert "block_apply_handoff_resource_ids: Array.from(document.querySelectorAll('.pf-hw-chk:checked'))" in src
    assert "payload.block_apply_handoff_resource_ids = state.form.block_apply_handoff_resource_ids;" in src
    assert "const resource = findRuntimeHardwareResource(state, resourceId);" in src
    assert "primaryName: displayPrimaryName(resource)," in src
    assert "secondaryMeta: displaySecondaryMeta(resource)," in src
    assert "data?.hardware_deploy?.block_apply_handoff_resource_ids_requested" in src
    assert "data?.hardware_deploy?.block_apply_handoff_resource_ids_applied" in src
    assert "Applied handoffs:" in src
    assert "Not applied:" in src
