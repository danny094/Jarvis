from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.layers.control import ControlLayer


def test_resolve_model_uses_deep_model_for_deep_mode():
    layer = ControlLayer()
    with patch("core.layers.control.get_control_model", return_value="control-interactive"), \
         patch("core.layers.control.get_control_model_deep", return_value="control-deep"):
        assert layer._resolve_model("interactive") == "control-interactive"
        assert layer._resolve_model("deep") == "control-deep"


def test_resolve_model_override_wins_for_all_modes():
    layer = ControlLayer(model="forced-control-model")
    with patch("core.layers.control.get_control_model", return_value="control-interactive"), \
         patch("core.layers.control.get_control_model_deep", return_value="control-deep"):
        assert layer._resolve_model("interactive") == "forced-control-model"
        assert layer._resolve_model("deep") == "forced-control-model"


def test_resolve_verify_timeout_is_mode_aware_and_clamped():
    layer = ControlLayer()
    with patch("core.layers.control.get_control_timeout_interactive_s", return_value=3), \
         patch("core.layers.control.get_control_timeout_deep_s", return_value=900):
        assert layer._resolve_verify_timeout_s("interactive") == 5.0
        assert layer._resolve_verify_timeout_s("deep") == 600.0


def test_resolve_control_endpoint_override_uses_resolver():
    layer = ControlLayer()
    with patch("core.layers.control.get_control_endpoint_override", return_value="http://control-override:11434/"), \
         patch("core.layers.control.resolve_ollama_base_endpoint", return_value="http://resolved-control:11434"):
        endpoint = layer._resolve_control_endpoint_override("deep")
    assert endpoint == "http://resolved-control:11434"


@pytest.mark.asyncio
async def test_verify_uses_deep_runtime_budget_and_model():
    layer = ControlLayer()
    complete_prompt_mock = AsyncMock(
        return_value="{\"approved\": true, \"corrections\": {}, \"warnings\": [], \"final_instruction\": \"ok\"}"
    )
    with patch.object(layer, "_resolve_verify_timeout_s", return_value=77.0), \
         patch.object(layer, "_resolve_model", return_value="control-deep-model"), \
         patch.object(layer, "_resolve_control_endpoint_override", return_value=""), \
         patch("core.layers.control.resolve_role_endpoint", return_value={
             "requested_target": "control",
             "effective_target": "control",
             "fallback_reason": "",
             "endpoint_source": "routing",
             "hard_error": False,
             "error_code": None,
             "endpoint": "http://fake-ollama:11434",
         }), \
         patch("core.layers.control.complete_prompt", complete_prompt_mock), \
         patch("core.layers.control.safe_parse_json", return_value={
             "approved": True,
             "corrections": {},
             "warnings": [],
             "final_instruction": "ok",
         }):
        out = await layer.verify(
            user_text="deep request",
            thinking_plan={"intent": "analysis", "suggested_tools": []},
            retrieved_memory="",
            response_mode="deep",
        )

    assert out["approved"] is True
    complete_prompt_mock.assert_awaited_once()
    kwargs = complete_prompt_mock.await_args.kwargs
    assert kwargs["timeout_s"] == 77.0
    assert kwargs["model"] == "control-deep-model"


@pytest.mark.asyncio
async def test_verify_fetches_available_skills_via_async_hub_call():
    layer = ControlLayer()
    hub = MagicMock()
    hub.call_tool_async = AsyncMock(return_value={
        "installed": [{"name": "system_hardware_info"}],
    })
    hub.call_tool = MagicMock(side_effect=AssertionError("sync call must not be used in verify"))
    layer.set_mcp_hub(hub)

    action = type("Action", (), {"value": "list_skills"})
    decision = type(
        "Decision",
        (),
        {
            "matched": True,
            "requires_confirmation": False,
            "skill_name": "system_hardware_info",
            "action": action,
            "policy_match": None,
        },
    )()

    with patch("core.layers.control.CIM_POLICY_AVAILABLE", True), \
         patch("core.layers.control.process_cim_policy", return_value=decision):
        out = await layer.verify(
            user_text="Bitte erstelle einen Skill für Systeminfos",
            thinking_plan={"intent": "skill_create", "suggested_tools": ["create_skill"]},
            retrieved_memory="",
            response_mode="interactive",
        )

    assert out["approved"] is True
    assert out["suggested_tools"] == ["list_skills"]
    hub.call_tool_async.assert_awaited_once_with("list_skills", {})
    hub.call_tool.assert_not_called()


def test_apply_corrections_sanitizes_prompt_artifact_warnings():
    layer = ControlLayer()
    out = layer.apply_corrections(
        thinking_plan={"intent": "request"},
        verification={
            "corrections": {},
            "warnings": [
                "Prüfe explizit, ob die Skills-Liste aktuell ist (Stand: {today}).",
                "Die aktuelle Systemzeit ist nicht im Wissensstand (Stand: 2023-10-01) enthalten.",
                "Tool timeout bei list_skills erkannt.",
            ],
            "final_instruction": "ok",
        },
    )

    warnings = out.get("_warnings", [])
    assert "Tool timeout bei list_skills erkannt." in warnings
    assert not any("{today}" in w for w in warnings)
    assert not any("2023-10-01" in w for w in warnings)
