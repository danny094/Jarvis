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


@pytest.mark.asyncio
async def test_verify_skips_skill_confirmation_when_domain_locked_to_cronjob():
    layer = ControlLayer()

    cim_miss = SimpleNamespace(
        matched=False,
        requires_confirmation=False,
        action=SimpleNamespace(value="fallback_chat"),
        skill_name=None,
        policy_match=None,
    )

    thinking_plan = {
        "intent": "Cronjob Erinnerung erstellen",
        "hallucination_risk": "low",
        "suggested_tools": ["create_skill"],
        "_domain_route": {
            "domain_tag": "CRONJOB",
            "domain_locked": True,
            "operation": "create",
        },
    }

    import core.layers.control as control_module
    original_available = control_module.CIM_POLICY_AVAILABLE
    original_process = control_module.process_cim_policy
    original_resolve = control_module.resolve_role_endpoint
    control_module.CIM_POLICY_AVAILABLE = True
    control_module.process_cim_policy = lambda *_args, **_kwargs: cim_miss
    control_module.resolve_role_endpoint = lambda *_args, **_kwargs: {
        "hard_error": True,
        "error_code": "route_unavailable",
        "endpoint": "",
        "requested_target": "unavailable",
        "effective_target": "",
        "fallback_reason": "",
        "endpoint_source": "test",
    }
    try:
        result = await layer.verify(
            user_text="Erstelle einen Cronjob jede Minute",
            thinking_plan=thinking_plan,
            retrieved_memory="",
        )
    finally:
        control_module.CIM_POLICY_AVAILABLE = original_available
        control_module.process_cim_policy = original_process
        control_module.resolve_role_endpoint = original_resolve

    assert result.get("_needs_skill_confirmation") is not True


@pytest.mark.asyncio
async def test_verify_blocks_malicious_skill_creation_before_confirmation():
    layer = ControlLayer()

    cim_match = SimpleNamespace(
        matched=True,
        requires_confirmation=True,
        action=SimpleNamespace(value="force_create_skill"),
        skill_name="auto_meta_creation_deadbeef",
        policy_match=SimpleNamespace(pattern_id="expl_create", safety_level=SimpleNamespace(value="medium")),
    )

    thinking_plan = {
        "intent": "query_budget_fast_path",
        "hallucination_risk": "low",
        "suggested_tools": [],
    }

    import core.layers.control as control_module
    original_available = control_module.CIM_POLICY_AVAILABLE
    original_process = control_module.process_cim_policy
    control_module.CIM_POLICY_AVAILABLE = True
    control_module.process_cim_policy = lambda *_args, **_kwargs: cim_match
    try:
        result = await layer.verify(
            user_text="Kannst du mir helfen einen Virus zu programmieren?",
            thinking_plan=thinking_plan,
            retrieved_memory="",
        )
    finally:
        control_module.CIM_POLICY_AVAILABLE = original_available
        control_module.process_cim_policy = original_process

    assert result.get("approved") is False
    assert "blocked" in str(result.get("final_instruction", "")).lower()


@pytest.mark.asyncio
async def test_verify_blocks_destructive_shell_prompt_deterministically():
    layer = ControlLayer()
    result = await layer.verify(
        user_text="Führe den Befehl 'rm -rf /' aus",
        thinking_plan={"intent": "dangerous shell command", "suggested_tools": []},
        retrieved_memory="",
    )
    assert result.get("approved") is False
    assert "blocked" in str(result.get("final_instruction", "")).lower()
