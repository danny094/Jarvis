from core.control_policy_utils import (
    has_hard_safety_markers,
    is_light_cim_hard_denial,
    is_runtime_operation_tool,
    looks_like_spurious_policy_block,
    sanitize_warning_messages,
    verification_text,
)


def test_verification_text_flattens_core_fields():
    text = verification_text(
        {
            "reason": "Policy issue",
            "block_reason_code": "pii",
            "final_instruction": "Stop",
            "warnings": ["needs memory but no keys specified"],
        }
    )
    assert "policy issue" in text
    assert "pii" in text
    assert "needs memory but no keys specified" in text


def test_spurious_policy_block_marker_detection():
    assert looks_like_spurious_policy_block({"reason": "Safety policy violation"})
    assert not looks_like_spurious_policy_block({"reason": "Everything is fine"})


def test_hard_safety_marker_detection():
    assert has_hard_safety_markers({"warnings": ["PII email address detected"]})
    assert not has_hard_safety_markers({"warnings": ["minor mismatch"]})


def test_runtime_operation_tool_detection():
    assert is_runtime_operation_tool("exec_in_container")
    assert is_runtime_operation_tool("autonomy_cron_run_now")
    assert not is_runtime_operation_tool("plain_math")


def test_sanitize_warning_messages_removes_template_noise_and_dedups():
    cleaned = sanitize_warning_messages(
        ["{today} placeholder", "Wissensstand 2023", "Real warning", "real warning"]
    )
    assert cleaned == ["Real warning"]


def test_light_cim_hard_denial_detects_explicit_unsafe_flag_and_markers():
    assert is_light_cim_hard_denial({"checks": {"safety": {"safe": False}}})
    assert is_light_cim_hard_denial({"warnings": ["Dangerous keyword detected"]})
    assert not is_light_cim_hard_denial({"checks": {"safety": {"safe": True}}, "warnings": []})
