from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROMPTS = ROOT / "intelligence_modules" / "prompts" / "contracts"


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_output_prompt_contract_templates_exist():
    expected = [
        "output.md",
        "output_grounding.md",
        "output_analysis_guard.md",
        "output_anti_hallucination.md",
        "output_chat_history.md",
        "output_budget_interactive.md",
        "output_budget_deep.md",
        "output_sequential_summary.md",
        "output_style.md",
        "output_dialogue_header.md",
        "output_dialogue_metadata.md",
        "output_tone_mirror_user.md",
        "output_tone_warm.md",
        "output_tone_formal.md",
        "output_tone_neutral.md",
        "output_dialogue_ack_feedback.md",
        "output_dialogue_smalltalk_experience_guard.md",
        "output_dialogue_smalltalk_day_guard.md",
        "output_length_short.md",
        "output_length_long.md",
        "output_legacy_history_header.md",
        "output_legacy_user_block.md",
        "output_legacy_answer_header.md",
        "grounding_fallback_evidence_summary.md",
        "grounding_fallback_verified_only.md",
        "grounding_fallback_missing_evidence.md",
        "tool_failure_fallback_missing_detail.md",
        "tool_failure_fallback_with_issues.md",
        "output_error_compute_unavailable.md",
        "output_error_sync_compute_unavailable.md",
        "output_error_timeout.md",
        "output_error_server.md",
        "output_error_disconnected.md",
        "output_error_connect.md",
        "output_error_generic.md",
        "output_error_sync_generic.md",
        "output_sync_cloud_provider.md",
        "output_truncation_interactive.md",
        "output_truncation_deep.md",
        "output_grounding_correction_marker.md",
        "container_inventory.md",
        "container_blueprint_catalog.md",
        "container_state_binding.md",
        "skill_catalog.md",
    ]

    for name in expected:
        assert (PROMPTS / name).is_file(), name


def test_output_prompt_contract_index_documents_templates():
    src = (PROMPTS / "output.md").read_text(encoding="utf-8")

    required_markers = [
        "Output Prompt Contracts",
        "output_grounding.md",
        "output_analysis_guard.md",
        "output_anti_hallucination.md",
        "output_chat_history.md",
        "output_budget_interactive.md",
        "output_budget_deep.md",
        "output_dialogue_*.md",
        "output_tone_*.md",
        "output_length_*.md",
        "output_legacy_*.md",
        "grounding_fallback_*.md",
        "tool_failure_fallback_*.md",
        "output_error_*.md",
        "output_sync_cloud_provider.md",
        "output_truncation_*.md",
        "output_grounding_correction_marker.md",
        "container_inventory.md",
        "container_blueprint_catalog.md",
        "container_state_binding.md",
        "skill_catalog.md",
        "Prompt files define wording only.",
    ]
    for marker in required_markers:
        assert marker in src


def test_output_system_prompt_uses_prompt_loader_for_static_blocks():
    src = _read("core/layers/output/prompt/system_prompt.py")

    assert "from intelligence_modules.prompt_manager import load_prompt" in src
    for template_name in [
        "output_grounding",
        "output_analysis_guard",
        "output_anti_hallucination",
        "output_chat_history",
        "output_budget_interactive",
        "output_budget_deep",
        "output_sequential_summary",
        "output_style",
        "output_dialogue_header",
        "output_dialogue_metadata",
        "output_tone_mirror_user",
        "output_tone_warm",
        "output_tone_formal",
        "output_tone_neutral",
        "output_dialogue_ack_feedback",
        "output_dialogue_smalltalk_experience_guard",
        "output_dialogue_smalltalk_day_guard",
        "output_length_short",
        "output_length_long",
        "output_legacy_history_header",
        "output_legacy_user_block",
        "output_legacy_answer_header",
    ]:
        assert f'"{template_name}"' in src

    forbidden_inline_markers = [
        'prompt_parts.append("\\n### OUTPUT-GROUNDING:")',
        'prompt_parts.append("\\n### ANALYSE-GUARD:")',
        'prompt_parts.append("\\n### ANTI-HALLUZINATION:")',
        'prompt_parts.append("\\n### CHAT-HISTORY:")',
        'prompt_parts.append("\\n### ANTWORT-BUDGET:")',
        'prompt_parts.append("\\n### DIALOG-FÜHRUNG:")',
        "Priorisiere klare Antworten; bei Bedarf lieber in 2 kurzen Schritten antworten.",
        "Spiegle Ton und Energie des Users, ohne künstlich zu wirken.",
        "Antworte warm, zugewandt und direkt.",
        "Antworte sachlich-formal und präzise.",
        "Antworte neutral, klar und kooperativ.",
        "Bei Bestätigung/Feedback: kurz antworten (1-3 Sätze), keine Bulletpoints.",
        "Bei Smalltalk: keine erfundenen persönlichen Erlebnisse oder Nutzergeschichten behaupten.",
        'Wenn nach deinem \\"Tag\\" gefragt wird, transparent als Assistenzsystem ohne menschlichen Alltag antworten.',
        "Halte die Antwort kurz.",
        "Antwort darf ausführlicher sein, aber strukturiert bleiben.",
        'prompt_parts.append("\\n\\n### BISHERIGE KONVERSATION:")',
        'prompt_parts.append(f"\\n\\n### USER:\\n{user_text}")',
        'prompt_parts.append("\\n\\n### DEINE ANTWORT:")',
    ]
    for marker in forbidden_inline_markers:
        assert marker not in src


def test_output_fallback_and_stream_notices_use_templates():
    src = "\n".join(
        [
            _read("core/layers/output/grounding/fallback.py"),
            _read("core/layers/output/generation/async_stream.py"),
            _read("core/layers/output/generation/sync_stream.py"),
            _read("core/layers/output/layer.py"),
            _read("core/layers/output/prompt/notices.py"),
        ]
    )

    for template_name in [
        "grounding_fallback_evidence_summary",
        "grounding_fallback_verified_only",
        "grounding_fallback_missing_evidence",
        "tool_failure_fallback_missing_detail",
        "tool_failure_fallback_with_issues",
        "output_error_compute_unavailable",
        "output_error_sync_compute_unavailable",
        "output_error_timeout",
        "output_error_server",
        "output_error_disconnected",
        "output_error_connect",
        "output_error_generic",
        "output_error_sync_generic",
        "output_sync_cloud_provider",
        "output_truncation_interactive",
        "output_truncation_deep",
        "output_grounding_correction_marker",
    ]:
        assert f'"{template_name}"' in src

    forbidden_inline_markers = [
        "Bitte Tool-Abfrage erneut ausführen.",
        "Bitte Anfrage mit denselben Parametern erneut ausführen.",
        "Bitte Parameter korrigieren oder den vorgeschlagenen sicheren Fallback bestätigen.",
        "Verbindung zum Model wurde unterbrochen. Bitte Anfrage erneut senden.",
        "Bitte nutze den normalen Streaming-Chatpfad.",
        "Antwort gekürzt: Interaktiv-Budget erreicht.",
        "Grounding-Korrektur",
    ]
    for marker in forbidden_inline_markers:
        assert marker not in src
