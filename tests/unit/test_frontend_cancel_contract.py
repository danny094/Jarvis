from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_chat_exposes_cancel_function_and_abort():
    src = _read("adapters/Jarvis/static/js/chat.js")
    assert "export function cancelActiveRequest()" in src
    assert "void cancelDeepChatJob(deepJobId)" in src
    assert "activeAbortController.abort();" in src
    assert "return hasAbortController || Boolean(deepJobId);" in src


def test_stream_and_deep_job_paths_are_signal_aware():
    src = _read("adapters/Jarvis/static/js/chat.js")
    assert "{ signal: activeAbortController.signal }" in src
    assert "waitForDeepChatJob(jobId, {" in src
    assert "signal: activeAbortController.signal" in src


def test_abort_branch_shows_stopped_message():
    src = _read("adapters/Jarvis/static/js/chat.js")
    assert 'const aborted = error?.name === "AbortError" || errMsg.toLowerCase().includes("abort");' in src
    assert "⏹️ Request stopped." in src


def test_finally_resets_ui_after_abort_or_error():
    src = _read("adapters/Jarvis/static/js/chat.js")
    assert "} finally {" in src
    assert "activeAbortController = null;" in src
    assert "State.setProcessing(false);" in src
    assert "UI.setProfileBusy(false);" in src
    assert 'UI.setActivityState("Ready for input", { active: false, stalled: false });' in src
    assert "UI.updateUIState(false);" in src


def test_api_wait_for_deep_job_honors_abort_signal():
    src = _read("adapters/Jarvis/static/js/api.js")
    assert "function _sleepWithSignal(ms, signal)" in src
    assert "if (signal?.aborted) {" in src
    assert 'throw new DOMException("Aborted", "AbortError");' in src
    assert "await _sleepWithSignal(pollIntervalMs, signal);" in src


def test_api_exposes_backend_cancel_for_deep_jobs():
    src = _read("adapters/Jarvis/static/js/api.js")
    assert "export async function cancelDeepChatJob(jobId, options = {})" in src
    assert '/api/chat/deep-jobs/${encodeURIComponent(jobId)}/cancel' in src


def test_deep_job_id_is_tracked_for_cancel_flow():
    src = _read("adapters/Jarvis/static/js/chat.js")
    assert "let activeDeepJobId = null;" in src
    assert "activeDeepJobId = jobId;" in src
    assert "activeDeepJobId = null;" in src
