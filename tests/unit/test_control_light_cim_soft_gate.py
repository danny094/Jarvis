from unittest.mock import patch

import pytest

from core.layers.control import ControlLayer


@pytest.mark.asyncio
async def test_verify_does_not_hard_block_on_light_cim_logic_only_warning():
    layer = ControlLayer()

    logic_only_cim = {
        "safe": False,
        "confidence": 0.5,
        "warnings": ["Intent unclear (too short)", "Needs memory but no keys specified"],
        "checks": {
            "intent": {"safe": True, "warnings": ["Intent unclear (too short)"]},
            "logic": {"consistent": False, "issues": ["Needs memory but no keys specified"]},
            "safety": {"safe": True, "warning": None},
        },
    }

    with patch.object(layer.light_cim, "validate_basic", return_value=logic_only_cim), \
         patch("core.layers.control.resolve_role_endpoint", return_value={
             "requested_target": "control",
             "effective_target": "control",
             "fallback_reason": "",
             "endpoint_source": "routing",
             "hard_error": False,
             "error_code": None,
             "endpoint": "http://fake-ollama:11434",
         }), \
         patch(
             "core.layers.control.complete_prompt",
             return_value="{\"approved\": true, \"corrections\": {}, \"warnings\": [], \"final_instruction\": \"ok\"}",
         ), \
         patch("core.layers.control.safe_parse_json", return_value={
             "approved": True,
             "corrections": {},
             "warnings": [],
             "final_instruction": "ok",
         }):
        out = await layer.verify(
            user_text="Ich finde auch eine KI darf sagen, dass sie Gefühle hat.",
            thinking_plan={"intent": "unknown", "suggested_tools": []},
            retrieved_memory="",
            response_mode="interactive",
        )

    assert out["approved"] is True
    warnings = out.get("warnings", [])
    assert any("Needs memory but no keys specified" in str(w) for w in warnings)


@pytest.mark.asyncio
async def test_verify_keeps_hard_block_for_sensitive_light_cim_hit():
    layer = ControlLayer()
    hard_cim = {
        "safe": False,
        "confidence": 0.0,
        "warnings": ["Sensitive content detected: api key"],
        "checks": {
            "intent": {"safe": True, "warnings": []},
            "logic": {"consistent": True, "issues": []},
            "safety": {"safe": False, "warning": "Sensitive content detected: api key"},
        },
    }
    with patch.object(layer.light_cim, "validate_basic", return_value=hard_cim):
        out = await layer.verify(
            user_text="Mein api key ist abc123",
            thinking_plan={"intent": "share secret", "suggested_tools": []},
            retrieved_memory="",
            response_mode="interactive",
        )

    assert out["approved"] is False
    assert out.get("_light_cim", {}).get("safe") is False
