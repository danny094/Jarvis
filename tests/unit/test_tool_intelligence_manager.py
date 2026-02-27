from core.tool_intelligence.manager import ToolIntelligenceManager


class _StubSearch:
    def __init__(self):
        self.calls = 0

    def search_past_solutions(self, tool_name, error_msg):
        self.calls += 1
        return f"stub:{tool_name}:{error_msg}"


class _StubRetry:
    def __init__(self):
        self.calls = 0

    def attempt_retry(self, tool_name, error_msg, original_args, tool_hub, retry_key=None):
        self.calls += 1
        return {
            "success": True,
            "result": {"ok": True},
            "fix_applied": "stub_fix",
            "attempts": 1,
            "reason": "retry_success",
        }


def test_manager_skips_retry_for_non_retryable_error():
    manager = ToolIntelligenceManager(archive_manager=None)
    manager.auto_search = _StubSearch()
    retry = _StubRetry()
    manager.auto_retry = retry

    result = manager.handle_tool_result(
        tool_name="workspace_save",
        result={"error": "permission denied"},
        tool_args={"entry_content": "x"},
        tool_hub=object(),
    )

    assert result["is_error"] is True
    assert result["error_classification"]["retryable"] is False
    assert result["retry_result"] is None
    assert retry.calls == 0
    assert manager.auto_search.calls == 1


def test_manager_attempts_retry_for_retryable_error():
    manager = ToolIntelligenceManager(archive_manager=None)
    manager.auto_search = _StubSearch()
    retry = _StubRetry()
    manager.auto_retry = retry

    result = manager.handle_tool_result(
        tool_name="create_skill",
        result={"error": "missing required parameter: name"},
        tool_args={"description": "test"},
        tool_hub=object(),
    )

    assert result["is_error"] is True
    assert result["error_classification"]["retryable"] is True
    assert result["retry_result"] is not None
    assert result["retry_result"]["success"] is True
    assert retry.calls == 1
