from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_normalize_runtime_mount_override_resolves_storage_asset(monkeypatch):
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
            get_secrets_for_blueprint=lambda *args, **kwargs: [],
            get_secret_value=lambda *args, **kwargs: "",
            log_secret_access=lambda *args, **kwargs: None,
        ),
    )

    import container_commander.engine as engine
    import container_commander.storage_assets as assets

    monkeypatch.setattr(
        assets,
        "get_asset",
        lambda asset_id: {
            "id": asset_id,
            "path": "/data/games",
            "published_to_commander": True,
            "default_mode": "ro",
        },
    )

    mounts = engine._normalize_runtime_mount_overrides(
        [{"asset_id": "games-lib", "container": "/games", "type": "bind"}]
    )

    assert len(mounts) == 1
    assert mounts[0].host == "/data/games"
    assert mounts[0].mode == "ro"
    assert mounts[0].asset_id == "games-lib"


def test_normalize_runtime_mount_override_blocks_rw_for_read_only_asset(monkeypatch):
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
            get_secrets_for_blueprint=lambda *args, **kwargs: [],
            get_secret_value=lambda *args, **kwargs: "",
            log_secret_access=lambda *args, **kwargs: None,
        ),
    )

    import container_commander.engine as engine
    import container_commander.storage_assets as assets

    monkeypatch.setattr(
        assets,
        "get_asset",
        lambda asset_id: {
            "id": asset_id,
            "path": "/data/games",
            "published_to_commander": True,
            "default_mode": "ro",
        },
    )

    with pytest.raises(RuntimeError) as exc:
        engine._normalize_runtime_mount_overrides(
            [{"asset_id": "games-lib", "container": "/games", "type": "bind", "mode": "rw"}]
        )

    assert "storage_asset_read_only" in str(exc.value)


def test_compose_runtime_blueprint_creates_deterministic_asset_scope(monkeypatch):
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
            get_secrets_for_blueprint=lambda *args, **kwargs: [],
            get_secret_value=lambda *args, **kwargs: "",
            log_secret_access=lambda *args, **kwargs: None,
        ),
    )

    import container_commander.engine as engine
    import container_commander.storage_scope as scopes
    from container_commander.models import Blueprint, MountDef

    captured = {}
    monkeypatch.setattr(scopes, "get_scope", lambda name: None)

    def fake_upsert_scope(name, roots, approved_by="user", metadata=None):
        captured["name"] = name
        captured["roots"] = roots
        captured["approved_by"] = approved_by
        captured["metadata"] = metadata
        return {"name": name, "roots": roots, "approved_by": approved_by, "metadata": metadata}

    monkeypatch.setattr(scopes, "upsert_scope", fake_upsert_scope)

    bp = Blueprint(id="retro-box", name="Retro Box")
    override = MountDef(host="/data/games", container="/games", type="bind", mode="ro", asset_id="games-lib")

    effective = engine._compose_runtime_blueprint(
        bp,
        runtime_mount_overrides=[override],
        runtime_device_overrides=[],
        storage_scope_override="",
        force_auto_scope=True,
    )

    assert effective.storage_scope.startswith("deploy_auto_asset_retro-box_games-lib_")
    assert captured["name"] == effective.storage_scope
    assert captured["approved_by"] == "system:auto"
    assert captured["metadata"]["origin"] == "storage_asset_auto_scope"
    assert captured["metadata"]["asset_ids"] == ["games-lib"]
    assert captured["metadata"]["blueprint_id"] == "retro-box"


def test_start_container_passes_effective_auto_scope_to_approval(monkeypatch):
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
            get_secrets_for_blueprint=lambda *args, **kwargs: [],
            get_secret_value=lambda *args, **kwargs: "",
            log_secret_access=lambda *args, **kwargs: None,
        ),
    )

    import container_commander.engine as engine
    import container_commander.storage_assets as assets
    from container_commander.models import Blueprint, NetworkMode

    monkeypatch.setattr(
        assets,
        "get_asset",
        lambda asset_id: {
            "id": asset_id,
            "path": "/data/games",
            "published_to_commander": True,
            "default_mode": "ro",
        },
    )

    request_calls = {}
    monkeypatch.setattr(engine, "resolve_blueprint", lambda blueprint_id: Blueprint(
        id="retro-box",
        name="Retro Box",
        image="busybox:latest",
        network=NetworkMode.FULL,
    ))
    monkeypatch.setattr(engine, "_emit_ws_activity", lambda *args, **kwargs: None)

    with pytest.raises(engine.PendingApprovalError):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("container_commander.storage_scope.validate_blueprint_mounts", lambda bp: (True, "ok"))
            mp.setattr("container_commander.storage_scope.get_scope", lambda name: None)
            mp.setattr(
                "container_commander.storage_scope.upsert_scope",
                lambda name, roots, approved_by="user", metadata=None: {
                    "name": name,
                    "roots": roots,
                    "approved_by": approved_by,
                    "metadata": metadata or {},
                },
            )
            mp.setattr("container_commander.mount_utils.ensure_bind_mount_host_dirs", lambda mounts: None)
            mp.setattr("container_commander.approval.evaluate_deploy_risk", lambda bp: {
                "requires_approval": True,
                "reasons": ["Container requests internet access (network: full)"],
                "risk_flags": ["network_full"],
                "cap_add": [],
                "security_opt": [],
                "cap_drop": [],
                "read_only_rootfs": False,
            })
            def fake_request_approval(**kwargs):
                request_calls["kwargs"] = kwargs
                return SimpleNamespace(id="appr-asset")
            mp.setattr(
                "container_commander.approval.request_approval",
                fake_request_approval,
            )
            engine.start_container(
                "retro-box",
                mount_overrides=[{"asset_id": "games-lib", "container": "/games", "type": "bind"}],
                storage_scope_override="__auto__",
            )

    kwargs = request_calls["kwargs"]
    assert kwargs["mount_overrides"][0]["asset_id"] == "games-lib"
    assert kwargs["storage_scope_override"].startswith("deploy_auto_asset_retro-box_games-lib_")


def test_start_container_auto_scopes_asset_mounts_even_when_blueprint_has_existing_scope(monkeypatch):
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
            get_secrets_for_blueprint=lambda *args, **kwargs: [],
            get_secret_value=lambda *args, **kwargs: "",
            log_secret_access=lambda *args, **kwargs: None,
        ),
    )

    import container_commander.engine as engine
    import container_commander.storage_assets as assets
    from container_commander.models import Blueprint, NetworkMode

    monkeypatch.setattr(
        assets,
        "get_asset",
        lambda asset_id: {
            "id": asset_id,
            "path": "/mnt/games/services/gaming-station-games/data",
            "published_to_commander": True,
            "default_mode": "rw",
        },
    )

    request_calls = {}
    monkeypatch.setattr(engine, "resolve_blueprint", lambda blueprint_id: Blueprint(
        id="gaming-station",
        name="Gaming Station",
        image="busybox:latest",
        network=NetworkMode.FULL,
        storage_scope="gaming-station-host-bridge",
    ))
    monkeypatch.setattr(engine, "_emit_ws_activity", lambda *args, **kwargs: None)

    with pytest.raises(engine.PendingApprovalError):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("container_commander.storage_scope.validate_blueprint_mounts", lambda bp: (True, "ok"))
            mp.setattr("container_commander.storage_scope.get_scope", lambda name: None)
            mp.setattr(
                "container_commander.storage_scope.upsert_scope",
                lambda name, roots, approved_by="user", metadata=None: {
                    "name": name,
                    "roots": roots,
                    "approved_by": approved_by,
                    "metadata": metadata or {},
                },
            )
            mp.setattr("container_commander.mount_utils.ensure_bind_mount_host_dirs", lambda mounts: None)
            mp.setattr("container_commander.approval.evaluate_deploy_risk", lambda bp: {
                "requires_approval": True,
                "reasons": ["Container requests internet access (network: full)"],
                "risk_flags": ["network_full"],
                "cap_add": [],
                "security_opt": [],
                "cap_drop": [],
                "read_only_rootfs": False,
            })

            def fake_request_approval(**kwargs):
                request_calls["kwargs"] = kwargs
                return SimpleNamespace(id="appr-asset-existing-scope")

            mp.setattr("container_commander.approval.request_approval", fake_request_approval)
            engine.start_container(
                "gaming-station",
                mount_overrides=[{"asset_id": "gaming-station-games", "container": "/games", "type": "bind"}],
            )

    kwargs = request_calls["kwargs"]
    assert kwargs["mount_overrides"][0]["asset_id"] == "gaming-station-games"
    assert kwargs["storage_scope_override"].startswith("deploy_auto_asset_gaming-station_gaming-station-games_")
