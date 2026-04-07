from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_simple_wizard_uses_structured_runtime_hardware_intents():
    src = _read("adapters/Jarvis/js/apps/terminal/blueprint-simple.js")
    assert "const hwKinds = ['input', 'device', 'usb', 'block_device_ref', 'mount_ref'];" in src
    assert "hardware_intents: hardwareIntents.length ? hardwareIntents : undefined," in src
    assert "requested_by: 'simple-wizard'" in src
    assert "policy: buildHardwareIntentPolicy(resource)," in src
    assert "policyState === 'managed_rw' ? 'rw' : 'ro'" in src
    assert "return { mode: sourceMode, container_path: containerPath };" in src
    assert "return `/storage/${token}`;" in src
    assert "Standard-Ziel:" in src
    assert "dockerfile: form.dockerfile || undefined," in src
    assert 'label for="swz-dockerfile"' in src
    assert "Dockerfile oder Image muss gesetzt sein" in src
    assert "devices: devices.length ? devices : undefined," not in src
    assert 'from "./runtime-hardware-ui.js"' in src
    assert "loadRuntimeHardwareResources(deps.getApiBase)" in src
    assert "const primary = displayPrimaryName(r);" in src
    assert "const selectableIds = simpleSelectableResourceIds(r);" in src
    assert "const badges = displayBadges(r);" in src
    assert "const resource = findHardwareResource(id);" in src
    assert 'class="swz-summary-meta"' in src


def test_blueprint_editor_keeps_hardware_preview_read_only_and_raw_runtime_separate():
    src = _read("adapters/Jarvis/js/apps/terminal/blueprint-editor.js")
    assert "<summary>Raw Runtime</summary>" in src
    assert "<label for=\"bp-ed-devices\">Raw Device Overrides</label>" in src
    assert "Read-only Preview. Die Auswahl erfolgt spaeter im Deploy-Dialog." in src
    assert 'class="bp-hw-chk"' not in src
