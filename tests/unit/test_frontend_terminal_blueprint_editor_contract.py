from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_terminal_blueprint_editor_uses_structured_form_layout():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    assert 'id="bp-editor-form"' in src
    assert 'class="bp-editor-form"' in src
    assert 'class="bp-editor-head"' in src
    assert 'class="bp-editor-grid bp-editor-grid-3"' in src
    assert 'class="bp-editor-grid bp-editor-grid-5"' in src


def test_terminal_blueprint_editor_exposes_new_runtime_fields():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    assert 'id="bp-ed-image"' in src
    assert 'id="bp-ed-swap"' in src
    assert 'id="bp-ed-pids"' in src
    assert 'id="bp-ed-mounts"' in src
    assert 'id="bp-ed-env"' in src
    assert 'id="bp-ed-devices"' in src
    assert 'id="bp-ed-secrets"' in src
    assert 'id="bp-ed-allowed-exec"' in src


def test_terminal_blueprint_editor_validates_and_builds_extended_payload():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    assert "function validateBlueprintFormAndBuildPayload()" in src
    assert "if (!dockerfile && !image) {" in src
    assert "const mountParse = parseBlueprintMounts(mountsRaw);" in src
    assert "const secretParse = parseBlueprintSecrets(secretsRaw);" in src
    assert "environment = parseEnvOverrides(environmentRaw);" in src
    assert "devices = parseDeviceOverrides(devicesRaw);" in src
    assert "devices," in src
    assert "environment," in src
    assert "memory_swap: memorySwap || '1g'," in src
    assert "pids_limit: pids || 100," in src


def test_terminal_blueprint_editor_has_error_summary_and_close_controls():
    src = _read("adapters/Jarvis/js/apps/terminal.js")
    assert 'id="bp-editor-errors"' in src
    assert "renderBlueprintEditorErrorSummary(errors);" in src
    assert "id=\"bp-editor-close\"" in src
    assert "if (event.key === 'Escape') {" in src
    assert "cancelBtn?.addEventListener('click', closeBlueprintEditor);" in src
