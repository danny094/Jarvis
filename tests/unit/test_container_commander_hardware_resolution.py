import container_commander.hardware_resolution as hardware_resolution
from container_commander.hardware_resolution import resolve_blueprint_hardware_for_deploy, resolve_hardware_plan
from pathlib import Path


def test_hardware_resolution_builds_device_overrides_for_stage_only_devices():
    result = resolve_hardware_plan(
        blueprint_id="demo-bp",
        connector="container",
        target_type="blueprint",
        target_id="demo-bp",
        intents=[
            {
                "resource_id": "container::input::/dev/input/event21",
                "policy": {},
            }
        ],
        plan_payload={
            "actions": [
                {
                    "resource_id": "container::input::/dev/input/event21",
                    "action": "stage_for_recreate",
                    "supported": True,
                    "requires_restart": True,
                    "requires_approval": False,
                }
            ]
        },
        validate_payload={"valid": True, "issues": []},
    )

    assert result.supported is True
    assert result.requires_restart is True
    assert result.device_overrides == ["/dev/input/event21"]
    assert result.stage_only_resource_ids == ["container::input::/dev/input/event21"]
    assert result.unresolved_resource_ids == []


def test_hardware_resolution_prefers_dynamic_gateway_before_hardcoded_host_fallbacks():
    src = Path(__file__).resolve().parents[2].joinpath("container_commander/hardware_resolution.py").read_text(encoding="utf-8")
    helper_src = Path(__file__).resolve().parents[2].joinpath("utils/service_endpoint_resolver.py").read_text(encoding="utf-8")
    assert "candidate_service_endpoints(" in src
    assert 'host.docker.internal' in helper_src
    assert '127.0.0.1' in helper_src
    assert 'http://172.17.0.1:8420' not in src


def test_hardware_resolution_does_not_prefer_local_support_without_host_visibility(monkeypatch):
    monkeypatch.delenv("RUNTIME_HARDWARE_LOCAL_FIRST", raising=False)
    monkeypatch.setattr(hardware_resolution.Path, "is_dir", lambda self: str(self) == "/app/adapters/runtime-hardware")
    monkeypatch.setattr(hardware_resolution, "_local_runtime_hardware_has_host_visibility", lambda: False)

    assert hardware_resolution._should_prefer_local_runtime_hardware() is False


def test_hardware_resolution_prefers_local_support_with_host_visibility(monkeypatch):
    monkeypatch.delenv("RUNTIME_HARDWARE_LOCAL_FIRST", raising=False)
    monkeypatch.setattr(hardware_resolution.Path, "is_dir", lambda self: str(self) == "/app/adapters/runtime-hardware")
    monkeypatch.setattr(hardware_resolution, "_local_runtime_hardware_has_host_visibility", lambda: True)

    assert hardware_resolution._should_prefer_local_runtime_hardware() is True


def test_hardware_resolution_uses_local_fallback_when_http_unavailable(monkeypatch):
    calls = []

    def _raise_http_failure(**kwargs):
        raise RuntimeError("runtime_hardware_unreachable:test")

    def _local_fallback(*, path, json_body):
        calls.append(path)
        if path == "/hardware/plan":
            return {
                "actions": [
                    {
                        "resource_id": "container::input::/dev/input/event21",
                        "action": "stage_for_recreate",
                        "supported": True,
                        "requires_restart": True,
                        "requires_approval": False,
                    }
                ]
            }
        return {"valid": True, "issues": []}

    monkeypatch.setattr(hardware_resolution, "_request_runtime_hardware", _raise_http_failure)
    monkeypatch.setattr(hardware_resolution, "_request_runtime_hardware_local_fallback", _local_fallback)

    result = resolve_blueprint_hardware_for_deploy(
        blueprint_id="demo-bp",
        intents=[
            {
                "resource_id": "container::input::/dev/input/event21",
                "policy": {},
            }
        ],
        connector="container",
        target_type="blueprint",
        target_id="demo-bp",
    )

    assert calls == ["/hardware/plan", "/hardware/validate"]
    assert result.supported is True
    assert result.device_overrides == ["/dev/input/event21"]


def test_hardware_resolution_prefers_local_runtime_support_when_available(monkeypatch):
    calls = []

    def _local_fallback(*, path, json_body):
        calls.append(path)
        if path == "/hardware/plan":
            return {
                "actions": [
                    {
                        "resource_id": "container::input::/dev/input/event21",
                        "action": "stage_for_recreate",
                        "supported": True,
                        "requires_restart": True,
                        "requires_approval": False,
                    }
                ]
            }
        return {"valid": True, "issues": []}

    def _http_should_not_run(**kwargs):
        raise AssertionError("http_runtime_hardware_should_not_run")

    monkeypatch.setattr(hardware_resolution, "_should_prefer_local_runtime_hardware", lambda: True)
    monkeypatch.setattr(hardware_resolution, "_request_runtime_hardware_local_fallback", _local_fallback)
    monkeypatch.setattr(hardware_resolution, "_request_runtime_hardware", _http_should_not_run)

    result = resolve_blueprint_hardware_for_deploy(
        blueprint_id="demo-bp",
        intents=[
            {
                "resource_id": "container::input::/dev/input/event21",
                "policy": {},
            }
        ],
        connector="container",
        target_type="blueprint",
        target_id="demo-bp",
    )

    assert calls == ["/hardware/plan", "/hardware/validate"]
    assert result.supported is True
    assert result.device_overrides == ["/dev/input/event21"]


def test_hardware_resolution_keeps_block_refs_as_storage_review_items():
    result = resolve_hardware_plan(
        blueprint_id="demo-bp",
        connector="container",
        target_type="blueprint",
        target_id="demo-bp",
        intents=[
            {
                "resource_id": "container::block_device_ref::/dev/dm-0",
                "policy": {},
            }
        ],
        plan_payload={
            "actions": [
                {
                    "resource_id": "container::block_device_ref::/dev/dm-0",
                    "action": "stage_for_recreate",
                    "supported": True,
                    "requires_restart": True,
                    "requires_approval": True,
                    "metadata": {
                        "host_path": "/dev/dm-0",
                        "resource_metadata": {
                            "policy_state": "managed_rw",
                            "zone": "managed_services",
                        },
                    },
                }
            ]
        },
        validate_payload={"valid": True, "issues": []},
    )

    assert result.supported is True
    assert result.requires_approval is True
    assert result.block_device_refs == ["container::block_device_ref::/dev/dm-0"]
    assert result.device_overrides == []
    assert "storage_review_required:container::block_device_ref::/dev/dm-0" in result.warnings
    assert result.block_apply_previews == [
        {
            "resource_id": "container::block_device_ref::/dev/dm-0",
            "host_path": "/dev/dm-0",
            "disk_type": "unknown",
            "zone": "managed_services",
            "policy_state": "managed_rw",
            "requested_mode": "ro",
            "target_runtime": "container",
            "target_runtime_path": "/dev/dm-0",
            "candidate_runtime_binding": {
                "kind": "device_path",
                "source_path": "/dev/dm-0",
                "target_path": "/dev/dm-0",
                "binding_expression": "/dev/dm-0",
            },
            "apply_strategy": "runtime_device_binding",
            "allowed_operations": [],
            "eligible": False,
            "apply_mode": "review_only",
            "reason": "whole_disk_or_unknown_review_only",
            "requirements": [
                "explicit_user_approval",
                "container_recreate_required",
                "future_engine_block_apply_enablement",
            ],
            "blockers": ["whole_disk_or_unknown_review_only"],
            "requires_restart": True,
            "requires_approval": True,
            "warnings": ["storage_review_required:container::block_device_ref::/dev/dm-0"],
            "runtime_parameters": {
                "container": {
                    "candidate_container_path": "/dev/dm-0",
                    "candidate_device_override": "/dev/dm-0",
                    "device_override_mode": "docker_devices",
                }
            },
        }
    ]
    assert result.block_apply_candidates == []
    assert result.block_apply_container_plans == []
    assert result.block_apply_engine_handoffs == []


def test_hardware_resolution_blocks_system_block_refs_from_plan_metadata():
    result = resolve_hardware_plan(
        blueprint_id="demo-bp",
        connector="container",
        target_type="blueprint",
        target_id="demo-bp",
        intents=[
            {
                "resource_id": "container::block_device_ref::/dev/sda",
                "policy": {},
            }
        ],
        plan_payload={
            "actions": [
                {
                    "resource_id": "container::block_device_ref::/dev/sda",
                    "action": "stage_for_recreate",
                    "supported": True,
                    "requires_restart": True,
                    "requires_approval": True,
                    "metadata": {
                        "host_path": "/dev/sda",
                        "resource_metadata": {
                            "policy_state": "managed_rw",
                            "zone": "system",
                            "is_system": True,
                        },
                    },
                }
            ]
        },
        validate_payload={"valid": True, "issues": []},
    )

    assert result.supported is False
    assert result.block_device_refs == []
    assert result.unresolved_resource_ids == ["container::block_device_ref::/dev/sda"]
    assert "system_block_device_ref_forbidden:container::block_device_ref::/dev/sda" in result.warnings
    assert result.block_apply_previews == [
        {
            "resource_id": "container::block_device_ref::/dev/sda",
            "host_path": "/dev/sda",
            "disk_type": "unknown",
            "zone": "system",
            "policy_state": "managed_rw",
            "requested_mode": "ro",
            "target_runtime": "container",
            "target_runtime_path": "/dev/sda",
            "candidate_runtime_binding": {
                "kind": "device_path",
                "source_path": "/dev/sda",
                "target_path": "/dev/sda",
                "binding_expression": "/dev/sda",
            },
            "apply_strategy": "runtime_device_binding",
            "allowed_operations": [],
            "eligible": False,
            "apply_mode": "review_only",
            "reason": "policy_blocked",
            "requirements": [
                "explicit_user_approval",
                "container_recreate_required",
                "future_engine_block_apply_enablement",
            ],
            "blockers": ["policy_blocked"],
            "requires_restart": True,
            "requires_approval": True,
            "warnings": ["system_block_device_ref_forbidden:container::block_device_ref::/dev/sda"],
            "runtime_parameters": {
                "container": {
                    "candidate_container_path": "/dev/sda",
                    "candidate_device_override": "/dev/sda",
                    "device_override_mode": "docker_devices",
                }
            },
        }
    ]
    assert result.block_apply_candidates == []
    assert result.block_apply_container_plans == []
    assert result.block_apply_engine_handoffs == []


def test_hardware_resolution_builds_candidate_preview_for_partition_block_refs():
    result = resolve_hardware_plan(
        blueprint_id="demo-bp",
        connector="container",
        target_type="blueprint",
        target_id="demo-bp",
        intents=[
            {
                "resource_id": "container::block_device_ref::/dev/sdc1",
                "policy": {"mode": "rw"},
            }
        ],
        plan_payload={
            "actions": [
                {
                    "resource_id": "container::block_device_ref::/dev/sdc1",
                    "action": "stage_for_recreate",
                    "supported": True,
                    "requires_restart": True,
                    "requires_approval": True,
                    "metadata": {
                        "host_path": "/dev/sdc1",
                        "resource_metadata": {
                            "policy_state": "managed_rw",
                            "zone": "managed_services",
                            "disk_type": "part",
                            "allowed_operations": ["assign_to_container"],
                        },
                    },
                }
            ]
        },
        validate_payload={"valid": True, "issues": []},
    )

    assert result.block_device_refs == ["container::block_device_ref::/dev/sdc1"]
    assert result.block_apply_previews == [
        {
            "resource_id": "container::block_device_ref::/dev/sdc1",
            "host_path": "/dev/sdc1",
            "disk_type": "part",
            "zone": "managed_services",
            "policy_state": "managed_rw",
            "requested_mode": "rw",
            "target_runtime": "container",
            "target_runtime_path": "/dev/sdc1",
            "candidate_runtime_binding": {
                "kind": "device_path",
                "source_path": "/dev/sdc1",
                "target_path": "/dev/sdc1",
                "binding_expression": "/dev/sdc1",
            },
            "apply_strategy": "runtime_device_binding",
            "allowed_operations": ["assign_to_container"],
            "eligible": True,
            "apply_mode": "stage_device_passthrough_candidate",
            "reason": "candidate_for_explicit_container_apply",
            "requirements": [
                "explicit_user_approval",
                "container_recreate_required",
                "future_engine_block_apply_enablement",
                "write_access_review",
                "device_path_must_remain_visible_on_host",
            ],
            "blockers": [],
            "requires_restart": True,
            "requires_approval": True,
            "warnings": [
                "storage_review_required:container::block_device_ref::/dev/sdc1",
                "block_device_write_review_required:container::block_device_ref::/dev/sdc1",
            ],
            "runtime_parameters": {
                "container": {
                    "candidate_container_path": "/dev/sdc1",
                    "candidate_device_override": "/dev/sdc1",
                    "device_override_mode": "docker_devices",
                }
            },
        }
    ]
    assert result.block_apply_candidates == [
        {
            "resource_id": "container::block_device_ref::/dev/sdc1",
            "host_path": "/dev/sdc1",
            "target_runtime": "container",
            "target_runtime_path": "/dev/sdc1",
            "runtime_binding": {
                "kind": "device_path",
                "source_path": "/dev/sdc1",
                "target_path": "/dev/sdc1",
                "binding_expression": "/dev/sdc1",
            },
            "requested_mode": "rw",
            "apply_strategy": "runtime_device_binding",
            "activation_state": "disabled_until_engine_support",
            "activation_reason": "future_engine_block_apply_enablement",
            "requires_restart": True,
            "requires_approval": True,
            "requirements": [
                "explicit_user_approval",
                "container_recreate_required",
                "future_engine_block_apply_enablement",
                "write_access_review",
                "device_path_must_remain_visible_on_host",
            ],
            "warnings": [
                "storage_review_required:container::block_device_ref::/dev/sdc1",
                "block_device_write_review_required:container::block_device_ref::/dev/sdc1",
            ],
            "runtime_parameters": {
                "container": {
                    "candidate_container_path": "/dev/sdc1",
                    "candidate_device_override": "/dev/sdc1",
                    "device_override_mode": "docker_devices",
                }
            },
        }
    ]
    assert result.block_apply_container_plans == [
        {
            "resource_id": "container::block_device_ref::/dev/sdc1",
            "target_runtime": "container",
            "adapter_state": "disabled_until_engine_support",
            "adapter_reason": "future_engine_block_apply_enablement",
            "device_overrides": ["/dev/sdc1"],
            "container_path": "/dev/sdc1",
            "runtime_binding": {
                "kind": "device_path",
                "source_path": "/dev/sdc1",
                "target_path": "/dev/sdc1",
                "binding_expression": "/dev/sdc1",
            },
            "requirements": [
                "explicit_user_approval",
                "container_recreate_required",
                "future_engine_block_apply_enablement",
                "write_access_review",
                "device_path_must_remain_visible_on_host",
            ],
            "warnings": [
                "storage_review_required:container::block_device_ref::/dev/sdc1",
                "block_device_write_review_required:container::block_device_ref::/dev/sdc1",
            ],
        }
    ]
    assert result.block_apply_engine_handoffs == [
        {
            "resource_id": "container::block_device_ref::/dev/sdc1",
            "target_runtime": "container",
            "engine_handoff_state": "disabled_until_engine_support",
            "engine_handoff_reason": "explicit_engine_opt_in_required",
            "engine_target": "start_container",
            "device_overrides": ["/dev/sdc1"],
            "container_path": "/dev/sdc1",
            "runtime_binding": {
                "kind": "device_path",
                "source_path": "/dev/sdc1",
                "target_path": "/dev/sdc1",
                "binding_expression": "/dev/sdc1",
            },
            "requirements": [
                "explicit_user_approval",
                "container_recreate_required",
                "future_engine_block_apply_enablement",
                "write_access_review",
                "device_path_must_remain_visible_on_host",
            ],
            "warnings": [
                "storage_review_required:container::block_device_ref::/dev/sdc1",
                "block_device_write_review_required:container::block_device_ref::/dev/sdc1",
            ],
        }
    ]


def test_hardware_resolution_marks_invalid_container_device_path_in_preview():
    result = resolve_hardware_plan(
        blueprint_id="demo-bp",
        connector="container",
        target_type="blueprint",
        target_id="demo-bp",
        intents=[
            {
                "resource_id": "container::block_device_ref::/dev/sdc1",
                "policy": {"mode": "ro", "container_path": "/mnt/game-disk"},
            }
        ],
        plan_payload={
            "actions": [
                {
                    "resource_id": "container::block_device_ref::/dev/sdc1",
                    "action": "stage_for_recreate",
                    "supported": True,
                    "requires_restart": True,
                    "requires_approval": True,
                    "metadata": {
                        "host_path": "/dev/sdc1",
                        "resource_metadata": {
                            "policy_state": "managed_rw",
                            "zone": "managed_services",
                            "disk_type": "part",
                            "allowed_operations": ["assign_to_container"],
                        },
                    },
                }
            ]
        },
        validate_payload={"valid": True, "issues": []},
    )

    assert result.block_device_refs == ["container::block_device_ref::/dev/sdc1"]
    assert result.block_apply_previews == [
        {
            "resource_id": "container::block_device_ref::/dev/sdc1",
            "host_path": "/dev/sdc1",
            "disk_type": "part",
            "zone": "managed_services",
            "policy_state": "managed_rw",
            "requested_mode": "ro",
            "target_runtime": "container",
            "target_runtime_path": "",
            "candidate_runtime_binding": {
                "kind": "device_path",
                "source_path": "/dev/sdc1",
                "target_path": "",
                "binding_expression": "",
            },
            "apply_strategy": "runtime_device_binding",
            "allowed_operations": ["assign_to_container"],
            "eligible": False,
            "apply_mode": "review_only",
            "reason": "invalid_container_device_path",
            "requirements": [
                "explicit_user_approval",
                "container_recreate_required",
                "future_engine_block_apply_enablement",
            ],
            "blockers": ["invalid_container_device_path"],
            "requires_restart": True,
            "requires_approval": True,
            "warnings": ["storage_review_required:container::block_device_ref::/dev/sdc1"],
            "runtime_parameters": {
                "container": {
                    "candidate_container_path": "",
                    "candidate_device_override": "",
                    "device_override_mode": "docker_devices",
                }
            },
        }
    ]
    assert result.block_apply_candidates == []
    assert result.block_apply_container_plans == []
    assert result.block_apply_engine_handoffs == []


def test_hardware_resolution_materializes_mount_ref_when_container_path_is_explicit(monkeypatch):
    import container_commander.hardware_resolution as hr
    import container_commander.storage_assets as assets

    monkeypatch.setattr(
        assets,
        "get_asset",
        lambda asset_id: {
            "id": asset_id,
            "path": "/data/games",
            "published_to_commander": True,
            "default_mode": "rw",
        },
    )
    monkeypatch.setattr(
        hr,
        "_request_runtime_hardware",
        lambda **kwargs: (
            {
                "actions": [
                    {
                        "resource_id": "container::mount_ref::games-lib",
                        "action": "stage_for_recreate",
                        "supported": True,
                        "requires_restart": True,
                        "requires_approval": False,
                    }
                ]
            }
            if kwargs.get("path") == "/hardware/plan"
            else {"valid": True, "issues": []}
        ),
    )

    result = resolve_blueprint_hardware_for_deploy(
        blueprint_id="demo-bp",
        connector="container",
        target_type="blueprint",
        target_id="demo-bp",
        intents=[
            {
                "resource_id": "container::mount_ref::games-lib",
                "policy": {"container_path": "/games"},
            }
        ],
    )

    assert result.supported is True
    assert result.mount_refs == ["container::mount_ref::games-lib"]
    assert result.mount_overrides == [
        {"asset_id": "games-lib", "container": "/games", "type": "bind", "mode": "rw"}
    ]
    assert "storage_broker_materialization_required:container::mount_ref::games-lib" not in result.warnings


def test_hardware_resolution_blocks_mount_ref_targets_under_reserved_container_paths(monkeypatch):
    import container_commander.hardware_resolution as hr
    import container_commander.storage_assets as assets

    monkeypatch.setattr(
        assets,
        "get_asset",
        lambda asset_id: {
            "id": asset_id,
            "path": "/data/games",
            "published_to_commander": True,
            "default_mode": "rw",
        },
    )
    monkeypatch.setattr(
        hr,
        "_request_runtime_hardware",
        lambda **kwargs: (
            {
                "actions": [
                    {
                        "resource_id": "container::mount_ref::games-lib",
                        "action": "stage_for_recreate",
                        "supported": True,
                        "requires_restart": True,
                        "requires_approval": False,
                    }
                ]
            }
            if kwargs.get("path") == "/hardware/plan"
            else {"valid": True, "issues": []}
        ),
    )

    result = resolve_blueprint_hardware_for_deploy(
        blueprint_id="demo-bp",
        connector="container",
        target_type="blueprint",
        target_id="demo-bp",
        intents=[
            {
                "resource_id": "container::mount_ref::games-lib",
                "policy": {"container_path": "/proc/runtime-hw"},
            }
        ],
    )

    assert result.supported is False
    assert result.mount_overrides == []
    assert result.unresolved_resource_ids == ["container::mount_ref::games-lib"]
    assert "blocked_mount_ref_target:container::mount_ref::games-lib:/proc/runtime-hw" in result.warnings


def test_hardware_resolution_blocks_mount_ref_when_asset_policy_is_blocked(monkeypatch):
    import container_commander.hardware_resolution as hr
    import container_commander.storage_assets as assets

    monkeypatch.setattr(
        assets,
        "get_asset",
        lambda asset_id: {
            "id": asset_id,
            "path": "/data/games",
            "published_to_commander": True,
            "default_mode": "rw",
            "policy_state": "blocked",
        },
    )
    monkeypatch.setattr(
        hr,
        "_request_runtime_hardware",
        lambda **kwargs: (
            {
                "actions": [
                    {
                        "resource_id": "container::mount_ref::games-lib",
                        "action": "stage_for_recreate",
                        "supported": True,
                        "requires_restart": True,
                        "requires_approval": False,
                    }
                ]
            }
            if kwargs.get("path") == "/hardware/plan"
            else {"valid": True, "issues": []}
        ),
    )

    result = resolve_blueprint_hardware_for_deploy(
        blueprint_id="demo-bp",
        connector="container",
        target_type="blueprint",
        target_id="demo-bp",
        intents=[
            {
                "resource_id": "container::mount_ref::games-lib",
                "policy": {"container_path": "/games"},
            }
        ],
    )

    assert result.supported is False
    assert result.mount_overrides == []
    assert result.unresolved_resource_ids == ["container::mount_ref::games-lib"]
    assert "storage_asset_policy_blocked:games-lib" in result.warnings


def test_hardware_resolution_blocks_rw_mount_ref_when_asset_policy_is_read_only(monkeypatch):
    import container_commander.hardware_resolution as hr
    import container_commander.storage_assets as assets

    monkeypatch.setattr(
        assets,
        "get_asset",
        lambda asset_id: {
            "id": asset_id,
            "path": "/data/games",
            "published_to_commander": True,
            "default_mode": "rw",
            "policy_state": "read_only",
        },
    )
    monkeypatch.setattr(
        hr,
        "_request_runtime_hardware",
        lambda **kwargs: (
            {
                "actions": [
                    {
                        "resource_id": "container::mount_ref::games-lib",
                        "action": "stage_for_recreate",
                        "supported": True,
                        "requires_restart": True,
                        "requires_approval": False,
                    }
                ]
            }
            if kwargs.get("path") == "/hardware/plan"
            else {"valid": True, "issues": []}
        ),
    )

    result = resolve_blueprint_hardware_for_deploy(
        blueprint_id="demo-bp",
        connector="container",
        target_type="blueprint",
        target_id="demo-bp",
        intents=[
            {
                "resource_id": "container::mount_ref::games-lib",
                "policy": {"container_path": "/games", "mode": "rw"},
            }
        ],
    )

    assert result.supported is False
    assert result.mount_overrides == []
    assert result.unresolved_resource_ids == ["container::mount_ref::games-lib"]
    assert "storage_asset_policy_read_only:games-lib" in result.warnings


def test_hardware_resolution_marks_unsupported_or_invalid_resources_unresolved():
    result = resolve_hardware_plan(
        blueprint_id="demo-bp",
        connector="container",
        target_type="blueprint",
        target_id="demo-bp",
        intents=[
            {
                "resource_id": "container::device::/dev/uinput",
                "policy": {},
            }
        ],
        plan_payload={
            "actions": [
                {
                    "resource_id": "container::device::/dev/uinput",
                    "action": "unsupported",
                    "supported": False,
                    "explanation": "unsupported_resource_kind:device",
                }
            ]
        },
        validate_payload={"valid": False, "issues": []},
    )

    assert result.supported is False
    assert result.device_overrides == []
    assert result.unresolved_resource_ids == ["container::device::/dev/uinput"]
    assert "unsupported_resource_kind:device" in result.warnings
