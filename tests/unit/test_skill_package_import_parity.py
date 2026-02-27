from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_SKILL_SERVER_DIR = os.path.join(_REPO_ROOT, "mcp-servers", "skill-server")
_TOOL_EXECUTOR_DIR = os.path.join(_REPO_ROOT, "tool_executor")

if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
if _SKILL_SERVER_DIR not in sys.path:
    sys.path.insert(0, _SKILL_SERVER_DIR)
if _TOOL_EXECUTOR_DIR not in sys.path:
    sys.path.insert(0, _TOOL_EXECUTOR_DIR)


def _load_skill_runner_module():
    spec = importlib.util.spec_from_file_location(
        "skill_runner_parity_test_mod",
        os.path.join(_TOOL_EXECUTOR_DIR, "engine", "skill_runner.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_mini_control_module():
    # Minimal stubs for optional skill-server dependencies.
    sys.modules.setdefault("cim_rag", MagicMock(cim_kb=MagicMock()))
    sys.modules.setdefault(
        "skill_cim_light",
        MagicMock(
            SkillCIMLight=MagicMock,
            ValidationResult=MagicMock,
            get_skill_cim=MagicMock(return_value=MagicMock()),
        ),
    )

    spec = importlib.util.spec_from_file_location(
        "mini_control_parity_test_mod",
        os.path.join(_SKILL_SERVER_DIR, "mini_control_layer.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSkillRunnerAllowlistParity(unittest.TestCase):
    def test_allowlist_modules_include_package_policy_import_names(self):
        mod = _load_skill_runner_module()

        required_modules = {
            "qrcode",
            "httpx",
            "numpy",
            "pandas",
            "bs4",          # beautifulsoup4
            "PIL",          # pillow
            "dateutil",     # python-dateutil
            "dotenv",       # python-dotenv
            "Levenshtein",  # python-levenshtein
        }
        for module_name in required_modules:
            self.assertIn(module_name, mod.ALLOWED_MODULES)


class TestMiniControlPackageMapping(unittest.TestCase):
    def test_module_to_package_name_mapping(self):
        mod = _load_mini_control_module()

        self.assertEqual(mod.SkillMiniControl._module_to_package_name("bs4"), "beautifulsoup4")
        self.assertEqual(mod.SkillMiniControl._module_to_package_name("PIL"), "pillow")
        self.assertEqual(mod.SkillMiniControl._module_to_package_name("dateutil"), "python-dateutil")
        self.assertEqual(mod.SkillMiniControl._module_to_package_name("dotenv"), "python-dotenv")
        self.assertEqual(mod.SkillMiniControl._module_to_package_name("Levenshtein"), "python-levenshtein")
        self.assertEqual(mod.SkillMiniControl._module_to_package_name("qrcode"), "qrcode")

    def test_check_missing_packages_uses_distribution_names(self):
        mod = _load_mini_control_module()
        control = mod.SkillMiniControl(cim=MagicMock())

        code = "\n".join(
            [
                "import bs4",
                "from PIL import Image",
                "import dateutil.parser",
                "import qrcode",
            ]
        )

        # All normalized package names are present -> nothing missing.
        control._get_installed_packages = AsyncMock(
            return_value={"beautifulsoup4", "pillow", "python-dateutil", "qrcode"}
        )
        missing = asyncio.run(control._check_missing_packages(code))
        self.assertEqual(missing, [])

        # Without installed set -> normalized package names are reported.
        control._get_installed_packages = AsyncMock(return_value=set())
        missing = asyncio.run(control._check_missing_packages(code))
        self.assertIn("beautifulsoup4", missing)
        self.assertIn("pillow", missing)
        self.assertIn("python-dateutil", missing)
        self.assertIn("qrcode", missing)

