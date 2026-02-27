from types import SimpleNamespace

import pytest

from core.layers.control import ControlLayer


@pytest.mark.asyncio
async def test_verify_fallback_confirmation_when_cim_does_not_match_but_create_skill_is_sensitive():
    layer = ControlLayer()

    cim_miss = SimpleNamespace(
        matched=False,
        requires_confirmation=False,
        action=SimpleNamespace(value="fallback_chat"),
        skill_name=None,
        policy_match=None,
    )

    thinking_plan = {
        "intent": "feature implementation",
        "hallucination_risk": "low",
        "suggested_tools": ["create_skill"],
    }

    # Patch module-level symbols used by ControlLayer.verify
    import core.layers.control as control_module
    original_available = control_module.CIM_POLICY_AVAILABLE
    original_process = control_module.process_cim_policy
    control_module.CIM_POLICY_AVAILABLE = True
    control_module.process_cim_policy = lambda *_args, **_kwargs: cim_miss
    try:
        result = await layer.verify(
            user_text="Baue eine neue Funktion namens quick_probe_helper, die hallo sagt.",
            thinking_plan=thinking_plan,
            retrieved_memory="",
        )
    finally:
        control_module.CIM_POLICY_AVAILABLE = original_available
        control_module.process_cim_policy = original_process

    assert result.get("_needs_skill_confirmation") is True
    assert result.get("_skill_name") == "quick_probe_helper"
    assert result.get("_cim_decision", {}).get("pattern_id") == "fallback_skill_confirmation"
