from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
BROKER_ROOT = ROOT / "mcp-servers" / "storage-broker"
if str(BROKER_ROOT) not in sys.path:
    sys.path.insert(0, str(BROKER_ROOT))

from storage_broker_mcp import policy as sb_policy
from storage_broker_mcp import provisioner as sb_provisioner
from storage_broker_mcp.models import PolicyConfig, ValidationResult


def test_validate_path_accepts_managed_base_from_saved_policy(monkeypatch):
    monkeypatch.setattr(
        sb_policy,
        "_load",
        lambda: {
            "external_default_policy": "read_only",
            "unknown_mount_default": "blocked",
            "dry_run_default": True,
            "blacklist_extra": [],
            "managed_bases": ["/mnt/trion-data"],
            "zone_overrides": {},
            "policy_overrides": {},
        },
    )

    result = sb_policy.validate_path("/mnt/trion-data/services/sdd")

    assert result.valid is True
    assert result.policy_state == "managed_rw"
    assert result.zone == "managed_services"


def test_provisioner_prefers_saved_managed_base_when_env_empty(monkeypatch):
    monkeypatch.setattr(
        sb_provisioner,
        "get_policy",
        lambda: PolicyConfig(managed_bases=["/mnt/trion-data"]),
    )
    monkeypatch.setattr(
        sb_provisioner,
        "validate_path",
        lambda path: ValidationResult(
            path=path,
            real_path=path,
            valid=True,
            policy_state="managed_rw",
            zone="managed_services",
            reason="path is within managed zone",
        ),
    )

    result = sb_provisioner.create_service_storage("sdd", "managed_services", dry_run=True)

    assert result.ok is True
    assert result.target_base == "/mnt/trion-data/services/sdd"
    assert "/mnt/trion-data/services/sdd/config" in result.paths_to_create


def test_provisioner_uses_host_helper_for_apply_and_listing(monkeypatch):
    calls = []

    def _fake_post(path, payload, timeout=30):
        calls.append((path, payload, timeout))
        if path == "/v1/path-exists":
            return {"ok": True, "exists": payload["path"] == "/DATA/AppData"}
        if path == "/v1/mkdirs":
            return {"ok": True, "paths": payload["paths"]}
        if path == "/v1/ensure-symlink":
            return {"ok": True, "link_path": payload["link_path"]}
        if path == "/v1/listdir":
            return {"ok": True, "entries": ["/mnt/trion-data/services/gaming-station"]}
        raise AssertionError(path)

    monkeypatch.setattr(
        sb_provisioner,
        "get_policy",
        lambda: PolicyConfig(managed_bases=["/mnt/trion-data"]),
    )
    monkeypatch.setattr(
        sb_provisioner,
        "validate_path",
        lambda path: ValidationResult(
            path=path,
            real_path=path,
            valid=True,
            policy_state="managed_rw",
            zone="managed_services",
            reason="path is within managed zone",
        ),
    )
    monkeypatch.setattr(sb_provisioner, "_host_helper_post", _fake_post)

    result = sb_provisioner.create_service_storage("gaming-station", "managed_services", dry_run=False)

    assert result.ok is True
    assert result.created == [
        "/mnt/trion-data/services/gaming-station",
        "/mnt/trion-data/services/gaming-station/config",
        "/mnt/trion-data/services/gaming-station/data",
        "/mnt/trion-data/services/gaming-station/logs",
    ]
    assert result.aliases_created == ["/DATA/AppData/TRION/gaming-station"]

    paths = sb_provisioner.list_managed_paths()
    assert paths == ["/mnt/trion-data/services/gaming-station"]
    assert calls[0][0] == "/v1/path-exists"
    assert calls[1][0] == "/v1/mkdirs"
    assert calls[2][0] == "/v1/mkdirs"
    assert calls[3][0] == "/v1/ensure-symlink"
    assert calls[4][0] == "/v1/listdir"


def test_provisioner_targets_explicit_managed_base_when_requested(monkeypatch):
    monkeypatch.setattr(
        sb_provisioner,
        "validate_path",
        lambda path: ValidationResult(
            path=path,
            real_path=path,
            valid=True,
            policy_state="managed_rw",
            zone="managed_services",
            reason="path is within managed zone",
        ),
    )

    result = sb_provisioner.create_service_storage(
        "gaming-station-games",
        "managed_services",
        dry_run=True,
        base_path="/mnt/games",
    )

    assert result.ok is True
    assert result.base_path == "/mnt/games"
    assert result.target_base == "/mnt/games/services/gaming-station-games"


def test_provisioner_apply_forwards_owner_and_group_to_host_helper(monkeypatch):
    calls = []

    def _fake_post(path, payload, timeout=30):
        calls.append((path, payload, timeout))
        if path == "/v1/path-exists":
            return {"ok": True, "exists": False}
        if path == "/v1/mkdirs":
            return {"ok": True, "paths": payload["paths"]}
        return {"ok": True}

    monkeypatch.setattr(
        sb_provisioner,
        "validate_path",
        lambda path: ValidationResult(
            path=path,
            real_path=path,
            valid=True,
            policy_state="managed_rw",
            zone="managed_services",
            reason="path is within managed zone",
        ),
    )
    monkeypatch.setattr(sb_provisioner, "_host_helper_post", _fake_post)

    result = sb_provisioner.create_service_storage(
        "gaming-station-games",
        "managed_services",
        dry_run=False,
        base_path="/mnt/games",
        owner="1000",
        group="1000",
    )

    assert result.ok is True
    mkdir_call = next(payload for path, payload, _ in calls if path == "/v1/mkdirs")
    assert mkdir_call["owner"] == "1000"
    assert mkdir_call["group"] == "1000"
