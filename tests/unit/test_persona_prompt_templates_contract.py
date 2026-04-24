from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PERSONA_PROMPTS = ROOT / "intelligence_modules" / "prompts" / "personas"


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_persona_prompt_templates_exist_and_are_documented():
    expected = [
        "persona_identity.md",
        "persona_user_profile_header.md",
        "persona_profile_field.md",
        "persona_direct_address.md",
        "persona_onboarding_header.md",
        "persona_bullet.md",
        "persona_personality.md",
        "persona_tone.md",
        "persona_verbosity.md",
        "persona_capabilities_header.md",
        "persona_tool_access_header.md",
        "persona_live_tools_header.md",
        "persona_live_tool_line.md",
        "persona_tool_usage_rules.md",
        "persona_container_management.md",
        "persona_trion_home.md",
        "persona_cron_autonomy.md",
        "persona_rules_header.md",
        "persona_numbered_rule.md",
        "persona_privacy_header.md",
    ]

    for name in expected:
        assert (PERSONA_PROMPTS / name).is_file(), name

    readme = (PERSONA_PROMPTS / "README.md").read_text(encoding="utf-8")
    for marker in [
        "persona_identity.md",
        "persona_live_tools_header.md",
        "persona_container_management.md",
        "persona_trion_home.md",
        "persona_cron_autonomy.md",
    ]:
        assert marker in readme


def test_persona_system_prompt_builder_uses_templates():
    src = _read("core/persona.py")

    assert "from intelligence_modules.prompt_manager import load_prompt" in src
    for template_name in [
        "persona_identity",
        "persona_user_profile_header",
        "persona_profile_field",
        "persona_direct_address",
        "persona_onboarding_header",
        "persona_bullet",
        "persona_personality",
        "persona_tone",
        "persona_verbosity",
        "persona_capabilities_header",
        "persona_tool_access_header",
        "persona_live_tools_header",
        "persona_live_tool_line",
        "persona_tool_usage_rules",
        "persona_container_management",
        "persona_trion_home",
        "persona_cron_autonomy",
        "persona_rules_header",
        "persona_numbered_rule",
        "persona_privacy_header",
    ]:
        assert f'"{template_name}"' in src

    forbidden_inline_markers = [
        "Du bist {self.name}, {self.role}.",
        "### USER-PROFIL:",
        "Sprich {name} direkt mit 'du' an.",
        "### ONBOARDING (Neuer User):",
        "Deine Persönlichkeit:",
        "Antwortlänge:",
        "### DEINE FÄHIGKEITEN:",
        "### TOOL-ZUGRIFF:",
        "### VERFÜGBARE TOOLS (live vom System geladen):",
        "WICHTIG: Wenn du ein Tool nutzt",
        "### CONTAINER-MANAGEMENT:",
        "### DEIN ZUHAUSE:",
        "### GEPLANTE AUTONOMIE:",
        "### REGELN:",
        "### SICHERHEIT:",
    ]
    for marker in forbidden_inline_markers:
        assert marker not in src
