from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
RUNTIME_HARDWARE_ROOT = ROOT / "adapters" / "runtime-hardware"
if str(RUNTIME_HARDWARE_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_HARDWARE_ROOT))

from runtime_hardware import api as rh_api
from runtime_hardware.models import HardwareResource
from runtime_hardware.store import StateStore


def test_state_store_write_json_returns_empty_on_oserror(monkeypatch, tmp_path):
    store = StateStore(config_dir=str(tmp_path / "config"), state_dir=str(tmp_path / "state"))

    def _raise(*_args, **_kwargs):
        raise OSError(117, "Structure needs cleaning")

    monkeypatch.setattr(Path, "write_text", _raise)

    written = store.write_json("last_resources.json", {"ok": True})

    assert written == ""


def test_runtime_hardware_resources_ignores_state_snapshot_failures(monkeypatch):
    resource = HardwareResource(
        id="container::device::/dev/dri/renderD128",
        kind="device",
        source_connector="container",
        label="GPU",
        host_path="/dev/dri/renderD128",
    )

    class _Connector:
        def list_resources(self):
            return [resource]

    class _Store:
        def write_json(self, _name, _payload):
            raise OSError(117, "Structure needs cleaning")

    monkeypatch.setattr(rh_api, "_connector_or_404", lambda _name: _Connector())
    monkeypatch.setattr(rh_api, "_store", lambda: _Store())

    payload = rh_api.resources("container")

    assert payload["count"] == 1
    assert payload["resources"][0]["id"] == resource.id
