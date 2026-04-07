from container_commander.hardware_block_resolution import resolve_block_device_ref


def test_block_device_resolution_emits_storage_review_warning():
    decision = resolve_block_device_ref(
        resource_id="container::block_device_ref::/dev/dm-0",
        action={"action": "stage_for_recreate"},
        action_metadata={
            "host_path": "/dev/dm-0",
            "resource_metadata": {"policy_state": "managed_rw", "zone": "managed_services"},
        },
        policy={},
    )

    assert decision.block_device_refs == ["container::block_device_ref::/dev/dm-0"]
    assert decision.unresolved_resource_ids == []
    assert "storage_review_required:container::block_device_ref::/dev/dm-0" in decision.warnings


def test_block_device_resolution_marks_explicit_rw_requests_for_extra_review():
    decision = resolve_block_device_ref(
        resource_id="container::block_device_ref::/dev/sdb1",
        action={"action": "stage_for_recreate"},
        action_metadata={
            "host_path": "/dev/sdb1",
            "resource_metadata": {"policy_state": "managed_rw", "zone": "managed_services"},
        },
        policy={"mode": "rw"},
    )

    assert decision.block_device_refs == ["container::block_device_ref::/dev/sdb1"]
    assert "storage_review_required:container::block_device_ref::/dev/sdb1" in decision.warnings
    assert "block_device_write_review_required:container::block_device_ref::/dev/sdb1" in decision.warnings


def test_block_device_resolution_blocks_system_zone_resources():
    decision = resolve_block_device_ref(
        resource_id="container::block_device_ref::/dev/sda",
        action={"action": "stage_for_recreate"},
        action_metadata={
            "host_path": "/dev/sda",
            "resource_metadata": {"policy_state": "managed_rw", "zone": "system", "is_system": True},
        },
        policy={},
    )

    assert decision.block_device_refs == []
    assert decision.unresolved_resource_ids == ["container::block_device_ref::/dev/sda"]
    assert "system_block_device_ref_forbidden:container::block_device_ref::/dev/sda" in decision.warnings


def test_block_device_resolution_blocks_read_only_write_requests():
    decision = resolve_block_device_ref(
        resource_id="container::block_device_ref::/dev/sdb1",
        action={"action": "stage_for_recreate"},
        action_metadata={
            "host_path": "/dev/sdb1",
            "resource_metadata": {"policy_state": "read_only", "zone": "managed_services"},
        },
        policy={"mode": "rw"},
    )

    assert decision.block_device_refs == []
    assert decision.unresolved_resource_ids == ["container::block_device_ref::/dev/sdb1"]
    assert "storage_broker_policy_read_only:container::block_device_ref::/dev/sdb1" in decision.warnings


def test_block_device_resolution_requires_assign_to_container_operation():
    decision = resolve_block_device_ref(
        resource_id="container::block_device_ref::/dev/sdb1",
        action={"action": "stage_for_recreate"},
        action_metadata={
            "host_path": "/dev/sdb1",
            "resource_metadata": {
                "policy_state": "managed_rw",
                "zone": "managed_services",
                "allowed_operations": ["format", "mount_host"],
            },
        },
        policy={},
    )

    assert decision.block_device_refs == []
    assert decision.unresolved_resource_ids == ["container::block_device_ref::/dev/sdb1"]
    assert "storage_broker_operation_not_allowed:container::block_device_ref::/dev/sdb1" in decision.warnings
