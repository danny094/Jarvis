from container_commander.hardware_block_engine_opt_in import select_block_engine_handoffs


def test_block_engine_opt_in_selects_requested_handoffs_only():
    decision = select_block_engine_handoffs(
        [
            {
                "resource_id": "container::block_device_ref::/dev/sdd1",
                "device_overrides": ["/dev/sdd1:/dev/game-disk"],
            },
            {
                "resource_id": "container::block_device_ref::/dev/sde1",
                "device_overrides": ["/dev/sde1:/dev/other-disk"],
            },
        ],
        ["container::block_device_ref::/dev/sdd1"],
    )

    assert decision.requested_resource_ids == ["container::block_device_ref::/dev/sdd1"]
    assert decision.device_overrides == ["/dev/sdd1:/dev/game-disk"]
    assert decision.selected_resource_ids == ["container::block_device_ref::/dev/sdd1"]
    assert decision.warnings == ["block_engine_handoff_opt_in_applied:container::block_device_ref::/dev/sdd1"]


def test_block_engine_opt_in_reports_unmatched_resource_ids():
    decision = select_block_engine_handoffs([], ["container::block_device_ref::/dev/missing1"])

    assert decision.requested_resource_ids == ["container::block_device_ref::/dev/missing1"]
    assert decision.device_overrides == []
    assert decision.selected_resource_ids == []
    assert decision.warnings == ["block_engine_handoff_opt_in_unmatched:container::block_device_ref::/dev/missing1"]
