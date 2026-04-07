from types import SimpleNamespace
import sys
import types


def test_run_package_host_runtime_checks_detects_active_sunshine_service(monkeypatch):
    import container_commander.host_runtime_discovery as discovery
    monkeypatch.setattr(discovery, "HOST_COMPANION_HOME", "/home/hostuser")

    manifest = {
        "host_runtime_requirements": {
            "sunshine": {
                "required": False,
                "systemd_user_units": ["sunshine-host.service"],
                "systemd_user_globs": ["sunshine*.service"],
                "binary_candidates": ["/usr/bin/sunshine"],
                "message_when_found": "Sunshine auf dem Host gefunden",
                "message_when_missing": "Sunshine auf dem Host nicht gefunden",
            }
        }
    }

    def _fake_helper(path, payload, timeout=30):
        assert timeout == 30
        if path == "/v1/systemctl-user":
            args = list(payload.get("args") or [])
            if args[:2] == ["is-active", "sunshine-host.service"]:
                return {"ok": True, "returncode": 0, "stdout": "active", "stderr": ""}
            if args and args[0] == "show":
                return {
                    "ok": True,
                    "returncode": 0,
                    "stdout": (
                        "ExecStart={ path=/usr/bin/sunshine ; argv[]=/usr/bin/sunshine ; }\n"
                        "FragmentPath=/home/hostuser/.config/systemd/user/sunshine-host.service\n"
                        "UnitFileState=enabled\n"
                    ),
                    "stderr": "",
                }
            if args and args[0] in {"list-units", "list-unit-files"}:
                return {"ok": False, "returncode": 1, "stdout": "", "stderr": ""}
        if path == "/v1/path-exists":
            return {"exists": False}
        raise AssertionError(f"unexpected helper call: {path} {payload}")

    monkeypatch.setattr(discovery, "_helper_post_json", _fake_helper)

    result = discovery.run_package_host_runtime_checks("gaming-station", manifest=manifest)

    assert result["ok"] is True
    assert result["warnings"] == []
    assert len(result["infos"]) == 1
    check = result["infos"][0]
    assert check["name"] == "host_runtime_sunshine"
    assert check["ok"] is True
    assert check["detail"]["message"] == "Sunshine auf dem Host gefunden"
    assert check["detail"]["service_name"] == "sunshine-host.service"
    assert check["detail"]["binary_path"] == "/usr/bin/sunshine"


def test_run_package_host_runtime_checks_warns_when_sunshine_missing(monkeypatch):
    import container_commander.host_runtime_discovery as discovery

    manifest = {
        "host_runtime_requirements": {
            "sunshine": {
                "required": False,
                "systemd_user_units": ["sunshine-host.service"],
                "systemd_user_globs": ["sunshine*.service"],
                "binary_candidates": ["/usr/bin/sunshine"],
                "message_when_found": "Sunshine auf dem Host gefunden",
                "message_when_missing": "Sunshine auf dem Host nicht gefunden",
            }
        }
    }

    def _fake_helper(path, payload, timeout=30):
        assert timeout == 30
        if path == "/v1/systemctl-user":
            args = list(payload.get("args") or [])
            if args and args[0] in {"is-active", "show", "list-units", "list-unit-files"}:
                return {"ok": False, "returncode": 1, "stdout": "", "stderr": ""}
        if path == "/v1/path-exists":
            return {"exists": False}
        raise AssertionError(f"unexpected helper call: {path} {payload}")

    monkeypatch.setattr(discovery, "_helper_post_json", _fake_helper)

    result = discovery.run_package_host_runtime_checks("gaming-station", manifest=manifest)

    assert result["ok"] is True
    assert result["infos"] == []
    assert len(result["warnings"]) == 1
    check = result["warnings"][0]
    assert check["name"] == "host_runtime_sunshine"
    assert check["ok"] is False
    assert check["detail"]["message"] == "Sunshine auf dem Host nicht gefunden"
    assert check["detail"]["required"] is False


def test_setup_host_companion_skips_mutation_for_discovery_only(monkeypatch):
    docker_mod = types.ModuleType("docker")
    docker_errors = types.ModuleType("docker.errors")
    docker_errors.APIError = RuntimeError
    docker_mod.errors = docker_errors
    monkeypatch.setitem(sys.modules, "docker", docker_mod)
    monkeypatch.setitem(sys.modules, "docker.errors", docker_errors)

    import container_commander.engine_start_support as start_support
    import container_commander.host_companions as companions

    calls = []
    manifest = {"host_companion": {"mode": "discovery_only"}}

    monkeypatch.setattr(companions, "get_package_manifest", lambda package_id: manifest)
    monkeypatch.setattr(companions, "ensure_host_companion", lambda package_id, overwrite=False: calls.append(("ensure", package_id, overwrite)))
    monkeypatch.setattr(
        companions,
        "ensure_package_storage_scope",
        lambda package_id, blueprint=None, manifest=None: calls.append(("scope", package_id, blueprint, manifest)),
    )

    bp = SimpleNamespace(storage_scope="gaming-station-host-bridge")
    result = start_support.setup_host_companion("gaming-station", bp)

    assert result is manifest
    assert calls == [("scope", "gaming-station", bp, manifest)]
