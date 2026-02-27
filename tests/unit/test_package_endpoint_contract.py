"""
tests/unit/test_package_endpoint_contract.py — C2.5 Package Endpoint Contract
===============================================================================

Covers:
  1. /v1/packages  → existing UI shape preserved ({packages:[{name,version}], allowlist:[...]})
  2. /v1/packages/installed → compat shape ({packages:["pkg1","pkg2",...]})
  3. _parse_packages() handles both list[str] and list[dict{name,...}]
  4. _get_installed_packages() uses /v1/packages/installed (compat, mode=auto)
  5. _get_installed_packages() fallback: /installed→404 → /v1/packages (mode=auto)
  6. _get_installed_packages() fail-closed to _KNOWN_INSTALLED on full error
  7. mode=modern: skips /installed, uses /v1/packages directly
  8. mode=compat: uses /installed, no fallback to /v1/packages
  9. _check_missing_packages returns correct missing list from real endpoint data

All tests use direct async/handler calls — no TestClient (avoids MagicMock await-hang).

Gate: python -m pytest tests/unit/test_package_endpoint_contract.py -q
Expected: ≥ 12 passed, 0 failures
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
import importlib.util
from unittest.mock import AsyncMock, MagicMock, patch

# ── Repo paths ─────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_TOOL_EXECUTOR = os.path.join(_REPO_ROOT, "tool_executor")
_SKILL_SERVER = os.path.join(_REPO_ROOT, "mcp-servers", "skill-server")

if not os.path.isdir(os.path.join(_REPO_ROOT, "tool_executor")):
    _REPO_ROOT = "/DATA/AppData/MCP/Jarvis/Jarvis"
    _TOOL_EXECUTOR = os.path.join(_REPO_ROOT, "tool_executor")
    _SKILL_SERVER = os.path.join(_REPO_ROOT, "mcp-servers", "skill-server")

for p in [_REPO_ROOT, _TOOL_EXECUTOR, _SKILL_SERVER]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ── Load tool_executor/api.py ──────────────────────────────────────────────────

def _load_api_module():
    _control_instance = MagicMock()
    _control_instance.process_request = AsyncMock(
        return_value=MagicMock(action=object(), to_dict=lambda: {"action": "reject"})
    )
    _mcl = MagicMock()
    _mcl.get_mini_control.return_value = _control_instance
    _mcl.SkillRequest = MagicMock
    _mcl.ControlAction = MagicMock()

    _obs_events = MagicMock()
    _obs_events.EventLogger = MagicMock()
    _obs_events.EventLogger.emit = MagicMock()

    for mod_name, mock_obj in [
        ("mini_control_layer", _mcl),
        ("engine.skill_installer", MagicMock()),
        ("engine.skill_runner", MagicMock()),
        ("observability.events", _obs_events),
        ("observability", MagicMock()),
        ("engine", MagicMock()),
    ]:
        sys.modules.setdefault(mod_name, mock_obj)

    spec = importlib.util.spec_from_file_location(
        "tool_executor_api_pkg_test",
        os.path.join(_TOOL_EXECUTOR, "api.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Load mini_control_layer.py ────────────────────────────────────────────────

def _load_mini_control_module():
    for mod_name, mock_obj in [
        ("cim_rag", MagicMock(cim_kb=MagicMock())),
        ("skill_cim_light", MagicMock(
            SkillCIMLight=MagicMock,
            ValidationResult=MagicMock,
            get_skill_cim=MagicMock(return_value=MagicMock()),
        )),
    ]:
        sys.modules.setdefault(mod_name, mock_obj)

    spec = importlib.util.spec_from_file_location(
        "mini_control_layer_pkg_test",
        os.path.join(_SKILL_SERVER, "mini_control_layer.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_api_skip = ""
_api_mod = None
try:
    _api_mod = _load_api_module()
    _HAS_API = True
except Exception as e:
    _HAS_API = False
    _api_skip = f"api.py load failed: {e}"

_mcl_skip = ""
_mcl_mod = None
try:
    _mcl_mod = _load_mini_control_module()
    _HAS_MCL = True
except Exception as e:
    _HAS_MCL = False
    _mcl_skip = f"mini_control_layer.py load failed: {e}"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _pip_mock(packages: list[dict]) -> MagicMock:
    """Mock subprocess.run returning a pip list JSON output."""
    m = MagicMock()
    m.returncode = 0
    m.stdout = json.dumps(packages)
    return m


def _http_mock(url_responses: dict) -> MagicMock:
    """
    Build an async httpx mock that routes GET calls by URL substring.
    url_responses: {"/v1/packages/installed": (status, json_body), ...}
    """
    async def _get(url, **kw):
        for pattern, (status, body) in url_responses.items():
            if pattern in url:
                r = MagicMock()
                r.status_code = status
                r.json.return_value = body
                return r
        r = MagicMock()
        r.status_code = 404
        r.json.return_value = {}
        return r

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=_get)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


# ─────────────────────────────────────────────────────────────────────────────
# Part 1 — Executor endpoint shape tests
# ─────────────────────────────────────────────────────────────────────────────

@unittest.skipUnless(_HAS_API, _api_skip)
class TestPackageEndpointContract(unittest.TestCase):
    """Direct async handler calls — no TestClient."""

    # ── /v1/packages (existing UI endpoint) ───────────────────────────────────

    def test_packages_endpoint_preserves_ui_shape(self):
        """/v1/packages must still return {packages:[{name,version}], allowlist:[...]}."""
        pip_data = [
            {"name": "FastAPI", "version": "0.100.0"},
            {"name": "pydantic", "version": "2.0.0"},
        ]
        with patch("subprocess.run", return_value=_pip_mock(pip_data)):
            result = asyncio.run(_api_mod.list_packages())

        self.assertIn("packages", result)
        self.assertIn("allowlist", result)
        # packages must be list of dicts
        self.assertIsInstance(result["packages"], list)
        self.assertIsInstance(result["packages"][0], dict)
        self.assertIn("name", result["packages"][0])
        self.assertIn("version", result["packages"][0])

    def test_packages_endpoint_has_allowlist(self):
        """allowlist must be present and non-empty."""
        pip_data = [{"name": "httpx", "version": "0.24.0"}]
        with patch("subprocess.run", return_value=_pip_mock(pip_data)):
            result = asyncio.run(_api_mod.list_packages())
        self.assertIsInstance(result["allowlist"], list)
        self.assertGreater(len(result["allowlist"]), 0)

    # ── /v1/packages/installed (new compat endpoint) ──────────────────────────

    def test_installed_endpoint_returns_string_list(self):
        """/v1/packages/installed returns {"packages": ["pkg1", ...]} with lowercase strings."""
        pip_data = [
            {"name": "FastAPI", "version": "0.100.0"},
            {"name": "Pydantic", "version": "2.0.0"},
        ]
        with patch("subprocess.run", return_value=_pip_mock(pip_data)):
            result = asyncio.run(_api_mod.list_installed_packages_compat())

        self.assertIn("packages", result)
        self.assertIsInstance(result["packages"], list)
        # All entries must be strings (not dicts)
        for entry in result["packages"]:
            self.assertIsInstance(entry, str, f"Expected str, got {type(entry)}: {entry}")
        self.assertIn("fastapi", result["packages"])
        self.assertIn("pydantic", result["packages"])

    def test_installed_endpoint_lowercases_names(self):
        """Package names from /v1/packages/installed must be lowercase."""
        pip_data = [{"name": "NumPy", "version": "1.24.0"}]
        with patch("subprocess.run", return_value=_pip_mock(pip_data)):
            result = asyncio.run(_api_mod.list_installed_packages_compat())
        self.assertIn("numpy", result["packages"])
        self.assertNotIn("NumPy", result["packages"])

    def test_installed_endpoint_on_pip_failure_returns_empty_list(self):
        """When pip fails, /v1/packages/installed returns {packages: []} not 500."""
        bad_result = MagicMock()
        bad_result.returncode = 1
        bad_result.stdout = ""
        with patch("subprocess.run", return_value=bad_result):
            result = asyncio.run(_api_mod.list_installed_packages_compat())
        self.assertEqual(result, {"packages": []})

    def test_both_endpoints_use_same_data_source(self):
        """Both endpoints rely on pip list backend (at least one subprocess call each)."""
        pip_data = [{"name": "httpx", "version": "0.24.0"}]
        with patch("subprocess.run", return_value=_pip_mock(pip_data)) as mock_sub:
            asyncio.run(_api_mod.list_packages())
            count_packages = mock_sub.call_count
            asyncio.run(_api_mod.list_installed_packages_compat())
            count_installed = mock_sub.call_count - count_packages
        self.assertGreaterEqual(count_packages, 1)
        self.assertGreaterEqual(count_installed, 1)

    # ── /v1/packages/install (venv-based, PEP668-safe) ───────────────────────

    def test_install_package_uses_executor_venv_helpers(self):
        """Allowlisted package install must go through venv helpers."""
        req = _api_mod.InstallPackageRequest(package="httpx")
        with patch.object(_api_mod, "_ensure_executor_venv", return_value=(True, "")) as p_venv, \
             patch.object(_api_mod, "_install_package_in_executor_venv", return_value=(True, "ok")) as p_install:
            result = asyncio.run(_api_mod.install_package(req))

        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("package"), "httpx")
        p_venv.assert_called_once()
        p_install.assert_called_once_with("httpx")

    def test_install_package_returns_error_when_venv_creation_fails(self):
        """Fail-closed: venv setup error must be returned as install error."""
        req = _api_mod.InstallPackageRequest(package="httpx")
        with patch.object(_api_mod, "_ensure_executor_venv", return_value=(False, "venv failed")) as p_venv, \
             patch.object(_api_mod, "_install_package_in_executor_venv") as p_install:
            result = asyncio.run(_api_mod.install_package(req))

        self.assertFalse(result.get("success"))
        self.assertIn("venv failed", result.get("error", ""))
        p_venv.assert_called_once()
        p_install.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Part 2 — Mini-Control _parse_packages unit tests
# ─────────────────────────────────────────────────────────────────────────────

@unittest.skipUnless(_HAS_MCL, _mcl_skip)
class TestParsePackages(unittest.TestCase):
    """Unit tests for MiniControlLayer._parse_packages (static method)."""

    def _parse(self, pkgs):
        return _mcl_mod.SkillMiniControl._parse_packages(pkgs)

    def test_parses_string_list(self):
        result = self._parse(["httpx", "pydantic", "fastapi"])
        self.assertEqual(result, {"httpx", "pydantic", "fastapi"})

    def test_parses_dict_list(self):
        pkgs = [{"name": "FastAPI", "version": "0.100.0"},
                {"name": "Pydantic", "version": "2.0.0"}]
        result = self._parse(pkgs)
        self.assertIn("fastapi", result)
        self.assertIn("pydantic", result)

    def test_lowercases_string_entries(self):
        result = self._parse(["NumPy", "HTTPX"])
        self.assertIn("numpy", result)
        self.assertIn("httpx", result)

    def test_lowercases_dict_name(self):
        result = self._parse([{"name": "NumPy", "version": "1.24"}])
        self.assertIn("numpy", result)
        self.assertNotIn("NumPy", result)

    def test_skips_empty_strings(self):
        result = self._parse(["", "httpx"])
        self.assertNotIn("", result)
        self.assertIn("httpx", result)

    def test_skips_dict_with_missing_name(self):
        result = self._parse([{"version": "1.0"}, {"name": "httpx"}])
        self.assertIn("httpx", result)
        self.assertEqual(len(result), 1)

    def test_mixed_shapes(self):
        pkgs = ["requests", {"name": "FastAPI", "version": "0.1"}]
        result = self._parse(pkgs)
        self.assertIn("requests", result)
        self.assertIn("fastapi", result)

    def test_empty_list(self):
        self.assertEqual(self._parse([]), set())


# ─────────────────────────────────────────────────────────────────────────────
# Part 3 — _get_installed_packages integration tests
# ─────────────────────────────────────────────────────────────────────────────

@unittest.skipUnless(_HAS_MCL, _mcl_skip)
class TestGetInstalledPackages(unittest.TestCase):
    """Tests for _get_installed_packages with mocked httpx."""

    def _make_instance(self):
        """Minimal SkillMiniControl instance with mocked CIM."""
        mcl_cls = _mcl_mod.SkillMiniControl
        instance = object.__new__(mcl_cls)
        instance.cim = MagicMock()
        instance.skills_dir = MagicMock()
        instance.block_score_threshold = 0.3
        instance.warn_score_threshold = 0.7
        instance.auto_create_threshold = 5
        return instance

    def _run(self, coro):
        return asyncio.run(coro)

    # ── Test: uses /v1/packages/installed (auto mode, default) ────────────────

    def test_uses_compat_endpoint_in_auto_mode(self):
        """mode=auto: /v1/packages/installed 200 → returns its packages."""
        mock_client = _http_mock({
            "/v1/packages/installed": (200, {"packages": ["httpx", "pydantic"]}),
        })
        instance = self._make_instance()
        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch.dict(os.environ, {"EXECUTOR_PACKAGES_ENDPOINT_MODE": "auto"}):
            result = self._run(instance._get_installed_packages())
        self.assertIn("httpx", result)
        self.assertIn("pydantic", result)

    # ── Test 2: fallback auto mode ─────────────────────────────────────────────

    def test_fallback_to_packages_on_installed_404(self):
        """mode=auto: /installed→404 → fallback to /v1/packages → parses dict-list."""
        mock_client = _http_mock({
            "/v1/packages/installed": (404, {}),
            "/v1/packages": (200, {
                "packages": [{"name": "requests", "version": "2.28.0"}],
                "allowlist": [],
            }),
        })
        instance = self._make_instance()
        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch.dict(os.environ, {"EXECUTOR_PACKAGES_ENDPOINT_MODE": "auto"}):
            result = self._run(instance._get_installed_packages())
        self.assertIn("requests", result)

    # ── Test 3: fail-closed to _KNOWN_INSTALLED ────────────────────────────────

    def test_fail_closed_on_full_error(self):
        """When all HTTP calls raise, returns _KNOWN_INSTALLED."""
        async def _raise(*a, **kw):
            raise Exception("network error")

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=_raise)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        instance = self._make_instance()
        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch.dict(os.environ, {"EXECUTOR_PACKAGES_ENDPOINT_MODE": "auto"}):
            result = self._run(instance._get_installed_packages())

        known = _mcl_mod._KNOWN_INSTALLED
        self.assertTrue(result.issuperset(known),
                        f"Should fall back to _KNOWN_INSTALLED, got: {result}")

    # ── Test 4: mode=modern skips /installed ──────────────────────────────────

    def test_mode_modern_skips_compat_endpoint(self):
        """mode=modern: goes directly to /v1/packages, never calls /installed."""
        calls = []

        async def _get(url, **kw):
            calls.append(url)
            if "/v1/packages" in url and "installed" not in url:
                r = MagicMock()
                r.status_code = 200
                r.json.return_value = {
                    "packages": [{"name": "numpy", "version": "1.24"}],
                    "allowlist": [],
                }
                return r
            r = MagicMock()
            r.status_code = 404
            r.json.return_value = {}
            return r

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=_get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        instance = self._make_instance()
        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch.dict(os.environ, {"EXECUTOR_PACKAGES_ENDPOINT_MODE": "modern"}):
            result = self._run(instance._get_installed_packages())

        self.assertIn("numpy", result)
        self.assertTrue(
            all("installed" not in url for url in calls),
            f"mode=modern must not call /installed, but called: {calls}"
        )

    # ── Test 5: mode=compat no fallback ───────────────────────────────────────

    def test_mode_compat_no_fallback_to_packages(self):
        """mode=compat: /installed→404 → returns _KNOWN_INSTALLED, NOT /v1/packages."""
        calls = []

        async def _get(url, **kw):
            calls.append(url)
            r = MagicMock()
            r.status_code = 404
            r.json.return_value = {}
            return r

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=_get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        instance = self._make_instance()
        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch.dict(os.environ, {"EXECUTOR_PACKAGES_ENDPOINT_MODE": "compat"}):
            result = self._run(instance._get_installed_packages())

        known = _mcl_mod._KNOWN_INSTALLED
        self.assertTrue(result.issuperset(known))
        # Must NOT have called /v1/packages (without "installed")
        self.assertFalse(
            any("packages" in url and "installed" not in url for url in calls),
            f"mode=compat must not fall back to /v1/packages, called: {calls}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Part 4 — _check_missing_packages end-to-end
# ─────────────────────────────────────────────────────────────────────────────

@unittest.skipUnless(_HAS_MCL, _mcl_skip)
class TestCheckMissingPackages(unittest.TestCase):
    """Verify _check_missing_packages uses real endpoint data."""

    def _make_instance(self):
        mcl_cls = _mcl_mod.SkillMiniControl
        instance = object.__new__(mcl_cls)
        instance.cim = MagicMock()
        instance.skills_dir = MagicMock()
        instance.block_score_threshold = 0.3
        instance.warn_score_threshold = 0.7
        instance.auto_create_threshold = 5
        return instance

    def test_missing_package_reported_from_endpoint_data(self):
        """Package present in code but absent from endpoint → appears in missing list."""
        # Executor says only 'httpx' is installed
        mock_client = _http_mock({
            "/v1/packages/installed": (200, {"packages": ["httpx"]}),
        })
        code = "import httpx\nimport pandas\nimport numpy"
        instance = self._make_instance()
        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch.dict(os.environ, {"EXECUTOR_PACKAGES_ENDPOINT_MODE": "auto"}):
            missing = asyncio.run(instance._check_missing_packages(code))

        self.assertIn("pandas", missing)
        self.assertIn("numpy", missing)
        self.assertNotIn("httpx", missing)

    def test_no_missing_when_all_installed(self):
        """All third-party packages installed → empty missing list."""
        mock_client = _http_mock({
            "/v1/packages/installed": (200, {"packages": ["httpx", "pandas", "numpy"]}),
        })
        code = "import httpx\nimport pandas\nimport numpy"
        instance = self._make_instance()
        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch.dict(os.environ, {"EXECUTOR_PACKAGES_ENDPOINT_MODE": "auto"}):
            missing = asyncio.run(instance._check_missing_packages(code))
        self.assertEqual(missing, [])

    def test_stdlib_modules_never_flagged_missing(self):
        """stdlib modules (os, json, re, ...) are never in the missing list."""
        mock_client = _http_mock({
            "/v1/packages/installed": (200, {"packages": []}),
        })
        code = "import os\nimport json\nimport re\nimport datetime"
        instance = self._make_instance()
        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch.dict(os.environ, {"EXECUTOR_PACKAGES_ENDPOINT_MODE": "auto"}):
            missing = asyncio.run(instance._check_missing_packages(code))
        self.assertEqual(missing, [], f"stdlib must not appear in missing: {missing}")

    def test_real_endpoint_used_not_permanent_fallback(self):
        """Verify the compat endpoint is actually called (not skipped to fallback)."""
        call_log = []

        async def _get(url, **kw):
            call_log.append(url)
            r = MagicMock()
            r.status_code = 200
            r.json.return_value = {"packages": ["httpx"]}
            return r

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=_get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        code = "import httpx"
        instance = self._make_instance()
        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch.dict(os.environ, {"EXECUTOR_PACKAGES_ENDPOINT_MODE": "auto"}):
            asyncio.run(instance._check_missing_packages(code))

        self.assertTrue(
            any("packages" in url for url in call_log),
            f"Expected HTTP call to packages endpoint, got: {call_log}"
        )


if __name__ == "__main__":
    unittest.main()
