from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_index_wires_cron_app_in_sidebar_launchpad_and_viewport():
    src = _read("adapters/Jarvis/index.html")
    assert 'data-app="cron"' in src
    assert 'id="app-cron"' in src
    assert 'data-action="app:cron"' in src
    assert "./static/css/cron.css" in src


def test_shell_lazy_loads_cron_app():
    src = _read("adapters/Jarvis/js/shell.js")
    assert "cronLoaded" in src
    assert "cron: document.getElementById('app-cron')" in src
    assert "if (appName === 'cron')" in src
    assert "import('./apps/cron.js')" in src
    assert "module.initCronApp" in src


def test_cron_app_calls_autonomy_cron_api():
    src = _read("adapters/Jarvis/js/apps/cron.js")
    assert "/api/autonomy/cron/status" in src
    assert "/api/autonomy/cron/jobs" in src
    assert "/api/autonomy/cron/queue" in src
    assert "/run-now" in src
    assert "/pause" in src
    assert "/resume" in src
    assert "cron-policy-hints" in src
    assert "formatApiError" in src
    assert "resolveConversationId(" in src
    assert "webui-default" not in src
