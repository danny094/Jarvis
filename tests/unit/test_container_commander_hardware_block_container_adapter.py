from container_commander.hardware_block_container_adapter import build_container_block_apply_adapter_plan


def test_container_block_adapter_builds_disabled_plan_for_container_candidates():
    decision = build_container_block_apply_adapter_plan(
        [
            {
                "resource_id": "container::block_device_ref::/dev/sdc1",
                "target_runtime": "container",
                "runtime_binding": {
                    "kind": "device_path",
                    "source_path": "/dev/sdc1",
                    "target_path": "/dev/game-disk",
                    "binding_expression": "/dev/sdc1:/dev/game-disk",
                },
                "requirements": ["explicit_user_approval"],
                "warnings": ["storage_review_required:container::block_device_ref::/dev/sdc1"],
                "runtime_parameters": {
                    "container": {
                        "candidate_container_path": "/dev/game-disk",
                        "candidate_device_override": "/dev/sdc1:/dev/game-disk",
                    }
                },
            }
        ]
    )

    assert decision.plans == [
        {
            "resource_id": "container::block_device_ref::/dev/sdc1",
            "target_runtime": "container",
            "adapter_state": "disabled_until_engine_support",
            "adapter_reason": "future_engine_block_apply_enablement",
            "device_overrides": ["/dev/sdc1:/dev/game-disk"],
            "container_path": "/dev/game-disk",
            "runtime_binding": {
                "kind": "device_path",
                "source_path": "/dev/sdc1",
                "target_path": "/dev/game-disk",
                "binding_expression": "/dev/sdc1:/dev/game-disk",
            },
            "requirements": ["explicit_user_approval"],
            "warnings": ["storage_review_required:container::block_device_ref::/dev/sdc1"],
        }
    ]
