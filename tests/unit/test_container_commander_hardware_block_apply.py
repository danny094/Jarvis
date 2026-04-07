from container_commander.hardware_block_apply import build_block_apply_preview


def test_block_apply_preview_keeps_whole_disks_review_only():
    decision = build_block_apply_preview(
        resource_id="container::block_device_ref::/dev/sdc",
        action_metadata={
            "host_path": "/dev/sdc",
            "resource_metadata": {
                "disk_type": "disk",
                "zone": "managed_services",
                "policy_state": "managed_rw",
                "allowed_operations": ["assign_to_container"],
            },
        },
        policy={"mode": "rw"},
        unresolved=False,
        warnings=["whole_disk_review_required:container::block_device_ref::/dev/sdc"],
    )

    preview = decision.previews[0]
    assert preview["eligible"] is False
    assert preview["apply_mode"] == "review_only"
    assert preview["reason"] == "whole_disk_or_unknown_review_only"
    assert preview["target_runtime"] == "container"
    assert preview["target_runtime_path"] == "/dev/sdc"
    assert preview["candidate_runtime_binding"] == {
        "kind": "device_path",
        "source_path": "/dev/sdc",
        "target_path": "/dev/sdc",
        "binding_expression": "/dev/sdc",
    }
    assert preview["apply_strategy"] == "runtime_device_binding"
    assert preview["runtime_parameters"]["container"]["candidate_container_path"] == "/dev/sdc"
    assert preview["runtime_parameters"]["container"]["candidate_device_override"] == "/dev/sdc"
    assert preview["blockers"] == ["whole_disk_or_unknown_review_only"]


def test_block_apply_preview_marks_partitions_as_candidates_only_when_explicitly_allowed():
    decision = build_block_apply_preview(
        resource_id="container::block_device_ref::/dev/sdc1",
        action_metadata={
            "host_path": "/dev/sdc1",
            "resource_metadata": {
                "disk_type": "part",
                "zone": "managed_services",
                "policy_state": "managed_rw",
                "allowed_operations": ["assign_to_container"],
            },
        },
        policy={"mode": "rw"},
        unresolved=False,
        warnings=["storage_review_required:container::block_device_ref::/dev/sdc1"],
    )

    preview = decision.previews[0]
    assert preview["eligible"] is True
    assert preview["apply_mode"] == "stage_device_passthrough_candidate"
    assert preview["reason"] == "candidate_for_explicit_container_apply"
    assert preview["target_runtime"] == "container"
    assert preview["target_runtime_path"] == "/dev/sdc1"
    assert preview["candidate_runtime_binding"]["binding_expression"] == "/dev/sdc1"
    assert preview["blockers"] == []
    assert "future_engine_block_apply_enablement" in preview["requirements"]


def test_block_apply_preview_marks_unresolved_items_as_policy_blocked():
    decision = build_block_apply_preview(
        resource_id="container::block_device_ref::/dev/sda",
        action_metadata={
            "host_path": "/dev/sda",
            "resource_metadata": {
                "disk_type": "disk",
                "zone": "system",
                "policy_state": "blocked",
            },
        },
        policy={},
        unresolved=True,
        warnings=["system_block_device_ref_forbidden:container::block_device_ref::/dev/sda"],
    )

    preview = decision.previews[0]
    assert preview["eligible"] is False
    assert preview["reason"] == "policy_blocked"
    assert preview["warnings"] == ["system_block_device_ref_forbidden:container::block_device_ref::/dev/sda"]
    assert preview["blockers"] == ["policy_blocked"]


def test_block_apply_preview_uses_explicit_container_device_path_for_candidates():
    decision = build_block_apply_preview(
        resource_id="container::block_device_ref::/dev/sdc1",
        action_metadata={
            "host_path": "/dev/sdc1",
            "resource_metadata": {
                "disk_type": "part",
                "zone": "managed_services",
                "policy_state": "managed_rw",
                "allowed_operations": ["assign_to_container"],
            },
        },
        policy={"mode": "ro", "container_path": "/dev/game-disk"},
        unresolved=False,
        warnings=["storage_review_required:container::block_device_ref::/dev/sdc1"],
    )

    preview = decision.previews[0]
    assert preview["eligible"] is True
    assert preview["target_runtime_path"] == "/dev/game-disk"
    assert preview["candidate_runtime_binding"]["binding_expression"] == "/dev/sdc1:/dev/game-disk"
    assert preview["runtime_parameters"]["container"]["candidate_container_path"] == "/dev/game-disk"


def test_block_apply_preview_rejects_invalid_container_device_paths():
    decision = build_block_apply_preview(
        resource_id="container::block_device_ref::/dev/sdc1",
        action_metadata={
            "host_path": "/dev/sdc1",
            "resource_metadata": {
                "disk_type": "part",
                "zone": "managed_services",
                "policy_state": "managed_rw",
                "allowed_operations": ["assign_to_container"],
            },
        },
        policy={"mode": "ro", "container_path": "/mnt/game-disk"},
        unresolved=False,
        warnings=["storage_review_required:container::block_device_ref::/dev/sdc1"],
    )

    preview = decision.previews[0]
    assert preview["eligible"] is False
    assert preview["reason"] == "invalid_container_device_path"
    assert preview["blockers"] == ["invalid_container_device_path"]
