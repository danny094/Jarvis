from container_commander.hardware_resolution import HardwareResolution
from container_commander.hardware_resolution_preview import (
    build_hardware_resolution_preview_payload,
)


def test_hardware_resolution_preview_exposes_engine_opt_in_hint():
    preview = build_hardware_resolution_preview_payload(
        HardwareResolution(
            blueprint_id="demo-bp",
            connector="container",
            target_type="blueprint",
            target_id="demo-bp",
            supported=True,
            resolved_count=1,
            requires_restart=True,
            requires_approval=True,
            block_apply_candidates=[
                {"resource_id": "container::block_device_ref::/dev/sdd1"},
            ],
            block_apply_container_plans=[
                {"resource_id": "container::block_device_ref::/dev/sdd1"},
            ],
            block_apply_engine_handoffs=[
                {"resource_id": "container::block_device_ref::/dev/sdd1"},
            ],
            warnings=["storage_review_required:container::block_device_ref::/dev/sdd1"],
        )
    )

    assert preview == {
        "supported": True,
        "resolved_count": 1,
        "requires_restart": True,
        "requires_approval": True,
        "device_override_count": 0,
        "mount_override_count": 0,
        "block_candidate_resource_ids": ["container::block_device_ref::/dev/sdd1"],
        "container_plan_resource_ids": ["container::block_device_ref::/dev/sdd1"],
        "engine_handoff_resource_ids": ["container::block_device_ref::/dev/sdd1"],
        "block_apply_handoff_resource_ids_hint": ["container::block_device_ref::/dev/sdd1"],
        "engine_opt_in_available": True,
        "unresolved_resource_ids": [],
        "warnings": ["storage_review_required:container::block_device_ref::/dev/sdd1"],
    }
