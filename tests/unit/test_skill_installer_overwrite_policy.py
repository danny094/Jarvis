import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _load_skill_installer_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "tool_executor" / "engine" / "skill_installer.py"
    spec = importlib.util.spec_from_file_location("skill_installer_overwrite_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def installer_mod(monkeypatch):
    obs_events = MagicMock()
    obs_events.EventLogger = MagicMock()
    obs_events.EventLogger.emit = MagicMock()
    monkeypatch.setitem(sys.modules, "observability.events", obs_events)
    monkeypatch.setitem(sys.modules, "observability", MagicMock(events=obs_events))
    return _load_skill_installer_module()


def test_overwrite_policy_error_blocks_existing_target(installer_mod, monkeypatch, tmp_path):
    monkeypatch.setenv("SKILL_OVERWRITE_POLICY", "error")
    installer = installer_mod.SkillInstaller(skills_dir=str(tmp_path))

    installer.save_skill(
        name="test_skill",
        code="def run(**k): return {'v': 1}\n",
        manifest_data={"description": "v1", "triggers": []},
        is_draft=False,
    )

    with pytest.raises(FileExistsError):
        installer.save_skill(
            name="test_skill",
            code="def run(**k): return {'v': 2}\n",
            manifest_data={"description": "v2", "triggers": []},
            is_draft=False,
        )


def test_overwrite_policy_archive_preserves_previous_version(installer_mod, monkeypatch, tmp_path):
    monkeypatch.setenv("SKILL_OVERWRITE_POLICY", "archive")
    installer = installer_mod.SkillInstaller(skills_dir=str(tmp_path))

    installer.save_skill(
        name="archive_skill",
        code="def run(**k):\n    return {'v': 1}\n",
        manifest_data={"description": "v1", "triggers": []},
        is_draft=False,
    )

    result = installer.save_skill(
        name="archive_skill",
        code="def run(**k):\n    return {'v': 2}\n",
        manifest_data={"description": "v2", "triggers": []},
        is_draft=False,
    )

    archived_to = result.get("archived_to")
    assert result.get("overwrite_policy") == "archive"
    assert archived_to

    active_main = tmp_path / "archive_skill" / "main.py"
    archived_main = Path(archived_to) / "main.py"
    assert active_main.exists()
    assert archived_main.exists()
    assert "v': 2" in active_main.read_text(encoding="utf-8")
    assert "v': 1" in archived_main.read_text(encoding="utf-8")

    registry_path = tmp_path / "_registry" / "installed.json"
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    assert data["skills"]["archive_skill"]["revision"] == 2
