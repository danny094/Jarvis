from core.container_state_utils import (
    merge_container_state_from_tool_result,
    normalize_container_entries,
    select_preferred_container_id,
    tool_requires_container_id,
)


def test_normalize_container_entries_filters_invalid_rows():
    rows = [{"container_id": "abc", "status": "running"}, {"status": "running"}, "bad"]
    assert normalize_container_entries(rows) == [
        {"container_id": "abc", "blueprint_id": "", "status": "running", "name": ""}
    ]


def test_select_preferred_container_id_prefers_running_home():
    rows = [
        {"container_id": "1", "status": "stopped", "blueprint_id": "trion-home"},
        {"container_id": "2", "status": "running", "blueprint_id": "trion-home"},
    ]
    selected = select_preferred_container_id(
        rows,
        expected_home_blueprint_id="trion-home",
        preferred_ids=[],
    )
    assert selected == "2"


def test_merge_container_state_from_request_container_sets_last_active():
    merged = merge_container_state_from_tool_result(
        {"known_containers": [], "last_active_container_id": "", "home_container_id": ""},
        tool_name="request_container",
        tool_args={},
        result={"container_id": "x1", "blueprint_id": "bp"},
        expected_home_blueprint_id="trion-home",
    )
    assert merged["last_active_container_id"] == "x1"
    assert any(r.get("container_id") == "x1" for r in merged["known_containers"])


def test_tool_requires_container_id_uses_allow_list():
    assert tool_requires_container_id("exec_in_container", ["exec_in_container"])
    assert not tool_requires_container_id("container_list", ["exec_in_container"])
