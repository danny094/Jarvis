from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import utils.ollama_endpoint_manager as mgr


class _FakeNotFound(Exception):
    pass


class _FakeAPIError(Exception):
    pass


class _FakeContainer:
    def __init__(
        self,
        name: str,
        labels: dict | None = None,
        status: str = "running",
        exec_outputs: dict | None = None,
    ):
        self.name = name
        self.id = f"id-{name}"
        self.labels = labels or {}
        self.status = status
        self.exec_outputs = dict(exec_outputs or {})
        self.attrs = {"NetworkSettings": {"Networks": {"big-bear-lobe-chat_default": {}}}}

    def reload(self):
        return None

    def start(self):
        self.status = "running"

    def stop(self, timeout: int = 20):
        self.status = "exited"

    def exec_run(self, cmd, stdout=True, stderr=False):
        if isinstance(cmd, (list, tuple)):
            key = " ".join(str(x) for x in cmd)
        else:
            key = str(cmd)
        out = self.exec_outputs.get(key)
        if out is None:
            return (127, b"")
        return out


class _FakeContainersAPI:
    def __init__(self):
        self.by_name: dict[str, _FakeContainer] = {}
        self.last_run_kwargs: dict | None = None

    def get(self, name: str):
        c = self.by_name.get(name)
        if c is None:
            raise _FakeNotFound(name)
        return c

    def run(self, **kwargs):
        self.last_run_kwargs = dict(kwargs)
        c = _FakeContainer(
            name=kwargs["name"],
            labels=kwargs.get("labels", {}),
            status="running",
        )
        self.by_name[c.name] = c
        return c


class _FakeVolumesAPI:
    def __init__(self):
        self.names = set()

    def get(self, name: str):
        if name not in self.names:
            raise _FakeNotFound(name)
        return {"name": name}

    def create(self, name: str, labels=None):
        self.names.add(name)
        return {"name": name, "labels": labels or {}}


class _FakeClient:
    def __init__(self):
        self.containers = _FakeContainersAPI()
        self.volumes = _FakeVolumesAPI()


class _FakeSettings:
    def __init__(self, initial=None):
        self.settings = dict(initial or {})

    def get(self, key, default=None):
        return self.settings.get(key, default)

    def set(self, key, value):
        self.settings[key] = value


class TestComputeRouting(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(
            os.environ,
            {
                "TRION_COMPUTE_NETWORK": "big-bear-lobe-chat_default",
                "TRION_OLLAMA_GPU_IDS": "0,1",
                "TRION_OLLAMA_INSTANCE_PREFIX": "trion-ollama",
                "TRION_OLLAMA_GPU_BACKEND": "nvidia",
            },
            clear=False,
        )
        self._env.start()
        self.fake_settings = _FakeSettings()
        self._settings_patch = patch.object(mgr, "settings", self.fake_settings)
        self._settings_patch.start()

    def tearDown(self):
        self._settings_patch.stop()
        self._env.stop()

    def test_allowed_targets_includes_cpu_and_gpus(self):
        fake_client = _FakeClient()
        with patch.object(mgr, "_docker_client", return_value=fake_client), \
             patch.object(mgr, "_docker_exceptions", return_value=(_FakeNotFound, _FakeAPIError)):
            allowed = mgr.allowed_targets()
        self.assertIn("auto", allowed)
        self.assertIn("cpu", allowed)
        self.assertIn("gpu0", allowed)
        self.assertIn("gpu1", allowed)

    def test_update_layer_routing_persists_merged_values(self):
        self.fake_settings.settings["layer_routing"] = {"thinking": "auto", "control": "auto"}
        fake_client = _FakeClient()
        with patch.object(mgr, "_docker_client", return_value=fake_client), \
             patch.object(mgr, "_docker_exceptions", return_value=(_FakeNotFound, _FakeAPIError)):
            saved = mgr.update_layer_routing({"output": "cpu"})

        self.assertEqual(saved["output"], "cpu")
        self.assertEqual(self.fake_settings.settings["layer_routing"]["output"], "cpu")
        self.assertEqual(saved["thinking"], "auto")

    def test_validate_routing_targets_rejects_unknown_target(self):
        with self.assertRaises(mgr.ComputeValidationError):
            mgr.validate_routing_targets({"thinking": "gpu99"}, allowed=["auto", "cpu", "gpu0"])

    def test_resolve_auto_prefers_healthy_gpu(self):
        layer = {"thinking": "auto", "control": "auto", "output": "auto", "tool_selector": "auto", "embedding": "auto"}
        snapshot = {
            "instances": [
                {"id": "cpu", "target": "cpu", "running": True, "health": {"ok": True}, "endpoint": "http://cpu:11434"},
                {"id": "gpu0", "target": "gpu", "running": True, "health": {"ok": True}, "endpoint": "http://gpu0:11434"},
            ]
        }
        resolved = mgr.resolve_layer_routing(layer_routing=layer, instances_snapshot=snapshot)
        self.assertEqual(resolved["thinking"]["effective_target"], "gpu0")
        self.assertEqual(resolved["embedding"]["effective_endpoint"], "http://gpu0:11434")

    def test_resolve_gpu_falls_back_to_cpu_when_unavailable(self):
        layer = {"thinking": "gpu0", "control": "auto", "output": "auto", "tool_selector": "auto", "embedding": "auto"}
        snapshot = {
            "instances": [
                {"id": "cpu", "target": "cpu", "running": True, "health": {"ok": True}, "endpoint": "http://cpu:11434"},
                {"id": "gpu0", "target": "gpu", "running": False, "health": {"ok": False}, "endpoint": "http://gpu0:11434"},
            ]
        }
        resolved = mgr.resolve_layer_routing(layer_routing=layer, instances_snapshot=snapshot)
        self.assertEqual(resolved["thinking"]["effective_target"], "cpu")
        self.assertEqual(resolved["thinking"]["fallback_reason"], "requested_unavailable")

    def test_backend_auto_detects_amd_when_rocm_devices_exist(self):
        with patch.dict(os.environ, {"TRION_OLLAMA_GPU_BACKEND": "auto"}, clear=False), \
             patch("utils.ollama_endpoint_manager.os.path.exists", side_effect=lambda p: p in {"/dev/kfd", "/dev/dri"}), \
             patch("utils.ollama_endpoint_manager.shutil.which", return_value=None):
            backend = mgr._resolve_gpu_backend()
        self.assertEqual(backend, "amd")

    def test_detect_gpu_name_nvidia_from_nvidia_smi(self):
        c = _FakeContainer(
            "trion-ollama-gpu0",
            exec_outputs={
                "nvidia-smi --query-gpu=index,name --format=csv,noheader,nounits": (
                    0,
                    b"0, NVIDIA GeForce RTX 4090\n",
                ),
            },
        )
        tpl = mgr.InstanceTemplate(
            instance_id="gpu0",
            target="gpu",
            container_name="trion-ollama-gpu0",
            endpoint="http://trion-ollama-gpu0:11434",
            image="ollama/ollama:latest",
            network="big-bear-lobe-chat_default",
            model_volume="trion-ollama-models",
            gpu_device_id="0",
            gpu_backend="nvidia",
        )
        name = mgr._detect_gpu_name(c, tpl)
        self.assertEqual(name, "NVIDIA GeForce RTX 4090")

    def test_detect_gpu_name_amd_from_rocm_json(self):
        c = _FakeContainer(
            "trion-ollama-gpu0",
            exec_outputs={
                "rocm-smi --showproductname --json": (
                    0,
                    b'{"card0":{"Card series":"AMD Radeon RX 7900 XTX"}}',
                ),
            },
        )
        tpl = mgr.InstanceTemplate(
            instance_id="gpu0",
            target="gpu",
            container_name="trion-ollama-gpu0",
            endpoint="http://trion-ollama-gpu0:11434",
            image="ollama/ollama:latest",
            network="big-bear-lobe-chat_default",
            model_volume="trion-ollama-models",
            gpu_device_id="0",
            gpu_backend="amd",
        )
        name = mgr._detect_gpu_name(c, tpl)
        self.assertEqual(name, "AMD Radeon RX 7900 XTX")

    def test_detect_host_nvidia_name_from_proc_information(self):
        info = (
            "Model: NVIDIA GeForce RTX 2060 SUPER\n"
            "Device Minor: 0\n"
        )
        with patch("utils.ollama_endpoint_manager.os.path.isdir", return_value=True), \
             patch("utils.ollama_endpoint_manager.os.listdir", return_value=["0000:01:00.0"]), \
             patch("builtins.open", unittest.mock.mock_open(read_data=info)):
            name = mgr._detect_host_nvidia_name("0")
        self.assertEqual(name, "NVIDIA GeForce RTX 2060 SUPER")

    def test_describe_instance_includes_gpu_name_capability(self):
        fake_client = _FakeClient()
        fake_client.containers.by_name["trion-ollama-gpu0"] = _FakeContainer(
            "trion-ollama-gpu0",
            labels={
                "trion.ollama.endpoint_manager": "true",
                "trion.ollama.instance_id": "gpu0",
            },
            status="running",
        )
        tpl = mgr.InstanceTemplate(
            instance_id="gpu0",
            target="gpu",
            container_name="trion-ollama-gpu0",
            endpoint="http://trion-ollama-gpu0:11434",
            image="ollama/ollama:latest",
            network="big-bear-lobe-chat_default",
            model_volume="trion-ollama-models",
            gpu_device_id="0",
            gpu_backend="nvidia",
        )
        with patch.object(mgr, "_check_endpoint_health", return_value={"ok": True}), \
             patch.object(mgr, "_get_gpu_name_cached", return_value="NVIDIA GeForce RTX 4090"):
            desc = mgr._describe_instance(fake_client, tpl)
        self.assertEqual(desc["capability"]["gpu_name"], "NVIDIA GeForce RTX 4090")

    def test_describe_instance_uses_host_fallback_when_container_not_running(self):
        fake_client = _FakeClient()
        tpl = mgr.InstanceTemplate(
            instance_id="gpu0",
            target="gpu",
            container_name="trion-ollama-gpu0",
            endpoint="http://trion-ollama-gpu0:11434",
            image="ollama/ollama:latest",
            network="big-bear-lobe-chat_default",
            model_volume="trion-ollama-models",
            gpu_device_id="0",
            gpu_backend="nvidia",
        )
        with patch.object(mgr, "_docker_exceptions", return_value=(_FakeNotFound, _FakeAPIError)), \
             patch.object(mgr, "_get_host_gpu_name_cached", return_value="NVIDIA GeForce RTX 2060 SUPER"):
            desc = mgr._describe_instance(fake_client, tpl)
        self.assertEqual(desc["status"], "not_created")
        self.assertEqual(desc["capability"]["gpu_name"], "NVIDIA GeForce RTX 2060 SUPER")


class TestComputeLifecycle(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(
            os.environ,
            {
                "TRION_COMPUTE_NETWORK": "big-bear-lobe-chat_default",
                "TRION_OLLAMA_GPU_IDS": "0",
                "TRION_OLLAMA_INSTANCE_PREFIX": "trion-ollama",
                "TRION_OLLAMA_GPU_BACKEND": "nvidia",
            },
            clear=False,
        )
        self._env.start()
        self.fake_client = _FakeClient()
        self.p_client = patch.object(mgr, "_docker_client", return_value=self.fake_client)
        self.p_exc = patch.object(mgr, "_docker_exceptions", return_value=(_FakeNotFound, _FakeAPIError))
        self.p_client.start()
        self.p_exc.start()

    def tearDown(self):
        self.p_exc.stop()
        self.p_client.stop()
        self._env.stop()

    def test_start_unknown_instance_raises_validation(self):
        with self.assertRaises(mgr.ComputeValidationError):
            mgr.start_instance("gpu9")

    def test_start_conflicts_with_foreign_container(self):
        self.fake_client.containers.by_name["trion-ollama-cpu"] = _FakeContainer(
            "trion-ollama-cpu",
            labels={"foo": "bar"},
            status="running",
        )
        with self.assertRaises(mgr.ComputeConflictError):
            mgr.start_instance("cpu")

    def test_start_existing_managed_running_is_idempotent(self):
        self.fake_client.containers.by_name["trion-ollama-cpu"] = _FakeContainer(
            "trion-ollama-cpu",
            labels={
                "trion.ollama.endpoint_manager": "true",
                "trion.ollama.instance_id": "cpu",
            },
            status="running",
        )
        out = mgr.start_instance("cpu")
        self.assertTrue(out["started"])
        self.assertTrue(out["idempotent"])
        self.assertEqual(out["instance"]["status"], "running")

    def test_start_new_instance_creates_container_and_volume(self):
        out = mgr.start_instance("cpu")
        self.assertTrue(out["started"])
        self.assertFalse(out["idempotent"])
        self.assertIn("trion-ollama-cpu", self.fake_client.containers.by_name)
        self.assertIn("trion-ollama-models", self.fake_client.volumes.names)

    def test_start_new_amd_gpu_instance_sets_rocm_devices_and_env(self):
        with patch.dict(os.environ, {"TRION_OLLAMA_GPU_BACKEND": "amd"}, clear=False), \
             patch("utils.ollama_endpoint_manager.os.path.exists", side_effect=lambda p: p in {"/dev/kfd", "/dev/dri"}):
            out = mgr.start_instance("gpu0")
        self.assertTrue(out["started"])
        run_kwargs = self.fake_client.containers.last_run_kwargs or {}
        self.assertIn("/dev/kfd:/dev/kfd", run_kwargs.get("devices", []))
        self.assertIn("/dev/dri:/dev/dri", run_kwargs.get("devices", []))
        self.assertEqual(run_kwargs.get("group_add"), ["video", "render"])
        env = run_kwargs.get("environment", {})
        self.assertEqual(env.get("HSA_VISIBLE_DEVICES"), "0")
        self.assertEqual(env.get("ROCR_VISIBLE_DEVICES"), "0")
        self.assertEqual(env.get("HIP_VISIBLE_DEVICES"), "0")

    def test_stop_missing_instance_is_idempotent(self):
        out = mgr.stop_instance("cpu")
        self.assertTrue(out["stopped"])
        self.assertTrue(out["idempotent"])
        self.assertEqual(out["instance"]["status"], "not_created")


class TestRuntimeRoutesSource(unittest.TestCase):
    def test_compute_endpoints_present_in_runtime_routes(self):
        path = os.path.join(_REPO_ROOT, "adapters", "admin-api", "runtime_routes.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('/api/runtime/compute/instances', src)
        self.assertIn('/api/runtime/compute/routing', src)


if __name__ == "__main__":
    unittest.main()
