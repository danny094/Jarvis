"""
Filestash blueprint helpers.

Seeds a first-class `filestash` blueprint as a lightweight reference service
for the generic Storage-Broker -> runtime-hardware -> container mount flow.
"""

from __future__ import annotations

def ensure_filestash_blueprint() -> None:
    from .blueprint_store import create_blueprint, get_blueprint, update_blueprint
    from .models import Blueprint, MountDef, NetworkMode, ResourceLimits

    blueprint_id = "filestash"
    desired = Blueprint(
        id=blueprint_id,
        name="Filestash",
        description=(
            "Webbasierter File Manager als Referenzdienst fuer die generische "
            "Storage-Broker-, runtime-hardware- und Simple-Blueprint-Integration."
        ),
        image="machines/filestash:latest",
        image_digest="",
        resources=ResourceLimits(
            cpu_limit="1.0",
            memory_limit="512m",
            memory_swap="1g",
            timeout_seconds=0,
            pids_limit=128,
        ),
        mounts=[
            MountDef(host="filestash_state", container="/app/data/state", type="volume", mode="rw"),
        ],
        network=NetworkMode.BRIDGE,
        ports=["8334:8334/tcp"],
        environment={
            "TRION_FILESTASH_CONNECTIONS_JSON": "[]",
            "TRION_FILESTASH_STORAGE_ROOT": "/srv/storage-broker",
        },
        healthcheck={
            "test": [
                "CMD",
                "sh",
                "-c",
                "wget -q -O - http://127.0.0.1:8334/ >/dev/null 2>&1 || curl -fsS http://127.0.0.1:8334/ >/dev/null",
            ],
            "interval_seconds": 20,
            "timeout_seconds": 5,
            "retries": 5,
            "ready_timeout_seconds": 90,
        },
        tags=["storage", "files", "reference", "web"],
        icon="🗂",
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
