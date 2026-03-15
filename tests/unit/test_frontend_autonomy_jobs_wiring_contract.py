from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_api_js_exposes_autonomy_job_helpers():
    src = _read("adapters/Jarvis/static/js/api.js")
    assert "export async function submitAutonomyJob" in src
    assert "export async function getAutonomyJobStatus" in src
    assert "export async function cancelAutonomyJob" in src
    assert "export async function retryAutonomyJob" in src
    assert "export async function getAutonomyJobsStats" in src
    assert "export async function waitForAutonomyJob" in src
    assert "/api/autonomous/jobs" in src
    assert "/api/autonomous/jobs-stats" in src
    assert "resolveConversationId(" in src
    assert 'conversationId = "webui-default"' not in src


def test_workspace_panel_wires_autonomy_controls_and_job_actions():
    src = _read("adapters/Jarvis/static/js/workspace.js")
    assert "Autonomy Control" in src
    assert "submitAutonomyJob(" in src
    assert "cancelAutonomyJob(" in src
    assert "retryAutonomyJob(" in src
    assert 'data-autonomy-action="cancel"' in src
    assert 'data-autonomy-action="retry"' in src
    assert "AUTONOMY_POLL_MS = 3000" in src
    assert "getActiveConversationId()" in src
    assert "webui-default" not in src


def test_workspace_css_has_autonomy_block_styles():
    src = _read("adapters/Jarvis/static/css/workspace.css")
    assert ".ws-autonomy" in src
    assert ".ws-autonomy-form" in src
    assert ".ws-autonomy-job-actions" in src
    assert ".ws-pill-ok" in src
