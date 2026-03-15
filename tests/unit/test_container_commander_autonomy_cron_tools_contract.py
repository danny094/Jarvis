from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_commander_tool_definitions_include_autonomy_cron_tools():
    src = _read("container_commander/mcp_tools.py")
    expected = [
        '"name": "autonomy_cron_status"',
        '"name": "autonomy_cron_list_jobs"',
        '"name": "autonomy_cron_validate"',
        '"name": "autonomy_cron_create_job"',
        '"name": "autonomy_cron_update_job"',
        '"name": "autonomy_cron_pause_job"',
        '"name": "autonomy_cron_resume_job"',
        '"name": "autonomy_cron_run_now"',
        '"name": "autonomy_cron_delete_job"',
        '"name": "autonomy_cron_queue"',
        '"name": "cron_reference_links_list"',
    ]
    for marker in expected:
        assert marker in src


def test_commander_tool_dispatch_routes_autonomy_cron_tools():
    src = _read("container_commander/mcp_tools.py")
    expected = [
        'elif tool_name == "autonomy_cron_status":',
        'elif tool_name == "autonomy_cron_list_jobs":',
        'elif tool_name == "autonomy_cron_validate":',
        'elif tool_name == "autonomy_cron_create_job":',
        'elif tool_name == "autonomy_cron_update_job":',
        'elif tool_name == "autonomy_cron_pause_job":',
        'elif tool_name == "autonomy_cron_resume_job":',
        'elif tool_name == "autonomy_cron_run_now":',
        'elif tool_name == "autonomy_cron_delete_job":',
        'elif tool_name == "autonomy_cron_queue":',
        'elif tool_name == "cron_reference_links_list":',
    ]
    for marker in expected:
        assert marker in src


def test_cron_runtime_registry_present_and_used():
    runtime_src = _read("core/autonomy/cron_runtime.py")
    assert "def set_scheduler" in runtime_src
    assert "def get_scheduler" in runtime_src
    assert "def clear_scheduler" in runtime_src

    api_src = _read("adapters/admin-api/main.py")
    assert "set_autonomy_cron_runtime_scheduler" in api_src
    assert "clear_autonomy_cron_runtime_scheduler" in api_src


def test_commander_cron_tools_expose_user_approval_and_error_codes():
    src = _read("container_commander/mcp_tools.py")
    assert '"user_approved": {"type": "boolean"' in src
    assert '"schedule_mode": {"type": "string"' in src
    assert '"run_at": {"type": "string"' in src
    assert '"error_code": error_code' in src
    assert '"default": "webui-default"' not in src


def test_commander_exposes_reference_links_read_only_tool():
    src = _read("container_commander/mcp_tools.py")
    assert "def _tool_cron_reference_links_list" in src
    assert '"mode": "read_only_for_trion"' in src
    assert '"TRION_REFERENCE_LINK_COLLECTIONS"' in src


def test_cron_create_auto_attaches_reference_links_for_trion():
    src = _read("container_commander/mcp_tools.py")
    assert '_reference_links_rows_for_category("cronjobs"' in src
    assert '"reference_source"] = "settings:cronjobs:auto"' in src
    assert '"reference_links_used"' in src
