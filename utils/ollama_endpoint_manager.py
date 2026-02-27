"""
utils/ollama_endpoint_manager.py

Managed lifecycle for dedicated Ollama compute instances:
- cpu
- gpu0, gpu1, ...

This module is intentionally strict:
- only pre-defined templates are allowed
- no arbitrary command/image/network input from API callers
"""
from __future__ import annotations

import json
import os
import time
import threading
import shutil
import glob
import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

import requests

from utils.settings import settings


# ─────────────────────────────────────────────────────────────────────────────
# Public constants
# ─────────────────────────────────────────────────────────────────────────────

ROLES: Tuple[str, ...] = ("thinking", "control", "output", "tool_selector", "embedding")

_LABEL_MANAGER = "trion.ollama.endpoint_manager"
_LABEL_INSTANCE = "trion.ollama.instance_id"
_HEALTH_TTL_SECONDS = float(os.getenv("TRION_OLLAMA_HEALTH_TTL", "5"))
_GPU_NAME_TTL_SECONDS = float(os.getenv("TRION_OLLAMA_GPU_NAME_TTL", "30"))


# ─────────────────────────────────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────────────────────────────────

class ComputeValidationError(ValueError):
    pass


class ComputeConflictError(RuntimeError):
    pass


class ComputeDependencyError(RuntimeError):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Template model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class InstanceTemplate:
    instance_id: str
    target: str  # "cpu" | "gpu"
    container_name: str
    endpoint: str
    image: str
    network: str
    model_volume: str
    gpu_device_id: Optional[str] = None
    gpu_backend: Optional[str] = None  # "nvidia" | "amd" | None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

_health_cache_lock = threading.Lock()
_health_cache: Dict[str, Dict[str, Any]] = {}
_gpu_name_cache_lock = threading.Lock()
_gpu_name_cache: Dict[str, Dict[str, Any]] = {}
_host_gpu_name_cache_lock = threading.Lock()
_host_gpu_name_cache: Dict[str, Dict[str, Any]] = {}


def _docker_client():
    try:
        from container_commander.engine import get_client
        return get_client()
    except Exception as exc:
        raise ComputeDependencyError(f"Docker unavailable: {exc}") from exc


def _docker_exceptions():
    try:
        from docker.errors import NotFound, APIError
        return NotFound, APIError
    except Exception:
        class _DummyNotFound(Exception):
            pass
        class _DummyAPIError(Exception):
            pass
        return _DummyNotFound, _DummyAPIError


def _dedupe_keep_order(values: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for v in values:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _parse_gpu_device_ids() -> List[str]:
    enabled = os.getenv("TRION_OLLAMA_ENABLE_GPU", "true").strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return []

    raw = os.getenv("TRION_OLLAMA_GPU_IDS", "0,1,2").strip()
    if not raw:
        return []
    ids = [x.strip() for x in raw.split(",") if x.strip()]
    ids = [x for x in ids if x.isdigit()]
    return _dedupe_keep_order(ids)


def _detect_nvidia_runtime() -> bool:
    if any(os.path.exists(p) for p in ("/dev/nvidiactl", "/dev/nvidia0")):
        return True
    return bool(shutil.which("nvidia-smi"))


def _detect_amd_runtime() -> bool:
    if os.path.exists("/dev/kfd"):
        return True
    if os.path.exists("/dev/dri"):
        return True
    return bool(shutil.which("rocm-smi"))


def _resolve_gpu_backend() -> str:
    """
    Resolve GPU backend for managed Ollama containers.
    Supported values: nvidia | amd | auto.
    """
    raw = os.getenv("TRION_OLLAMA_GPU_BACKEND", "auto").strip().lower()
    if raw in {"nvidia", "amd"}:
        return raw
    # auto-detect path
    if _detect_nvidia_runtime():
        return "nvidia"
    if _detect_amd_runtime():
        return "amd"
    # Keep legacy behavior as default fallback.
    return "nvidia"


def _detect_network(client) -> str:
    forced = os.getenv("TRION_COMPUTE_NETWORK", "").strip()
    if forced:
        return forced

    # Try to inherit the current container network.
    this_container_id = os.getenv("HOSTNAME", "").strip()
    if this_container_id:
        try:
            c = client.containers.get(this_container_id)
            nets = c.attrs.get("NetworkSettings", {}).get("Networks", {}) or {}
            if nets:
                return list(nets.keys())[0]
        except Exception:
            pass

    return "big-bear-lobe-chat_default"


def _build_templates(client=None) -> Dict[str, InstanceTemplate]:
    client = client or _docker_client()
    network = _detect_network(client)
    gpu_backend = _resolve_gpu_backend()
    image = os.getenv("TRION_OLLAMA_IMAGE", "ollama/ollama:latest").strip()
    if not image:
        image = "ollama/ollama:latest"
    model_volume = os.getenv("TRION_OLLAMA_MODELS_VOLUME", "trion-ollama-models").strip() or "trion-ollama-models"
    prefix = os.getenv("TRION_OLLAMA_INSTANCE_PREFIX", "trion-ollama").strip() or "trion-ollama"

    templates: Dict[str, InstanceTemplate] = {
        "cpu": InstanceTemplate(
            instance_id="cpu",
            target="cpu",
            container_name=f"{prefix}-cpu",
            endpoint=f"http://{prefix}-cpu:11434",
            image=image,
            network=network,
            model_volume=model_volume,
        )
    }

    for gpu_id in _parse_gpu_device_ids():
        instance_id = f"gpu{gpu_id}"
        container_name = f"{prefix}-{instance_id}"
        templates[instance_id] = InstanceTemplate(
            instance_id=instance_id,
            target="gpu",
            container_name=container_name,
            endpoint=f"http://{container_name}:11434",
            image=image,
            network=network,
            model_volume=model_volume,
            gpu_device_id=gpu_id,
            gpu_backend=gpu_backend,
        )
    return templates


def allowed_targets(client=None) -> List[str]:
    templates = _build_templates(client=client)
    ordered = ["cpu"] + sorted([k for k in templates.keys() if k != "cpu"], key=lambda k: (len(k), k))
    return ["auto"] + ordered


def _check_endpoint_health(endpoint: str, timeout_s: float = 1.5) -> Dict[str, Any]:
    now = time.monotonic()
    with _health_cache_lock:
        cached = _health_cache.get(endpoint)
        if cached and (now - float(cached.get("ts", 0))) < _HEALTH_TTL_SECONDS:
            return dict(cached["data"])

    data = {
        "ok": False,
        "status_code": None,
        "error": None,
        "checked_at": int(time.time()),
    }
    try:
        resp = requests.get(f"{endpoint}/api/version", timeout=timeout_s)
        data["status_code"] = int(resp.status_code)
        data["ok"] = bool(resp.status_code < 500)
        if not data["ok"]:
            data["error"] = f"http_{resp.status_code}"
    except Exception as exc:
        data["error"] = str(exc)

    with _health_cache_lock:
        _health_cache[endpoint] = {"ts": now, "data": dict(data)}
    return data


def _exec_in_container(container, cmd: List[str]) -> Tuple[int, str]:
    try:
        res = container.exec_run(cmd, stdout=True, stderr=False)
    except Exception:
        return 127, ""

    exit_code = None
    output = ""
    if hasattr(res, "exit_code"):
        exit_code = int(getattr(res, "exit_code", 127))
        raw_out = getattr(res, "output", b"")
    else:
        try:
            exit_code, raw_out = res
            exit_code = int(exit_code)
        except Exception:
            return 127, ""

    if isinstance(raw_out, bytes):
        output = raw_out.decode("utf-8", errors="ignore")
    elif isinstance(raw_out, str):
        output = raw_out
    else:
        output = str(raw_out or "")
    return exit_code if exit_code is not None else 127, output


def _parse_nvidia_name(output: str, gpu_id: Optional[str]) -> Optional[str]:
    lines = [ln.strip() for ln in (output or "").splitlines() if ln.strip()]
    if not lines:
        return None
    for ln in lines:
        parts = [p.strip() for p in ln.split(",", 1)]
        if len(parts) < 2:
            continue
        idx, name = parts[0], parts[1]
        if gpu_id is not None and idx == str(gpu_id):
            return name
    # Fallback: first parsed name
    for ln in lines:
        parts = [p.strip() for p in ln.split(",", 1)]
        if len(parts) >= 2 and parts[1]:
            return parts[1]
    return None


def _parse_amd_name(output: str) -> Optional[str]:
    raw = (output or "").strip()
    if not raw:
        return None

    # Try JSON format first.
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            for v in parsed.values():
                if isinstance(v, dict):
                    for k in ("Card series", "Product Name", "Card model"):
                        name = v.get(k)
                        if isinstance(name, str) and name.strip():
                            return name.strip()
    except Exception:
        pass

    # Text fallback: use first useful value after ":".
    for ln in raw.splitlines():
        ln = ln.strip()
        if ":" not in ln:
            continue
        key, val = ln.split(":", 1)
        key = key.strip().lower()
        val = val.strip()
        if not val:
            continue
        if any(token in key for token in ("card series", "product", "name", "gpu")):
            return val
    return None


def _parse_nvidia_proc_info(output: str) -> Optional[str]:
    for ln in (output or "").splitlines():
        ln = ln.strip()
        if ln.lower().startswith("model:"):
            val = ln.split(":", 1)[1].strip()
            if val:
                return val
    return None


def _detect_gpu_name(container, template: InstanceTemplate) -> Optional[str]:
    if template.target != "gpu":
        return None
    backend = (template.gpu_backend or "nvidia").strip().lower()
    gpu_id = str(template.gpu_device_id) if template.gpu_device_id is not None else None

    if backend == "amd":
        code, out = _exec_in_container(container, ["rocm-smi", "--showproductname", "--json"])
        if code == 0:
            name = _parse_amd_name(out)
            if name:
                return name
        code, out = _exec_in_container(container, ["rocm-smi", "--showproductname"])
        if code == 0:
            name = _parse_amd_name(out)
            if name:
                return name
        code, out = _exec_in_container(
            container,
            ["sh", "-lc", "for f in /sys/class/drm/card*/device/product_name; do [ -r \"$f\" ] && cat \"$f\"; done"],
        )
        if code == 0:
            name = _parse_amd_name(out)
            if name:
                return name
        return None

    # NVIDIA default
    code, out = _exec_in_container(
        container,
        ["nvidia-smi", "--query-gpu=index,name", "--format=csv,noheader,nounits"],
    )
    if code == 0:
        name = _parse_nvidia_name(out, gpu_id)
        if name:
            return name
    code, out = _exec_in_container(container, ["sh", "-lc", "cat /proc/driver/nvidia/gpus/*/information"])
    if code == 0:
        name = _parse_nvidia_proc_info(out)
        if name:
            return name
    return None


def _get_gpu_name_cached(container, template: InstanceTemplate) -> Optional[str]:
    if template.target != "gpu":
        return None

    key = f"{template.instance_id}:{template.container_name}"
    now = time.monotonic()
    with _gpu_name_cache_lock:
        cached = _gpu_name_cache.get(key)
        if cached and (now - float(cached.get("ts", 0.0))) < _GPU_NAME_TTL_SECONDS:
            return cached.get("name")

    name = _detect_gpu_name(container, template)
    with _gpu_name_cache_lock:
        _gpu_name_cache[key] = {"ts": now, "name": name}
    return name


def _detect_host_nvidia_name(gpu_id: Optional[str]) -> Optional[str]:
    base = "/proc/driver/nvidia/gpus"
    if not os.path.isdir(base):
        return None

    entries: List[Tuple[Optional[str], str]] = []
    for gpu_dir in sorted(os.listdir(base)):
        info_path = os.path.join(base, gpu_dir, "information")
        try:
            with open(info_path, "r", encoding="utf-8", errors="ignore") as fh:
                raw = fh.read()
        except Exception:
            continue

        model = None
        minor = None
        for ln in raw.splitlines():
            if ":" not in ln:
                continue
            key, val = ln.split(":", 1)
            key = key.strip().lower()
            val = val.strip()
            if key == "model" and val:
                model = val
            elif key == "device minor" and val:
                minor = val
        if model:
            entries.append((minor, model))

    if not entries:
        return None

    gid = str(gpu_id).strip() if gpu_id is not None else ""
    if gid:
        for minor, model in entries:
            if minor == gid:
                return model
        if gid.isdigit():
            idx = int(gid)
            if 0 <= idx < len(entries):
                return entries[idx][1]
        return None
    return entries[0][1]


def _detect_host_amd_name(gpu_id: Optional[str]) -> Optional[str]:
    paths = sorted(glob.glob("/sys/class/drm/card*/device/product_name"))
    if not paths:
        return None

    entries: List[Tuple[Optional[str], str]] = []
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                name = fh.read().strip()
        except Exception:
            continue
        if not name:
            continue
        m = re.search(r"/card(\d+)/", path)
        card_idx = m.group(1) if m else None
        entries.append((card_idx, name))

    if not entries:
        return None

    gid = str(gpu_id).strip() if gpu_id is not None else ""
    if gid:
        for card_idx, name in entries:
            if card_idx == gid:
                return name
        if gid.isdigit():
            idx = int(gid)
            if 0 <= idx < len(entries):
                return entries[idx][1]
        return None
    return entries[0][1]


def _detect_host_gpu_name(template: InstanceTemplate) -> Optional[str]:
    if template.target != "gpu":
        return None
    backend = (template.gpu_backend or "nvidia").strip().lower()
    gpu_id = str(template.gpu_device_id) if template.gpu_device_id is not None else None
    if backend == "amd":
        return _detect_host_amd_name(gpu_id)
    return _detect_host_nvidia_name(gpu_id)


def _get_host_gpu_name_cached(template: InstanceTemplate) -> Optional[str]:
    if template.target != "gpu":
        return None
    key = f"{template.gpu_backend}:{template.gpu_device_id}"
    now = time.monotonic()
    with _host_gpu_name_cache_lock:
        cached = _host_gpu_name_cache.get(key)
        if cached and (now - float(cached.get("ts", 0.0))) < _GPU_NAME_TTL_SECONDS:
            return cached.get("name")

    name = _detect_host_gpu_name(template)
    with _host_gpu_name_cache_lock:
        _host_gpu_name_cache[key] = {"ts": now, "name": name}
    return name


def _is_managed_instance_container(container, expected_instance_id: str) -> bool:
    labels = container.labels or {}
    return (
        labels.get(_LABEL_MANAGER) == "true"
        and labels.get(_LABEL_INSTANCE) == expected_instance_id
    )


def _ensure_models_volume(client, volume_name: str) -> None:
    NotFound, _ = _docker_exceptions()
    try:
        client.volumes.get(volume_name)
        return
    except NotFound:
        client.volumes.create(
            name=volume_name,
            labels={
                _LABEL_MANAGER: "true",
                "trion.managed": "true",
                "trion.ollama.volume": "models",
            },
        )


def _run_kwargs_for_template(template: InstanceTemplate) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {
        "image": template.image,
        "name": template.container_name,
        "detach": True,
        "command": ["ollama", "serve"],
        "network": template.network,
        "volumes": {
            template.model_volume: {"bind": "/root/.ollama", "mode": "rw"}
        },
        "labels": {
            _LABEL_MANAGER: "true",
            _LABEL_INSTANCE: template.instance_id,
            "trion.managed": "true",
            "trion.ollama.target": template.target,
        },
        "restart_policy": {"Name": "unless-stopped"},
    }
    if template.target == "gpu":
        backend = (template.gpu_backend or "nvidia").strip().lower()
        if backend == "amd":
            devices: List[str] = []
            if os.path.exists("/dev/kfd"):
                devices.append("/dev/kfd:/dev/kfd")
            if os.path.exists("/dev/dri"):
                devices.append("/dev/dri:/dev/dri")
            if not devices:
                raise ComputeDependencyError("AMD runtime unavailable: missing /dev/kfd and /dev/dri")
            kwargs["devices"] = devices
            kwargs["group_add"] = ["video", "render"]
            env = dict(kwargs.get("environment") or {})
            if template.gpu_device_id is not None:
                gpu_id = str(template.gpu_device_id)
                env["HSA_VISIBLE_DEVICES"] = gpu_id
                env["ROCR_VISIBLE_DEVICES"] = gpu_id
                env["HIP_VISIBLE_DEVICES"] = gpu_id
            kwargs["environment"] = env
        else:
            if template.gpu_device_id is None:
                raise ComputeValidationError("GPU template missing gpu_device_id")
            try:
                from docker.types import DeviceRequest
                kwargs["device_requests"] = [
                    DeviceRequest(
                        device_ids=[str(template.gpu_device_id)],
                        capabilities=[["gpu"]],
                    )
                ]
            except Exception as exc:
                raise ComputeDependencyError(f"GPU runtime unavailable: {exc}") from exc
    return kwargs


def _template_for_id(instance_id: str, client=None) -> InstanceTemplate:
    templates = _build_templates(client=client)
    tpl = templates.get(instance_id)
    if tpl is None:
        raise ComputeValidationError(
            f"Unknown instance '{instance_id}'. Allowed: {', '.join(allowed_targets(client=client)[1:])}"
        )
    return tpl


def _describe_instance(client, template: InstanceTemplate) -> Dict[str, Any]:
    NotFound, _ = _docker_exceptions()
    container = None
    exists = False
    managed = False
    status = "not_created"
    running = False
    container_id = None

    try:
        container = client.containers.get(template.container_name)
        exists = True
        container.reload()
        container_id = container.id
        running = (container.status == "running")
        managed = _is_managed_instance_container(container, template.instance_id)
        if not managed:
            status = "foreign"
        else:
            status = "running" if running else "stopped"
    except NotFound:
        pass

    health = {
        "ok": False,
        "status_code": None,
        "error": "not_running",
        "checked_at": int(time.time()),
    }
    if running and managed:
        health = _check_endpoint_health(template.endpoint)
    gpu_name = None
    if running and managed and template.target == "gpu" and container is not None:
        gpu_name = _get_gpu_name_cached(container, template)
    if template.target == "gpu" and not gpu_name:
        gpu_name = _get_host_gpu_name_cached(template)

    return {
        "id": template.instance_id,
        "target": template.target,
        "endpoint": template.endpoint,
        "container_name": template.container_name,
        "container_id": container_id,
        "status": status,
        "exists": exists,
        "managed": managed,
        "running": running,
        "health": health,
        "capability": {
            "gpu": template.target == "gpu",
            "gpu_device_id": template.gpu_device_id,
            "gpu_backend": template.gpu_backend,
            "gpu_name": gpu_name,
        },
        "template": {
            "image": template.image,
            "network": template.network,
            "model_volume": template.model_volume,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public lifecycle API
# ─────────────────────────────────────────────────────────────────────────────

def list_instances() -> Dict[str, Any]:
    client = _docker_client()
    templates = _build_templates(client=client)
    instances = [_describe_instance(client, templates[k]) for k in sorted(templates.keys())]
    return {
        "instances": instances,
        "count": len(instances),
        "allowed_targets": allowed_targets(client=client),
    }


def start_instance(instance_id: str) -> Dict[str, Any]:
    client = _docker_client()
    template = _template_for_id(instance_id, client=client)
    NotFound, APIError = _docker_exceptions()

    try:
        container = client.containers.get(template.container_name)
        if not _is_managed_instance_container(container, template.instance_id):
            raise ComputeConflictError(
                f"Container name '{template.container_name}' exists but is not manager-owned"
            )
        container.reload()
        if container.status != "running":
            container.start()
        return {
            "started": True,
            "idempotent": True,
            "instance": _describe_instance(client, template),
        }
    except NotFound:
        pass
    except APIError as exc:
        raise ComputeDependencyError(f"Docker API error while starting '{instance_id}': {exc}") from exc

    _ensure_models_volume(client, template.model_volume)
    kwargs = _run_kwargs_for_template(template)
    try:
        client.containers.run(**kwargs)
    except APIError as exc:
        raise ComputeDependencyError(f"Docker API error while creating '{instance_id}': {exc}") from exc
    except Exception as exc:
        raise ComputeDependencyError(f"Failed to create '{instance_id}': {exc}") from exc

    return {
        "started": True,
        "idempotent": False,
        "instance": _describe_instance(client, template),
    }


def stop_instance(instance_id: str) -> Dict[str, Any]:
    client = _docker_client()
    template = _template_for_id(instance_id, client=client)
    NotFound, APIError = _docker_exceptions()

    try:
        container = client.containers.get(template.container_name)
    except NotFound:
        return {
            "stopped": True,
            "idempotent": True,
            "instance": _describe_instance(client, template),
        }

    if not _is_managed_instance_container(container, template.instance_id):
        raise ComputeConflictError(
            f"Container name '{template.container_name}' exists but is not manager-owned"
        )

    try:
        container.reload()
        if container.status == "running":
            container.stop(timeout=20)
    except APIError as exc:
        raise ComputeDependencyError(f"Docker API error while stopping '{instance_id}': {exc}") from exc

    return {
        "stopped": True,
        "idempotent": False,
        "instance": _describe_instance(client, template),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Routing config (persisted via SettingsManager)
# ─────────────────────────────────────────────────────────────────────────────

def _default_layer_routing() -> Dict[str, str]:
    return {role: "auto" for role in ROLES}


def _parse_layer_routing(raw: Any) -> Dict[str, str]:
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}
    out = _default_layer_routing()
    for role in ROLES:
        v = data.get(role)
        if isinstance(v, str) and v.strip():
            out[role] = v.strip()
    return out


def get_layer_routing() -> Dict[str, str]:
    return _parse_layer_routing(settings.get("layer_routing", {}))


def _choose_auto_target(instances_by_id: Dict[str, Dict[str, Any]]) -> Optional[str]:
    healthy_gpu = [
        iid for iid, meta in instances_by_id.items()
        if meta["target"] == "gpu" and meta["running"] and meta["health"]["ok"]
    ]
    if healthy_gpu:
        return sorted(healthy_gpu, key=lambda x: (len(x), x))[0]

    cpu_meta = instances_by_id.get("cpu")
    if cpu_meta and cpu_meta["running"] and cpu_meta["health"]["ok"]:
        return "cpu"

    running_gpu = [
        iid for iid, meta in instances_by_id.items()
        if meta["target"] == "gpu" and meta["running"]
    ]
    if running_gpu:
        return sorted(running_gpu, key=lambda x: (len(x), x))[0]

    if cpu_meta and cpu_meta["running"]:
        return "cpu"
    return None


def resolve_layer_routing(
    layer_routing: Optional[Dict[str, str]] = None,
    instances_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    if instances_snapshot is None:
        instances_snapshot = list_instances()
    inst_list = instances_snapshot.get("instances", [])
    instances_by_id = {it["id"]: it for it in inst_list}
    layer_routing = layer_routing or get_layer_routing()

    resolved: Dict[str, Dict[str, Any]] = {}
    for role in ROLES:
        requested = (layer_routing.get(role) or "auto").strip()
        fallback_reason = None
        effective = requested
        if requested == "auto":
            effective = _choose_auto_target(instances_by_id)
            fallback_reason = None if effective else "no_target_available"
        else:
            req_meta = instances_by_id.get(requested)
            if not req_meta:
                effective = None
                fallback_reason = "unknown_target"
            elif not (req_meta.get("running") and req_meta.get("health", {}).get("ok")):
                cpu_meta = instances_by_id.get("cpu")
                if requested.startswith("gpu") and cpu_meta and cpu_meta.get("running") and cpu_meta.get("health", {}).get("ok"):
                    effective = "cpu"
                    fallback_reason = "requested_unavailable"
                else:
                    effective = None
                    fallback_reason = "requested_unavailable"

        eff_meta = instances_by_id.get(effective) if effective else None
        resolved[role] = {
            "requested_target": requested,
            "effective_target": effective,
            "effective_endpoint": eff_meta.get("endpoint") if eff_meta else None,
            "effective_health": eff_meta.get("health") if eff_meta else None,
            "fallback_reason": fallback_reason,
        }
    return resolved


def validate_routing_targets(layer_routing: Dict[str, str], allowed: List[str]) -> None:
    allowed_set = set(allowed)
    for role in ROLES:
        target = (layer_routing.get(role) or "auto").strip()
        if target not in allowed_set:
            raise ComputeValidationError(
                f"Invalid target '{target}' for role '{role}'. Allowed: {', '.join(allowed)}"
            )


def update_layer_routing(update: Dict[str, Any]) -> Dict[str, Any]:
    current = get_layer_routing()
    next_routing = dict(current)
    for role in ROLES:
        if role in update and isinstance(update[role], str) and update[role].strip():
            next_routing[role] = update[role].strip()

    allowed = allowed_targets()
    validate_routing_targets(next_routing, allowed=allowed)
    settings.set("layer_routing", next_routing)
    return next_routing
