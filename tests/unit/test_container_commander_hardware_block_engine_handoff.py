from container_commander.hardware_block_engine_handoff import (
    build_disabled_container_block_engine_handoffs,
)


def test_block_engine_handoffs_are_built_from_container_plans():
    decision = build_disabled_container_block_engine_handoffs(
        [
            {
                "resource_id": "container::block_device_ref::/dev/sdd1",
                "target_runtime": "container",
                "device_overrides": ["/dev/sdd1:/dev/game-disk"],
                "container_path": "/dev/game-disk",
                "runtime_binding": {
                    "kind": "device_path",
                    "source_path": "/dev/sdd1",
                    "target_path": "/dev/game-disk",
                    "binding_expression": "/dev/sdd1:/dev/game-disk",
                },
                "requirements": ["explicit_user_approval"],
                "warnings": ["storage_review_required:container::block_device_ref::/dev/sdd1"],
            }
        ]
    )

    assert decision.handoffs == [
        {
            "resource_id": "container::block_device_ref::/dev/sdd1",
            "target_runtime": "container",
            "engine_handoff_state": "disabled_until_engine_support",
            "engine_handoff_reason": "explicit_engine_opt_in_required",
            "engine_target": "start_container",
            "device_overrides": ["/dev/sdd1:/dev/game-disk"],
            "container_path": "/dev/game-disk",
            "runtime_binding": {
                "kind": "device_path",
                "source_path": "/dev/sdd1",
                "target_path": "/dev/game-disk",
                "binding_expression": "/dev/sdd1:/dev/game-disk",
            },
            "requirements": ["explicit_user_approval"],
            "warnings": ["storage_review_required:container::block_device_ref::/dev/sdd1"],
        }
    ]
