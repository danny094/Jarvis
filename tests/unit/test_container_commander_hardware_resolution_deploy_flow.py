from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _import_engine():
    sys.modules.setdefault("docker", MagicMock())
    sys.modules.setdefault(
        "docker.errors",
        SimpleNamespace(
            DockerException=Exception,
            NotFound=Exception,
            APIError=Exception,
            BuildError=Exception,
            ImageNotFound=Exception,
        ),
    )
    sys.modules.setdefault(
        "container_commander.blueprint_store",
        SimpleNamespace(resolve_blueprint=lambda *args, **kwargs: None, log_action=lambda *args, **kwargs: None),
    )
    sys.modules.setdefault(
        "container_commander.secret_store",
        SimpleNamespace(
            get_secrets_for_blueprint=lambda *args, **kwargs: {},
            get_secret_value=lambda *args, **kwargs: "",
            log_secret_access=lambda *args, **kwargs: None,
        ),
    )

    import container_commander.engine as engine

    return engine


def _fake_runtime():
    return {
        "client": object(),
        "container": SimpleNamespace(id="container-1234567890", short_id="container1234"),
        "container_name": "trion_demo_1",
        "volume_name": "trion_ws_demo_1",
        "mem_bytes": 512 * 1024 * 1024,
        "net_info": {"network": "internal"},
    }


def test_start_container_merges_resolved_hardware_device_overrides(monkeypatch):
    engine = _import_engine()

    from container_commander.hardware_resolution import HardwareResolution
    from container_commander.models import Blueprint, HardwareIntent, NetworkMode, ResourceLimits

    bp = Blueprint(
        id="demo-blueprint",
        name="Demo Blueprint",
        image="busybox:latest",
        network=NetworkMode.INTERNAL,
        resources=ResourceLimits(timeout_seconds=0),
        hardware_intents=[HardwareIntent(resource_id="container::input::/dev/input/event21")],
    )

    prepare_calls = {}

    monkeypatch.setattr(engine, "resolve_blueprint", lambda blueprint_id: bp)
    monkeypatch.setattr(engine, "_setup_host_companion_impl", lambda blueprint_id, resolved_bp: None)
    monkeypatch.setattr(
        engine,
        "_resolve_blueprint_hardware_for_deploy_impl",
        lambda **kwargs: HardwareResolution(
            blueprint_id="demo-blueprint",
            connector="container",
            target_type="blueprint",
            target_id="demo-blueprint",
            supported=True,
            resolved_count=1,
            requires_restart=True,
            device_overrides=["/dev/input/event21"],
        ),
    )

    def fake_prepare(bp_arg, mount_overrides, device_overrides, storage_scope_override, **kwargs):
        prepare_calls["device_overrides"] = list(device_overrides or [])
        return bp_arg, [], list(device_overrides or []), [], [], ""

    monkeypatch.setattr(engine, "_prepare_runtime_blueprint_impl", fake_prepare)
    monkeypatch.setattr(engine, "_request_deploy_approval_if_needed_impl", lambda **kwargs: None)
    monkeypatch.setattr(engine, "_emit_ws_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "_enforce_trust_gates_impl", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "_reserve_quota", lambda resources: (0.0, 0.0))
    monkeypatch.setattr(engine, "build_image", lambda bp_arg: "busybox:latest")
    monkeypatch.setattr(engine, "_build_env_vars_impl", lambda *args, **kwargs: {})
    monkeypatch.setattr(engine, "_run_pre_start_exec", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "get_client", lambda: object())
    monkeypatch.setattr(engine, "_validate_runtime_preflight", lambda client, runtime: (True, "ok"))
    monkeypatch.setattr(engine, "_start_runtime_container_impl", lambda **kwargs: _fake_runtime())
    monkeypatch.setattr(engine, "_run_post_start_checks_impl", lambda **kwargs: [])
    monkeypatch.setattr(engine, "_commit_quota_reservation", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "_set_ttl_timer", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "log_action", lambda *args, **kwargs: None)

    instance = engine.start_container(
        "demo-blueprint",
        device_overrides=["/dev/dri:/dev/dri"],
    )

    assert prepare_calls["device_overrides"] == ["/dev/dri:/dev/dri", "/dev/input/event21"]
    assert instance.deploy_warnings == []


def test_start_container_merges_explicit_block_engine_opt_in_device_overrides(monkeypatch):
    engine = _import_engine()

    from container_commander.hardware_resolution import HardwareResolution
    from container_commander.models import Blueprint, HardwareIntent, NetworkMode, ResourceLimits

    bp = Blueprint(
        id="block-opt-in-demo",
        name="Block Opt In Demo",
        image="busybox:latest",
        network=NetworkMode.INTERNAL,
        resources=ResourceLimits(timeout_seconds=0),
        hardware_intents=[HardwareIntent(resource_id="container::block_device_ref::/dev/sdd1")],
    )

    prepare_calls = {}

    monkeypatch.setattr(engine, "resolve_blueprint", lambda blueprint_id: bp)
    monkeypatch.setattr(engine, "_setup_host_companion_impl", lambda blueprint_id, resolved_bp: None)
    monkeypatch.setattr(
        engine,
        "_resolve_blueprint_hardware_for_deploy_impl",
        lambda **kwargs: HardwareResolution(
            blueprint_id="block-opt-in-demo",
            connector="container",
            target_type="blueprint",
            target_id="block-opt-in-demo",
            supported=True,
            resolved_count=1,
            requires_restart=True,
            requires_approval=True,
            block_apply_engine_handoffs=[
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
            ],
        ),
    )

    def fake_prepare(bp_arg, mount_overrides, device_overrides, storage_scope_override, **kwargs):
        prepare_calls["device_overrides"] = list(device_overrides or [])
        return bp_arg, [], list(device_overrides or []), [], [], ""

    monkeypatch.setattr(engine, "_prepare_runtime_blueprint_impl", fake_prepare)
    monkeypatch.setattr(engine, "_request_deploy_approval_if_needed_impl", lambda **kwargs: None)
    monkeypatch.setattr(engine, "_emit_ws_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "_enforce_trust_gates_impl", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "_reserve_quota", lambda resources: (0.0, 0.0))
    monkeypatch.setattr(engine, "build_image", lambda bp_arg: "busybox:latest")
    monkeypatch.setattr(engine, "_build_env_vars_impl", lambda *args, **kwargs: {})
    monkeypatch.setattr(engine, "_run_pre_start_exec", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "get_client", lambda: object())
    monkeypatch.setattr(engine, "_validate_runtime_preflight", lambda client, runtime: (True, "ok"))
    monkeypatch.setattr(engine, "_start_runtime_container_impl", lambda **kwargs: _fake_runtime())
    monkeypatch.setattr(engine, "_run_post_start_checks_impl", lambda **kwargs: [])
    monkeypatch.setattr(engine, "_commit_quota_reservation", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "_set_ttl_timer", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "log_action", lambda *args, **kwargs: None)

    instance = engine.start_container(
        "block-opt-in-demo",
        block_apply_handoff_resource_ids=["container::block_device_ref::/dev/sdd1"],
    )

    assert prepare_calls["device_overrides"] == ["/dev/sdd1:/dev/game-disk"]
    assert instance.block_apply_handoff_resource_ids_requested == ["container::block_device_ref::/dev/sdd1"]
    assert instance.block_apply_handoff_resource_ids_applied == ["container::block_device_ref::/dev/sdd1"]
    assert instance.hardware_resolution_preview["engine_opt_in_available"] is True
    messages = [str((item.get("detail") or {}).get("message") or "") for item in instance.deploy_warnings]
    assert "block_engine_handoff_opt_in_applied:container::block_device_ref::/dev/sdd1" in messages


def test_start_container_projects_hardware_resolution_warnings(monkeypatch):
    engine = _import_engine()

    from container_commander.hardware_resolution import HardwareResolution
    from container_commander.models import Blueprint, HardwareIntent, NetworkMode, ResourceLimits

    bp = Blueprint(
        id="storage-demo",
        name="Storage Demo",
        image="busybox:latest",
        network=NetworkMode.INTERNAL,
        resources=ResourceLimits(timeout_seconds=0),
        hardware_intents=[HardwareIntent(resource_id="container::block_device_ref::/dev/dm-0")],
    )

    monkeypatch.setattr(engine, "resolve_blueprint", lambda blueprint_id: bp)
    monkeypatch.setattr(engine, "_setup_host_companion_impl", lambda blueprint_id, resolved_bp: None)
    monkeypatch.setattr(
        engine,
        "_resolve_blueprint_hardware_for_deploy_impl",
        lambda **kwargs: HardwareResolution(
            blueprint_id="storage-demo",
            connector="container",
            target_type="blueprint",
            target_id="storage-demo",
            supported=True,
            resolved_count=1,
            requires_restart=True,
            requires_approval=True,
            block_device_refs=["container::block_device_ref::/dev/dm-0"],
            warnings=["storage_review_required:container::block_device_ref::/dev/dm-0"],
            block_apply_engine_handoffs=[
                {
                    "resource_id": "container::block_device_ref::/dev/dm-0",
                    "target_runtime": "container",
                    "engine_handoff_state": "disabled_until_engine_support",
                    "engine_handoff_reason": "explicit_engine_opt_in_required",
                    "engine_target": "start_container",
                    "device_overrides": ["/dev/dm-0"],
                    "container_path": "/dev/dm-0",
                    "runtime_binding": {
                        "kind": "device_path",
                        "source_path": "/dev/dm-0",
                        "target_path": "/dev/dm-0",
                        "binding_expression": "/dev/dm-0",
                    },
                    "requirements": ["explicit_user_approval"],
                    "warnings": ["storage_review_required:container::block_device_ref::/dev/dm-0"],
                }
            ],
        ),
    )
    monkeypatch.setattr(
        engine,
        "_prepare_runtime_blueprint_impl",
        lambda bp_arg, mount_overrides, device_overrides, storage_scope_override, **kwargs: (
            bp_arg,
            [],
            list(device_overrides or []),
            [],
            [],
            "",
        ),
    )
    monkeypatch.setattr(engine, "_request_deploy_approval_if_needed_impl", lambda **kwargs: None)
    monkeypatch.setattr(engine, "_emit_ws_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "_enforce_trust_gates_impl", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "_reserve_quota", lambda resources: (0.0, 0.0))
    monkeypatch.setattr(engine, "build_image", lambda bp_arg: "busybox:latest")
    monkeypatch.setattr(engine, "_build_env_vars_impl", lambda *args, **kwargs: {})
    monkeypatch.setattr(engine, "_run_pre_start_exec", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "get_client", lambda: object())
    monkeypatch.setattr(engine, "_validate_runtime_preflight", lambda client, runtime: (True, "ok"))
    monkeypatch.setattr(engine, "_start_runtime_container_impl", lambda **kwargs: _fake_runtime())
    monkeypatch.setattr(
        engine,
        "_run_post_start_checks_impl",
        lambda **kwargs: [{"name": "existing_warning", "detail": {"message": "postcheck_warning"}}],
    )
    monkeypatch.setattr(engine, "_commit_quota_reservation", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "_set_ttl_timer", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "log_action", lambda *args, **kwargs: None)

    instance = engine.start_container("storage-demo")

    messages = [str((item.get("detail") or {}).get("message") or "") for item in instance.deploy_warnings]
    names = [str(item.get("name") or "") for item in instance.deploy_warnings]

    assert "existing_warning" in names
    assert "hardware_resolution" in names
    assert "hardware_block_engine_handoff" in names
    assert "postcheck_warning" in messages
    assert "storage_review_required:container::block_device_ref::/dev/dm-0" in messages
    assert "disabled_block_engine_handoff_available:container::block_device_ref::/dev/dm-0" in messages


def test_start_container_merges_resolved_mount_overrides(monkeypatch):
    engine = _import_engine()

    from container_commander.hardware_resolution import HardwareResolution
    from container_commander.models import Blueprint, HardwareIntent, NetworkMode, ResourceLimits

    bp = Blueprint(
        id="mount-demo",
        name="Mount Demo",
        image="busybox:latest",
        network=NetworkMode.INTERNAL,
        resources=ResourceLimits(timeout_seconds=0),
        hardware_intents=[
            HardwareIntent(
                resource_id="container::mount_ref::games-lib",
                policy={"container_path": "/games"},
            )
        ],
    )

    prepare_calls = {}

    monkeypatch.setattr(engine, "resolve_blueprint", lambda blueprint_id: bp)
    monkeypatch.setattr(engine, "_setup_host_companion_impl", lambda blueprint_id, resolved_bp: None)
    monkeypatch.setattr(
        engine,
        "_resolve_blueprint_hardware_for_deploy_impl",
        lambda **kwargs: HardwareResolution(
            blueprint_id="mount-demo",
            connector="container",
            target_type="blueprint",
            target_id="mount-demo",
            supported=True,
            resolved_count=1,
            requires_restart=True,
            mount_refs=["container::mount_ref::games-lib"],
            mount_overrides=[
                {"asset_id": "games-lib", "container": "/games", "type": "bind", "mode": "rw"}
            ],
        ),
    )

    def fake_prepare(bp_arg, mount_overrides, device_overrides, storage_scope_override, **kwargs):
        prepare_calls["mount_overrides"] = list(mount_overrides or [])
        return bp_arg, list(mount_overrides or []), list(device_overrides or []), list(mount_overrides or []), ["games-lib"], "deploy_auto_asset_mount-demo_games-lib_deadbeef"

    monkeypatch.setattr(engine, "_prepare_runtime_blueprint_impl", fake_prepare)
    monkeypatch.setattr(engine, "_request_deploy_approval_if_needed_impl", lambda **kwargs: None)
    monkeypatch.setattr(engine, "_emit_ws_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "_enforce_trust_gates_impl", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "_reserve_quota", lambda resources: (0.0, 0.0))
    monkeypatch.setattr(engine, "build_image", lambda bp_arg: "busybox:latest")
    monkeypatch.setattr(engine, "_build_env_vars_impl", lambda *args, **kwargs: {})
    monkeypatch.setattr(engine, "_run_pre_start_exec", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "get_client", lambda: object())
    monkeypatch.setattr(engine, "_validate_runtime_preflight", lambda client, runtime: (True, "ok"))
    monkeypatch.setattr(engine, "_start_runtime_container_impl", lambda **kwargs: _fake_runtime())
    monkeypatch.setattr(engine, "_run_post_start_checks_impl", lambda **kwargs: [])
    monkeypatch.setattr(engine, "_commit_quota_reservation", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "_set_ttl_timer", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "log_action", lambda *args, **kwargs: None)

    engine.start_container(
        "mount-demo",
        mount_overrides=[{"asset_id": "games-lib", "container": "/games", "type": "bind", "mode": "rw"}],
    )

    assert prepare_calls["mount_overrides"] == [
        {"asset_id": "games-lib", "container": "/games", "type": "bind", "mode": "rw"}
    ]
