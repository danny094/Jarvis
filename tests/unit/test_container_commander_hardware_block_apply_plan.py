from container_commander.hardware_block_apply_plan import build_block_apply_candidates


def test_block_apply_candidates_only_include_eligible_previews():
    decision = build_block_apply_candidates(
        [
            {
                "resource_id": "container::block_device_ref::/dev/sdc1",
                "host_path": "/dev/sdc1",
                "target_runtime": "container",
                "target_runtime_path": "/dev/game-disk",
                "candidate_runtime_binding": {
                    "kind": "device_path",
                    "source_path": "/dev/sdc1",
                    "target_path": "/dev/game-disk",
                    "binding_expression": "/dev/sdc1:/dev/game-disk",
                },
                "requested_mode": "rw",
                "apply_strategy": "runtime_device_binding",
                "eligible": True,
                "requires_restart": True,
                "requires_approval": True,
                "requirements": ["explicit_user_approval"],
                "warnings": ["storage_review_required:container::block_device_ref::/dev/sdc1"],
                "runtime_parameters": {
                    "container": {
                        "candidate_container_path": "/dev/game-disk",
                        "candidate_device_override": "/dev/sdc1:/dev/game-disk",
                        "device_override_mode": "docker_devices",
                    }
                },
            },
            {
                "resource_id": "container::block_device_ref::/dev/sda",
                "host_path": "/dev/sda",
                "target_runtime": "container",
                "target_runtime_path": "/dev/sda",
                "candidate_runtime_binding": {
                    "kind": "device_path",
                    "source_path": "/dev/sda",
                    "target_path": "/dev/sda",
                    "binding_expression": "/dev/sda",
                },
                "requested_mode": "ro",
                "apply_strategy": "runtime_device_binding",
                "eligible": False,
                "requires_restart": True,
                "requires_approval": True,
                "requirements": ["explicit_user_approval"],
                "warnings": ["system_block_device_ref_forbidden:container::block_device_ref::/dev/sda"],
            },
        ]
    )

    assert decision.candidates == [
        {
            "resource_id": "container::block_device_ref::/dev/sdc1",
            "host_path": "/dev/sdc1",
            "target_runtime": "container",
            "target_runtime_path": "/dev/game-disk",
            "runtime_binding": {
                "kind": "device_path",
                "source_path": "/dev/sdc1",
                "target_path": "/dev/game-disk",
                "binding_expression": "/dev/sdc1:/dev/game-disk",
            },
            "requested_mode": "rw",
            "apply_strategy": "runtime_device_binding",
            "activation_state": "disabled_until_engine_support",
            "activation_reason": "future_engine_block_apply_enablement",
            "requires_restart": True,
            "requires_approval": True,
            "requirements": ["explicit_user_approval"],
            "warnings": ["storage_review_required:container::block_device_ref::/dev/sdc1"],
            "runtime_parameters": {
                "container": {
                    "candidate_container_path": "/dev/game-disk",
                    "candidate_device_override": "/dev/sdc1:/dev/game-disk",
                    "device_override_mode": "docker_devices",
                }
            },
        }
    ]
