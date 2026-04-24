from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LAYER_PROMPTS = ROOT / "intelligence_modules" / "prompts" / "layers"


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_control_layer_prompt_template_exists_and_is_active():
    assert (LAYER_PROMPTS / "control.md").is_file()
    assert (LAYER_PROMPTS / "control_sequential.md").is_file()

    src = (LAYER_PROMPTS / "control.md").read_text(encoding="utf-8")
    assert "status: active" in src
    assert "Du bist der CONTROL-Layer" in src
    assert "ENTSCHEIDUNGSREGELN" in src
    assert "blueprint_gate_blocked" in src
    assert "ROUTING-SIGNAL" in src

    sequential_src = (LAYER_PROMPTS / "control_sequential.md").read_text(encoding="utf-8")
    assert "status: active" in sequential_src
    assert "You are a rigorous step-by-step reasoner." in sequential_src
    assert 'Start each step with "## Step N:"' in sequential_src


def test_control_prompt_constant_uses_prompt_loader():
    src = _read("core/layers/control/prompting/constants.py")

    assert "from intelligence_modules.prompt_manager import load_prompt" in src
    assert 'CONTROL_PROMPT = load_prompt("layers", "control")' in src
    assert 'SEQUENTIAL_SYSTEM_PROMPT = load_prompt("layers", "control_sequential")' in src

    forbidden_inline_markers = [
        'CONTROL_PROMPT = """',
        'SEQUENTIAL_SYSTEM_PROMPT = """',
        "Du bist der CONTROL-Layer eines AI-Systems.",
        "Deine Aufgabe: Überprüfe den Plan vom Thinking-Layer",
        "ENTSCHEIDUNGSREGELN:",
        "BLUEPRINT-GATE-REGEL",
        "You are a rigorous step-by-step reasoner.",
        'Start each step with "## Step N:"',
    ]
    for marker in forbidden_inline_markers:
        assert marker not in src
