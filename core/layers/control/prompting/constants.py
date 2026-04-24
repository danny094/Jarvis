"""Prompt constants for ControlLayer verification and sequential reasoning."""

from intelligence_modules.prompt_manager import load_prompt

CONTROL_PROMPT = load_prompt("layers", "control")

SEQUENTIAL_SYSTEM_PROMPT = load_prompt("layers", "control_sequential")
