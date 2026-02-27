from core.tool_intelligence.error_detector import detect_tool_error, classify_error
from core.tools.tool_result import ToolResult


def test_detect_tool_error_dict_error_without_success_flag_is_error():
    is_error, error_msg = detect_tool_error({"error": "boom"})
    assert is_error is True
    assert error_msg == "boom"


def test_detect_tool_error_dict_error_with_success_true_is_not_error():
    is_error, error_msg = detect_tool_error({"success": True, "error": "boom"})
    assert is_error is False
    assert error_msg is None


def test_detect_tool_error_dict_error_none_is_not_error():
    is_error, error_msg = detect_tool_error({"error": None})
    assert is_error is False
    assert error_msg is None


def test_detect_tool_error_toolresult_failure_is_error():
    result = ToolResult.from_error(error="fail-fast", tool_name="demo-tool")
    is_error, error_msg = detect_tool_error(result)
    assert is_error is True
    assert "fail-fast" in str(error_msg)


def test_classify_error_marks_validation_as_retryable():
    classification = classify_error("Missing required parameter: name", "create_skill")
    assert classification["retryable"] is True
    assert classification["error_type"] == "validation"
    assert classification["category"] == "input"
    assert classification["confidence"] >= 0.9


def test_classify_error_marks_permission_as_non_retryable():
    classification = classify_error("Permission denied: cannot write file", "workspace_save")
    assert classification["retryable"] is False
    assert classification["error_type"] == "permission_denied"
    assert classification["category"] == "auth"


def test_classify_error_marks_timeout_as_retryable():
    classification = classify_error("Gateway timeout while calling service", "memory_save")
    assert classification["retryable"] is True
    assert classification["error_type"] == "transient"
    assert classification["category"] == "infrastructure"


def test_classify_error_unknown_defaults_to_non_retryable():
    classification = classify_error("Unexpected internal state marker abc123", "unknown_tool")
    assert classification["retryable"] is False
    assert classification["error_type"] == "unknown"
