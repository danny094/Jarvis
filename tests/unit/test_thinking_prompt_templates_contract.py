from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LAYER_PROMPTS = ROOT / "intelligence_modules" / "prompts" / "layers"


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_thinking_layer_prompt_template_exists_and_is_active():
    for name in [
        "thinking.md",
        "thinking_memory_context.md",
        "thinking_available_tools.md",
        "thinking_tone_signal.md",
        "thinking_user_request.md",
    ]:
        assert (LAYER_PROMPTS / name).is_file()

    src = (LAYER_PROMPTS / "thinking.md").read_text(encoding="utf-8")
    assert "status: active" in src
    assert "Du bist der THINKING-Layer" in src
    assert "Runtime-Härtung" in src
    assert "skill_catalog_context" in src
    assert "new_fact_value NUR setzen" in src

    assert "VERFÜGBARER MEMORY-KONTEXT" in (LAYER_PROMPTS / "thinking_memory_context.md").read_text(encoding="utf-8")
    assert "VERFÜGBARE TOOLS" in (LAYER_PROMPTS / "thinking_available_tools.md").read_text(encoding="utf-8")
    assert "TONALITÄTS-SIGNAL" in (LAYER_PROMPTS / "thinking_tone_signal.md").read_text(encoding="utf-8")
    assert "USER-ANFRAGE" in (LAYER_PROMPTS / "thinking_user_request.md").read_text(encoding="utf-8")


def test_thinking_prompt_constant_uses_prompt_loader():
    src = _read("core/layers/thinking.py")

    assert "from intelligence_modules.prompt_manager import load_prompt" in src
    assert 'THINKING_PROMPT = load_prompt("layers", "thinking")' in src
    for template_name in [
        "thinking_memory_context",
        "thinking_available_tools",
        "thinking_tone_signal",
        "thinking_user_request",
    ]:
        assert f'"{template_name}"' in src

    forbidden_inline_markers = [
        'THINKING_PROMPT = """',
        "Du bist der THINKING-Layer von TRION.",
        "Analysiere die User-Anfrage und erstelle einen Plan als JSON.",
        "Runtime-Härtung (wichtig):",
        "WICHTIG new_fact_value-Regel:",
        'prompt += f"VERFÜGBARER MEMORY-KONTEXT:',
        'prompt += f"VERFÜGBARE TOOLS',
        "TONALITÄTS-SIGNAL (Hybrid-Classifier, deterministisch):",
        "Nutze dieses Signal als Leitplanke",
        'prompt += f"USER-ANFRAGE:',
    ]
    for marker in forbidden_inline_markers:
        assert marker not in src
