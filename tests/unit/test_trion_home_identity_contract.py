from utils.trion_home_identity import load_home_identity, evaluate_home_status


class _Container:
    def __init__(self, container_id: str, blueprint_id: str, status: str, name: str = ""):
        self.container_id = container_id
        self.blueprint_id = blueprint_id
        self.status = status
        self.name = name


def test_home_identity_bootstrap_creates_default_file(tmp_path):
    identity_path = tmp_path / "config" / "home_identity.json"
    identity = load_home_identity(identity_path=str(identity_path), create_if_missing=True)

    assert identity_path.exists()
    assert identity.get("container_id") == "trion-home"
    assert identity.get("capabilities", {}).get("importance_threshold") == 0.72


def test_evaluate_home_status_reports_connected_for_single_running_home():
    identity = {"container_id": "trion-home"}
    containers = [
        _Container("abc123", "trion-home", "running", "trion_home"),
        _Container("def456", "python-sandbox", "running", "py"),
    ]

    status = evaluate_home_status(containers, identity=identity)

    assert status["status"] == "connected"
    assert status["home_container_id"] == "abc123"
    assert status["error_code"] == ""


def test_evaluate_home_status_reports_offline_when_missing():
    identity = {"container_id": "trion-home"}
    containers = [_Container("def456", "python-sandbox", "running", "py")]

    status = evaluate_home_status(containers, identity=identity)

    assert status["status"] == "offline"
    assert status["error_code"] == "home_container_missing"
