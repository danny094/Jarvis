from container_commander import blueprint_store
from container_commander.models import Blueprint


def test_blueprint_store_persists_and_resolves_hardware_intents(monkeypatch, tmp_path):
    db_path = tmp_path / "commander.db"
    monkeypatch.setattr(blueprint_store, "DB_PATH", str(db_path))
    monkeypatch.setattr(blueprint_store, "_INIT_DONE", False)

    parent = blueprint_store.create_blueprint(
        Blueprint(
            id="parent-hw",
            name="Parent HW",
            hardware_intents=[
                {
                    "resource_id": "container::device::/dev/uinput",
                    "target_type": "container",
                    "target_id": "",
                    "attachment_mode": "attach",
                    "policy": {"mode": "rw"},
                    "requested_by": "seed",
                }
            ],
        )
    )
    assert parent.hardware_intents[0].resource_id == "container::device::/dev/uinput"

    child = blueprint_store.create_blueprint(
        Blueprint(
            id="child-hw",
            name="Child HW",
            extends="parent-hw",
            hardware_intents=[
                {
                    "resource_id": "container::input::/dev/input/event21",
                    "target_type": "container",
                    "target_id": "",
                    "attachment_mode": "attach",
                    "policy": {"preferred": True},
                    "requested_by": "test",
                }
            ],
        )
    )
    assert child.hardware_intents[0].requested_by == "test"

    reloaded = blueprint_store.get_blueprint("child-hw")
    assert reloaded is not None
    assert reloaded.hardware_intents[0].resource_id == "container::input::/dev/input/event21"

    resolved = blueprint_store.resolve_blueprint("child-hw")
    assert resolved is not None
    resource_ids = [item.resource_id for item in resolved.hardware_intents]
    assert "container::device::/dev/uinput" in resource_ids
    assert "container::input::/dev/input/event21" in resource_ids
