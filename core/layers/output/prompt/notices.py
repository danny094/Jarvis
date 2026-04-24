from __future__ import annotations

from intelligence_modules.prompt_manager import load_prompt


def output_notice(template_name: str, **kwargs: object) -> str:
    return load_prompt("contracts", template_name, **kwargs)


def output_truncation_note(response_mode: str) -> str:
    template = (
        "output_truncation_deep"
        if str(response_mode or "").strip().lower() == "deep"
        else "output_truncation_interactive"
    )
    return "\n\n" + output_notice(template)


def output_grounding_correction_marker() -> str:
    return "\n\n" + output_notice("output_grounding_correction_marker") + "\n"
