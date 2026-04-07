from unittest.mock import MagicMock, patch


def test_blueprint_create_passes_runtime_security_fields_into_blueprint():
    created_blueprints = {}

    class FakeBlueprint:
        def __init__(self, **kw):
            self.__dict__.update(kw)
            self.id = kw.get("id", "test-bp")

    class FakeMountDef:
        def __init__(self, host, container, mode, type):
            self.host = host
            self.container = container
            self.mode = mode
            self.type = type

    class FakeResourceLimits:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class FakeNetworkMode(str):
        def __new__(cls, value):
            return str.__new__(cls, value)

    def fake_is_trusted(_image):
        return True

    def fake_get_bp(_blueprint_id):
        return None

    def fake_create(bp):
        created_blueprints[bp.id] = bp
        return bp

    def fake_evaluate(_bp):
        return {"level": "verified"}

    def fake_sync(_bp, trust_level=None):
        _ = trust_level

    import container_commander.mcp_tools as tools

    with patch.dict("sys.modules", {
        "container_commander.blueprint_store": MagicMock(
            create_blueprint=fake_create,
            get_blueprint=fake_get_bp,
            sync_blueprint_to_graph=fake_sync,
        ),
        "container_commander.models": MagicMock(
            Blueprint=FakeBlueprint,
            MountDef=FakeMountDef,
            ResourceLimits=FakeResourceLimits,
            NetworkMode=FakeNetworkMode,
        ),
        "container_commander.trust": MagicMock(
            is_trusted_image=fake_is_trusted,
            evaluate_blueprint_trust=fake_evaluate,
        ),
    }):
        result = tools._tool_blueprint_create({
            "id": "secure-bp",
            "image": "python:3.12-slim",
            "name": "Secure Blueprint",
            "security_opt": ["seccomp=unconfined"],
            "cap_drop": ["NET_RAW"],
            "read_only_rootfs": True,
        })

    assert result.get("created") is True
    bp = created_blueprints["secure-bp"]
    assert bp.security_opt == ["seccomp=unconfined"]
    assert bp.cap_drop == ["NET_RAW"]
    assert bp.read_only_rootfs is True
