"""
Runtime Hardware blueprint helpers.

This module seeds a first-class `runtime-hardware` blueprint that builds the
standalone v0 service image from source files stored in the repository.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from textwrap import dedent
from typing import Dict


_DOCKERFILE_B64_CHUNK_SIZE = 12000


def _service_source_root() -> Path:
    override = str(os.environ.get("RUNTIME_HARDWARE_SOURCE_ROOT", "")).strip()
    if override:
        return Path(override)
    container_path = Path("/app/adapters/runtime-hardware")
    if container_path.exists():
        return container_path
    return Path(__file__).resolve().parents[1] / "adapters" / "runtime-hardware"


def _service_file_map() -> Dict[str, str]:
    return {
        "requirements.txt": "requirements.txt",
        "main.py": "main.py",
        "runtime_hardware/__init__.py": "runtime_hardware/__init__.py",
        "runtime_hardware/api.py": "runtime_hardware/api.py",
        "runtime_hardware/models.py": "runtime_hardware/models.py",
        "runtime_hardware/planner.py": "runtime_hardware/planner.py",
        "runtime_hardware/store.py": "runtime_hardware/store.py",
        "runtime_hardware/connectors/__init__.py": "runtime_hardware/connectors/__init__.py",
        "runtime_hardware/connectors/base.py": "runtime_hardware/connectors/base.py",
        "runtime_hardware/connectors/container_connector.py": "runtime_hardware/connectors/container_connector.py",
        "runtime_hardware/connectors/container_display.py": "runtime_hardware/connectors/container_display.py",
        "runtime_hardware/connectors/container_storage_discovery.py": "runtime_hardware/connectors/container_storage_discovery.py",
    }


def _load_service_sources() -> Dict[str, str]:
    root = _service_source_root()
    payload: Dict[str, str] = {}
    missing = []
    for target, rel_path in _service_file_map().items():
        source = root / rel_path
        if not source.exists():
            missing.append(str(source))
            continue
        payload[target] = source.read_text(encoding="utf-8")
    if missing:
        raise RuntimeError(f"runtime_hardware_source_missing: {', '.join(missing)}")
    return payload


def _chunk_ascii(value: str, *, size: int = _DOCKERFILE_B64_CHUNK_SIZE) -> list[str]:
    text = str(value or "")
    if not text:
        return [""]
    return [text[index:index + size] for index in range(0, len(text), size)]


def runtime_hardware_dockerfile() -> str:
    files = {
        target: base64.b64encode(content.encode("utf-8")).decode("ascii")
        for target, content in _load_service_sources().items()
    }
    files_json = json.dumps(files, ensure_ascii=True, sort_keys=True)
    write_script = dedent(
        f"""
        import base64
        import json
        from pathlib import Path

        files = json.loads({files_json!r})
        for target, content_b64 in files.items():
            path = Path("/app") / target
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(content_b64))
        Path("/app/data/config").mkdir(parents=True, exist_ok=True)
        Path("/app/data/state").mkdir(parents=True, exist_ok=True)
        """
    ).strip()
    write_script_b64 = base64.b64encode(write_script.encode("utf-8")).decode("ascii")
    write_script_b64_chunks = _chunk_ascii(write_script_b64)
    chunk_env_lines = "\n".join(
        f'ENV RUNTIME_HARDWARE_WRITE_SCRIPT_B64_{index:03d}="{chunk}"'
        for index, chunk in enumerate(write_script_b64_chunks)
    )
    chunk_var_names = ", ".join(
        repr(f"RUNTIME_HARDWARE_WRITE_SCRIPT_B64_{index:03d}")
        for index in range(len(write_script_b64_chunks))
    )
    return dedent(
        f"""
        FROM python:3.12-slim

        WORKDIR /app

        {chunk_env_lines}

        RUN python3 -c "import base64, os; exec(base64.b64decode(''.join(os.environ[name] for name in [{chunk_var_names}])).decode('utf-8'))"

        RUN pip install --no-cache-dir -r /app/requirements.txt

        EXPOSE 8420

        CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8420", "--log-level", "info"]
        """
    ).strip()


def ensure_runtime_hardware_blueprint() -> None:
    from .blueprint_store import create_blueprint, get_blueprint, update_blueprint
    from .models import Blueprint, MountDef, NetworkMode, ResourceLimits
    from .storage_scope import upsert_scope

    blueprint_id = "runtime-hardware"
    scope_name = "runtime-hardware"
    scope_roots = [
        {"path": "/data/services/runtime-hardware/config", "mode": "rw"},
        {"path": "/data/services/runtime-hardware/data", "mode": "rw"},
        {"path": "/sys", "mode": "ro"},
        {"path": "/run/udev", "mode": "ro"},
        {"path": "/dev", "mode": "ro"},
        {"path": "/proc", "mode": "ro"},
        {"path": "/var/run/docker.sock", "mode": "rw"},
    ]
    upsert_scope(
        scope_name,
        scope_roots,
        approved_by="system",
        metadata={"origin": "runtime_hardware_blueprint", "system_service": True},
    )

    desired = Blueprint(
        id=blueprint_id,
        name="Runtime Hardware Service",
        description="Generischer Hardware-, Capability- und Attachment-Planungsdienst fuer Jarvis Runtime-Connectoren.",
        dockerfile=runtime_hardware_dockerfile(),
        image="",
        image_digest="",
        resources=ResourceLimits(
            cpu_limit="1.0",
            memory_limit="768m",
            memory_swap="1g",
            timeout_seconds=0,
            pids_limit=256,
        ),
        mounts=[
            MountDef(host="/data/services/runtime-hardware/config", container="/app/data/config", mode="rw"),
            MountDef(host="/data/services/runtime-hardware/data", container="/app/data/state", mode="rw"),
            MountDef(host="/sys", container="/sys", mode="ro"),
            MountDef(host="/run/udev", container="/run/udev", mode="ro"),
            MountDef(host="/dev", container="/dev", mode="ro"),
            MountDef(host="/proc", container="/host_proc", mode="ro"),
            MountDef(host="/var/run/docker.sock", container="/var/run/docker.sock", mode="rw"),
        ],
        storage_scope=scope_name,
        network=NetworkMode.BRIDGE,
        ports=["8420:8420/tcp"],
        environment={
            "LOG_LEVEL": "INFO",
            "RUNTIME_HARDWARE_CONFIG_DIR": "/app/data/config",
            "RUNTIME_HARDWARE_STATE_DIR": "/app/data/state",
        },
        healthcheck={
            "test": [
                "CMD",
                "python3",
                "-c",
                "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8420/health', timeout=2)",
            ],
            "interval_seconds": 15,
            "timeout_seconds": 5,
            "retries": 3,
            "ready_timeout_seconds": 60,
        },
        tags=["system", "hardware", "runtime", "inventory"],
        icon="🧩",
    )

    existing = get_blueprint(blueprint_id)
    if existing:
        updates = {}
        desired_dump = desired.model_dump()
        existing_dump = existing.model_dump()
        for key, value in desired_dump.items():
            if existing_dump.get(key) != value:
                updates[key] = value
        if updates:
            update_blueprint(blueprint_id, updates)
        return

    create_blueprint(desired)
