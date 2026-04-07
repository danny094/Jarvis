from core.host_runtime_policy import (
    build_direct_host_runtime_response,
    build_host_runtime_exec_args,
    build_host_runtime_failure_response,
    enforce_host_runtime_exec_first,
    extract_blueprint_id_from_create_result,
)


def _extract_tool_name(tool):
    if isinstance(tool, dict):
        return str(tool.get("tool") or tool.get("name") or "")
    return str(tool)


def _is_host_lookup(text):
    low = str(text or "").lower()
    return "host" in low and "ip" in low


def test_enforce_host_runtime_exec_first_keeps_only_exec():
    tools = ["list_blueprint_ports", "request_container"]
    result = enforce_host_runtime_exec_first(
        user_text="kannst du die host ip finden?",
        suggested_tools=tools,
        looks_like_host_runtime_lookup_fn=_is_host_lookup,
        extract_tool_name_fn=_extract_tool_name,
    )
    assert result == ["exec_in_container"]


def test_enforce_host_runtime_exec_first_reuses_existing_exec_spec():
    spec = {"tool": "exec_in_container", "args": {"container_id": "abc"}}
    result = enforce_host_runtime_exec_first(
        user_text="host ip?",
        suggested_tools=[spec, "request_container"],
        looks_like_host_runtime_lookup_fn=_is_host_lookup,
        extract_tool_name_fn=_extract_tool_name,
    )
    assert result == [spec]


def test_build_direct_host_runtime_response_from_stdout():
    args = build_host_runtime_exec_args(container_id="PENDING")
    msg = build_direct_host_runtime_response(
        "exec_in_container",
        args,
        {"stdout": "203.0.113.10\n"},
    )
    assert "203.0.113.10" in msg


def test_extract_blueprint_id_from_create_result_nested():
    result = {"success": True, "blueprint": {"id": "host-runtime-auto-123"}}
    assert extract_blueprint_id_from_create_result(result) == "host-runtime-auto-123"


def test_build_host_runtime_failure_response_contains_reason():
    msg = build_host_runtime_failure_response(
        reason="request_container_blocked:no_match",
        attempted_blueprint_create=True,
    )
    assert "request_container_blocked:no_match" in msg
    assert "blueprint_create versucht: ja" in msg
