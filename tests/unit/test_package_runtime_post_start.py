from types import SimpleNamespace

from container_commander.models import Blueprint


class _ExecResult:
    def __init__(self, exit_code=0, output=b""):
        self.exit_code = exit_code
        self.output = output


def test_filestash_runtime_post_start_merges_managed_local_connections(monkeypatch):
    from container_commander import package_runtime_post_start as hooks

    monkeypatch.setattr(
        hooks,
        "_list_broker_assets",
        lambda published_only, source_kinds: [
            {
                "id": "containers",
                "label": "containers",
                "path": "/data/services/containers",
                "default_mode": "rw",
                "source_kind": "service_dir",
            }
        ],
    )

    calls = []

    class _Container:
        short_id = "abc123"

        def exec_run(self, cmd, demux=False):
            calls.append(cmd)
            script = cmd[-1]
            if "cat /app/data/state/config/config.json" in script:
                return _ExecResult(
                    0,
                    b'{"general":{"secret_key":"x"},"connections":[{"label":"WebDav","type":"webdav"}]}',
                )
            return _ExecResult(0, b"")

    manifest = {
        "runtime_storage_views": {
            "broker_assets": {
                "enabled": True,
                "published_only": True,
                "source_kinds": ["service_dir"],
                "container_root": "/srv/storage-broker",
                "connection_mode": "filestash_local",
                "label_prefix": "TRION /",
            }
        }
    }

    hooks.run_package_runtime_post_start("filestash", Blueprint(id="filestash", name="Filestash"), manifest, _Container())

    write_script = calls[-1][-1]
    assert "TRION / containers" in write_script
    assert "/srv/storage-broker/containers" in write_script
    assert '"type": "local"' in write_script
